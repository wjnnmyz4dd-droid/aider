from __future__ import annotations

import unittest

from phantom_pipeline.statistical_risk import drawdown
from phantom_pipeline.statistical_risk.models import MonteCarloResult


class TestRollingMaxDrawdown(unittest.TestCase):
    def test_empty_is_none(self):
        self.assertIsNone(drawdown.rolling_max_drawdown([]))

    def test_simple_peak_to_trough(self):
        # cumulative: 10, 20, 10, 15 -> peak 20, trough 10 -> drawdown 10
        self.assertEqual(drawdown.rolling_max_drawdown([10.0, 10.0, -10.0, 5.0]), 10.0)

    def test_monotonic_gains_have_zero_drawdown(self):
        self.assertEqual(drawdown.rolling_max_drawdown([10.0, 10.0, 10.0]), 0.0)


class TestExpectedDrawdown(unittest.TestCase):
    def test_none_when_no_simulation(self):
        self.assertIsNone(drawdown.expected_drawdown(None))

    def test_reads_mean_max_drawdown_pct(self):
        result = MonteCarloResult(
            iterations=10, seed=1, starting_equity=1000.0, mean_final_equity=1000.0,
            median_final_equity=1000.0, worst_final_equity=900.0, best_final_equity=1100.0,
            probability_of_ruin=0.0, mean_max_drawdown_pct=7.5,
        )
        self.assertEqual(drawdown.expected_drawdown(result), 7.5)


if __name__ == "__main__":
    unittest.main()
