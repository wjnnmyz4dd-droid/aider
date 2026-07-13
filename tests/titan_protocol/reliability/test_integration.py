"""Integration category: `ReliabilityEngine` consuming a real Runtime
`CycleReport`/`RuntimeAuditRecord` (ADR-032's own observer relationship
to ADR-031) end to end."""

from __future__ import annotations

import unittest
from datetime import timedelta

from titan_protocol.reliability.config import ReliabilityConfig
from titan_protocol.reliability.engine import ReliabilityEngine
from titan_protocol.reliability.models import DegradationLevel
from titan_protocol.runtime.models import CycleOutcome
from tests.titan_protocol.reliability._fixtures import T0, make_audit_record, make_cycle_report, make_config


class TestReliabilityConsumesRuntimeOutput(unittest.TestCase):
    def test_record_cycle_updates_per_pair_stats(self):
        engine = ReliabilityEngine(make_config())
        report = make_cycle_report([
            make_audit_record(pair="EURUSD", outcome=CycleOutcome.SUBMITTED, now=T0),
            make_audit_record(pair="GBPUSD", outcome=CycleOutcome.NO_STRATEGY, now=T0),
        ])
        engine.record_cycle(report)
        health = engine.evaluate_health(T0)
        pairs = {s.pair: s for s in health.cycle_stats}
        self.assertEqual(pairs["EURUSD"].total_cycles, 1)
        self.assertEqual(pairs["EURUSD"].failed_cycles, 0)
        self.assertEqual(pairs["GBPUSD"].last_outcome, CycleOutcome.NO_STRATEGY)

    def test_repeated_failures_escalate_to_critical(self):
        config = make_config(cycle_failure_rate_critical=0.5)
        engine = ReliabilityEngine(config)
        records = [make_audit_record(pair="EURUSD", outcome=CycleOutcome.FAILED, cycle_id=f"C{i}", now=T0) for i in range(10)]
        engine.record_cycle(make_cycle_report(records))
        health = engine.evaluate_health(T0)
        self.assertEqual(health.degradation_level, DegradationLevel.CRITICAL)

    def test_healthy_heartbeats_and_successful_cycles_stay_normal(self):
        engine = ReliabilityEngine(make_config())
        for component in ("evidence_engine", "market_intelligence", "strategy_engine", "risk_engine"):
            engine.report_heartbeat(component, T0)
        engine.record_cycle(make_cycle_report([make_audit_record(now=T0)]))
        health = engine.evaluate_health(T0)
        self.assertEqual(health.degradation_level, DegradationLevel.NORMAL)
        self.assertFalse(engine.is_halted(T0))

    def test_a_single_engine_going_silent_halts_the_system(self):
        engine = ReliabilityEngine(make_config())
        engine.report_heartbeat("evidence_engine", T0)
        # A very long time later, with no further heartbeat -- this
        # engine went silent (a lost-heartbeat recovery scenario).
        later = T0 + timedelta(minutes=5)
        self.assertTrue(engine.is_halted(later))


if __name__ == "__main__":
    unittest.main()
