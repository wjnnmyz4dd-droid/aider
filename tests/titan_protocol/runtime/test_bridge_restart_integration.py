"""Integration tests: restart-safe in-flight persistence (production-
readiness hardening, ADR-034 Amendment 9).

Simulates a real Bridge process restart by constructing an entirely
FRESH set of `BridgeEngine`/`CommandQueue`/`ConnectionHealth`/
`InFlightCommandRegistry` objects for the "after" half of each test --
exactly what a real process restart does to in-memory state -- sharing
only the on-disk file an `InFlightCommandStore` pointed at the same path
provides. Never mocks `InFlightCommandRegistry` or `CommandQueue`
themselves.

Documents, via `test_restart_after_delivery_before_execution_report`,
the deliberate scope limit already called out in
`in_flight_commands.py`'s own module docstring: persistence covers only
the pair-level *blocking* effect (preventing a duplicate submission),
never `CommandQueue`'s own memory of the original `TradeCommand` --
a late-arriving execution report for a pre-restart command is correctly
rejected as unknown by the fresh, empty `CommandQueue`, exactly as it
would be without this hardening. The bounded TTL is what eventually
frees such a pair, not a resurrected `ExecutionReport`."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from titan_protocol.bridge.command_queue import CommandQueue
from titan_protocol.bridge.connection_health import ConnectionHealth
from titan_protocol.bridge.engine import BridgeEngine
from titan_protocol.bridge.models import ExecutionReport
from titan_protocol.runtime.in_flight_commands import InFlightCommandRegistry
from titan_protocol.runtime.in_flight_store import InFlightCommandStore, InFlightStoreConfig
from tests.titan_protocol.bridge._fixtures import make_command, make_config

T0 = datetime(2026, 7, 21, tzinfo=timezone.utc)
_TTL_SECONDS = 15.0
_IN_FLIGHT_TTL_SECONDS = 300.0
_POSITION_CONFIRMATION_TIMEOUT_SECONDS = 120.0


class _RestartTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)
        self.addCleanup(self._tmpdir.cleanup)
        self.state_file = self.tmp_path / "in_flight_commands.json"

    def _build_pre_restart(self):
        """One 'before restart' process: real BridgeEngine/CommandQueue/
        InFlightCommandRegistry, all freshly constructed for this test."""
        config = make_config(command_ttl_seconds=_TTL_SECONDS, allowed_symbols=("EURUSD", "GBPUSD", "USDJPY"))
        health = ConnectionHealth(config, lambda: T0)
        health.record_heartbeat(T0)
        bridge_engine = BridgeEngine(config, CommandQueue(config), health, lambda: T0)
        registry = InFlightCommandRegistry(
            ttl_seconds=_IN_FLIGHT_TTL_SECONDS,
            position_confirmation_timeout_seconds=_POSITION_CONFIRMATION_TIMEOUT_SECONDS,
        )
        store = InFlightCommandStore(InFlightStoreConfig(state_file=self.state_file))
        return bridge_engine, registry, store

    def _build_post_restart(self):
        """The 'after restart' process -- entirely new objects, zero
        shared Python state with the pre-restart process; only the
        on-disk file (same path) can carry anything across."""
        config = make_config(command_ttl_seconds=_TTL_SECONDS, allowed_symbols=("EURUSD", "GBPUSD", "USDJPY"))
        health = ConnectionHealth(config, lambda: T0)
        health.record_heartbeat(T0)
        bridge_engine = BridgeEngine(config, CommandQueue(config), health, lambda: T0)
        registry = InFlightCommandRegistry(
            ttl_seconds=_IN_FLIGHT_TTL_SECONDS,
            position_confirmation_timeout_seconds=_POSITION_CONFIRMATION_TIMEOUT_SECONDS,
        )
        store = InFlightCommandStore(InFlightStoreConfig(state_file=self.state_file))
        return bridge_engine, registry, store


class TestRestartBeforeDelivery(_RestartTestCase):
    def test_pair_stays_blocked_across_restart_preventing_a_duplicate_submission(self):
        bridge_engine, registry, store = self._build_pre_restart()
        cmd = make_command(correlation_id="cycle-1:EURUSD", symbol="EURUSD", issued_at=T0)
        self.assertIsNone(bridge_engine.submit_command(cmd, T0))
        registry.record_submission("EURUSD", "cycle-1:EURUSD", T0)
        # EA never polls before the crash/restart.
        store.save(registry.snapshot_for_persistence())

        restart_time = T0 + timedelta(seconds=2)
        post_bridge_engine, post_registry, post_store = self._build_post_restart()
        restored_entries = post_store.load()
        restored_count = post_registry.restore(restored_entries, restart_time)
        self.assertEqual(restored_count, 1)

        # Runtime's own duplicate-prevention gate sees the pair as still
        # blocked -- no fresh command may be submitted for it yet.
        self.assertTrue(post_registry.has_unresolved("EURUSD", restart_time))
        self.assertEqual(post_registry.correlation_id_for("EURUSD"), "cycle-1:EURUSD")

        # The fresh CommandQueue has no memory of the pre-restart command
        # (never delivered, never persisted itself) -- poll() naturally
        # returns nothing for it, matching a real EA reconnect.
        self.assertEqual(post_bridge_engine.poll_commands(restart_time), ())


class TestRestartAfterDeliveryBeforeExecutionReport(_RestartTestCase):
    def test_pair_stays_blocked_and_late_execution_report_is_rejected_as_unknown(self):
        """Documents the deliberate scope limit: only the pair-level
        block survives a restart, never CommandQueue's own memory of the
        TradeCommand -- so an ExecutionReport for a truly pre-restart
        command is (correctly) rejected as unknown once the Bridge has
        restarted. The pair remains protected by its own TTL instead."""
        bridge_engine, registry, store = self._build_pre_restart()
        cmd = make_command(correlation_id="cycle-1:EURUSD", symbol="EURUSD", issued_at=T0)
        self.assertIsNone(bridge_engine.submit_command(cmd, T0))
        registry.record_submission("EURUSD", "cycle-1:EURUSD", T0)
        delivered = bridge_engine.poll_commands(T0 + timedelta(seconds=1))
        self.assertEqual(len(delivered), 1)  # EA received it before the crash
        store.save(registry.snapshot_for_persistence())  # still "in_flight" -- registry has no separate "delivered" state

        restart_time = T0 + timedelta(seconds=3)
        post_bridge_engine, post_registry, post_store = self._build_post_restart()
        restored_count = post_registry.restore(post_store.load(), restart_time)
        self.assertEqual(restored_count, 1)
        self.assertTrue(post_registry.has_unresolved("EURUSD", restart_time))

        # The EA (having actually executed it before the crash) now
        # reports the result -- but the fresh CommandQueue never enqueued
        # this correlation_id, so it is correctly rejected, not silently
        # accepted as a phantom fill.
        report = ExecutionReport(
            schema_version=1, correlation_id="cycle-1:EURUSD", magic_number=20260709,
            success=True, broker_ticket="777", filled_price=1.1, filled_volume=0.1,
            error_code=None, reported_at=restart_time,
        )
        recorded = post_bridge_engine.handle_execution_report(report)
        self.assertFalse(recorded, "a post-restart CommandQueue must never accept a result for a command it never enqueued")
        self.assertFalse(post_bridge_engine.command_resolved("cycle-1:EURUSD"))

        # The pair is eventually freed by its own (restart-surviving) TTL,
        # not by the late execution report -- reconcile() at T0+300s+ε
        # would drop it as unresolved-and-expired (is_abandoned() on the
        # fresh queue is fail-closed False for an unknown id, so this is
        # the plain age-based reconcile() branch, not is_abandoned()).
        long_after = T0 + timedelta(seconds=_IN_FLIGHT_TTL_SECONDS + 1)
        outcome = post_registry.reconcile(long_after, post_bridge_engine.command_resolved)
        self.assertEqual(outcome.dropped_count, 1)
        self.assertFalse(post_registry.has_unresolved("EURUSD", long_after))


class TestRestartAfterExecutionReport(_RestartTestCase):
    def test_awaiting_confirmation_state_survives_restart_and_a_fresh_snapshot_releases_it(self):
        bridge_engine, registry, store = self._build_pre_restart()
        cmd = make_command(correlation_id="cycle-1:GBPUSD", symbol="GBPUSD", issued_at=T0)
        self.assertIsNone(bridge_engine.submit_command(cmd, T0))
        registry.record_submission("GBPUSD", "cycle-1:GBPUSD", T0)
        bridge_engine.poll_commands(T0 + timedelta(seconds=1))
        report = ExecutionReport(
            schema_version=1, correlation_id="cycle-1:GBPUSD", magic_number=20260709,
            success=True, broker_ticket="888", filled_price=1.25, filled_volume=0.2,
            error_code=None, reported_at=T0 + timedelta(seconds=2),
        )
        self.assertTrue(bridge_engine.handle_execution_report(report))
        outcome = registry.reconcile(T0 + timedelta(seconds=2), bridge_engine.command_resolved)
        self.assertEqual(outcome.dropped_count, 1)
        self.assertTrue(registry.is_awaiting_position_confirmation("GBPUSD"))
        store.save(registry.snapshot_for_persistence())  # persisted as "awaiting_position_confirmation"

        restart_time = T0 + timedelta(seconds=5)
        _, post_registry, post_store = self._build_post_restart()
        restored_count = post_registry.restore(post_store.load(), restart_time)
        self.assertEqual(restored_count, 1)
        self.assertTrue(post_registry.is_awaiting_position_confirmation("GBPUSD"))
        self.assertTrue(post_registry.has_unresolved("GBPUSD", restart_time))

        # A fresh /bridge/positions snapshot, dated at or after the
        # ORIGINAL resolution time (T0+2s, not the restart time), confirms
        # and releases it -- exactly as it would with no restart at all.
        confirmed = post_registry.confirm_position_report(T0 + timedelta(seconds=6))
        self.assertEqual(len(confirmed), 1)
        self.assertFalse(post_registry.has_unresolved("GBPUSD", restart_time))


class TestRestartWithCorruptedPersistence(_RestartTestCase):
    def test_corrupted_state_file_never_crashes_restart_just_loses_restart_safety_for_that_pair(self):
        bridge_engine, registry, store = self._build_pre_restart()
        cmd = make_command(correlation_id="cycle-1:EURUSD", symbol="EURUSD", issued_at=T0)
        self.assertIsNone(bridge_engine.submit_command(cmd, T0))
        registry.record_submission("EURUSD", "cycle-1:EURUSD", T0)
        store.save(registry.snapshot_for_persistence())
        # Simulate a crash mid-write / disk corruption: the file on disk
        # is no longer valid JSON.
        self.state_file.write_text("{not valid json at all", encoding="utf-8")

        restart_time = T0 + timedelta(seconds=2)
        _, post_registry, post_store = self._build_post_restart()
        restored_entries = post_store.load()  # must not raise
        self.assertEqual(restored_entries, ())
        restored_count = post_registry.restore(restored_entries, restart_time)
        self.assertEqual(restored_count, 0)
        # Documented, accepted consequence: this one restart's worth of
        # restart-safety is lost for this pair -- it is NOT blocked. This
        # is a return to today's pre-hardening behavior for this single
        # restart, never a crash, and Compliance's own independent live
        # position-limit check (not exercised by this unit test) remains
        # the actual duplicate-position guard regardless.
        self.assertFalse(post_registry.has_unresolved("EURUSD", restart_time))

    def test_corrupted_primary_with_valid_backup_still_restores_correctly(self):
        bridge_engine, registry, store = self._build_pre_restart()
        cmd = make_command(correlation_id="cycle-1:EURUSD", symbol="EURUSD", issued_at=T0)
        self.assertIsNone(bridge_engine.submit_command(cmd, T0))
        registry.record_submission("EURUSD", "cycle-1:EURUSD", T0)
        store.save(registry.snapshot_for_persistence())  # this becomes the .bak on the next save
        cmd2 = make_command(correlation_id="cycle-2:GBPUSD", symbol="GBPUSD", issued_at=T0)
        self.assertIsNone(bridge_engine.submit_command(cmd2, T0))
        registry.record_submission("GBPUSD", "cycle-2:GBPUSD", T0)
        store.save(registry.snapshot_for_persistence())
        # Corrupt only the primary -- the .bak rotated from the first save
        # (EURUSD only) remains valid.
        self.state_file.write_text("{not valid json", encoding="utf-8")

        restart_time = T0 + timedelta(seconds=2)
        _, post_registry, post_store = self._build_post_restart()
        restored_entries = post_store.load()
        self.assertEqual(len(restored_entries), 1)
        self.assertEqual(restored_entries[0].pair, "EURUSD")
        restored_count = post_registry.restore(restored_entries, restart_time)
        self.assertEqual(restored_count, 1)
        self.assertTrue(post_registry.has_unresolved("EURUSD", restart_time))


class TestMultipleSimultaneousUnresolvedCommands(_RestartTestCase):
    def test_several_pairs_at_once_all_restore_independently(self):
        bridge_engine, registry, store = self._build_pre_restart()
        for pair, corr in (("EURUSD", "cycle-1:EURUSD"), ("GBPUSD", "cycle-1:GBPUSD"), ("USDJPY", "cycle-1:USDJPY")):
            cmd = make_command(correlation_id=corr, symbol=pair, issued_at=T0)
            self.assertIsNone(bridge_engine.submit_command(cmd, T0))
            registry.record_submission(pair, corr, T0)
        store.save(registry.snapshot_for_persistence())
        self.assertEqual(len(json.loads(self.state_file.read_text())["entries"]), 3)

        restart_time = T0 + timedelta(seconds=2)
        _, post_registry, post_store = self._build_post_restart()
        restored_count = post_registry.restore(post_store.load(), restart_time)
        self.assertEqual(restored_count, 3)
        for pair, corr in (("EURUSD", "cycle-1:EURUSD"), ("GBPUSD", "cycle-1:GBPUSD"), ("USDJPY", "cycle-1:USDJPY")):
            self.assertTrue(post_registry.has_unresolved(pair, restart_time))
            self.assertEqual(post_registry.correlation_id_for(pair), corr)


if __name__ == "__main__":
    unittest.main()
