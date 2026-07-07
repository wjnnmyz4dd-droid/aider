from __future__ import annotations

import unittest

from phantom_pipeline.statistical_risk import correlation
from phantom_pipeline.statistical_risk.config import StatisticalRiskConfig
from phantom_pipeline.statistical_risk.models import RiskRecommendation

from ._fixtures import make_open_position


class TestBuildCorrelationState(unittest.TestCase):
    def test_no_positions_means_empty_state(self):
        state = correlation.build_correlation_state([])
        self.assertEqual(state.bucket_exposure_count, {})
        self.assertIsNone(state.most_concentrated_bucket)
        self.assertEqual(state.flagged_buckets, ())

    def test_unevaluated_bucket_counted_separately(self):
        positions = [make_open_position(correlation_bucket=None)]
        state = correlation.build_correlation_state(positions)
        self.assertEqual(state.bucket_exposure_count, {correlation.UNEVALUATED_BUCKET: 1})

    def test_concentration_flagged_at_threshold(self):
        config = StatisticalRiskConfig(position_concentration_warning_count=2)
        positions = [
            make_open_position(symbol="EURUSD", correlation_bucket="EUR_MAJORS"),
            make_open_position(symbol="GBPUSD", correlation_bucket="EUR_MAJORS"),
        ]
        state = correlation.build_correlation_state(positions, config)
        self.assertIn("EUR_MAJORS", state.flagged_buckets)
        self.assertEqual(state.most_concentrated_bucket, "EUR_MAJORS")
        self.assertEqual(state.max_bucket_concentration_count, 2)

    def test_below_threshold_not_flagged(self):
        config = StatisticalRiskConfig(position_concentration_warning_count=5)
        positions = [make_open_position(correlation_bucket="EUR_MAJORS")]
        state = correlation.build_correlation_state(positions, config)
        self.assertEqual(state.flagged_buckets, ())


class TestRecommendationForCorrelation(unittest.TestCase):
    def test_unevaluated_flagged_means_reduce_50(self):
        positions = [
            make_open_position(symbol="AAA", correlation_bucket=None),
            make_open_position(symbol="BBB", correlation_bucket=None),
        ]
        config = StatisticalRiskConfig(position_concentration_warning_count=2)
        state = correlation.build_correlation_state(positions, config)
        self.assertEqual(
            correlation.recommendation_for_correlation(state), RiskRecommendation.REDUCE_RISK_50
        )

    def test_named_bucket_flagged_means_reduce_25(self):
        positions = [
            make_open_position(symbol="EURUSD", correlation_bucket="EUR_MAJORS"),
            make_open_position(symbol="GBPUSD", correlation_bucket="EUR_MAJORS"),
        ]
        config = StatisticalRiskConfig(position_concentration_warning_count=2)
        state = correlation.build_correlation_state(positions, config)
        self.assertEqual(
            correlation.recommendation_for_correlation(state), RiskRecommendation.REDUCE_RISK_25
        )

    def test_no_flags_means_normal_risk(self):
        state = correlation.build_correlation_state([])
        self.assertEqual(
            correlation.recommendation_for_correlation(state), RiskRecommendation.NORMAL_RISK
        )


if __name__ == "__main__":
    unittest.main()
