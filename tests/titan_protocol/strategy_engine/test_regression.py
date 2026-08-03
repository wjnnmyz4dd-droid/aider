"""Regression tests: fixed input/output anchors for scenarios worked
through during development."""

from __future__ import annotations

import unittest

from titan_protocol.evidence_engine.models import TrendClassification
from titan_protocol.strategy_engine.engine import StrategyEngine
from titan_protocol.strategy_engine.models import StrategyId
from tests.titan_protocol.strategy_engine._fixtures import make_config, make_evidence_snapshot, make_mi_snapshot, make_structure_result


class TestKnownGoodEvaluation(unittest.TestCase):
    def test_default_fixture_always_rejects(self):
        # The plain default fixture (RANGE trend, no events/sweeps/gaps/
        # candlesticks) qualifies nothing -- anchors that "nothing
        # special" input stays rejected across refactors.
        engine = StrategyEngine(make_config())
        snapshot = engine.evaluate("EURUSD", make_evidence_snapshot(), make_mi_snapshot())
        self.assertTrue(snapshot.rejected)
        self.assertEqual(len(snapshot.all_qualifications), 5)
        self.assertTrue(all(q.score == 0.0 for q in snapshot.all_qualifications))

    def test_strong_directional_trend_selects_trend_continuation(self):
        engine = StrategyEngine(make_config())
        evidence = make_evidence_snapshot(
            structure=make_structure_result(trend=TrendClassification.TRENDING_UP),
            component_overrides={"trend": {"value": 90.0, "confidence": 0.9}},
        )
        snapshot = engine.evaluate("EURUSD", evidence, make_mi_snapshot())
        self.assertFalse(snapshot.rejected)
        self.assertEqual(snapshot.winning_strategy.strategy_id, StrategyId.TREND_CONTINUATION)
        self.assertAlmostEqual(snapshot.winning_strategy.qualification.score, 90.0 * 0.7 + 50.0 * 0.3, places=6)


if __name__ == "__main__":
    unittest.main()
