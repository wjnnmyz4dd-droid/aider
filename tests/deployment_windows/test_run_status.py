"""Tests for the Run Status diagnostics (item 10): a single,
health.json-backed view an operator can read to determine why Titan is
or is not trading, without cross-referencing bridge_reachable/
mt5_connected/live_cycle separately or grepping the log file.

Covers `_LiveCycleStatus`'s new compliance-lock/pair-status/
last-submitted-correlation_id fields and `_write_health_snapshot()`'s
new `run_status` block."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ._fixtures import DEPLOYMENT_DIR  # noqa: F401 -- ensures deployment_windows/ is on sys.path

import start

from tests.titan_protocol.bridge._fixtures import make_config as make_bridge_config
from titan_protocol.bridge.command_queue import CommandQueue
from titan_protocol.bridge.connection_health import ConnectionHealth
from titan_protocol.bridge.engine import BridgeEngine
from titan_protocol.bridge.metrics import BridgeMetrics
from titan_protocol.bridge.models import AccountState, HeartbeatMessage, PositionDirection, PositionReport, SCHEMA_VERSION
from titan_protocol.reliability.config import ReliabilityConfig
from titan_protocol.reliability.engine import ReliabilityEngine
from titan_protocol.runtime.in_flight_commands import InFlightCommandRegistry


class TestLiveCycleStatusDecisions(unittest.TestCase):
    def test_defaults_are_ready_and_empty(self):
        status = start._LiveCycleStatus()
        snapshot = status.snapshot()
        self.assertFalse(snapshot["compliance_lock_active"])
        self.assertIsNone(snapshot["compliance_lock_reason"])
        self.assertEqual(snapshot["pair_status"], {})
        self.assertIsNone(snapshot["last_submitted_correlation_id"])

    def test_update_decisions_sets_all_fields(self):
        status = start._LiveCycleStatus()
        status.update_decisions(True, "daily loss limit reached", {"EURUSD": {"outcome": "COMPLIANCE_REJECTED"}}, "live-1:EURUSD")
        snapshot = status.snapshot()
        self.assertTrue(snapshot["compliance_lock_active"])
        self.assertEqual(snapshot["compliance_lock_reason"], "daily loss limit reached")
        self.assertEqual(snapshot["pair_status"], {"EURUSD": {"outcome": "COMPLIANCE_REJECTED"}})
        self.assertEqual(snapshot["last_submitted_correlation_id"], "live-1:EURUSD")

    def test_last_submitted_correlation_id_persists_when_no_new_submission(self):
        """A cycle with no fresh submission passes None -- the last real
        correlation_id must not be wiped out by that no-op cycle."""
        status = start._LiveCycleStatus()
        status.update_decisions(False, None, {}, "live-1:EURUSD")
        status.update_decisions(False, None, {}, None)
        self.assertEqual(status.snapshot()["last_submitted_correlation_id"], "live-1:EURUSD")


class TestWriteHealthSnapshotRunStatus(unittest.TestCase):
    def setUp(self) -> None:
        # start._live_cycle_status is a module-level singleton written by
        # the live-cycle thread in the real process -- swap in a fresh
        # instance per test so one test's compliance-lock/pair-status
        # writes can never leak into another's assertions.
        self._original_live_cycle_status = start._live_cycle_status
        start._live_cycle_status = start._LiveCycleStatus()

    def tearDown(self) -> None:
        start._live_cycle_status = self._original_live_cycle_status

    def test_run_status_block_reflects_live_state(self):
        bridge_config = make_bridge_config()
        queue = CommandQueue(bridge_config)
        real_now = datetime.now(timezone.utc)
        connection_health = ConnectionHealth(bridge_config, clock=lambda: real_now)
        bridge_metrics = BridgeMetrics()
        bridge_engine = BridgeEngine(bridge_config, queue, connection_health, clock=lambda: real_now, metrics=bridge_metrics)

        heartbeat_at = real_now - timedelta(seconds=5)
        bridge_engine.handle_heartbeat(HeartbeatMessage(
            schema_version=SCHEMA_VERSION, magic_number=bridge_config.magic_number, account_login=1,
            terminal_connected=True, received_at=heartbeat_at,
        ))
        position_at = real_now - timedelta(seconds=3)
        bridge_engine.handle_positions(
            (
                PositionReport(
                    schema_version=SCHEMA_VERSION, position_id="p1", symbol="EURUSD",
                    direction=PositionDirection.BUY, volume=0.1, open_price=1.10, stop_loss=None,
                    take_profit=None, unrealized_pnl=None, magic_number=bridge_config.magic_number,
                    received_at=position_at,
                ),
            ),
            position_at,
        )

        account_state_at = real_now - timedelta(seconds=4)
        bridge_engine.handle_account_state(AccountState(
            schema_version=SCHEMA_VERSION, magic_number=bridge_config.magic_number, balance=10000.0,
            equity=10000.0, margin=0.0, free_margin=10000.0, currency="USD", leverage=100,
            received_at=account_state_at,
        ))

        in_flight_commands = InFlightCommandRegistry(ttl_seconds=300.0)
        in_flight_commands.record_submission("EURUSD", "live-1:EURUSD", real_now)

        start._live_cycle_status.update_decisions(
            True, "daily loss limit reached",
            {"EURUSD": {"outcome": "COMPLIANCE_REJECTED", "reason": "MAX_POSITIONS_PER_PAIR_EXCEEDED.", "correlation_id": None, "compliance_decision": "REJECT"}},
            "live-1:EURUSD",
        )

        reliability = ReliabilityEngine(ReliabilityConfig())

        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            start._write_health_snapshot(
                state_dir, reliability, bridge_engine, "127.0.0.1", 1, queue_depth=0,
                bridge_transport="socket",
                connection_health=connection_health, in_flight_commands=in_flight_commands,
                http_fallback_active=True, configured_max_positions_per_pair=1,
                configured_max_account_state_age_seconds=30.0,
            )
            payload = json.loads((state_dir / "health.json").read_text())

        run_status = payload["run_status"]
        self.assertEqual(run_status["communication_mode"], "socket")
        self.assertTrue(run_status["http_fallback_enabled"])
        self.assertEqual(run_status["bridge_connection_status"], "connected")
        self.assertIsNotNone(run_status["runtime_status"])
        self.assertGreater(run_status["last_heartbeat_age_seconds"], 0)
        self.assertLess(run_status["last_heartbeat_age_seconds"], 30)
        self.assertGreater(run_status["last_position_report_age_seconds"], 0)
        self.assertLess(run_status["last_position_report_age_seconds"], 30)
        self.assertEqual(run_status["in_flight_command_count"], 1)
        self.assertEqual(run_status["open_positions_per_pair"], {"EURUSD": 1})
        self.assertEqual(run_status["configured_max_positions_per_pair"], 1)
        self.assertGreater(run_status["account_report_age_seconds"], 0)
        self.assertLess(run_status["account_report_age_seconds"], 30)
        self.assertEqual(run_status["configured_max_account_state_age_seconds"], 30.0)
        self.assertTrue(run_status["account_state_fresh"])
        self.assertEqual(run_status["compliance_state"], "BLOCKED")
        self.assertEqual(run_status["compliance_block_reason"], "daily loss limit reached")
        self.assertEqual(run_status["last_submitted_correlation_id"], "live-1:EURUSD")
        self.assertEqual(run_status["pairs"]["EURUSD"]["outcome"], "COMPLIANCE_REJECTED")

    def test_run_status_absent_optional_fields_are_none(self):
        """Without connection_health/in_flight_commands/configured limit
        supplied, the new fields degrade to None rather than raising --
        matches every other optional diagnostic in this same payload
        (e.g. market_data/news are None when their engine is absent)."""
        bridge_config = make_bridge_config()
        queue = CommandQueue(bridge_config)
        now = datetime.now(timezone.utc)
        connection_health = ConnectionHealth(bridge_config, clock=lambda: now)
        bridge_engine = BridgeEngine(bridge_config, queue, connection_health, clock=lambda: now)
        reliability = ReliabilityEngine(ReliabilityConfig())

        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            start._write_health_snapshot(state_dir, reliability, bridge_engine, "127.0.0.1", 1, queue_depth=0)
            payload = json.loads((state_dir / "health.json").read_text())

        run_status = payload["run_status"]
        self.assertIsNone(run_status["last_heartbeat_age_seconds"])
        self.assertIsNone(run_status["last_position_report_age_seconds"])
        self.assertIsNone(run_status["in_flight_command_count"])
        self.assertEqual(run_status["open_positions_per_pair"], {})
        self.assertIsNone(run_status["configured_max_positions_per_pair"])
        self.assertFalse(run_status["http_fallback_enabled"])
        self.assertEqual(run_status["bridge_connection_status"], "disconnected")
        self.assertIsNone(run_status["account_report_age_seconds"])
        self.assertIsNone(run_status["configured_max_account_state_age_seconds"])
        self.assertIsNone(run_status["account_state_fresh"])


class TestRunStatusAccountStateFreshness(unittest.TestCase):
    """ACCOUNT_STATE_STALE diagnostics (deployment_windows/start.py's
    _write_health_snapshot): account_report_age_seconds/account_state_fresh
    are independently recomputed from BridgeEngine.latest_account_state,
    the same source _build_compliance_account_state() reads -- not
    threaded through from the live-cycle loop -- so they stay accurate
    even on a cycle where the compliance gate itself never ran."""

    def _bridge_engine_with_account_age(self, age_seconds: float):
        bridge_config = make_bridge_config()
        queue = CommandQueue(bridge_config)
        now = datetime.now(timezone.utc)
        connection_health = ConnectionHealth(bridge_config, clock=lambda: now)
        bridge_engine = BridgeEngine(bridge_config, queue, connection_health, clock=lambda: now)
        bridge_engine.handle_account_state(AccountState(
            schema_version=SCHEMA_VERSION, magic_number=bridge_config.magic_number, balance=10000.0,
            equity=10000.0, margin=0.0, free_margin=10000.0, currency="USD", leverage=100,
            received_at=now - timedelta(seconds=age_seconds),
        ))
        return bridge_engine

    def test_fresh_account_state_reports_fresh_true(self):
        bridge_engine = self._bridge_engine_with_account_age(5.0)
        reliability = ReliabilityEngine(ReliabilityConfig())
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            start._write_health_snapshot(
                state_dir, reliability, bridge_engine, "127.0.0.1", 1, queue_depth=0,
                configured_max_account_state_age_seconds=30.0,
            )
            run_status = json.loads((state_dir / "health.json").read_text())["run_status"]
        self.assertTrue(run_status["account_state_fresh"])

    def test_stale_account_state_reports_fresh_false(self):
        bridge_engine = self._bridge_engine_with_account_age(45.0)
        reliability = ReliabilityEngine(ReliabilityConfig())
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            start._write_health_snapshot(
                state_dir, reliability, bridge_engine, "127.0.0.1", 1, queue_depth=0,
                configured_max_account_state_age_seconds=30.0,
            )
            run_status = json.loads((state_dir / "health.json").read_text())["run_status"]
        self.assertFalse(run_status["account_state_fresh"])
        self.assertGreater(run_status["account_report_age_seconds"], 30.0)

    def test_never_reported_account_state_is_none_not_stale_or_fresh(self):
        bridge_config = make_bridge_config()
        queue = CommandQueue(bridge_config)
        now = datetime.now(timezone.utc)
        connection_health = ConnectionHealth(bridge_config, clock=lambda: now)
        bridge_engine = BridgeEngine(bridge_config, queue, connection_health, clock=lambda: now)
        reliability = ReliabilityEngine(ReliabilityConfig())
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            start._write_health_snapshot(
                state_dir, reliability, bridge_engine, "127.0.0.1", 1, queue_depth=0,
                configured_max_account_state_age_seconds=30.0,
            )
            run_status = json.loads((state_dir / "health.json").read_text())["run_status"]
        self.assertIsNone(run_status["account_report_age_seconds"])
        self.assertIsNone(run_status["account_state_fresh"])


if __name__ == "__main__":
    unittest.main()
