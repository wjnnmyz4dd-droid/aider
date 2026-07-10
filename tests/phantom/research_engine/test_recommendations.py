"""Unit tests: the deterministic threshold-based Recommendation Engine
(ADR-029 §5) -- no ML, no LLM, matches the task's own worked examples."""

from __future__ import annotations

import unittest

from phantom.evidence_engine.models import SessionName
from phantom.research_engine.attribution import DIMENSION_KEY_FUNCS, attribute_all_dimensions
from phantom.research_engine.models import AttributionDimension, EffectivenessComparison
from phantom.research_engine.recommendations import cross_dimension_recommendations, recommendations_from_attribution
from tests.phantom.research_engine._fixtures import make_config, make_executed_trade


class TestSingleDimensionRecommendations(unittest.TestCase):
    def test_underperforming_bucket_flagged(self):
        config = make_config(min_sample_size_for_recommendation=5, recommendation_expectancy_delta_threshold=0.3)
        good = [make_executed_trade(index=i, pair="EURUSD", won=True, r_multiple=2.0) for i in range(10)]
        bad = [make_executed_trade(index=i, pair="GBPUSD", won=False, r_multiple=-1.0) for i in range(10, 20)]
        trades = good + bad
        attributions = attribute_all_dimensions(trades, config)
        overall = EffectivenessComparison(
            label="overall", baseline_sample_size=0, baseline_expectancy=None,
            comparison_sample_size=len(trades), comparison_expectancy=0.5, delta=None, notable=False,
        )
        recs = recommendations_from_attribution(attributions, overall, config)
        self.assertTrue(any("GBPUSD" in r.text and "underperforms" in r.text for r in recs))
        self.assertTrue(any("EURUSD" in r.text and "outperforms" in r.text for r in recs))

    def test_no_overall_expectancy_produces_no_recommendations(self):
        config = make_config()
        attributions = attribute_all_dimensions([], config)
        overall = EffectivenessComparison(
            label="overall", baseline_sample_size=0, baseline_expectancy=None,
            comparison_sample_size=0, comparison_expectancy=None, delta=None, notable=False,
        )
        recs = recommendations_from_attribution(attributions, overall, config)
        self.assertEqual(recs, [])


class TestCrossDimensionRecommendations(unittest.TestCase):
    def test_matches_the_tasks_own_worked_example_shape(self):
        """"EURUSD Trend Continuation performs better in London than NY" --
        exactly a (pair, strategy) x session cross-tabulation."""

        config = make_config(min_sample_size_for_recommendation=5, recommendation_expectancy_delta_threshold=0.3, effectiveness_min_sample_size=3)
        london = [make_executed_trade(index=i, pair="EURUSD", session=SessionName.LONDON, won=True, r_multiple=2.0) for i in range(10)]
        asian = [make_executed_trade(index=i, pair="EURUSD", session=SessionName.ASIAN, won=False, r_multiple=-1.0) for i in range(10, 20)]
        trades = london + asian
        recs = cross_dimension_recommendations(trades, DIMENSION_KEY_FUNCS[AttributionDimension.SESSION], "session", config)
        texts = [r.text for r in recs]
        self.assertTrue(any("EURUSD TREND_CONTINUATION" in t and "LONDON" in t for t in texts))

    def test_confidence_tag_scales_with_sample_size(self):
        config = make_config(
            min_sample_size_for_recommendation=5, recommendation_expectancy_delta_threshold=0.3,
            effectiveness_min_sample_size=3, high_confidence_sample_size=30, medium_confidence_sample_size=15,
        )
        london = [make_executed_trade(index=i, session=SessionName.LONDON, won=True, r_multiple=2.0) for i in range(40)]
        asian = [make_executed_trade(index=i, session=SessionName.ASIAN, won=False, r_multiple=-1.0) for i in range(40, 80)]
        recs = cross_dimension_recommendations(london + asian, DIMENSION_KEY_FUNCS[AttributionDimension.SESSION], "session", config)
        self.assertTrue(any(r.confidence == "HIGH" for r in recs))


if __name__ == "__main__":
    unittest.main()
