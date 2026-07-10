"""Explainability tests: every `StrategySnapshot` traces to a reason,
and the winning strategy's own qualification is fully explained."""

from __future__ import annotations

import unittest

from phantom.evidence_engine.models import TrendClassification
from phantom.strategy_engine.engine import StrategyEngine
from tests.phantom.strategy_engine._fixtures import make_config, make_evidence_snapshot, make_mi_snapshot, make_structure_result


class TestRejectionExplainability(unittest.TestCase):
    def test_rejection_carries_a_reason_and_per_strategy_reasons(self):
        engine = StrategyEngine(make_config())
        snapshot = engine.evaluate("EURUSD", make_evidence_snapshot(), make_mi_snapshot())
        self.assertTrue(snapshot.rejected)
        self.assertTrue(snapshot.rejection_reason)
        for qualification in snapshot.all_qualifications:
            self.assertTrue(qualification.reason)

    def test_evidence_and_market_intelligence_summaries_always_populated(self):
        engine = StrategyEngine(make_config())
        snapshot = engine.evaluate("EURUSD", make_evidence_snapshot(), make_mi_snapshot())
        self.assertTrue(snapshot.supporting_evidence_summary)
        self.assertTrue(snapshot.supporting_market_intelligence_summary)


class TestWinningStrategyExplainability(unittest.TestCase):
    def test_winning_strategy_carries_strengths_and_reason(self):
        engine = StrategyEngine(make_config())
        evidence = make_evidence_snapshot(
            structure=make_structure_result(trend=TrendClassification.TRENDING_UP),
            component_overrides={"trend": {"value": 90.0, "confidence": 0.9}},
        )
        snapshot = engine.evaluate("EURUSD", evidence, make_mi_snapshot())
        self.assertFalse(snapshot.rejected)
        self.assertIsNotNone(snapshot.winning_strategy)
        self.assertTrue(snapshot.winning_strategy.qualification.reason)
        self.assertIsNone(snapshot.rejection_reason)


if __name__ == "__main__":
    unittest.main()
