"""Explainability tests: every `Recommendation` carries a supporting
dimension, supporting data, and a confidence tag; the `ResearchSnapshot`
always carries the period it covers and a sample size (ADR-029 §6)."""

from __future__ import annotations

import unittest
from datetime import timedelta

from phantom.evidence_engine.models import SessionName
from phantom.research_engine.engine import ResearchEngine
from phantom.research_engine.models import ReportPeriod
from tests.phantom.research_engine._fixtures import T0, make_config, make_executed_trade, make_trade_history


class TestRecommendationExplainability(unittest.TestCase):
    def test_every_recommendation_carries_full_explanation(self):
        config = make_config(min_sample_size_for_ranking=5, min_sample_size_for_recommendation=5, recommendation_expectancy_delta_threshold=0.3, effectiveness_min_sample_size=3)
        engine = ResearchEngine(config)
        london = [make_executed_trade(index=i, session=SessionName.LONDON, won=True, r_multiple=2.0) for i in range(15)]
        asian = [make_executed_trade(index=i, session=SessionName.ASIAN, won=False, r_multiple=-1.0) for i in range(15, 30)]
        history = make_trade_history(london + asian)
        snapshot = engine.evaluate(
            history, period=ReportPeriod.CUSTOM, now=T0 + timedelta(hours=40),
            custom_start=T0 - timedelta(hours=1), custom_end=T0 + timedelta(hours=40),
        )
        self.assertTrue(snapshot.recommendations)
        for recommendation in snapshot.recommendations:
            self.assertTrue(recommendation.text)
            self.assertTrue(recommendation.supporting_dimension)
            self.assertIn(recommendation.confidence, ("LOW", "MEDIUM", "HIGH"))


class TestSnapshotExplainability(unittest.TestCase):
    def test_snapshot_always_carries_period_and_sample_size(self):
        config = make_config()
        engine = ResearchEngine(config)
        trades = [make_executed_trade(index=i) for i in range(5)]
        history = make_trade_history(trades)
        snapshot = engine.evaluate(
            history, period=ReportPeriod.CUSTOM, now=T0 + timedelta(hours=10),
            custom_start=T0 - timedelta(hours=1), custom_end=T0 + timedelta(hours=10),
        )
        self.assertEqual(snapshot.period, ReportPeriod.CUSTOM)
        self.assertEqual(snapshot.sample_size, 5)
        self.assertIsNotNone(snapshot.period_start)
        self.assertIsNotNone(snapshot.period_end)

    def test_effectiveness_comparisons_carry_sample_sizes(self):
        config = make_config(effectiveness_min_sample_size=3)
        engine = ResearchEngine(config)
        trades = [make_executed_trade(index=i, news_blackout_was_active=(i % 2 == 0)) for i in range(20)]
        history = make_trade_history(trades)
        snapshot = engine.evaluate(
            history, period=ReportPeriod.CUSTOM, now=T0 + timedelta(hours=30),
            custom_start=T0 - timedelta(hours=1), custom_end=T0 + timedelta(hours=30),
        )
        comparison = snapshot.market_intelligence_review.news_blackout_effectiveness
        self.assertGreater(comparison.baseline_sample_size + comparison.comparison_sample_size, 0)


if __name__ == "__main__":
    unittest.main()
