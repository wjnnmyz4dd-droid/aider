"""`BridgeConfig` immutability and defaults (Phase 1)."""

from __future__ import annotations

import dataclasses
import unittest

from titan_protocol.bridge.config import BRIDGE_VERSION, VALID_TRANSPORTS, BridgeConfig


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


class TestSocketTransportFields(unittest.TestCase):
    """ADR-034 (Amendment 7) -- socket is the shipped default; http
    remains fully supported as an explicit rollback."""

    def test_transport_defaults_to_socket(self):
        config = BridgeConfig(api_key="k", allowed_symbols=("EURUSD",))
        self.assertEqual(config.transport, "socket")

    def test_transport_http_rollback_is_accepted(self):
        config = BridgeConfig(api_key="k", allowed_symbols=("EURUSD",), transport="http")
        self.assertEqual(config.transport, "http")

    def test_invalid_transport_rejected(self):
        with self.assertRaises(ValueError):
            BridgeConfig(api_key="k", allowed_symbols=("EURUSD",), transport="carrier-pigeon")

    def test_valid_transports_contains_exactly_http_and_socket(self):
        self.assertEqual(set(VALID_TRANSPORTS), {"http", "socket"})

    def test_socket_field_defaults(self):
        config = BridgeConfig(api_key="k", allowed_symbols=("EURUSD",))
        self.assertEqual(config.socket_port, 8788)
        self.assertEqual(config.socket_max_message_bytes, 65536)
        self.assertEqual(config.socket_idle_timeout_seconds, 60.0)
        self.assertEqual(config.socket_max_connections, 8)


if __name__ == "__main__":
    unittest.main()
