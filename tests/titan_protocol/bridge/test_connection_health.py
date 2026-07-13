"""`ConnectionHealth` tests -- liveness monitoring, distinct from the
command queue's authorization state (Phase 1)."""

from __future__ import annotations

import unittest
from datetime import timedelta

from titan_protocol.bridge.connection_health import ConnectionHealth
from tests.titan_protocol.bridge._fixtures import T0, make_config


class TestConnectionHealth(unittest.TestCase):
    def test_not_ready_before_any_heartbeat(self):
        health = ConnectionHealth(make_config(), clock=lambda: T0)
        self.assertFalse(health.is_ready())
        self.assertTrue(health.is_fail_closed())

    def test_ready_within_timeout(self):
        config = make_config(heartbeat_timeout_seconds=30.0)
        health = ConnectionHealth(config, clock=lambda: T0 + timedelta(seconds=10))
        health.record_heartbeat(T0)
        self.assertTrue(health.is_ready())
        self.assertFalse(health.is_fail_closed())

    def test_not_ready_outside_timeout(self):
        config = make_config(heartbeat_timeout_seconds=30.0)
        health = ConnectionHealth(config, clock=lambda: T0 + timedelta(seconds=60))
        health.record_heartbeat(T0)
        self.assertFalse(health.is_ready())
        self.assertTrue(health.is_fail_closed())

    def test_reset_clears_heartbeat(self):
        health = ConnectionHealth(make_config(), clock=lambda: T0)
        health.record_heartbeat(T0)
        health.reset()
        self.assertFalse(health.is_ready())
        self.assertIsNone(health.last_heartbeat_at)

    def test_last_heartbeat_at_tracks_most_recent(self):
        health = ConnectionHealth(make_config(), clock=lambda: T0)
        health.record_heartbeat(T0)
        later = T0 + timedelta(seconds=5)
        health.record_heartbeat(later)
        self.assertEqual(health.last_heartbeat_at, later)


if __name__ == "__main__":
    unittest.main()
