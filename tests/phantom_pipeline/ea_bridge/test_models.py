"""EA Bridge transport model immutability (`ADR-023` §4)."""

from __future__ import annotations

import dataclasses
import unittest

from phantom_pipeline.ea_bridge.models import HeartbeatMessage, SCHEMA_VERSION
from tests.phantom_pipeline.ea_bridge._fixtures import T0


class TestModelsAreFrozen(unittest.TestCase):
    def test_heartbeat_message_is_frozen(self):
        message = HeartbeatMessage(
            schema_version=SCHEMA_VERSION,
            magic_number=20260708,
            terminal_time=T0,
            account_login=12345,
            connected=True,
            received_at=T0,
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            message.connected = False  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
