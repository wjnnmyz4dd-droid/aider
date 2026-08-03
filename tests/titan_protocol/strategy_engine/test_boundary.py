"""Boundary tests: empty registry, no candlesticks/gaps/sweeps, exact
threshold edges."""

from __future__ import annotations

import unittest

from titan_protocol.evidence_engine.models import TrendClassification
from titan_protocol.strategy_engine.engine import StrategyEngine
from titan_protocol.strategy_engine.strategies import StrategyRegistry, TrendContinuationStrategy
from tests.titan_protocol.strategy_engine._fixtures import make_config, make_evidence_snapshot, make_mi_snapshot, make_structure_result


class TestEmptyRegistry(unittest.TestCase):
    def test_engine_with_no_registered_strategies_always_rejects(self):
        engine = StrategyEngine(make_config(), registry=StrategyRegistry())
        snapshot = engine.evaluate("EURUSD", make_evidence_snapshot(), make_mi_snapshot())
        self.assertTrue(snapshot.rejected)
        self.assertEqual(snapshot.all_qualifications, ())


class TestExactThresholdEdges(unittest.TestCase):
    def test_trend_score_exactly_at_threshold_qualifies(self):
        config = make_config()
        strategy = TrendContinuationStrategy()
        evidence = make_evidence_snapshot(
            structure=make_structure_result(trend=TrendClassification.TRENDING_UP),
            component_overrides={"trend": {"value": config.trend_continuation_min_trend_score}},
        )
        result = strategy.qualify("EURUSD", evidence, make_mi_snapshot(), config)
        self.assertEqual(result.status.value, "QUALIFIED")

    def test_trend_score_just_below_threshold_disqualifies(self):
        config = make_config()
        strategy = TrendContinuationStrategy()
        evidence = make_evidence_snapshot(
            structure=make_structure_result(trend=TrendClassification.TRENDING_UP),
            component_overrides={"trend": {"value": config.trend_continuation_min_trend_score - 0.01}},
        )
        result = strategy.qualify("EURUSD", evidence, make_mi_snapshot(), config)
        self.assertEqual(result.status.value, "NOT_QUALIFIED")


class TestEmptyCollections(unittest.TestCase):
    def test_no_candlesticks_no_gaps_no_sweeps_never_raises(self):
        engine = StrategyEngine(make_config())
        evidence = make_evidence_snapshot()  # all empty by default
        snapshot = engine.evaluate("EURUSD", evidence, make_mi_snapshot())
        self.assertTrue(snapshot.rejected)


if __name__ == "__main__":
    unittest.main()
