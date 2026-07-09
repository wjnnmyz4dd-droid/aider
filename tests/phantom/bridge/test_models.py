"""PhantomBridgeEA model immutability tests (Phase 1)."""

from __future__ import annotations

import dataclasses
import unittest

from phantom.bridge.models import HeartbeatMessage, SCHEMA_VERSION
from tests.phantom.bridge._fixtures import T0


class TestModelsAreFrozen(unittest.TestCase):
    def test_heartbeat_message_is_frozen(self):
        message = HeartbeatMessage(
            schema_version=SCHEMA_VERSION,
            magic_number=20260709,
            account_login=12345,
            terminal_connected=True,
            received_at=T0,
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            message.terminal_connected = False  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
