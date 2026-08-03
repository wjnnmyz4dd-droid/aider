from __future__ import annotations

import unittest

from phantom_pipeline.statistical_risk import monte_carlo
from phantom_pipeline.statistical_risk.config import StatisticalRiskConfig


class TestDeriveSeed(unittest.TestCase):
    def test_same_trace_id_same_seed(self):
        config = StatisticalRiskConfig()
        self.assertEqual(monte_carlo.derive_seed("trace-1", config), monte_carlo.derive_seed("trace-1", config))

    def test_different_trace_id_different_seed(self):
        config = StatisticalRiskConfig()
        self.assertNotEqual(monte_carlo.derive_seed("trace-1", config), monte_carlo.derive_seed("trace-2", config))

    def test_stable_across_process_boundary_via_hashlib(self):
        # Regression guard: must not use the builtin, PYTHONHASHSEED-randomized
        # hash() for strings -- that would break determinism across processes.
        import inspect

        source = inspect.getsource(monte_carlo)
        self.assertIn("hashlib", source)
        self.assertNotIn("hash(trace_id)", source)


class TestSimulate(unittest.TestCase):
    def test_empty_pnls_is_none(self):
        self.assertIsNone(monte_carlo.simulate([], 1000.0, 50.0, seed=1))

    def test_non_positive_equity_is_none(self):
        self.assertIsNone(monte_carlo.simulate([10.0, -5.0], 0.0, 50.0, seed=1))

    def test_deterministic_given_same_seed(self):
        pnls = [10.0, -5.0, 20.0, -10.0, 15.0]
        result_a = monte_carlo.simulate(pnls, 1000.0, 50.0, seed=42)
        result_b = monte_carlo.simulate(pnls, 1000.0, 50.0, seed=42)
        self.assertEqual(result_a, result_b)

    def test_different_seed_can_differ(self):
        pnls = [10.0, -50.0, 20.0, -80.0, 15.0]
        result_a = monte_carlo.simulate(pnls, 1000.0, 50.0, seed=1)
        result_b = monte_carlo.simulate(pnls, 1000.0, 50.0, seed=2)
        # Not asserting inequality (they *could* coincidentally match) --
        # only that both are valid, well-formed results.
        self.assertEqual(result_a.iterations, result_b.iterations)

    def test_probability_of_ruin_is_between_zero_and_one(self):
        pnls = [10.0] * 20 + [-500.0] * 5
        config = StatisticalRiskConfig(monte_carlo_iterations=200)
        result = monte_carlo.simulate(pnls, 1000.0, 50.0, seed=7, config=config)
        self.assertGreaterEqual(result.probability_of_ruin, 0.0)
        self.assertLessEqual(result.probability_of_ruin, 1.0)

    def test_all_winning_trades_means_zero_ruin_probability(self):
        pnls = [10.0, 20.0, 5.0, 15.0]
        config = StatisticalRiskConfig(monte_carlo_iterations=50)
        result = monte_carlo.simulate(pnls, 1000.0, 50.0, seed=3, config=config)
        self.assertEqual(result.probability_of_ruin, 0.0)
        self.assertEqual(result.mean_max_drawdown_pct, 0.0)


if __name__ == "__main__":
    unittest.main()
