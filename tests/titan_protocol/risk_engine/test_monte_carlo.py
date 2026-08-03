"""Monte Carlo verification tests (ADR-027 §3, Hard Rule 7): seeded
determinism, advisory-only scope, and sane statistical shape."""

from __future__ import annotations

import unittest

from titan_protocol.risk_engine.monte_carlo import percentile, run_monte_carlo, simulate_equity_paths
from tests.titan_protocol.risk_engine._fixtures import make_config, make_repeating_trade_history, make_trade_history


class TestSeededDeterminism(unittest.TestCase):
    def test_same_seed_same_history_reproduces_identical_paths(self):
        r_multiples = [1.0, -1.0, 2.0, -1.0, 1.5]
        first = simulate_equity_paths(r_multiples, seed=42, num_simulations=50, path_length=20)
        second = simulate_equity_paths(r_multiples, seed=42, num_simulations=50, path_length=20)
        self.assertEqual(first, second)

    def test_different_seed_produces_different_paths(self):
        r_multiples = [1.0, -1.0, 2.0, -1.0, 1.5]
        first = simulate_equity_paths(r_multiples, seed=1, num_simulations=50, path_length=20)
        second = simulate_equity_paths(r_multiples, seed=2, num_simulations=50, path_length=20)
        self.assertNotEqual(first, second)

    def test_empty_r_multiples_produces_no_paths(self):
        self.assertEqual(simulate_equity_paths([], seed=1, num_simulations=10, path_length=5), [])

    def test_run_monte_carlo_deterministic_across_calls(self):
        config = make_config(min_trade_history_for_statistics=20)
        history = make_repeating_trade_history(count=30, win_r=2.0, loss_r=-1.0, win_rate=0.5)
        first = run_monte_carlo(history, config)
        second = run_monte_carlo(history, config)
        self.assertEqual(first, second)


class TestAdvisoryOnly(unittest.TestCase):
    def test_insufficient_history_returns_none(self):
        config = make_config(min_trade_history_for_statistics=20)
        self.assertIsNone(run_monte_carlo(None, config))
        self.assertIsNone(run_monte_carlo(make_trade_history([]), config))

    def test_result_shape_is_sane(self):
        config = make_config(min_trade_history_for_statistics=20, monte_carlo_simulations=200, monte_carlo_sequence_length=20)
        history = make_repeating_trade_history(count=30, win_r=2.0, loss_r=-1.0, win_rate=0.5)
        result = run_monte_carlo(history, config)
        self.assertIsNotNone(result)
        self.assertEqual(result.simulations_run, 200)
        self.assertEqual(result.seed, config.monte_carlo_seed)
        self.assertLessEqual(result.expected_equity_low, result.expected_equity_high)
        self.assertGreaterEqual(result.expected_drawdown, 0.0)
        self.assertGreaterEqual(result.worst_case_drawdown, result.expected_drawdown - 1e-9)
        percentiles = dict(result.confidence_intervals)
        self.assertEqual(set(percentiles.keys()), {5, 25, 50, 75, 95})


class TestPercentile(unittest.TestCase):
    def test_empty_sequence_is_zero(self):
        self.assertEqual(percentile([], 50), 0.0)

    def test_single_value(self):
        self.assertEqual(percentile([7.0], 50), 7.0)

    def test_median_of_odd_length(self):
        self.assertAlmostEqual(percentile([1.0, 2.0, 3.0], 50), 2.0)


if __name__ == "__main__":
    unittest.main()
