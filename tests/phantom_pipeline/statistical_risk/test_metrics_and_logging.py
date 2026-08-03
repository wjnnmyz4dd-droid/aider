from __future__ import annotations

import unittest

from phantom_pipeline.scanner.models import VolatilityLabel
from phantom_pipeline.statistical_risk.logging_sink import log_assessment
from phantom_pipeline.statistical_risk.metrics import StatisticalRiskMetrics
from phantom_pipeline.statistical_risk.models import (
    CorrelationState,
    RiskRecommendation,
    StatisticalRiskAssessment,
    VolatilityState,
)


def _make_assessment(recommendation: RiskRecommendation) -> StatisticalRiskAssessment:
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
        correlation_state=CorrelationState({}, None, 0, ()),
        statistical_recommendation=recommendation,
    )


class TestStatisticalRiskMetrics(unittest.TestCase):
    def test_records_count_and_recommendation_breakdown(self):
        metrics = StatisticalRiskMetrics()
        metrics.record_assessment(_make_assessment(RiskRecommendation.NORMAL_RISK))
        metrics.record_assessment(_make_assessment(RiskRecommendation.REDUCE_RISK_25))
        metrics.record_assessment(_make_assessment(RiskRecommendation.REDUCE_RISK_25))

        self.assertEqual(metrics.assessment_count, 3)
        self.assertEqual(
            metrics.assessments_by_recommendation, {"NORMAL_RISK": 1, "REDUCE_RISK_25": 2}
        )

    def test_recording_never_mutates_the_assessment(self):
        metrics = StatisticalRiskMetrics()
        assessment = _make_assessment(RiskRecommendation.NORMAL_RISK)
        metrics.record_assessment(assessment)
        self.assertEqual(assessment.statistical_recommendation, RiskRecommendation.NORMAL_RISK)


class TestLogAssessment(unittest.TestCase):
    def test_logging_never_raises(self):
        assessment = _make_assessment(RiskRecommendation.SKIP_HIGH_RISK)
        try:
            log_assessment(assessment)
        except Exception as exc:  # pragma: no cover - failure path
            self.fail(f"log_assessment raised: {exc}")


if __name__ == "__main__":
    unittest.main()
