"""MT5BridgeConfig immutability tests (ADR-008 §4, §6)."""

from __future__ import annotations

import dataclasses
import unittest

from phantom_pipeline.mt5_bridge.config import MT5BridgeConfig


class TestMT5BridgeConfigImmutability(unittest.TestCase):
    def test_top_level_fields_cannot_be_reassigned(self):
        config = MT5BridgeConfig()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            config.heartbeat_timeout_seconds = 999.0  # type: ignore[misc]

    def test_defaults_are_sane(self):
        config = MT5BridgeConfig()
        self.assertGreater(config.reconnect_max_attempts, 0)
        self.assertGreater(config.heartbeat_timeout_seconds, config.heartbeat_interval_seconds)


if __name__ == "__main__":
    unittest.main()
