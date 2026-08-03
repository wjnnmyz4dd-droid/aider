from __future__ import annotations

import unittest

from phantom_pipeline.statistical_risk import expectancy
from phantom_pipeline.statistical_risk.config import StatisticalRiskConfig

from ._fixtures import make_open_record, make_records


class TestClosedTradePnls(unittest.TestCase):
    def test_only_closed_trades_counted(self):
        records = make_records([10.0, -5.0]) + (make_open_record("open-1"),)
        pnls = expectancy.closed_trade_pnls(records)
        self.assertEqual(pnls, [10.0, -5.0])

    def test_empty_when_none_closed(self):
        self.assertEqual(expectancy.closed_trade_pnls((make_open_record("open-1"),)), [])


class TestRollingWindow(unittest.TestCase):
    def test_window_limits_to_last_n_trades(self):
        pnls_input = list(range(50))
        records = make_records([float(p) for p in pnls_input])
        config = StatisticalRiskConfig(rolling_window_trades=5)
        windowed = expectancy.rolling_window_pnls(records, config)
        self.assertEqual(windowed, [45.0, 46.0, 47.0, 48.0, 49.0])

    def test_zero_window_means_unbounded(self):
        records = make_records([1.0, 2.0, 3.0])
        config = StatisticalRiskConfig(rolling_window_trades=0)
        self.assertEqual(expectancy.rolling_window_pnls(records, config), [1.0, 2.0, 3.0])


class TestRollingStatistics(unittest.TestCase):
    def test_win_rate(self):
        self.assertEqual(expectancy.rolling_win_rate([10.0, -5.0, 10.0, -5.0]), 0.5)

    def test_win_rate_empty(self):
        self.assertIsNone(expectancy.rolling_win_rate([]))

    def test_profit_factor(self):
        # gross profit 20, gross loss 10 -> 2.0
        self.assertEqual(expectancy.rolling_profit_factor([10.0, 10.0, -10.0]), 2.0)

    def test_profit_factor_no_losses_is_infinite(self):
        self.assertEqual(expectancy.rolling_profit_factor([10.0, 5.0]), float("inf"))

    def test_profit_factor_no_trades_is_none(self):
        self.assertIsNone(expectancy.rolling_profit_factor([0.0]))

    def test_expectancy(self):
        self.assertEqual(expectancy.rolling_expectancy([10.0, -10.0, 20.0]), 20.0 / 3)

    def test_sharpe_requires_two_samples(self):
        self.assertIsNone(expectancy.rolling_sharpe_ratio([10.0]))

    def test_sharpe_zero_variance_is_none(self):
        self.assertIsNone(expectancy.rolling_sharpe_ratio([5.0, 5.0, 5.0]))

    def test_sortino_requires_a_loss(self):
        self.assertIsNone(expectancy.rolling_sortino_ratio([10.0, 20.0]))

    def test_sortino_computed_with_losses(self):
        result = expectancy.rolling_sortino_ratio([10.0, -5.0, 10.0, -5.0])
        self.assertIsNotNone(result)


class TestConfidenceIntervalBounds(unittest.TestCase):
    def test_none_with_fewer_than_two_samples(self):
        lower, upper = expectancy.confidence_interval_bounds([10.0], 0.95)
        self.assertIsNone(lower)
        self.assertIsNone(upper)

    def test_bounds_straddle_the_mean(self):
        lower, upper = expectancy.confidence_interval_bounds([10.0, -10.0, 20.0, -20.0], 0.95)
        mean = sum([10.0, -10.0, 20.0, -20.0]) / 4
        self.assertLessEqual(lower, mean)
        self.assertGreaterEqual(upper, mean)


if __name__ == "__main__":
    unittest.main()
