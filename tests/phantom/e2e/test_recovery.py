"""Phase 3B end-to-end recovery suite: the 10 named recovery scenarios
(Bridge restart, Runtime restart, Engine timeout, Snapshot timeout,
Configuration corruption, Lost heartbeat, Slow engine, Partial engine
failure, Queue congestion, Repeated failures), each driven through a
real `RuntimeOrchestrator` (not just `phantom.reliability`'s own
already-passing unit-level recovery tests) and, where relevant, a real
`ReliabilityEngine` observing its output -- proving the two packages'
documented external-observer relationship (ADR-032 SS0/Hard Rule 2:
Reliability never calls into Runtime, and Runtime never gates itself on
Reliability's verdict) holds under combined use, not just in isolation.
"""

from __future__ import annotations

import dataclasses
import unittest
from datetime import timedelta

from phantom.reliability.config import ReliabilityConfig
from phantom.reliability.engine import ReliabilityEngine
from phantom.reliability.models import DegradationLevel, HealthState
from phantom.risk_engine.models import PortfolioState
from phantom.runtime.engine import RuntimeOrchestrator
from phantom.runtime.models import CycleOutcome, CycleStage
from phantom.runtime.validation import validate_profile
from tests.phantom.e2e._fixtures import (
    T0,
    RaisingStub,
    make_account_state,
    make_bars,
    make_compliance_config,
    make_config,
    make_market_safety_inputs,
    make_profile,
    make_stub_bridge_submit,
    make_stub_compliance_engine,
    make_stub_evidence_engine,
    make_stub_mi_engine,
    make_stub_risk_engine,
    make_stub_strategy_engine,
    make_strategy_config,
)


def _build_orchestrator(**overrides):
    defaults = dict(
        config=make_config(),
        evidence_engine=make_stub_evidence_engine(),
        market_intelligence_engine=make_stub_mi_engine(),
        strategy_engine=make_stub_strategy_engine(),
        risk_engine=make_stub_risk_engine(),
        compliance_engine=make_stub_compliance_engine(),
        bridge_submit=make_stub_bridge_submit(),
    )
    defaults.update(overrides)
    return RuntimeOrchestrator(
        defaults["config"], defaults["evidence_engine"], defaults["market_intelligence_engine"],
        defaults["strategy_engine"], defaults["risk_engine"], defaults["compliance_engine"], defaults["bridge_submit"],
    )


class TestBridgeRestart(unittest.TestCase):
    def test_bridge_restart_is_refused_but_runtime_keeps_processing_other_cycles(self):
        reliability = ReliabilityEngine(ReliabilityConfig())
        outcome = reliability.attempt_recovery("bridge", T0)
        self.assertFalse(outcome.attempted)

        # A refused Bridge restart never blocks Runtime from continuing
        # to process cycles through a healthy (stub) bridge -- Reliability
        # never gates Runtime (ADR-032 Hard Rule 2).
        orchestrator = _build_orchestrator()
        record = orchestrator.run_cycle_for_pair(
            "EURUSD", make_bars(), (), 1.0, 1.0, make_market_safety_inputs(),
            PortfolioState(), None, make_account_state(), make_profile(), T0, "CYCLE-1",
        )
        self.assertEqual(record.outcome, CycleOutcome.SUBMITTED)


class TestRuntimeRestart(unittest.TestCase):
    def test_a_fresh_orchestrator_instance_reproduces_the_same_decision(self):
        """`RuntimeOrchestrator` holds no mutable per-call state (ADR-031),
        so a "Runtime restart" is just constructing a new instance --
        deterministic behavior survives the restart."""
        profile = make_profile()
        args = (
            "EURUSD", make_bars(), (), 1.0, 1.0, make_market_safety_inputs(),
            PortfolioState(), None, make_account_state(), profile, T0, "CYCLE-1",
        )
        before = _build_orchestrator().run_cycle_for_pair(*args)
        after = _build_orchestrator().run_cycle_for_pair(*args)  # simulated restart: a brand new instance
        self.assertEqual(
            dataclasses.replace(before, duration_ms=0.0, stage_timings=()),
            dataclasses.replace(after, duration_ms=0.0, stage_timings=()),
        )


