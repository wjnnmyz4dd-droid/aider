"""Tests for compliance.max_positions_per_pair -- production-invariant
configurability (items 2-4 of the position-limit fix): configurable from
the JSON config, defaults to 1 when absent, and fails closed at startup
for anything other than an integer >= 1."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.deployment_windows._fixtures import load_example_config, write_config
from titan_protocol.evidence_engine.config import EvidenceEngineConfig
from titan_protocol.evidence_engine.models import SessionName
from titan_protocol.opportunity_selection_engine.config import (
    EnabledOpportunityWindow,
    OpportunitySelectionEngineConfig,
)
from titan_protocol.strategy_engine.config import StrategyEngineConfig

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


class TestStrategyEngineConfigurability(unittest.TestCase):
    """ADR-035 Phase 5: `strategy_engine.orb_*` fields wired through
    `StrategyEngineConfig`, and actually reaching `DeploymentSettings`,
    not merely parsed and discarded."""

    def test_defaults_when_section_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(Path(tmp), remove_sections=["strategy_engine"])
            settings = load_settings(config_path)
            self.assertEqual(settings.strategy_config, StrategyEngineConfig())

    def test_defaults_when_key_absent_within_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(Path(tmp), strategy_engine_overrides={})
            settings = load_settings(config_path)
            self.assertEqual(settings.strategy_config, StrategyEngineConfig())

    def test_explicit_value_is_honored_and_reaches_deployment_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(
                Path(tmp), strategy_engine_overrides={"orb_max_spread_pips": 5.0, "orb_min_confirmation_candles": 2},
            )
            settings = load_settings(config_path)
            self.assertEqual(settings.strategy_config.orb_max_spread_pips, 5.0)
            self.assertEqual(settings.strategy_config.orb_min_confirmation_candles, 2)
            # Every other field keeps its default -- only the two overridden above changed.
            self.assertEqual(settings.strategy_config.orb_min_liquidity_score, StrategyEngineConfig().orb_min_liquidity_score)

    def test_invalid_value_fails_closed_at_startup(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(Path(tmp), strategy_engine_overrides={"orb_max_spread_pips": 0.0})
            with self.assertRaises(ConfigError):
                load_settings(config_path)

    def test_malformed_type_fails_closed_at_startup(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(Path(tmp), strategy_engine_overrides={"orb_min_confirmation_candles": "2"})
            with self.assertRaises(ConfigError):
                load_settings(config_path)

    def test_orb_fvg_score_weight_lower_boundary_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(Path(tmp), strategy_engine_overrides={"orb_fvg_score_weight": 0.0})
            settings = load_settings(config_path)
            self.assertEqual(settings.strategy_config.orb_fvg_score_weight, 0.0)

    def test_orb_fvg_score_weight_upper_boundary_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(Path(tmp), strategy_engine_overrides={"orb_fvg_score_weight": 1.0})
            settings = load_settings(config_path)
            self.assertEqual(settings.strategy_config.orb_fvg_score_weight, 1.0)

    def test_orb_fvg_score_weight_above_upper_boundary_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(Path(tmp), strategy_engine_overrides={"orb_fvg_score_weight": 1.01})
            with self.assertRaises(ConfigError):
                load_settings(config_path)

    def test_orb_fvg_score_weight_below_lower_boundary_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(Path(tmp), strategy_engine_overrides={"orb_fvg_score_weight": -0.01})
            with self.assertRaises(ConfigError):
                load_settings(config_path)


class TestEvidenceEngineConfigurability(unittest.TestCase):
    """ADR-035 Phase 5: `evidence_engine.opening_range_*` fields wired
    through `EvidenceEngineConfig`, and actually reaching
    `DeploymentSettings`."""

    def test_defaults_when_section_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(Path(tmp), remove_sections=["evidence_engine"])
            settings = load_settings(config_path)
            self.assertEqual(settings.evidence_config, EvidenceEngineConfig())

    def test_explicit_value_is_honored_and_reaches_deployment_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(
                Path(tmp),
                evidence_engine_overrides={"opening_range_duration_minutes": 60, "opening_range_min_bars": 2},
            )
            settings = load_settings(config_path)
            self.assertEqual(settings.evidence_config.opening_range_duration_minutes, 60)
            self.assertEqual(settings.evidence_config.opening_range_min_bars, 2)
            self.assertEqual(
                settings.evidence_config.expected_bar_interval_seconds, EvidenceEngineConfig().expected_bar_interval_seconds
            )

    def test_invalid_duration_fails_closed_at_startup(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(Path(tmp), evidence_engine_overrides={"opening_range_duration_minutes": 0})
            with self.assertRaises(ConfigError):
                load_settings(config_path)

    def test_bar_count_feasibility_exact_boundary_passes_through_deployment_config(self):
        # duration=30min=1800s, interval=300s (both defaults) -> max_possible_bars=6.
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(Path(tmp), evidence_engine_overrides={"opening_range_min_bars": 6})
            settings = load_settings(config_path)
            self.assertEqual(settings.evidence_config.opening_range_min_bars, 6)

    def test_bar_count_one_above_maximum_fails_closed_through_deployment_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(Path(tmp), evidence_engine_overrides={"opening_range_min_bars": 7})
            with self.assertRaises(ConfigError):
                load_settings(config_path)

    def test_non_exact_division_duration_interval_boundary_through_deployment_config(self):
        # duration=22min=1320s, interval=300s -> ceil(1320/300)=5.
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(
                Path(tmp),
                evidence_engine_overrides={"opening_range_duration_minutes": 22, "opening_range_min_bars": 5},
            )
            settings = load_settings(config_path)
            self.assertEqual(settings.evidence_config.opening_range_min_bars, 5)
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(
                Path(tmp),
                evidence_engine_overrides={"opening_range_duration_minutes": 22, "opening_range_min_bars": 6},
            )
            with self.assertRaises(ConfigError):
                load_settings(config_path)


class TestOpeningRangeAnchorsConfigurability(unittest.TestCase):
    """ADR-035 Phase 5: `opening_range_anchors` JSON parsing and the
    already-existing `EvidenceEngineConfig` anchor-overlap check, proven
    reachable end-to-end through `load_settings()`, not merely at the
    dataclass level (already proven by `test_opening_range.py`)."""

    def test_valid_single_anchor_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(
                Path(tmp),
                evidence_engine_overrides={
                    "opening_range_anchors": [{"session": "LONDON", "start_hour_utc": 7, "start_minute_utc": 0}],
                },
            )
            settings = load_settings(config_path)
            self.assertEqual(
                settings.evidence_config.opening_range_anchors, ((SessionName.LONDON, 7, 0),),
            )

    def test_unknown_session_name_fails_closed_at_startup(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(
                Path(tmp),
                evidence_engine_overrides={
                    "opening_range_anchors": [{"session": "NOT_A_SESSION", "start_hour_utc": 7, "start_minute_utc": 0}],
                },
            )
            with self.assertRaises(ConfigError):
                load_settings(config_path)

    def test_overlapping_anchors_fail_closed_at_startup_through_the_loader(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(
                Path(tmp),
                evidence_engine_overrides={
                    "opening_range_anchors": [
                        {"session": "LONDON", "start_hour_utc": 7, "start_minute_utc": 0},
                        {"session": "LONDON", "start_hour_utc": 7, "start_minute_utc": 15},
                    ],
                },
            )
            with self.assertRaises(ConfigError):
                load_settings(config_path)

    def test_non_list_anchors_fails_closed_at_startup(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(Path(tmp), evidence_engine_overrides={"opening_range_anchors": "not-a-list"})
            with self.assertRaises(ConfigError):
                load_settings(config_path)

    def test_non_integer_start_hour_fails_closed_at_startup(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(
                Path(tmp),
                evidence_engine_overrides={
                    "opening_range_anchors": [{"session": "LONDON", "start_hour_utc": "7", "start_minute_utc": 0}],
                },
            )
            with self.assertRaises(ConfigError):
                load_settings(config_path)


class TestOpportunitySelectionEngineConfigurability(unittest.TestCase):
    """ADR-037 Production Activation Plan §3: `opportunity_selection_engine`
    JSON parsing (`enabled_windows`, `cross_pair_selection_enabled`,
    `tie_tolerance`), proven reachable end-to-end through
    `load_settings()`, mirroring `TestOpeningRangeAnchorsConfigurability`'s
    own established pattern exactly."""

    def test_valid_three_window_configuration_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(
                Path(tmp),
                opportunity_selection_engine_overrides={
                    "cross_pair_selection_enabled": True,
                    "enabled_windows": [
                        {"session": "LONDON", "anchor_hour_utc": 8, "anchor_minute_utc": 0, "enabled": True},
                        {"session": "LONDON_NEW_YORK_OVERLAP", "anchor_hour_utc": 13, "anchor_minute_utc": 0, "enabled": True},
                        {"session": "EARLY_NEW_YORK", "anchor_hour_utc": 13, "anchor_minute_utc": 30, "enabled": True},
                    ],
                },
                evidence_engine_overrides={
                    "opening_range_anchors": [
                        {"session": "LONDON", "start_hour_utc": 8, "start_minute_utc": 0},
                        {"session": "LONDON_NEW_YORK_OVERLAP", "start_hour_utc": 13, "start_minute_utc": 0},
                        {"session": "EARLY_NEW_YORK", "start_hour_utc": 13, "start_minute_utc": 30},
                    ],
                },
            )
            settings = load_settings(config_path)
            self.assertEqual(
                settings.opportunity_selection_config.enabled_windows,
                (
                    EnabledOpportunityWindow(SessionName.LONDON, 8, 0, True),
                    EnabledOpportunityWindow(SessionName.LONDON_NEW_YORK_OVERLAP, 13, 0, True),
                    EnabledOpportunityWindow(SessionName.EARLY_NEW_YORK, 13, 30, True),
                ),
            )
            self.assertTrue(settings.opportunity_selection_config.cross_pair_selection_enabled)

    def test_missing_section_defaults_inert(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(Path(tmp), remove_sections=["opportunity_selection_engine"])
            settings = load_settings(config_path)
            self.assertEqual(settings.opportunity_selection_config, OpportunitySelectionEngineConfig())
            self.assertEqual(settings.opportunity_selection_config.enabled_windows, ())
            self.assertFalse(settings.opportunity_selection_config.cross_pair_selection_enabled)

    def test_missing_enabled_windows_key_within_section_defaults_to_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(
                Path(tmp), opportunity_selection_engine_overrides={"cross_pair_selection_enabled": False},
            )
            # write_config's .update() leaves enabled_windows at the shipped
            # example's own [] -- this asserts that (not a removed key).
            settings = load_settings(config_path)
            self.assertEqual(settings.opportunity_selection_config.enabled_windows, ())

    def test_unknown_session_name_fails_closed_at_startup(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(
                Path(tmp),
                opportunity_selection_engine_overrides={
                    "enabled_windows": [{"session": "NOT_A_SESSION", "anchor_hour_utc": 8, "anchor_minute_utc": 0}],
                },
            )
            with self.assertRaises(ConfigError):
                load_settings(config_path)

    def test_non_list_enabled_windows_fails_closed_at_startup(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(
                Path(tmp), opportunity_selection_engine_overrides={"enabled_windows": "not-a-list"},
            )
            with self.assertRaises(ConfigError):
                load_settings(config_path)

    def test_non_integer_anchor_hour_fails_closed_at_startup(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(
                Path(tmp),
                opportunity_selection_engine_overrides={
                    "enabled_windows": [{"session": "LONDON", "anchor_hour_utc": "8", "anchor_minute_utc": 0}],
                },
            )
            with self.assertRaises(ConfigError):
                load_settings(config_path)

    def test_non_integer_anchor_minute_fails_closed_at_startup(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(
                Path(tmp),
                opportunity_selection_engine_overrides={
                    "enabled_windows": [{"session": "LONDON", "anchor_hour_utc": 8, "anchor_minute_utc": "0"}],
                },
            )
            with self.assertRaises(ConfigError):
                load_settings(config_path)

    def test_non_bool_cross_pair_selection_enabled_fails_closed_at_startup(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(
                Path(tmp), opportunity_selection_engine_overrides={"cross_pair_selection_enabled": "true"},
            )
            with self.assertRaises(ConfigError):
                load_settings(config_path)

    def test_non_bool_window_enabled_field_fails_closed_at_startup(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(
                Path(tmp),
                opportunity_selection_engine_overrides={
                    "enabled_windows": [{"session": "LONDON", "anchor_hour_utc": 8, "anchor_minute_utc": 0, "enabled": "yes"}],
                },
            )
            with self.assertRaises(ConfigError):
                load_settings(config_path)

    def test_window_enabled_field_defaults_true_when_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(
                Path(tmp),
                opportunity_selection_engine_overrides={
                    "enabled_windows": [{"session": "LONDON", "anchor_hour_utc": 8, "anchor_minute_utc": 0}],
                },
            )
            settings = load_settings(config_path)
            self.assertTrue(settings.opportunity_selection_config.enabled_windows[0].enabled)

    def test_duplicate_anchor_key_fails_closed_at_startup(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(
                Path(tmp),
                opportunity_selection_engine_overrides={
                    "enabled_windows": [
                        {"session": "LONDON", "anchor_hour_utc": 8, "anchor_minute_utc": 0},
                        {"session": "LONDON_NEW_YORK_OVERLAP", "anchor_hour_utc": 8, "anchor_minute_utc": 0},
                    ],
                },
            )
            with self.assertRaises(ConfigError):
                load_settings(config_path)

    def test_non_negative_tie_tolerance_is_honored(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(
                Path(tmp), opportunity_selection_engine_overrides={"tie_tolerance": 1.0},
            )
            settings = load_settings(config_path)
            self.assertEqual(settings.opportunity_selection_config.tie_tolerance, 1.0)

    def test_negative_tie_tolerance_fails_closed_at_startup(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(
                Path(tmp), opportunity_selection_engine_overrides={"tie_tolerance": -0.1},
            )
            with self.assertRaises(ConfigError):
                load_settings(config_path)

    def test_arbitrary_cardinality_beyond_three_windows_is_accepted(self):
        """The reviewed Plan's §1 explicitly authorizes only 3 initial
        windows as production *policy* -- this proves the config-loading
        *mechanism* itself imposes no hardcoded cardinality limit (never
        hardcodes London/Overlap/Early-New-York into the parsing path),
        matching the task's explicit "preserve arbitrary-cardinality
        support" requirement. LATE_NEW_YORK/ASIAN/CLOSED are real
        SessionName members not part of the authorized production set --
        used here purely to prove the parser itself has no 3-window
        limit, not to authorize a 4th production window."""
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(
                Path(tmp),
                opportunity_selection_engine_overrides={
                    "enabled_windows": [
                        {"session": "LONDON", "anchor_hour_utc": 8, "anchor_minute_utc": 0},
                        {"session": "LONDON_NEW_YORK_OVERLAP", "anchor_hour_utc": 13, "anchor_minute_utc": 0},
                        {"session": "EARLY_NEW_YORK", "anchor_hour_utc": 13, "anchor_minute_utc": 30},
                        {"session": "LATE_NEW_YORK", "anchor_hour_utc": 18, "anchor_minute_utc": 0},
                    ],
                },
                evidence_engine_overrides={
                    "opening_range_anchors": [
                        {"session": "LONDON", "start_hour_utc": 8, "start_minute_utc": 0},
                        {"session": "LONDON_NEW_YORK_OVERLAP", "start_hour_utc": 13, "start_minute_utc": 0},
                        {"session": "EARLY_NEW_YORK", "start_hour_utc": 13, "start_minute_utc": 30},
                        {"session": "LATE_NEW_YORK", "start_hour_utc": 18, "start_minute_utc": 0},
                    ],
                },
            )
            settings = load_settings(config_path)
            self.assertEqual(len(settings.opportunity_selection_config.enabled_windows), 4)


class TestGateBEnabledWindowMismatchThroughTheLoader(unittest.TestCase):
    """ADR-037 §11 item 2 / `validate_profile()` check 1: an
    `enabled_windows` entry whose `session` doesn't match the anchor's
    own configured `SessionName` is a distinct misconfiguration from an
    unreferenced anchor -- both must be independently reachable through
    the real deployment JSON, not merely at the dataclass level."""

    def test_session_mismatch_between_gate_b_and_enabled_window_loads_but_validate_profile_must_catch_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(
                Path(tmp),
                evidence_engine_overrides={
                    "opening_range_anchors": [{"session": "LONDON", "start_hour_utc": 8, "start_minute_utc": 0}],
                },
                opportunity_selection_engine_overrides={
                    "enabled_windows": [
                        {"session": "LONDON_NEW_YORK_OVERLAP", "anchor_hour_utc": 8, "anchor_minute_utc": 0},
                    ],
                },
            )
            # config_loader itself has no cross-section knowledge (each
            # section parses independently, matching every other section's
            # own convention) -- this loads without a ConfigError; it is
            # validate_profile()'s job (re-verified in
            # tests/titan_protocol/runtime/test_opportunity_selection_structural_readiness.py)
            # to catch the mismatch, not the loader's.
            settings = load_settings(config_path)
            self.assertEqual(len(settings.opportunity_selection_config.enabled_windows), 1)
            self.assertEqual(settings.evidence_config.opening_range_anchors[0][0], SessionName.LONDON)
            self.assertEqual(
                settings.opportunity_selection_config.enabled_windows[0].session_name,
                SessionName.LONDON_NEW_YORK_OVERLAP,
            )


class TestBackwardCompatibilityForOmittedNewSections(unittest.TestCase):
    """A pre-Phase-5 config file (neither new section present) must
    produce byte-identical `StrategyEngineConfig`/`EvidenceEngineConfig`
    objects to today's bare-default construction."""

    def test_both_sections_absent_produces_pure_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(Path(tmp), remove_sections=["strategy_engine", "evidence_engine"])
            settings = load_settings(config_path)
            self.assertEqual(settings.strategy_config, StrategyEngineConfig())
            self.assertEqual(settings.evidence_config, EvidenceEngineConfig())

    def test_opportunity_selection_engine_section_also_absent_produces_pure_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(
                Path(tmp),
                remove_sections=["strategy_engine", "evidence_engine", "opportunity_selection_engine"],
            )
            settings = load_settings(config_path)
            self.assertEqual(settings.strategy_config, StrategyEngineConfig())
            self.assertEqual(settings.evidence_config, EvidenceEngineConfig())
            self.assertEqual(settings.opportunity_selection_config, OpportunitySelectionEngineConfig())


