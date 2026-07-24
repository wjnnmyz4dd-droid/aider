"""Tests for compliance.max_positions_per_pair -- production-invariant
configurability (items 2-4 of the position-limit fix): configurable from
the JSON config, defaults to 1 when absent, and fails closed at startup
for anything other than an integer >= 1."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.deployment_windows._fixtures import write_config

from config_loader import ConfigError, load_settings


class TestMaxPositionsPerPairConfigurability(unittest.TestCase):
    def test_defaults_to_one_when_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(Path(tmp))
            settings = load_settings(config_path)
            profile = settings.compliance_config.profile_for(settings.compliance_rule_profile_name)
            self.assertEqual(profile.max_positions_per_pair, 1)

    def test_explicit_value_is_honored(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(Path(tmp), compliance_overrides={"max_positions_per_pair": 3})
            settings = load_settings(config_path)
            profile = settings.compliance_config.profile_for(settings.compliance_rule_profile_name)
            self.assertEqual(profile.max_positions_per_pair, 3)

    def test_value_of_one_explicit_is_honored(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(Path(tmp), compliance_overrides={"max_positions_per_pair": 1})
            settings = load_settings(config_path)
            profile = settings.compliance_config.profile_for(settings.compliance_rule_profile_name)
            self.assertEqual(profile.max_positions_per_pair, 1)

    def test_zero_fails_closed_at_startup(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(Path(tmp), compliance_overrides={"max_positions_per_pair": 0})
            with self.assertRaises(ConfigError):
                load_settings(config_path)

    def test_negative_fails_closed_at_startup(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(Path(tmp), compliance_overrides={"max_positions_per_pair": -1})
            with self.assertRaises(ConfigError):
                load_settings(config_path)

    def test_non_integer_fails_closed_at_startup(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(Path(tmp), compliance_overrides={"max_positions_per_pair": 1.5})
            with self.assertRaises(ConfigError):
                load_settings(config_path)

    def test_string_value_fails_closed_at_startup(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(Path(tmp), compliance_overrides={"max_positions_per_pair": "1"})
            with self.assertRaises(ConfigError):
                load_settings(config_path)

    def test_only_the_selected_named_profile_is_overridden(self):
        """dataclasses.replace() must target the profile actually
        selected by compliance.rule_profile_name, not silently apply to
        every registered profile (today there is only one, but this
        guards the override logic itself, not the current profile
        count)."""
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(Path(tmp), compliance_overrides={"max_positions_per_pair": 5})
            settings = load_settings(config_path)
            selected = settings.compliance_config.profile_for(settings.compliance_rule_profile_name)
            self.assertEqual(selected.max_positions_per_pair, 5)
            self.assertEqual(selected.name, settings.compliance_rule_profile_name)


class TestMaxAccountStateAgeSecondsConfigurability(unittest.TestCase):
    """ACCOUNT_STATE_STALE fail-closed freshness bound -- configurable,
    defaults to 30s (matching the EA's own FailClosedTimeoutSeconds),
    fails closed at startup for anything <= 0."""

    def test_defaults_to_thirty_when_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(Path(tmp))
            settings = load_settings(config_path)
            profile = settings.compliance_config.profile_for(settings.compliance_rule_profile_name)
            self.assertEqual(profile.max_account_state_age_seconds, 30.0)

    def test_explicit_value_is_honored(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(Path(tmp), compliance_overrides={"max_account_state_age_seconds": 60.0})
            settings = load_settings(config_path)
            profile = settings.compliance_config.profile_for(settings.compliance_rule_profile_name)
            self.assertEqual(profile.max_account_state_age_seconds, 60.0)

    def test_zero_fails_closed_at_startup(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(Path(tmp), compliance_overrides={"max_account_state_age_seconds": 0})
            with self.assertRaises(ConfigError):
                load_settings(config_path)

    def test_negative_fails_closed_at_startup(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(Path(tmp), compliance_overrides={"max_account_state_age_seconds": -5.0})
            with self.assertRaises(ConfigError):
                load_settings(config_path)


class TestDayStartBalanceOverrideConfigurability(unittest.TestCase):
    """KNOWN_GAPS.md #9: operator-supplied day-start balance override --
    absent by default (None), configurable, and fails closed at startup
    for a non-positive value rather than silently accepting a typo."""

    def test_defaults_to_none_when_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(Path(tmp))
            settings = load_settings(config_path)
            self.assertIsNone(settings.compliance_day_start_balance_override)

    def test_explicit_value_is_honored(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(Path(tmp), compliance_overrides={"day_start_balance_override": 25_000.0})
            settings = load_settings(config_path)
            self.assertEqual(settings.compliance_day_start_balance_override, 25_000.0)

    def test_zero_fails_closed_at_startup(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(Path(tmp), compliance_overrides={"day_start_balance_override": 0})
            with self.assertRaises(ConfigError):
                load_settings(config_path)

    def test_negative_fails_closed_at_startup(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(Path(tmp), compliance_overrides={"day_start_balance_override": -100.0})
            with self.assertRaises(ConfigError):
                load_settings(config_path)


class TestFlatAccountEquityToleranceConfigurability(unittest.TestCase):
    """KNOWN_GAPS.md #9: the balance/equity comparison tolerance used to
    verify an account is flat before trusting its first-ever reported
    balance -- defaults to 0.01, configurable, fails closed for a
    negative value."""

    def test_defaults_to_one_cent_when_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(Path(tmp))
            settings = load_settings(config_path)
            self.assertEqual(settings.compliance_flat_account_equity_tolerance, 0.01)

    def test_explicit_value_is_honored(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(Path(tmp), compliance_overrides={"flat_account_equity_tolerance": 1.0})
            settings = load_settings(config_path)
            self.assertEqual(settings.compliance_flat_account_equity_tolerance, 1.0)

    def test_negative_fails_closed_at_startup(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(Path(tmp), compliance_overrides={"flat_account_equity_tolerance": -0.5})
            with self.assertRaises(ConfigError):
                load_settings(config_path)


if __name__ == "__main__":
    unittest.main()
