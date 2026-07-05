"""Config tests (ADR-012 §5) — per-view component filters."""

from __future__ import annotations

import unittest

from phantom_pipeline.dashboard.config import DashboardConfig


class TestDashboardConfig(unittest.TestCase):
    def test_defaults_match_adr_named_components(self):
        config = DashboardConfig()
        self.assertEqual(config.trading_components, ("scanner", "strategy_engine", "scoring_engine"))
        self.assertEqual(config.risk_components, ("risk_engine",))
        self.assertEqual(config.compliance_components, ("compliance_engine",))
        self.assertEqual(config.execution_components, ("execution_validator", "mt5_bridge"))
        self.assertIn("watchdog", config.infrastructure_components)

    def test_config_is_frozen(self):
        config = DashboardConfig()
        with self.assertRaises(Exception):
            config.trading_components = ()


if __name__ == "__main__":
    unittest.main()
