"""`BridgeConfig` immutability and defaults (Phase 1)."""

from __future__ import annotations

import dataclasses
import unittest

from phantom.bridge.config import BRIDGE_VERSION, BridgeConfig


class TestBridgeConfig(unittest.TestCase):
    def test_is_frozen(self):
        config = BridgeConfig(api_key="k", allowed_symbols=("EURUSD",))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            config.api_key = "other"  # type: ignore[misc]

    def test_allowed_symbols_is_coerced_to_tuple(self):
        config = BridgeConfig(api_key="k", allowed_symbols=["EURUSD", "GBPUSD"])
        self.assertEqual(config.allowed_symbols, ("EURUSD", "GBPUSD"))

    def test_api_key_has_no_default(self):
        with self.assertRaises(TypeError):
            BridgeConfig(allowed_symbols=("EURUSD",))  # type: ignore[call-arg]

    def test_version_string_is_set(self):
        self.assertTrue(BRIDGE_VERSION)


if __name__ == "__main__":
    unittest.main()
