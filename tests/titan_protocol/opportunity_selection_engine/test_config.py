"""Tests for `OpportunitySelectionEngineConfig`/`EnabledOpportunityWindow`
(ADR-037 §8/§11): degenerate-by-default cardinality, duplicate-anchor
rejection, `cross_pair_selection_enabled` explicit-flag semantics."""

from __future__ import annotations

import unittest

from titan_protocol.opportunity_selection_engine.config import (
    EnabledOpportunityWindow,
    OpportunitySelectionEngineConfig,
)
from titan_protocol.strategy_engine.models import SessionName


def _window(session_name: SessionName, hour: int, minute: int = 0, enabled: bool = True) -> EnabledOpportunityWindow:
    return EnabledOpportunityWindow(session_name=session_name, anchor_hour_utc=hour, anchor_minute_utc=minute, enabled=enabled)


class TestDefaultsAreInert(unittest.TestCase):
    def test_default_enabled_windows_is_empty(self):
        config = OpportunitySelectionEngineConfig()
        self.assertEqual(config.enabled_windows, ())

    def test_default_cross_pair_selection_enabled_is_false(self):
        config = OpportunitySelectionEngineConfig()
        self.assertFalse(config.cross_pair_selection_enabled)

    def test_default_tie_tolerance_matches_closed_product_policy(self):
        config = OpportunitySelectionEngineConfig()
        self.assertEqual(config.tie_tolerance, 0.5)


class TestArbitraryWindowCardinality(unittest.TestCase):
    def test_zero_windows(self):
        config = OpportunitySelectionEngineConfig(enabled_windows=())
        self.assertEqual(len(config.enabled_windows), 0)

    def test_one_window(self):
        config = OpportunitySelectionEngineConfig(enabled_windows=(_window(SessionName.LONDON, 7),))
        self.assertEqual(len(config.enabled_windows), 1)

    def test_two_windows(self):
        config = OpportunitySelectionEngineConfig(
            enabled_windows=(_window(SessionName.LONDON, 7), _window(SessionName.EARLY_NEW_YORK, 12)),
        )
        self.assertEqual(len(config.enabled_windows), 2)

    def test_three_windows_matches_closed_initial_policy_cardinality(self):
        config = OpportunitySelectionEngineConfig(
            enabled_windows=(
                _window(SessionName.LONDON, 7),
                _window(SessionName.LONDON_NEW_YORK_OVERLAP, 12),
                _window(SessionName.EARLY_NEW_YORK, 13),
            ),
        )
        self.assertEqual(len(config.enabled_windows), 3)

    def test_more_than_three_windows(self):
        config = OpportunitySelectionEngineConfig(
            enabled_windows=tuple(_window(SessionName.LONDON, hour) for hour in range(6, 11)),
        )
        self.assertEqual(len(config.enabled_windows), 5)


class TestValidation(unittest.TestCase):
    def test_negative_tie_tolerance_rejected(self):
        with self.assertRaises(ValueError):
            OpportunitySelectionEngineConfig(tie_tolerance=-0.1)

    def test_zero_tie_tolerance_accepted(self):
        config = OpportunitySelectionEngineConfig(tie_tolerance=0.0)
        self.assertEqual(config.tie_tolerance, 0.0)

    def test_duplicate_anchor_hour_minute_pair_rejected(self):
        with self.assertRaises(ValueError):
            OpportunitySelectionEngineConfig(
                enabled_windows=(_window(SessionName.LONDON, 7, 0), _window(SessionName.EARLY_NEW_YORK, 7, 0)),
            )

    def test_same_hour_different_minute_is_not_a_duplicate(self):
        config = OpportunitySelectionEngineConfig(
            enabled_windows=(_window(SessionName.LONDON, 7, 0), _window(SessionName.EARLY_NEW_YORK, 7, 30)),
        )
        self.assertEqual(len(config.enabled_windows), 2)


class TestCrossPairSelectionEnabledIsExplicit(unittest.TestCase):
    def test_flag_never_inferred_it_is_a_plain_stored_field(self):
        config = OpportunitySelectionEngineConfig(cross_pair_selection_enabled=True, enabled_windows=())
        # Explicit flag, independent of enabled_windows cardinality -- a
        # deployment could (in principle) set this True with zero windows
        # configured, which must not raise or auto-correct anything.
        self.assertTrue(config.cross_pair_selection_enabled)


class TestEnabledOpportunityWindowIdentity(unittest.TestCase):
    def test_session_name_is_descriptive_only_not_part_of_any_key(self):
        window = _window(SessionName.LONDON, 7, 30)
        self.assertEqual(window.anchor_hour_utc, 7)
        self.assertEqual(window.anchor_minute_utc, 30)
        self.assertEqual(window.session_name, SessionName.LONDON)

    def test_enabled_defaults_to_true(self):
        window = EnabledOpportunityWindow(session_name=SessionName.LONDON, anchor_hour_utc=7, anchor_minute_utc=0)
        self.assertTrue(window.enabled)


if __name__ == "__main__":
    unittest.main()
