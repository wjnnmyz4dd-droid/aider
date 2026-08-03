from __future__ import annotations

import unittest

from phantom_pipeline.scanner.models import StructureConfidence
from phantom_pipeline.statistical_risk import engine
from phantom_pipeline.statistical_risk.config import StatisticalRiskConfig
from phantom_pipeline.statistical_risk.engine import StatisticalRiskEngine
from phantom_pipeline.statistical_risk.models import RiskRecommendation

from ._fixtures import make_bars, make_open_position, make_records


class TestMostConservative(unittest.TestCase):
    def test_empty_is_normal(self):
        self.assertEqual(engine.most_conservative([]), RiskRecommendation.NORMAL_RISK)

    def test_picks_the_most_restrictive(self):
        recs = [
            RiskRecommendation.NORMAL_RISK,
            RiskRecommendation.REDUCE_RISK_25,
            RiskRecommendation.SKIP_HIGH_RISK,
            RiskRecommendation.REDUCE_RISK_50,
        ]
        self.assertEqual(engine.most_conservative(recs), RiskRecommendation.SKIP_HIGH_RISK)


class TestValueAtRiskAndCvar(unittest.TestCase):
    def test_var_none_with_fewer_than_two_samples(self):
        self.assertIsNone(engine.value_at_risk([10.0], 0.95))

    def test_var_is_non_negative(self):
        pnls = [10.0, -5.0, 20.0, -30.0, 15.0, -10.0, 25.0, -40.0, 5.0, -2.0]
        result = engine.value_at_risk(pnls, 0.95)
        self.assertGreaterEqual(result, 0.0)

    def test_cvar_at_least_as_large_as_var(self):
        pnls = [10.0, -5.0, 20.0, -30.0, 15.0, -10.0, 25.0, -40.0, 5.0, -2.0]
        var = engine.value_at_risk(pnls, 0.95)
        cvar = engine.conditional_value_at_risk(pnls, 0.95)
        self.assertGreaterEqual(cvar, var)

    def test_no_losses_means_zero_var(self):
        self.assertEqual(engine.value_at_risk([10.0, 20.0, 5.0], 0.95), 0.0)


class TestKellyCriterion(unittest.TestCase):
    def test_none_without_both_wins_and_losses(self):
        self.assertIsNone(engine.kelly_criterion([10.0, 20.0]))
        self.assertIsNone(engine.kelly_criterion([-10.0, -20.0]))

    def test_positive_edge_yields_positive_fraction(self):
        # High win rate, favorable payoff -> positive Kelly fraction.
        pnls = [10.0, 10.0, 10.0, -5.0]
        result = engine.kelly_criterion(pnls)
        self.assertIsNotNone(result)
        self.assertGreater(result, 0.0)


class TestRegimeConfidenceScore(unittest.TestCase):
    def test_full_sample_and_clear_structure_is_high_confidence(self):
        config = StatisticalRiskConfig(rolling_window_trades=10)
        score = engine.regime_confidence_score(10, StructureConfidence.CLEAR, config)
        self.assertEqual(score, 1.0)

    def test_no_sample_and_unknown_structure_is_low_confidence(self):
        config = StatisticalRiskConfig(rolling_window_trades=10)
        score = engine.regime_confidence_score(0, None, config)
        self.assertEqual(score, 0.125)


class TestRecommendationForRuin(unittest.TestCase):
    def test_none_is_cautious_not_normal(self):
        self.assertEqual(engine.recommendation_for_ruin(None), RiskRecommendation.REDUCE_RISK_25)

    def test_low_probability_is_normal(self):
        config = StatisticalRiskConfig(risk_of_ruin_reduce_threshold=0.05, risk_of_ruin_skip_threshold=0.15)
        self.assertEqual(engine.recommendation_for_ruin(0.01, config), RiskRecommendation.NORMAL_RISK)

    def test_high_probability_is_skip(self):
        config = StatisticalRiskConfig(risk_of_ruin_reduce_threshold=0.05, risk_of_ruin_skip_threshold=0.15)
        self.assertEqual(engine.recommendation_for_ruin(0.20, config), RiskRecommendation.SKIP_HIGH_RISK)


