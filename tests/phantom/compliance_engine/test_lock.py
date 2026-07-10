"""Unit tests: pure compliance-lock/emergency-stop state helpers
(ADR-028 §5.10, §3) -- `ComplianceEngine` itself never mutates
`AccountState`; these are for whatever orchestrates the pipeline."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from phantom.compliance_engine.lock import apply_daily_reset, apply_operator_unlock, is_locked, trigger_lock
from phantom.compliance_engine.models import ComplianceLockState
from tests.phantom.compliance_engine._fixtures import make_account_state

T0 = datetime(2026, 7, 10, 13, 0, 0, tzinfo=timezone.utc)


class TestIsLocked(unittest.TestCase):
    def test_neither_active_not_locked(self):
        account = make_account_state()
        self.assertFalse(is_locked(account))

    def test_compliance_lock_active(self):
        account = make_account_state(compliance_lock=ComplianceLockState(active=True, reason="test"))
        self.assertTrue(is_locked(account))

    def test_emergency_stop_active(self):
        account = make_account_state(emergency_stop_active=True)
        self.assertTrue(is_locked(account))


class TestTriggerLock(unittest.TestCase):
    def test_sets_active_lock_with_reason(self):
        account = make_account_state()
        locked = trigger_lock(account, "daily loss limit reached", locked_at=T0)
        self.assertTrue(locked.compliance_lock.active)
        self.assertEqual(locked.compliance_lock.reason, "daily loss limit reached")
        self.assertEqual(locked.compliance_lock.locked_at, T0)


class TestDailyReset(unittest.TestCase):
    def test_resets_daily_starting_balance_and_trades_today(self):
        account = make_account_state(account_balance=95_000.0, daily_starting_balance=100_000.0, trades_today_count=5)
        reset = apply_daily_reset(account, T0)
        self.assertEqual(reset.daily_starting_balance, 95_000.0)
        self.assertEqual(reset.trades_today_count, 0)

    def test_lifts_lock_past_its_reset_time(self):
        locked_account = make_account_state(compliance_lock=ComplianceLockState(active=True, reason="x", locked_at=T0, resets_at=T0 + timedelta(hours=1)))
        reset = apply_daily_reset(locked_account, T0 + timedelta(hours=2))
        self.assertFalse(reset.compliance_lock.active)

    def test_does_not_lift_lock_before_its_reset_time(self):
        locked_account = make_account_state(compliance_lock=ComplianceLockState(active=True, reason="x", locked_at=T0, resets_at=T0 + timedelta(hours=5)))
        reset = apply_daily_reset(locked_account, T0 + timedelta(hours=1))
        self.assertTrue(reset.compliance_lock.active)

    def test_never_lifts_emergency_stop(self):
        account = make_account_state(emergency_stop_active=True)
        reset = apply_daily_reset(account, T0)
        self.assertTrue(reset.emergency_stop_active)


class TestOperatorUnlock(unittest.TestCase):
    def test_clears_both_lock_and_emergency_stop(self):
        account = make_account_state(
            compliance_lock=ComplianceLockState(active=True, reason="x"), emergency_stop_active=True,
        )
        unlocked = apply_operator_unlock(account)
        self.assertFalse(unlocked.compliance_lock.active)
        self.assertFalse(unlocked.emergency_stop_active)


if __name__ == "__main__":
    unittest.main()
