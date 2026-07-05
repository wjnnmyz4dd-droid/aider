"""Config tests (ADR-011 §9) — per-component heartbeat interval overrides."""

from __future__ import annotations

import unittest

from phantom_pipeline.watchdog.config import WatchdogConfig


class TestWatchdogConfig(unittest.TestCase):
    def test_default_interval_used_when_no_override(self):
        config = WatchdogConfig(default_heartbeat_interval_seconds=15.0)
        self.assertEqual(config.heartbeat_interval_for("scanner"), 15.0)

    def test_override_used_when_present(self):
        config = WatchdogConfig(
            default_heartbeat_interval_seconds=15.0,
            heartbeat_interval_overrides={"mt5_bridge": 5.0},
        )
        self.assertEqual(config.heartbeat_interval_for("mt5_bridge"), 5.0)
        self.assertEqual(config.heartbeat_interval_for("scanner"), 15.0)

    def test_config_is_frozen(self):
        config = WatchdogConfig()
        with self.assertRaises(Exception):
            config.default_heartbeat_interval_seconds = 999.0


if __name__ == "__main__":
    unittest.main()
