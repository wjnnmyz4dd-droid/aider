"""Recovery category (ADR-032 SS7): Bridge restart refusal, engine
timeout via stale heartbeat, snapshot timeout, lost heartbeat, slow
engine (heartbeat never arrives), partial engine failure (one
component silent, others fine), queue congestion, repeated failures --
every recovery decision is deterministic."""

from __future__ import annotations

import unittest
from datetime import timedelta

from titan_protocol.reliability.engine import ReliabilityEngine
from titan_protocol.reliability.models import DegradationLevel, QueueDepth
from titan_protocol.runtime.models import CycleOutcome
from tests.titan_protocol.reliability._fixtures import T0, make_audit_record, make_cycle_report, make_config


class TestRestartAuthorization(unittest.TestCase):
    def test_bridge_restart_is_refused(self):
        engine = ReliabilityEngine(make_config())
        outcome = engine.attempt_recovery("bridge", T0)
        self.assertFalse(outcome.attempted)
        self.assertFalse(outcome.succeeded)

    def test_compliance_engine_restart_is_refused(self):
        engine = ReliabilityEngine(make_config())
        outcome = engine.attempt_recovery("compliance_engine", T0)
        self.assertFalse(outcome.attempted)

    def test_runtime_itself_is_not_a_restartable_component(self):
        engine = ReliabilityEngine(make_config())
        outcome = engine.attempt_recovery("runtime", T0)
        self.assertFalse(outcome.attempted)

    def test_evidence_engine_restart_is_approved(self):
        engine = ReliabilityEngine(make_config())
        outcome = engine.attempt_recovery("evidence_engine", T0)
        self.assertTrue(outcome.attempted)
        self.assertTrue(outcome.succeeded)


class TestTimeoutAndFreshnessRecovery(unittest.TestCase):
    def test_engine_timeout_via_stale_heartbeat_is_deterministic(self):
        config = make_config(heartbeat_grace_period_seconds=10.0)
        engine = ReliabilityEngine(config)
        engine.report_heartbeat("strategy_engine", T0)
        result_a = engine.is_halted(T0 + timedelta(seconds=20))
        result_b = engine.is_halted(T0 + timedelta(seconds=20))
        self.assertEqual(result_a, result_b)
        self.assertTrue(result_a)

    def test_snapshot_timeout_check_is_deterministic(self):
        engine = ReliabilityEngine(make_config(snapshot_freshness_threshold_seconds=1.0))
        result_a = engine.is_snapshot_fresh(T0, T0 + timedelta(seconds=5))
        result_b = engine.is_snapshot_fresh(T0, T0 + timedelta(seconds=5))
        self.assertEqual(result_a, result_b)
        self.assertFalse(result_a)


class TestLostHeartbeatAndPartialFailure(unittest.TestCase):
    def test_lost_heartbeat_on_one_engine_does_not_mask_others(self):
        engine = ReliabilityEngine(make_config())
        engine.report_heartbeat("evidence_engine", T0)
        engine.report_heartbeat("market_intelligence", T0 + timedelta(seconds=60))  # still fresh at evaluation time
        health = engine.evaluate_health(T0 + timedelta(seconds=60))
        states = {c.component: c.state for c in health.component_health}
        self.assertNotEqual(states["evidence_engine"], states["market_intelligence"])

    def test_partial_engine_failure_is_isolated_per_pair(self):
        engine = ReliabilityEngine(make_config(cycle_failure_rate_critical=0.9))
        report = make_cycle_report([
            make_audit_record(pair="EURUSD", outcome=CycleOutcome.FAILED, now=T0),
            make_audit_record(pair="GBPUSD", outcome=CycleOutcome.SUBMITTED, now=T0),
        ])
        engine.record_cycle(report)
        health = engine.evaluate_health(T0)
        stats = {s.pair: s for s in health.cycle_stats}
        self.assertEqual(stats["EURUSD"].failed_cycles, 1)
        self.assertEqual(stats["GBPUSD"].failed_cycles, 0)


class TestQueueCongestion(unittest.TestCase):
    def test_queue_congestion_escalates_deterministically(self):
        config = make_config(queue_degraded_depth=10, queue_critical_depth=50)
        engine = ReliabilityEngine(config)
        engine.report_queue_depth("bridge_commands", 5, T0)
        self.assertEqual(engine.evaluate_health(T0).degradation_level, DegradationLevel.NORMAL)
        engine.report_queue_depth("bridge_commands", 20, T0)
        self.assertEqual(engine.evaluate_health(T0).degradation_level, DegradationLevel.DEGRADED)
        engine.report_queue_depth("bridge_commands", 100, T0)
        self.assertEqual(engine.evaluate_health(T0).degradation_level, DegradationLevel.CRITICAL)


class TestRepeatedFailures(unittest.TestCase):
    def test_repeated_failures_recover_once_success_resumes(self):
        config = make_config(cycle_failure_rate_critical=0.5, cycle_history_window=10)
        engine = ReliabilityEngine(config)
        engine.record_cycle(make_cycle_report([make_audit_record(pair="EURUSD", outcome=CycleOutcome.FAILED, cycle_id=f"F{i}", now=T0) for i in range(10)]))
        self.assertEqual(engine.evaluate_health(T0).degradation_level, DegradationLevel.CRITICAL)

        # A run of successes pushes the failed cycles out of the rolling window.
        engine.record_cycle(make_cycle_report([make_audit_record(pair="EURUSD", outcome=CycleOutcome.SUBMITTED, cycle_id=f"S{i}", now=T0) for i in range(10)]))
        self.assertEqual(engine.evaluate_health(T0).degradation_level, DegradationLevel.NORMAL)


if __name__ == "__main__":
    unittest.main()