class TestEngineTimeout(unittest.TestCase):
    def test_stale_heartbeat_halts_reliability_while_runtime_cycles_continue_unaffected(self):
        reliability = ReliabilityEngine(ReliabilityConfig(heartbeat_grace_period_seconds=10.0))
        reliability.report_heartbeat("strategy_engine", T0)
        later = T0 + timedelta(seconds=30)
        self.assertTrue(reliability.is_halted(later))

        # Runtime itself never consults Reliability -- it keeps producing
        # cycle decisions regardless of the engine-timeout verdict above.
        orchestrator = _build_orchestrator()
        record = orchestrator.run_cycle_for_pair(
            "EURUSD", make_bars(), (), 1.0, 1.0, make_market_safety_inputs(),
            PortfolioState(), None, make_account_state(), make_profile(), later, "CYCLE-1",
        )
        self.assertEqual(record.outcome, CycleOutcome.SUBMITTED)

        # Once the heartbeat resumes, the same engine recovers.
        reliability.report_heartbeat("strategy_engine", later)
        self.assertFalse(reliability.is_halted(later))


class TestSnapshotTimeout(unittest.TestCase):
    def test_snapshot_freshness_gates_operator_trust_not_runtime_execution(self):
        reliability = ReliabilityEngine(ReliabilityConfig(snapshot_freshness_threshold_seconds=1.0))
        orchestrator = _build_orchestrator()
        record = orchestrator.run_cycle_for_pair(
            "EURUSD", make_bars(), (), 1.0, 1.0, make_market_safety_inputs(),
            PortfolioState(), None, make_account_state(), make_profile(), T0, "CYCLE-1",
        )
        # Runtime always produces a record; a stale evidence snapshot is
        # an external freshness judgment an operator layers on top.
        self.assertIsNotNone(record.evidence_id)
        stale_generated_at = T0 - timedelta(seconds=30)
        self.assertFalse(reliability.is_snapshot_fresh(stale_generated_at, T0))


class TestConfigurationCorruption(unittest.TestCase):
    def test_corrupted_trading_window_is_rejected_before_trading(self):
        profile = make_profile()
        corrupted = dataclasses.replace(
            profile, trading_window=dataclasses.replace(profile.trading_window, start_hour_utc=20, end_hour_utc=5),
        )
        result = validate_profile(corrupted, make_strategy_config(), make_compliance_config())
        self.assertFalse(result.valid)
        self.assertTrue(any(issue.field == "trading_window" for issue in result.issues))

    def test_unknown_compliance_rule_profile_is_rejected(self):
        profile = make_profile()
        corrupted = dataclasses.replace(profile, compliance_rule_profile_name="does_not_exist")
        result = validate_profile(corrupted, make_strategy_config(), make_compliance_config())
        self.assertFalse(result.valid)


class TestLostHeartbeat(unittest.TestCase):
    def test_lost_heartbeat_on_one_component_does_not_mask_runtime_cycle_stats(self):
        reliability = ReliabilityEngine(ReliabilityConfig())
        reliability.report_heartbeat("evidence_engine", T0)
        orchestrator = _build_orchestrator()
        report = orchestrator.run_cycle(
            ["EURUSD", "GBPUSD"], make_profile(),
            {
                "EURUSD": (make_bars(), (), 1.0, 1.0, make_market_safety_inputs(), PortfolioState(), None, make_account_state()),
                "GBPUSD": (make_bars(), (), 1.0, 1.0, make_market_safety_inputs(), PortfolioState(), None, make_account_state()),
            },
            T0, "CYCLE-1",
        )
        reliability.record_cycle(report)
        later = T0 + timedelta(minutes=5)
        health = reliability.evaluate_health(later)
        states = {c.component: c.state for c in health.component_health}
        self.assertEqual(states["evidence_engine"], HealthState.UNKNOWN)
        pairs = {s.pair for s in health.cycle_stats}
        self.assertEqual(pairs, {"EURUSD", "GBPUSD"})


class TestSlowEngine(unittest.TestCase):
    def test_moderately_stale_heartbeat_is_degraded_not_halted_while_cycles_keep_submitting(self):
        config = ReliabilityConfig(heartbeat_healthy_interval_seconds=5.0, heartbeat_degraded_interval_seconds=15.0, heartbeat_grace_period_seconds=30.0)
        reliability = ReliabilityEngine(config)
        reliability.report_heartbeat("market_intelligence", T0)
        slightly_later = T0 + timedelta(seconds=10)
        health = reliability.evaluate_health(slightly_later)
        self.assertEqual(health.degradation_level, DegradationLevel.DEGRADED)

        orchestrator = _build_orchestrator()
        record = orchestrator.run_cycle_for_pair(
            "EURUSD", make_bars(), (), 1.0, 1.0, make_market_safety_inputs(),
            PortfolioState(), None, make_account_state(), make_profile(), slightly_later, "CYCLE-1",
        )
        self.assertEqual(record.outcome, CycleOutcome.SUBMITTED)


