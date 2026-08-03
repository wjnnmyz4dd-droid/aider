"""Unit tests: statistical metrics computed from `TradeHistory` (ADR-027
§3), including the fail-closed rule for insufficient history."""

from __future__ import annotations

import unittest

from titan_protocol.risk_engine.statistics import compute_statistical_metrics
from tests.titan_protocol.risk_engine._fixtures import make_config, make_repeating_trade_history, make_trade_history


class TestFailClosed(unittest.TestCase):
    def test_none_history_is_insufficient(self):
        config = make_config()
        metrics = compute_statistical_metrics(None, config)
        self.assertFalse(metrics.sufficient_data)
        self.assertEqual(metrics.sample_size, 0)
        self.assertIsNone(metrics.rolling_expectancy)

    def test_empty_history_is_insufficient(self):
        config = make_config()
        metrics = compute_statistical_metrics(make_trade_history([]), config)
        self.assertFalse(metrics.sufficient_data)

    def test_below_minimum_sample_size_is_insufficient(self):
        config = make_config(min_trade_history_for_statistics=20)
        history = make_repeating_trade_history(count=10)
        metrics = compute_statistical_metrics(history, config)
        self.assertFalse(metrics.sufficient_data)
        self.assertEqual(metrics.sample_size, 10)


class TestSufficientData(unittest.TestCase):
    def test_win_rate_and_expectancy(self):
        config = make_config(min_trade_history_for_statistics=20)
        history = make_repeating_trade_history(count=30, win_r=2.0, loss_r=-1.0, win_rate=0.5)
        metrics = compute_statistical_metrics(history, config)
        self.assertTrue(metrics.sufficient_data)
        self.assertAlmostEqual(metrics.win_rate, 0.5, places=2)
        self.assertAlmostEqual(metrics.loss_rate, 0.5, places=2)
        # 15 wins @ +2R, 15 losses @ -1R -> expectancy = (15*2 - 15*1)/30 = 0.5
        self.assertAlmostEqual(metrics.rolling_expectancy, 0.5, places=6)

    def test_profit_factor(self):
        config = make_config(min_trade_history_for_statistics=20)
        history = make_repeating_trade_history(count=30, win_r=2.0, loss_r=-1.0, win_rate=0.5)
        metrics = compute_statistical_metrics(history, config)
        # gross profit = 15*2=30, gross loss = 15*1=15 -> profit factor = 2.0
        self.assertAlmostEqual(metrics.profit_factor, 2.0, places=6)

    def test_max_drawdown_and_recovery_factor_are_nonnegative(self):
        config = make_config(min_trade_history_for_statistics=20)
        history = make_repeating_trade_history(count=30, win_r=2.0, loss_r=-1.0, win_rate=0.5)
        metrics = compute_statistical_metrics(history, config)
        self.assertGreaterEqual(metrics.max_drawdown_estimate, 0.0)
        self.assertIsNotNone(metrics.recovery_factor)

    def test_var_and_cvar_are_positive_loss_magnitudes(self):
        config = make_config(min_trade_history_for_statistics=20)
        history = make_repeating_trade_history(count=30, win_r=2.0, loss_r=-1.0, win_rate=0.5)
        metrics = compute_statistical_metrics(history, config)
        self.assertGreaterEqual(metrics.var_95, 0.0)
        self.assertGreaterEqual(metrics.cvar_95, metrics.var_95 - 1e-9)

    def test_ulcer_index_zero_for_monotonic_equity(self):
        config = make_config(min_trade_history_for_statistics=5)
        history = make_repeating_trade_history(count=10, win_r=1.0, loss_r=1.0, win_rate=1.0)
        metrics = compute_statistical_metrics(history, config)
        self.assertAlmostEqual(metrics.ulcer_index, 0.0, places=6)

    def test_kelly_fraction_positive_for_positive_edge(self):
        config = make_config(min_trade_history_for_statistics=20)
        history = make_repeating_trade_history(count=30, win_r=2.0, loss_r=-1.0, win_rate=0.5)
        metrics = compute_statistical_metrics(history, config)
        # p=0.5, b=2.0 -> f* = 0.5 - 0.5/2.0 = 0.25
        self.assertAlmostEqual(metrics.kelly_fraction, 0.25, places=6)

    def test_kelly_fraction_negative_for_negative_edge(self):
        config = make_config(min_trade_history_for_statistics=20)
        history = make_repeating_trade_history(count=30, win_r=1.0, loss_r=-2.0, win_rate=0.3)
        metrics = compute_statistical_metrics(history, config)
        self.assertLess(metrics.kelly_fraction, 0.0)

    def test_r_multiple_summary_matches_best_worst(self):
        config = make_config(min_trade_history_for_statistics=20)
        history = make_repeating_trade_history(count=30, win_r=3.0, loss_r=-1.5, win_rate=0.5)
        metrics = compute_statistical_metrics(history, config)
        self.assertAlmostEqual(metrics.r_multiple_summary.best, 3.0)
        self.assertAlmostEqual(metrics.r_multiple_summary.worst, -1.5)
        self.assertEqual(metrics.r_multiple_summary.count, 30)

    def test_risk_of_ruin_is_a_probability(self):
        config = make_config(min_trade_history_for_statistics=20, risk_of_ruin_simulations=200, monte_carlo_sequence_length=20)
        history = make_repeating_trade_history(count=30, win_r=2.0, loss_r=-1.0, win_rate=0.5)
        metrics = compute_statistical_metrics(history, config)
        self.assertGreaterEqual(metrics.risk_of_ruin, 0.0)
        self.assertLessEqual(metrics.risk_of_ruin, 1.0)

    def test_deterministic_across_repeated_calls(self):
        config = make_config(min_trade_history_for_statistics=20)
        history = make_repeating_trade_history(count=30, win_r=2.0, loss_r=-1.0, win_rate=0.5)
        first = compute_statistical_metrics(history, config)
        second = compute_statistical_metrics(history, config)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
