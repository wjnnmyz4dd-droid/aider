from __future__ import annotations

import unittest

from phantom_pipeline.statistical_risk import probability
from phantom_pipeline.statistical_risk.config import StatisticalRiskConfig


class TestProbabilityFunctions(unittest.TestCase):
    def setUp(self):
        self.config = StatisticalRiskConfig(monte_carlo_iterations=100)
        self.pnls = [10.0, -20.0, 15.0, -30.0, 25.0, -10.0]

    def test_daily_drawdown_limit_probability_is_bounded(self):
        value = probability.probability_of_reaching_daily_drawdown_limit(
            self.pnls, 1000.0, seed=1, config=self.config
        )
        self.assertIsNotNone(value)
        self.assertGreaterEqual(value, 0.0)
        self.assertLessEqual(value, 1.0)

    def test_total_drawdown_limit_probability_is_bounded(self):
        value = probability.probability_of_reaching_total_drawdown_limit(
            self.pnls, 1000.0, seed=1, config=self.config
        )
        self.assertIsNotNone(value)
        self.assertGreaterEqual(value, 0.0)
        self.assertLessEqual(value, 1.0)

    def test_risk_of_ruin_is_bounded(self):
        value = probability.risk_of_ruin(self.pnls, 1000.0, seed=1, config=self.config)
        self.assertIsNotNone(value)
        self.assertGreaterEqual(value, 0.0)
        self.assertLessEqual(value, 1.0)

    def test_none_with_no_historical_data(self):
        self.assertIsNone(probability.risk_of_ruin([], 1000.0, seed=1, config=self.config))

    def test_daily_limit_is_no_stricter_than_total_limit_probability_ordering(self):
        # Daily limit (5%) is tighter than total limit (10%) by default,
        # so breaching the daily threshold should be at least as likely.
        daily = probability.probability_of_reaching_daily_drawdown_limit(
            self.pnls, 1000.0, seed=5, config=self.config
        )
        total = probability.probability_of_reaching_total_drawdown_limit(
            self.pnls, 1000.0, seed=5, config=self.config
        )
        self.assertGreaterEqual(daily, total)


if __name__ == "__main__":
    unittest.main()
