"""Tests for the ADR-034 Amendment 4 transport-default flip: `http` is
now the shipped default for `bridge.transport` (both when the JSON
config omits the key entirely and via `BridgeConfig`'s own dataclass
default), with `socket` remaining a fully-supported explicit override.
Complements `tests/titan_protocol/bridge/test_config.py`'s dataclass-
level assertions with the config-loading path an operator's JSON file
actually goes through."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.deployment_windows._fixtures import load_example_config, write_config, TEST_API_KEY_ENV_VAR
import os

from config_loader import load_settings


class TestBridgeTransportDefault(unittest.TestCase):
    def test_missing_bridge_transport_defaults_to_http(self):
        """Deletes the key entirely (not merely overriding it) so this
        proves the loader's own fallback, not just an unrelated example
        value -- config_loader.py derives this from BridgeConfig.transport
        itself, never a second hardcoded literal."""
        config = load_example_config()
        del config["bridge"]["transport"]
        os.environ[TEST_API_KEY_ENV_VAR] = "test-key-value"
        config["bridge"]["api_key_env_var"] = TEST_API_KEY_ENV_VAR
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "titan_protocol_config.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            settings = load_settings(config_path)
        self.assertEqual(settings.bridge_config.transport, "http")

    def test_explicit_socket_override_still_works(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(Path(tmp), overrides={"transport": "socket"})
            settings = load_settings(config_path)
        self.assertEqual(settings.bridge_config.transport, "socket")

    def test_explicit_http_override_still_works(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(Path(tmp), overrides={"transport": "http"})
            settings = load_settings(config_path)
        self.assertEqual(settings.bridge_config.transport, "http")

    def test_shipped_example_config_itself_defaults_to_http(self):
        """The example config an operator copies is expected to already
        state the real default explicitly (documentation-as-code) --
        this guards against the example drifting from BridgeConfig's
        own default the way it did before Amendment 4."""
        config = load_example_config()
        self.assertEqual(config["bridge"]["transport"], "http")


if __name__ == "__main__":
    unittest.main()
