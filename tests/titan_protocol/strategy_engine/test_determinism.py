"""Determinism tests: same input always produces the same output."""

from __future__ import annotations

import unittest

from titan_protocol.evidence_engine.models import StructureDirection, StructureEvent, StructureEventType, SwingPoint, SwingType, TrendClassification
from titan_protocol.strategy_engine.engine import StrategyEngine
from tests.titan_protocol.strategy_engine._fixtures import T0, make_config, make_evidence_snapshot, make_mi_snapshot, make_structure_result


class TestDeterminism(unittest.TestCase):
    def test_repeated_evaluate_calls_produce_identical_snapshots(self):
        engine = StrategyEngine(make_config())
        evidence = make_evidence_snapshot(
            structure=make_structure_result(trend=TrendClassification.TRENDING_UP),
            component_overrides={"trend": {"value": 80.0, "confidence": 0.8}},
        )
        mi = make_mi_snapshot()
        r1 = engine.evaluate("EURUSD", evidence, mi)
        r2 = engine.evaluate("EURUSD", evidence, mi)
        self.assertEqual(r1, r2)

    def test_two_separate_engine_instances_agree(self):
        evidence = make_evidence_snapshot(
            structure=make_structure_result(trend=TrendClassification.TRENDING_DOWN),
            component_overrides={"trend": {"value": 75.0}},
        )
        mi = make_mi_snapshot()
        engine_a = StrategyEngine(make_config())
        engine_b = StrategyEngine(make_config())
        self.assertEqual(engine_a.evaluate("EURUSD", evidence, mi), engine_b.evaluate("EURUSD", evidence, mi))

    def test_evaluate_batch_result_stable_across_calls(self):
        engine = StrategyEngine(make_config())
        pairs = {
            "EURUSD": (make_evidence_snapshot(symbol="EURUSD"), make_mi_snapshot(pair="EURUSD")),
            "GBPUSD": (make_evidence_snapshot(symbol="GBPUSD"), make_mi_snapshot(pair="GBPUSD")),
        }
        r1 = engine.evaluate_batch(pairs)
        r2 = engine.evaluate_batch(pairs)
        self.assertEqual(r1, r2)


if __name__ == "__main__":
    unittest.main()
