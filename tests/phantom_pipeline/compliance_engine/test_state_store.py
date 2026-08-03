"""State store persistence tests (ADR-006 §14, §18)."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timezone

from phantom_pipeline.compliance_engine.state_store import (
    InMemoryComplianceStateStore,
    SqliteComplianceStateStore,
)

T0 = datetime(2026, 7, 6, 10, 0, 0, tzinfo=timezone.utc)


class TestInMemoryComplianceStateStore(unittest.TestCase):
    def test_not_triggered_by_default(self):
        store = InMemoryComplianceStateStore()
        self.assertFalse(store.is_kill_switch_triggered())

    def test_trigger_latches(self):
        store = InMemoryComplianceStateStore()
        store.trigger_kill_switch("total_drawdown_breach", "t1", T0)
        self.assertTrue(store.is_kill_switch_triggered())
        self.assertEqual(store.kill_switch_reason(), "total_drawdown_breach")

    def test_daily_lockout_is_scoped_by_day(self):
        store = InMemoryComplianceStateStore()
        store.trigger_daily_lockout("2026-07-06", "daily_drawdown_breach", "t1", T0)
        self.assertTrue(store.is_daily_locked_out("2026-07-06"))
        self.assertFalse(store.is_daily_locked_out("2026-07-07"))


class TestSqliteComplianceStateStorePersistence(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".sqlite3")
        os.close(fd)

    def tearDown(self):
        os.remove(self.db_path)

    def test_not_triggered_by_default(self):
        store = SqliteComplianceStateStore(self.db_path)
        self.assertFalse(store.is_kill_switch_triggered())

    def test_kill_switch_survives_a_simulated_process_restart(self):
        first_process_store = SqliteComplianceStateStore(self.db_path)
        first_process_store.trigger_kill_switch("total_drawdown_breach", "t1", T0)

        # Simulate a process restart: a brand-new store instance, same file.
        second_process_store = SqliteComplianceStateStore(self.db_path)
        self.assertTrue(second_process_store.is_kill_switch_triggered())
        self.assertEqual(second_process_store.kill_switch_reason(), "total_drawdown_breach")

    def test_kill_switch_trigger_is_idempotent_and_permanent(self):
        store = SqliteComplianceStateStore(self.db_path)
        store.trigger_kill_switch("total_drawdown_breach", "t1", T0)
        store.trigger_kill_switch("a_different_reason", "t2", T0)
        # First trigger wins; the switch does not get re-latched or cleared.
        self.assertEqual(store.kill_switch_reason(), "total_drawdown_breach")

    def test_daily_lockout_survives_a_simulated_process_restart(self):
        first_process_store = SqliteComplianceStateStore(self.db_path)
        first_process_store.trigger_daily_lockout("2026-07-06", "daily_drawdown_breach", "t1", T0)

        second_process_store = SqliteComplianceStateStore(self.db_path)
        self.assertTrue(second_process_store.is_daily_locked_out("2026-07-06"))

    def test_kill_switch_vs_daily_lockout_distinction(self):
        """Kill switch is permanent; daily lockout resets once the day
        advances (ADR-006 §6 vs §14)."""
        store = SqliteComplianceStateStore(self.db_path)
        store.trigger_kill_switch("total_drawdown_breach", "t1", T0)
        store.trigger_daily_lockout("2026-07-06", "daily_drawdown_breach", "t1", T0)

        # A new day: daily lockout no longer applies, kill switch still does.
        self.assertFalse(store.is_daily_locked_out("2026-07-07"))
        self.assertTrue(store.is_kill_switch_triggered())


if __name__ == "__main__":
    unittest.main()
