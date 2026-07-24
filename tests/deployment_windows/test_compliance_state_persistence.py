"""Integration tests for restart-safe compliance day-state wiring
(Final Release Hardening, requirement 2) -- exercises the real
`start.py` functions (`_build_compliance_account_state`) against a
real `ComplianceStateStore` backed by a real temp file, and the real
`config_loader.load_settings()` parsing of `compliance.
daily_reset_hour_utc`."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from ._fixtures import write_config

from config_loader import ConfigError, load_settings
import start as start_module
from titan_protocol.compliance_state_store.config import ComplianceStateStoreConfig
from titan_protocol.compliance_state_store.store import ComplianceStateStore


def _utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


class TestDailyResetHourUtcConfigParsing(unittest.TestCase):
    def test_default_is_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(Path(tmp))
            settings = load_settings(config_path)
            self.assertEqual(settings.compliance_daily_reset_hour_utc, 0)

    def test_configured_value_is_parsed(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(Path(tmp))
            data = json.loads(config_path.read_text())
            data["compliance"]["daily_reset_hour_utc"] = 17
            config_path.write_text(json.dumps(data))
            settings = load_settings(config_path)
            self.assertEqual(settings.compliance_daily_reset_hour_utc, 17)

    def test_out_of_range_value_fails_closed(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(Path(tmp))
            data = json.loads(config_path.read_text())
            data["compliance"]["daily_reset_hour_utc"] = 24
            config_path.write_text(json.dumps(data))
            with self.assertRaises(ConfigError):
                load_settings(config_path)


class _FakeBridgeEngine:
    def __init__(self, balance, received_at=None, equity=None, positions=()):
        """`equity` defaults to `balance` (no floating P&L) and
        `positions` defaults to empty -- i.e. "flat" -- so every
        pre-existing test below that doesn't pass them keeps exercising
        exactly the behavior it always has (KNOWN_GAPS.md #9's
        bootstrap-verification gate is satisfied by default)."""
        self.latest_account_state = (
            SimpleNamespace(
                balance=balance, equity=balance if equity is None else equity,
                received_at=received_at or _utc(2026, 7, 14, 7, 59, 0),
            )
            if balance is not None else None
        )
        self.latest_positions = tuple(positions)


class TestBuildComplianceAccountStateWiring(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)
        self.addCleanup(self._tmpdir.cleanup)
        self.store = ComplianceStateStore(
            ComplianceStateStoreConfig(state_file=self.tmp_path / "compliance_state.json", daily_reset_hour_utc=0)
        )

    def test_no_reported_balance_yet_returns_none_and_leaves_state_untouched(self):
        bridge = _FakeBridgeEngine(balance=None)
        account_state, persisted = start_module._build_compliance_account_state(
            bridge, self.store, None, _utc(2026, 7, 14, 8, 0, 0),
        )
        self.assertIsNone(account_state)
        self.assertIsNone(persisted)

    def test_first_reported_balance_bootstraps_and_returns_an_account_state(self):
        bridge = _FakeBridgeEngine(balance=10_000.0)
        account_state, persisted = start_module._build_compliance_account_state(
            bridge, self.store, None, _utc(2026, 7, 14, 8, 0, 0),
        )
        self.assertIsNotNone(account_state)
        self.assertEqual(account_state.account_balance, 10_000.0)
        self.assertEqual(account_state.daily_starting_balance, 10_000.0)
        self.assertIsNotNone(persisted)

    def test_state_carries_across_simulated_cycles_without_resetting(self):
        bridge = _FakeBridgeEngine(balance=10_000.0)
        _, persisted = start_module._build_compliance_account_state(
            bridge, self.store, None, _utc(2026, 7, 14, 8, 0, 0),
        )
        bridge.latest_account_state = SimpleNamespace(balance=9_000.0, received_at=_utc(2026, 7, 14, 11, 59, 0))
        account_state, persisted = start_module._build_compliance_account_state(
            bridge, self.store, persisted, _utc(2026, 7, 14, 12, 0, 0),
        )
        # Same trading day -- daily_starting_balance must not have moved.
        self.assertEqual(account_state.daily_starting_balance, 10_000.0)
        self.assertEqual(account_state.account_balance, 9_000.0)

    def test_state_survives_a_simulated_restart_via_a_fresh_store_instance(self):
        bridge = _FakeBridgeEngine(balance=10_000.0)
        start_module._build_compliance_account_state(bridge, self.store, None, _utc(2026, 7, 14, 8, 0, 0))

        restarted_store = ComplianceStateStore(
            ComplianceStateStoreConfig(state_file=self.tmp_path / "compliance_state.json", daily_reset_hour_utc=0)
        )
        account_state, _ = start_module._build_compliance_account_state(
            bridge, restarted_store, None, _utc(2026, 7, 14, 9, 0, 0),
        )
        self.assertEqual(account_state.daily_starting_balance, 10_000.0)


class TestBootstrapVerificationWiring(unittest.TestCase):
    """KNOWN_GAPS.md #9 at the real `start.py` wiring level: an open
    position or floating P&L on a fresh install must skip the cycle
    rather than bootstrap from a possibly-contaminated balance; a flat
    account (the common case) must bootstrap exactly as before."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)
        self.addCleanup(self._tmpdir.cleanup)
        self.store = ComplianceStateStore(
            ComplianceStateStoreConfig(state_file=self.tmp_path / "compliance_state.json", daily_reset_hour_utc=0)
        )

    def test_open_position_on_fresh_install_skips_the_cycle(self):
        bridge = _FakeBridgeEngine(balance=10_000.0, positions=(SimpleNamespace(position_id="P1"),))
        account_state, persisted = start_module._build_compliance_account_state(
            bridge, self.store, None, _utc(2026, 7, 14, 8, 0, 0),
        )
        self.assertIsNone(account_state)
        self.assertIsNone(persisted)
        self.assertFalse((self.tmp_path / "compliance_state.json").exists())

    def test_floating_pnl_on_fresh_install_skips_the_cycle(self):
        bridge = _FakeBridgeEngine(balance=10_000.0, equity=10_500.0)
        account_state, persisted = start_module._build_compliance_account_state(
            bridge, self.store, None, _utc(2026, 7, 14, 8, 0, 0),
        )
        self.assertIsNone(account_state)
        self.assertIsNone(persisted)

    def test_flat_account_on_fresh_install_bootstraps_normally(self):
        bridge = _FakeBridgeEngine(balance=10_000.0, equity=10_000.0, positions=())
        account_state, persisted = start_module._build_compliance_account_state(
            bridge, self.store, None, _utc(2026, 7, 14, 8, 0, 0),
        )
        self.assertIsNotNone(account_state)
        self.assertEqual(account_state.daily_starting_balance, 10_000.0)
        self.assertIsNotNone(persisted)

    def test_operator_override_bootstraps_despite_open_position(self):
        store = ComplianceStateStore(
            ComplianceStateStoreConfig(
                state_file=self.tmp_path / "compliance_state.json", daily_reset_hour_utc=0,
                day_start_balance_override=7_777.0,
            )
        )
        bridge = _FakeBridgeEngine(balance=10_000.0, equity=11_000.0, positions=(SimpleNamespace(position_id="P1"),))
        account_state, persisted = start_module._build_compliance_account_state(
            bridge, store, None, _utc(2026, 7, 14, 8, 0, 0),
        )
        self.assertIsNotNone(account_state)
        self.assertEqual(account_state.daily_starting_balance, 7_777.0)


if __name__ == "__main__":
    unittest.main()