class TestExampleConfigDefaultParity(unittest.TestCase):
    """ADR-035 Phase 5 (required by the finalized Plan §14/§19): the
    shipped example config's new sections must equal the engine
    defaults exactly, so drift is a same-commit, self-diagnosing test
    failure rather than something only discovered indirectly."""

    def test_shipped_strategy_engine_section_equals_python_defaults(self):
        example = load_example_config()
        defaults = StrategyEngineConfig()
        for field in (
            "orb_min_breakout_distance_atr_multiple", "orb_min_body_to_range_ratio",
            "orb_min_confirmation_candles", "orb_max_qualifications_per_range",
            "orb_fvg_max_age_bars", "orb_fvg_min_size_atr_multiple", "orb_fvg_score_weight",
            "orb_min_range_atr_ratio", "orb_max_spread_pips", "orb_min_liquidity_score",
        ):
            self.assertEqual(
                example["strategy_engine"][field], getattr(defaults, field),
                f"strategy_engine.{field} in the shipped example does not match StrategyEngineConfig()'s default",
            )

    def test_shipped_evidence_engine_section_equals_python_defaults(self):
        example = load_example_config()
        defaults = EvidenceEngineConfig()
        self.assertEqual(tuple(example["evidence_engine"]["opening_range_anchors"]), defaults.opening_range_anchors)
        for field in ("opening_range_duration_minutes", "opening_range_min_bars", "expected_bar_interval_seconds"):
            self.assertEqual(
                example["evidence_engine"][field], getattr(defaults, field),
                f"evidence_engine.{field} in the shipped example does not match EvidenceEngineConfig()'s default",
            )

    def test_shipped_opportunity_selection_engine_section_equals_python_defaults(self):
        """ADR-037 Production Activation Plan Phase A: the shipped example
        must remain fully inert (enabled_windows=(), cross_pair_selection_
        enabled=False) -- Gate A/B production values must never be written
        into this shipped default (§11's own explicit requirement)."""
        example = load_example_config()
        defaults = OpportunitySelectionEngineConfig()
        self.assertEqual(example["opportunity_selection_engine"]["enabled_windows"], [])
        self.assertEqual(
            example["opportunity_selection_engine"]["cross_pair_selection_enabled"],
            defaults.cross_pair_selection_enabled,
        )
        self.assertEqual(example["opportunity_selection_engine"]["tie_tolerance"], defaults.tie_tolerance)


if __name__ == "__main__":
    unittest.main()
