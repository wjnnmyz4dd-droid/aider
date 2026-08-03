"""Regression category: determinism -- identical heartbeat/cycle-report/
resource inputs evaluated at a fixed `now` produce an identical
`SystemHealthSnapshot` (aside from `generated_at`, which is the `now`
argument itself and therefore trivially equal) on repeated
`evaluate_health()` calls, and across independently constructed engines
given the same inputs."""

from __future__ import annotations

import unittest

from titan_protocol.reliability.engine import ReliabilityEngine
from titan_protocol.runtime.models import CycleOutcome
from tests.titan_protocol.reliability._fixtures import T0, make_audit_record, make_config, make_cycle_report


def _seeded_engine():
    engine = ReliabilityEngine(make_config())
    for component in ("evidence_engine", "market_intelligence", "strategy_engine", "risk_engine"):
        engine.report_heartbeat(component, T0)
    engine.record_cycle(make_cycle_report([
        make_audit_record(pair="EURUSD", outcome=CycleOutcome.SUBMITTED, now=T0),
        make_audit_record(pair="GBPUSD", outcome=CycleOutcome.FAILED, cycle_id="C2", now=T0),
    ]))
    engine.report_queue_depth("bridge_commands", 12, T0)
    return engine


class TestDeterminism(unittest.TestCase):
    def test_repeated_evaluations_produce_identical_snapshots(self):
        engine = _seeded_engine()
        results = [engine.evaluate_health(T0) for _ in range(10)]
        first = results[0]
        for result in results:
            self.assertEqual(result, first)

    def test_two_independently_seeded_engines_agree(self):
        engine_a = _seeded_engine()
        engine_b = _seeded_engine()
        snapshot_a = engine_a.evaluate_health(T0)
        snapshot_b = engine_b.evaluate_health(T0)
        self.assertEqual(snapshot_a, snapshot_b)

    def test_recovery_authorization_is_deterministic(self):
        engine = ReliabilityEngine(make_config())
        results = [engine.attempt_recovery("evidence_engine", T0) for _ in range(10)]
        first = results[0]
        for result in results:
            self.assertEqual(result, first)


if __name__ == "__main__":
    unittest.main()
