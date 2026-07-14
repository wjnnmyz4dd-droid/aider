"""Tests for `ComplianceStateStore` -- durable, restart-safe compliance
day-state (Final Release Hardening, requirement 2). Exercises real
temp-file-backed persistence, never mocked: bootstrap, restart,
corruption + backup recovery, daily-reset reconciliation, peak
tracking, and lock-recommendation application."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from titan_protocol.compliance_engine.models import ComplianceLockState, LockRecommendation
from titan_protocol.compliance_state_store.config import ComplianceStateStoreConfig
from titan_protocol.compliance_state_store.models import CorruptStateError
from titan_protocol.compliance_state_store.store import ComplianceStateStore, to_account_state


def _utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


class _StoreTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)
        self.addCleanup(self._tmpdir.cleanup)
        self.state_file = self.tmp_path / "compliance_state.json"
        self.store = ComplianceStateStore(ComplianceStateStoreConfig(state_file=self.state_file, daily_reset_hour_utc=0))


class TestBootstrapOnFirstRun(_StoreTestCase):
    def test_missing_file_bootstraps_fresh_state_from_current_balance(self):
        now = _utc(2026, 7, 14, 8, 0, 0)
        state = self.store.load_or_bootstrap(now, 10_000.0)
        self.assertEqual(state.daily_starting_balance, 10_000.0)
        self.assertEqual(state.peak_balance, 10_000.0)
        self.assertFalse(state.compliance_lock.active)
        self.assertEqual(state.trading_days_count, 1)
        self.assertTrue(self.state_file.exists())

    def test_bootstrap_is_never_re_triggered_once_a_file_exists(self):
        now = _utc(2026, 7, 14, 8, 0, 0)
        self.store.load_or_bootstrap(now, 10_000.0)
        # A second "first run" with a different balance must load the
        # existing file, not silently re-bootstrap from the new balance.
        state = self.store.load_or_bootstrap(now, 99_999.0)
        self.assertEqual(state.daily_starting_balance, 10_000.0)


class TestRestartSurvival(_StoreTestCase):
    def test_state_survives_a_simulated_process_restart(self):
        now = _utc(2026, 7, 14, 8, 0, 0)
        original = self.store.load_or_bootstrap(now, 10_000.0)
        locked = self.store.apply_lock_recommendation(
            original, LockRecommendation(trigger=True, reason="daily loss limit"), now,
            resets_at=now + timedelta(hours=10),
        )
        self.assertTrue(locked.compliance_lock.active)

        # A brand-new store instance (simulating a fresh process) must
        # see exactly the same persisted lock -- restarting must never
        # silently clear it.
        reloaded_store = ComplianceStateStore(ComplianceStateStoreConfig(state_file=self.state_file, daily_reset_hour_utc=0))
        reloaded = reloaded_store.load_or_bootstrap(now, 10_000.0)
        self.assertTrue(reloaded.compliance_lock.active)
        self.assertEqual(reloaded.compliance_lock.reason, "daily loss limit")


class TestCrashSafety(_StoreTestCase):
    def test_no_leftover_temp_file_after_a_normal_save(self):
        now = _utc(2026, 7, 14, 8, 0, 0)
        self.store.load_or_bootstrap(now, 10_000.0)
        leftover_temp_files = list(self.tmp_path.glob(".tmp-compliance-state-*"))
        self.assertEqual(leftover_temp_files, [])

    def test_a_half_written_primary_file_does_not_prevent_recovery_from_backup(self):
        now = _utc(2026, 7, 14, 8, 0, 0)
        good_state = self.store.load_or_bootstrap(now, 10_000.0)
        # Second save rotates the good file to .bak, then we simulate a
        # crash mid-write by truncating the primary file afterward.
        self.store.reconcile(good_state, now, 10_500.0)
        self.state_file.write_text("{not valid json at all", encoding="utf-8")

        recovered = self.store.load_or_bootstrap(now, 10_500.0)
        self.assertEqual(recovered.daily_starting_balance, 10_000.0)


class TestCorruptionFailsClosed(_StoreTestCase):
    def test_invalid_json_with_no_backup_raises(self):
        self.state_file.write_text("{not valid json", encoding="utf-8")
        with self.assertRaises(CorruptStateError):
            self.store.load_or_bootstrap(_utc(2026, 7, 14, 8, 0, 0), 10_000.0)

    def test_missing_required_key_raises(self):
        self.state_file.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
        with self.assertRaises(CorruptStateError):
            self.store.load_or_bootstrap(_utc(2026, 7, 14, 8, 0, 0), 10_000.0)

    def test_unknown_schema_version_raises(self):
        now = _utc(2026, 7, 14, 8, 0, 0)
        state = self.store.load_or_bootstrap(now, 10_000.0)
        raw = json.loads(self.state_file.read_text(encoding="utf-8"))
        raw["schema_version"] = 999
        self.state_file.write_text(json.dumps(raw), encoding="utf-8")

        fresh_store = ComplianceStateStore(ComplianceStateStoreConfig(state_file=self.state_file, daily_reset_hour_utc=0))
        with self.assertRaises(CorruptStateError):
            fresh_store.load_or_bootstrap(now, 10_000.0)

    def test_corrupt_primary_and_corrupt_backup_both_fail_closed(self):
        now = _utc(2026, 7, 14, 8, 0, 0)
        self.store.load_or_bootstrap(now, 10_000.0)
        backup = self.state_file.with_suffix(self.state_file.suffix + ".bak")
        self.state_file.write_text("corrupt primary", encoding="utf-8")
        backup.write_text("corrupt backup too", encoding="utf-8")
        with self.assertRaises(CorruptStateError):
            self.store.load_or_bootstrap(now, 10_000.0)


class TestDailyResetBoundary(_StoreTestCase):
    def test_same_trading_day_does_not_reset_daily_starting_balance(self):
        now = _utc(2026, 7, 14, 8, 0, 0)
        state = self.store.load_or_bootstrap(now, 10_000.0)
        later_same_day = _utc(2026, 7, 14, 20, 0, 0)
        reconciled = self.store.reconcile(state, later_same_day, 9_500.0)
        self.assertEqual(reconciled.daily_starting_balance, 10_000.0)
        self.assertEqual(reconciled.trading_day_id, state.trading_day_id)

    def test_crossing_the_boundary_resets_daily_starting_balance_to_current(self):
        now = _utc(2026, 7, 14, 8, 0, 0)
        state = self.store.load_or_bootstrap(now, 10_000.0)
        next_day = _utc(2026, 7, 15, 8, 0, 0)
        reconciled = self.store.reconcile(state, next_day, 9_500.0)
        self.assertEqual(reconciled.daily_starting_balance, 9_500.0)
        self.assertEqual(reconciled.trading_days_count, 2)
        self.assertNotEqual(reconciled.trading_day_id, state.trading_day_id)

    def test_restart_alone_never_triggers_a_reset(self):
        """The mission's own hard rule: a restart within the same
        trading day must never reset loss/lock state, even across a
        brand-new store instance."""
        now = _utc(2026, 7, 14, 8, 0, 0)
        state = self.store.load_or_bootstrap(now, 10_000.0)
        locked = self.store.apply_lock_recommendation(
            state, LockRecommendation(trigger=True, reason="daily loss limit"), now,
        )
        restarted_store = ComplianceStateStore(ComplianceStateStoreConfig(state_file=self.state_file, daily_reset_hour_utc=0))
        reloaded = restarted_store.load_or_bootstrap(now, 9_000.0)
        later_same_day = _utc(2026, 7, 14, 12, 0, 0)
        reconciled = restarted_store.reconcile(reloaded, later_same_day, 9_000.0)
        self.assertTrue(reconciled.compliance_lock.active)
        self.assertEqual(reconciled.daily_starting_balance, 10_000.0)

    def test_lock_with_expired_resets_at_is_cleared_only_at_the_day_boundary(self):
        now = _utc(2026, 7, 14, 8, 0, 0)
        state = self.store.load_or_bootstrap(now, 10_000.0)
        locked = self.store.apply_lock_recommendation(
            state, LockRecommendation(trigger=True, reason="daily loss limit"), now,
            resets_at=_utc(2026, 7, 15, 0, 0, 0),
        )
        next_day = _utc(2026, 7, 15, 8, 0, 0)
        reconciled = self.store.reconcile(locked, next_day, 10_000.0)
        self.assertFalse(reconciled.compliance_lock.active)


class TestPeakBalanceTracking(_StoreTestCase):
    def test_peak_balance_increases_with_new_highs(self):
        now = _utc(2026, 7, 14, 8, 0, 0)
        state = self.store.load_or_bootstrap(now, 10_000.0)
        reconciled = self.store.reconcile(state, now, 11_000.0)
        self.assertEqual(reconciled.peak_balance, 11_000.0)

    def test_peak_balance_never_decreases_on_a_drawdown(self):
        now = _utc(2026, 7, 14, 8, 0, 0)
        state = self.store.load_or_bootstrap(now, 10_000.0)
        state = self.store.reconcile(state, now, 12_000.0)
        state = self.store.reconcile(state, now, 8_000.0)
        self.assertEqual(state.peak_balance, 12_000.0)

    def test_peak_balance_survives_a_trading_day_rollover(self):
        now = _utc(2026, 7, 14, 8, 0, 0)
        state = self.store.load_or_bootstrap(now, 10_000.0)
        state = self.store.reconcile(state, now, 15_000.0)
        next_day = _utc(2026, 7, 15, 8, 0, 0)
        state = self.store.reconcile(state, next_day, 9_000.0)
        self.assertEqual(state.peak_balance, 15_000.0)


class TestLockRecommendationApplication(_StoreTestCase):
    def test_no_trigger_leaves_state_unchanged(self):
        now = _utc(2026, 7, 14, 8, 0, 0)
        state = self.store.load_or_bootstrap(now, 10_000.0)
        result = self.store.apply_lock_recommendation(state, LockRecommendation(trigger=False), now)
        self.assertEqual(result, state)

    def test_none_recommendation_leaves_state_unchanged(self):
        now = _utc(2026, 7, 14, 8, 0, 0)
        state = self.store.load_or_bootstrap(now, 10_000.0)
        result = self.store.apply_lock_recommendation(state, None, now)
        self.assertEqual(result, state)

    def test_trigger_persists_a_new_lock(self):
        now = _utc(2026, 7, 14, 8, 0, 0)
        state = self.store.load_or_bootstrap(now, 10_000.0)
        result = self.store.apply_lock_recommendation(
            state, LockRecommendation(trigger=True, reason="total drawdown exceeded"), now,
        )
        self.assertTrue(result.compliance_lock.active)
        self.assertEqual(result.compliance_lock.reason, "total drawdown exceeded")
        self.assertEqual(result.compliance_lock.locked_at, now)


class TestToAccountState(_StoreTestCase):
    def test_builds_a_valid_account_state_from_persisted_state(self):
        now = _utc(2026, 7, 14, 8, 0, 0)
        state = self.store.load_or_bootstrap(now, 10_000.0)
        account = to_account_state(state, 10_250.0)
        self.assertEqual(account.account_balance, 10_250.0)
        self.assertEqual(account.daily_starting_balance, 10_000.0)
        self.assertEqual(account.peak_balance, 10_000.0)
        self.assertIsInstance(account.compliance_lock, ComplianceLockState)

    def test_accepts_caller_owned_overrides(self):
        now = _utc(2026, 7, 14, 8, 0, 0)
        state = self.store.load_or_bootstrap(now, 10_000.0)
        account = to_account_state(state, 10_250.0, consecutive_losses=2, trades_today_count=5)
        self.assertEqual(account.consecutive_losses, 2)
        self.assertEqual(account.trades_today_count, 5)


if __name__ == "__main__":
    unittest.main()
