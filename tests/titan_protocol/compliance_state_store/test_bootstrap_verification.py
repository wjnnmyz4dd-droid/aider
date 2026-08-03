"""Tests for KNOWN_GAPS.md #9's fix: day-one bootstrap verification.

Covers the pure decision functions in `bootstrap.py` directly, then
`ComplianceStateStore.load_or_bootstrap()`'s integration of them --
fresh install with a flat account, a not-yet-flat account (open
positions or floating P&L), an operator-supplied override bypassing
verification entirely, and config validation. Restart-survival,
corruption-fails-closed, and daily-reset-boundary behavior are already
covered by `test_store.py` and are unaffected by this change (this
file does not re-test them)."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from titan_protocol.compliance_state_store.bootstrap import (
    is_account_verified_flat,
    resolve_bootstrap_balance,
)
from titan_protocol.compliance_state_store.config import ComplianceStateStoreConfig
from titan_protocol.compliance_state_store.store import ComplianceStateStore


def _utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


class TestIsAccountVerifiedFlat(unittest.TestCase):
    def test_true_when_no_positions_and_balance_equals_equity(self):
        self.assertTrue(is_account_verified_flat(10_000.0, 10_000.0, False, 0.01))

    def test_true_within_tolerance(self):
        self.assertTrue(is_account_verified_flat(10_000.0, 10_000.005, False, 0.01))

    def test_false_when_open_positions_exist_even_if_balance_equals_equity(self):
        """An account can show balance == equity while a position is
        open if that position currently has exactly zero floating P&L --
        `has_open_positions` must still veto it, since floating P&L can
        change the instant after this check runs."""
        self.assertFalse(is_account_verified_flat(10_000.0, 10_000.0, True, 0.01))

    def test_false_when_floating_pnl_exceeds_tolerance(self):
        self.assertFalse(is_account_verified_flat(10_000.0, 10_050.0, False, 0.01))

    def test_false_exactly_at_tolerance_boundary_plus_epsilon(self):
        self.assertFalse(is_account_verified_flat(10_000.0, 10_000.02, False, 0.01))


class TestResolveBootstrapBalance(unittest.TestCase):
    def test_override_wins_even_with_open_positions_and_floating_pnl(self):
        result = resolve_bootstrap_balance(
            current_balance=10_500.0, current_equity=11_000.0, has_open_positions=True,
            equity_tolerance=0.01, override_balance=9_999.0,
        )
        self.assertEqual(result, 9_999.0)

    def test_verified_flat_account_uses_current_balance(self):
        result = resolve_bootstrap_balance(
            current_balance=10_000.0, current_equity=10_000.0, has_open_positions=False,
            equity_tolerance=0.01, override_balance=None,
        )
        self.assertEqual(result, 10_000.0)

    def test_not_flat_and_no_override_returns_none(self):
        result = resolve_bootstrap_balance(
            current_balance=10_000.0, current_equity=10_500.0, has_open_positions=False,
            equity_tolerance=0.01, override_balance=None,
        )
        self.assertIsNone(result)

    def test_open_positions_and_no_override_returns_none(self):
        result = resolve_bootstrap_balance(
            current_balance=10_000.0, current_equity=10_000.0, has_open_positions=True,
            equity_tolerance=0.01, override_balance=None,
        )
        self.assertIsNone(result)


class _StoreTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)
        self.addCleanup(self._tmpdir.cleanup)
        self.state_file = self.tmp_path / "compliance_state.json"

    def _store(self, **overrides) -> ComplianceStateStore:
        defaults = dict(state_file=self.state_file, daily_reset_hour_utc=0)
        defaults.update(overrides)
        return ComplianceStateStore(ComplianceStateStoreConfig(**defaults))


class TestFreshInstallVerifiedFlatBootstraps(_StoreTestCase):
    def test_flat_account_bootstraps_immediately(self):
        store = self._store()
        state = store.load_or_bootstrap(
            _utc(2026, 7, 14, 8, 0, 0), 10_000.0, current_equity=10_000.0, has_open_positions=False,
        )
        self.assertIsNotNone(state)
        self.assertEqual(state.daily_starting_balance, 10_000.0)
        self.assertTrue(self.state_file.exists())

    def test_default_parameters_preserve_legacy_flat_behavior(self):
        """Callers that don't pass `current_equity`/`has_open_positions`
        at all (every pre-existing call site in test_store.py) must see
        identical behavior to before this fix -- defaults must resolve
        to "flat"."""
        store = self._store()
        state = store.load_or_bootstrap(_utc(2026, 7, 14, 8, 0, 0), 10_000.0)
        self.assertIsNotNone(state)
        self.assertEqual(state.daily_starting_balance, 10_000.0)


class TestFreshInstallNotYetVerifiedBlocksBootstrap(_StoreTestCase):
    def test_open_positions_blocks_bootstrap_and_writes_no_file(self):
        store = self._store()
        state = store.load_or_bootstrap(
            _utc(2026, 7, 14, 8, 0, 0), 10_000.0, current_equity=10_000.0, has_open_positions=True,
        )
        self.assertIsNone(state)
        self.assertFalse(self.state_file.exists(), "must not persist a bootstrap that was never verified")

    def test_floating_pnl_blocks_bootstrap(self):
        store = self._store()
        state = store.load_or_bootstrap(
            _utc(2026, 7, 14, 8, 0, 0), 10_000.0, current_equity=10_300.0, has_open_positions=False,
        )
        self.assertIsNone(state)
        self.assertFalse(self.state_file.exists())

    def test_becomes_flat_on_a_later_call_and_bootstraps_then(self):
        store = self._store()
        blocked = store.load_or_bootstrap(
            _utc(2026, 7, 14, 8, 0, 0), 10_000.0, current_equity=10_300.0, has_open_positions=False,
        )
        self.assertIsNone(blocked)

        state = store.load_or_bootstrap(
            _utc(2026, 7, 14, 8, 5, 0), 9_950.0, current_equity=9_950.0, has_open_positions=False,
        )
        self.assertIsNotNone(state)
        self.assertEqual(state.daily_starting_balance, 9_950.0)


class TestOperatorOverrideBypassesVerification(_StoreTestCase):
    def test_override_bootstraps_immediately_despite_open_positions(self):
        store = self._store(day_start_balance_override=12_345.0)
        state = store.load_or_bootstrap(
            _utc(2026, 7, 14, 8, 0, 0), 10_000.0, current_equity=11_000.0, has_open_positions=True,
        )
        self.assertIsNotNone(state)
        self.assertEqual(state.daily_starting_balance, 12_345.0)
        self.assertEqual(state.peak_balance, 12_345.0)


class TestExistingInstallationUnaffected(_StoreTestCase):
    def test_restart_with_existing_state_file_ignores_positions_entirely(self):
        """Once a state file exists, bootstrap verification is not
        re-evaluated at all -- restarts (before or after trading,
        including mid-day) must keep loading persisted state exactly as
        `test_store.py::TestRestartSurvival` already proves."""
        store = self._store()
        store.load_or_bootstrap(_utc(2026, 7, 14, 8, 0, 0), 10_000.0, current_equity=10_000.0, has_open_positions=False)

        restarted = self._store()
        reloaded = restarted.load_or_bootstrap(
            _utc(2026, 7, 14, 12, 0, 0), 9_500.0, current_equity=8_000.0, has_open_positions=True,
        )
        self.assertIsNotNone(reloaded)
        self.assertEqual(reloaded.daily_starting_balance, 10_000.0)


class TestConfigValidation(unittest.TestCase):
    def test_zero_override_rejected(self):
        with self.assertRaises(ValueError):
            ComplianceStateStoreConfig(state_file=Path("x"), day_start_balance_override=0.0)

    def test_negative_override_rejected(self):
        with self.assertRaises(ValueError):
            ComplianceStateStoreConfig(state_file=Path("x"), day_start_balance_override=-5.0)

    def test_negative_tolerance_rejected(self):
        with self.assertRaises(ValueError):
            ComplianceStateStoreConfig(state_file=Path("x"), flat_account_equity_tolerance=-0.01)

    def test_none_override_and_zero_tolerance_are_both_valid(self):
        ComplianceStateStoreConfig(state_file=Path("x"), day_start_balance_override=None, flat_account_equity_tolerance=0.0)


if __name__ == "__main__":
    unittest.main()
