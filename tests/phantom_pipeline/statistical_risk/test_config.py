from __future__ import annotations

import unittest

from phantom_pipeline.statistical_risk.config import DEFAULT_CONFIG, StatisticalRiskConfig


class TestStatisticalRiskConfig(unittest.TestCase):
    def test_default_config_is_frozen(self):
        with self.assertRaises(Exception):
            DEFAULT_CONFIG.rolling_window_trades = 5  # type: ignore[misc]

    def test_defaults_are_positive_and_sane(self):
        self.assertGreater(DEFAULT_CONFIG.rolling_window_trades, 0)
        self.assertGreater(DEFAULT_CONFIG.min_sample_size, 0)
        self.assertGreater(DEFAULT_CONFIG.monte_carlo_iterations, 0)
        self.assertTrue(0.0 < DEFAULT_CONFIG.var_confidence_level < 1.0)
        self.assertTrue(0.0 < DEFAULT_CONFIG.cvar_confidence_level < 1.0)

    def test_overridable(self):
        custom = StatisticalRiskConfig(rolling_window_trades=10)
        self.assertEqual(custom.rolling_window_trades, 10)
        self.assertEqual(custom.min_sample_size, DEFAULT_CONFIG.min_sample_size)


if __name__ == "__main__":
    unittest.main()