class TestPartialEngineFailure(unittest.TestCase):
    def test_one_pair_failing_at_runtime_level_does_not_affect_the_other_pairs_stats(self):
        orchestrator = _build_orchestrator(strategy_engine=RaisingStub())
        report_with_failure = orchestrator.run_cycle(
            ["EURUSD"], make_profile(),
            {"EURUSD": (make_bars(), (), 1.0, 1.0, make_market_safety_inputs(), PortfolioState(), None, make_account_state())},
            T0, "CYCLE-FAIL",
        )
        self.assertEqual(report_with_failure.records[0].outcome, CycleOutcome.FAILED)

        healthy_orchestrator = _build_orchestrator()
        report_healthy = healthy_orchestrator.run_cycle(
            ["GBPUSD"], make_profile(),
            {"GBPUSD": (make_bars(), (), 1.0, 1.0, make_market_safety_inputs(), PortfolioState(), None, make_account_state())},
            T0, "CYCLE-OK",
        )
        self.assertEqual(report_healthy.records[0].outcome, CycleOutcome.SUBMITTED)

        reliability = ReliabilityEngine(ReliabilityConfig())
        reliability.record_cycle(report_with_failure)
        reliability.record_cycle(report_healthy)
        health = reliability.evaluate_health(T0)
        stats = {s.pair: s for s in health.cycle_stats}
        self.assertEqual(stats["EURUSD"].failed_cycles, 1)
        self.assertEqual(stats["GBPUSD"].failed_cycles, 0)


class TestQueueCongestion(unittest.TestCase):
    def test_bridge_command_queue_depth_escalates_deterministically_alongside_real_cycles(self):
        reliability = ReliabilityEngine(ReliabilityConfig(queue_degraded_depth=5, queue_critical_depth=20))
        orchestrator = _build_orchestrator()
        record = orchestrator.run_cycle_for_pair(
            "EURUSD", make_bars(), (), 1.0, 1.0, make_market_safety_inputs(),
            PortfolioState(), None, make_account_state(), make_profile(), T0, "CYCLE-1",
        )
        self.assertEqual(record.outcome, CycleOutcome.SUBMITTED)

        reliability.report_queue_depth("bridge_commands", 2, T0)
        self.assertEqual(reliability.evaluate_health(T0).degradation_level, DegradationLevel.NORMAL)
        reliability.report_queue_depth("bridge_commands", 10, T0)
        self.assertEqual(reliability.evaluate_health(T0).degradation_level, DegradationLevel.DEGRADED)
        reliability.report_queue_depth("bridge_commands", 30, T0)
        self.assertEqual(reliability.evaluate_health(T0).degradation_level, DegradationLevel.CRITICAL)


class TestRepeatedFailures(unittest.TestCase):
    def test_repeated_real_runtime_failures_recover_once_success_resumes(self):
        config = ReliabilityConfig(cycle_failure_rate_critical=0.5, cycle_history_window=10)
        reliability = ReliabilityEngine(config)
        failing_orchestrator = _build_orchestrator(strategy_engine=RaisingStub())
        for i in range(10):
            report = failing_orchestrator.run_cycle(
                ["EURUSD"], make_profile(),
                {"EURUSD": (make_bars(), (), 1.0, 1.0, make_market_safety_inputs(), PortfolioState(), None, make_account_state())},
                T0, f"CYCLE-F{i}",
            )
            reliability.record_cycle(report)
        self.assertEqual(reliability.evaluate_health(T0).degradation_level, DegradationLevel.CRITICAL)

        healthy_orchestrator = _build_orchestrator()
        for i in range(10):
            report = healthy_orchestrator.run_cycle(
                ["EURUSD"], make_profile(),
                {"EURUSD": (make_bars(), (), 1.0, 1.0, make_market_safety_inputs(), PortfolioState(), None, make_account_state())},
                T0, f"CYCLE-S{i}",
            )
            reliability.record_cycle(report)
        self.assertEqual(reliability.evaluate_health(T0).degradation_level, DegradationLevel.NORMAL)


if __name__ == "__main__":
    unittest.main()
