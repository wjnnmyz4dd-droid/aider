from __future__ import annotations

import unittest

from phantom_pipeline.scanner.models import VolatilityLabel
from phantom_pipeline.statistical_risk.models import (
    ConfidenceInterval,
    CorrelationState,
    MonteCarloResult,
    RiskRecommendation,
    StatisticalRiskAssessment,
    VolatilityState,
)


class TestRiskRecommendation(unittest.TestCase):
    def test_exactly_four_values(self):
        self.assertEqual(
            {member.value for member in RiskRecommendation},
            {"NORMAL_RISK", "REDUCE_RISK_25", "REDUCE_RISK_50", "SKIP_HIGH_RISK"},
        )


class TestStatisticalRiskAssessmentImmutable(unittest.TestCase):
    def _make(self) -> StatisticalRiskAssessment:
        return StatisticalRiskAssessment(
            schema_version=1,
            trace_id="trace-1",
            confidence_score=0.5,
            risk_of_ruin=0.01,
            probability_of_drawdown=0.02,
            expected_drawdown=10.0,
            expected_return=5.0,
            rolling_expectancy=1.0,
            rolling_profit_factor=1.5,
            rolling_win_rate=0.5,
            sharpe_ratio=0.3,
            sortino_ratio=0.4,
            value_at_risk=8.0,
            conditional_value_at_risk=10.0,
            portfolio_heat=2.0,
            volatility_state=VolatilityState(VolatilityLabel.NORMAL, 0.001, 0.0002, 1.0),
            correlation_state=CorrelationState({"EUR": 1}, "EUR", 1, ()),
            statistical_recommendation=RiskRecommendation.NORMAL_RISK,
        )

    def test_frozen(self):
        assessment = self._make()
        with self.assertRaises(Exception):
            assessment.confidence_score = 0.9  # type: ignore[misc]

    def test_has_exactly_18_fields(self):
        assessment = self._make()
        field_names = set(assessment.__dataclass_fields__.keys())
        self.assertEqual(len(field_names), 18)

    def test_no_field_named_like_a_decision_verb(self):
        forbidden = ("decide", "approve", "reject", "execute", "size_", "submit")
        for name in StatisticalRiskAssessment.__dataclass_fields__:
            lowered = name.lower()
            for fragment in forbidden:
                self.assertNotIn(fragment, lowered)


class TestCorrelationStateCoercion(unittest.TestCase):
    def test_mapping_and_tuple_coercion(self):
        state = CorrelationState(
            bucket_exposure_count={"EUR": 2}, most_concentrated_bucket="EUR",
            max_bucket_concentration_count=2, flagged_buckets=["EUR"],
        )
        self.assertIsInstance(state.flagged_buckets, tuple)
        self.assertEqual(state.bucket_exposure_count, {"EUR": 2})


class TestConfidenceInterval(unittest.TestCase):
    def test_none_bounds_allowed(self):
        interval = ConfidenceInterval(
            trace_id="t", point_estimate=None, lower_bound=None, upper_bound=None,
            confidence_level=0.95, sample_size=0,
        )
        self.assertIsNone(interval.point_estimate)


class TestMonteCarloResult(unittest.TestCase):
    def test_fields(self):
        result = MonteCarloResult(
            iterations=100, seed=1, starting_equity=1000.0, mean_final_equity=1010.0,
            median_final_equity=1005.0, worst_final_equity=900.0, best_final_equity=1100.0,
            probability_of_ruin=0.01, mean_max_drawdown_pct=5.0,
        )
        self.assertEqual(result.iterations, 100)


if __name__ == "__main__":
    unittest.main()