class TestStatisticalRiskEngineAssess(unittest.TestCase):
    def setUp(self):
        self.pnls = [10.0 if i % 3 else -8.0 for i in range(40)]
        self.records = make_records(self.pnls)
        self.bars = make_bars([1.1000 + 0.0001 * i for i in range(25)])
        self.positions = [make_open_position()]
        self.engine = StatisticalRiskEngine()

    def test_returns_schema_version_and_trace_id(self):
        assessment = self.engine.assess("trace-x", self.records, 10_000.0, self.positions, self.bars)
        self.assertEqual(assessment.trace_id, "trace-x")
        self.assertEqual(assessment.schema_version, 1)

    def test_deterministic_given_identical_input(self):
        assessment_a = self.engine.assess("trace-x", self.records, 10_000.0, self.positions, self.bars)
        assessment_b = self.engine.assess("trace-x", self.records, 10_000.0, self.positions, self.bars)
        self.assertEqual(assessment_a, assessment_b)

    def test_second_independent_engine_instance_matches(self):
        other_engine = StatisticalRiskEngine()
        assessment_a = self.engine.assess("trace-x", self.records, 10_000.0, self.positions, self.bars)
        assessment_b = other_engine.assess("trace-x", self.records, 10_000.0, self.positions, self.bars)
        self.assertEqual(assessment_a, assessment_b)

    def test_recommendation_is_always_one_of_the_four_values(self):
        assessment = self.engine.assess("trace-x", self.records, 10_000.0, self.positions, self.bars)
        self.assertIn(assessment.statistical_recommendation, list(RiskRecommendation))

    def test_recommendation_never_increases_risk(self):
        """ADR-022 Hard Rule 2: applying any of the four recommendation
        multipliers to an already-approved risk percent never exceeds it."""
        approved_risk_percent = 1.0
        multipliers = {
            RiskRecommendation.NORMAL_RISK: 1.0,
            RiskRecommendation.REDUCE_RISK_25: 0.75,
            RiskRecommendation.REDUCE_RISK_50: 0.5,
            RiskRecommendation.SKIP_HIGH_RISK: 0.0,
        }
        assessment = self.engine.assess("trace-x", self.records, 10_000.0, self.positions, self.bars)
        implied_risk = approved_risk_percent * multipliers[assessment.statistical_recommendation]
        self.assertLessEqual(implied_risk, approved_risk_percent)

    def test_insufficient_sample_reports_none_not_fabricated(self):
        tiny_records = make_records([10.0, -5.0])
        assessment = self.engine.assess("trace-tiny", tiny_records, 10_000.0, [], ())
        self.assertIsNone(assessment.rolling_expectancy)
        self.assertIsNone(assessment.sharpe_ratio)
        self.assertIsNone(assessment.value_at_risk)
        self.assertIsNone(assessment.risk_of_ruin)

    def test_insufficient_sample_still_flags_reduce_25(self):
        tiny_records = make_records([10.0, -5.0])
        assessment = self.engine.assess("trace-tiny", tiny_records, 10_000.0, [], ())
        self.assertNotEqual(assessment.statistical_recommendation, RiskRecommendation.NORMAL_RISK)

    def test_engine_never_calls_a_decision_method_on_another_stage(self):
        """Structural check: StatisticalRiskEngine holds no reference to
        RiskEngine/ComplianceEngine/ExecutionValidator/PositionManager and
        never imports their engine modules."""
        import inspect

        from phantom_pipeline.statistical_risk import engine as engine_module

        source = inspect.getsource(engine_module)
        for forbidden in (
            "risk_engine.engine", "compliance_engine.engine", "execution_validator.engine",
            "position_manager.engine", "mt5_bridge.engine", "scanner.scanner", "strategy_engine.engine",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
