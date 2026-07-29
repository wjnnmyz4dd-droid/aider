"""`validate_profile()`'s four new, additive structural-readiness checks
(ADR-037 §11, Plan §5) -- gated entirely on the explicit
`cross_pair_selection_enabled` flag, never on Gate A's pair count."""

from __future__ import annotations

import unittest

from titan_protocol.compliance_engine.config import ComplianceEngineConfig
from titan_protocol.evidence_engine.config import EvidenceEngineConfig
from titan_protocol.opportunity_selection_engine.config import (
    EnabledOpportunityWindow,
    OpportunitySelectionEngineConfig,
)
from titan_protocol.runtime.validation import validate_profile
from titan_protocol.strategy_engine.config import StrategyEngineConfig
from titan_protocol.strategy_engine.models import SessionName, StrategyId
from tests.titan_protocol.runtime._fixtures import make_profile


def _strategy_config(orb_pairs) -> StrategyEngineConfig:
    return StrategyEngineConfig(approved_pairs_by_strategy=((StrategyId.OPENING_RANGE_BREAKOUT, tuple(orb_pairs)),))


class TestExistingCallersUnaffected(unittest.TestCase):
    def test_omitting_both_new_parameters_skips_all_four_checks(self):
        profile = make_profile()
        result = validate_profile(profile, StrategyEngineConfig(), ComplianceEngineConfig())
        self.assertTrue(result.valid)

    def test_omitting_only_one_new_parameter_still_skips_all_four_checks(self):
        profile = make_profile()
        result = validate_profile(
            profile, StrategyEngineConfig(), ComplianceEngineConfig(), evidence_config=EvidenceEngineConfig(),
        )
        self.assertTrue(result.valid)


class TestCheck1DanglingAnchorReferenceUnconditional(unittest.TestCase):
    def test_enabled_window_with_no_matching_gate_b_anchor_fails_even_when_selection_disabled(self):
        profile = make_profile()
        evidence_config = EvidenceEngineConfig(opening_range_anchors=())
        selection_config = OpportunitySelectionEngineConfig(
            enabled_windows=(EnabledOpportunityWindow(session_name=SessionName.LONDON, anchor_hour_utc=7, anchor_minute_utc=0),),
            cross_pair_selection_enabled=False,
        )
        result = validate_profile(profile, StrategyEngineConfig(), ComplianceEngineConfig(), evidence_config, selection_config)
        self.assertFalse(result.valid)

    def test_matching_anchor_but_mismatched_session_name_fails(self):
        profile = make_profile()
        evidence_config = EvidenceEngineConfig(opening_range_anchors=((SessionName.LONDON, 7, 0),))
        selection_config = OpportunitySelectionEngineConfig(
            enabled_windows=(EnabledOpportunityWindow(session_name=SessionName.EARLY_NEW_YORK, anchor_hour_utc=7, anchor_minute_utc=0),),
        )
        result = validate_profile(profile, StrategyEngineConfig(), ComplianceEngineConfig(), evidence_config, selection_config)
        self.assertFalse(result.valid)

    def test_matching_anchor_and_session_name_passes_check_1(self):
        profile = make_profile()
        evidence_config = EvidenceEngineConfig(opening_range_anchors=((SessionName.LONDON, 7, 0),))
        selection_config = OpportunitySelectionEngineConfig(
            enabled_windows=(EnabledOpportunityWindow(session_name=SessionName.LONDON, anchor_hour_utc=7, anchor_minute_utc=0),),
            cross_pair_selection_enabled=False,
        )
        result = validate_profile(profile, StrategyEngineConfig(), ComplianceEngineConfig(), evidence_config, selection_config)
        self.assertTrue(result.valid)


class TestChecks2Through4OnlyWhenFlagTrue(unittest.TestCase):
    def test_fixed_multi_pair_gate_a_with_selection_disabled_passes_validation_untouched(self):
        """The exact regression this correction exists to prevent: a
        fixed, non-cross-pair-selecting Gate A with more than one
        approved pair must never trip checks 2-4 just because it has a
        wide Gate A -- only the explicit flag does."""
        profile = make_profile()
        strategy_config = _strategy_config(["EURUSD", "GBPUSD", "USDJPY"])
        evidence_config = EvidenceEngineConfig(opening_range_anchors=())
        selection_config = OpportunitySelectionEngineConfig(enabled_windows=(), cross_pair_selection_enabled=False)
        result = validate_profile(profile, strategy_config, ComplianceEngineConfig(), evidence_config, selection_config)
        self.assertTrue(result.valid)

    def test_enabled_true_with_empty_enabled_windows_fails_check_3(self):
        profile = make_profile()
        strategy_config = _strategy_config(["EURUSD", "GBPUSD"])
        evidence_config = EvidenceEngineConfig(opening_range_anchors=())
        selection_config = OpportunitySelectionEngineConfig(enabled_windows=(), cross_pair_selection_enabled=True)
        result = validate_profile(profile, strategy_config, ComplianceEngineConfig(), evidence_config, selection_config)
        self.assertFalse(result.valid)

    def test_enabled_true_with_unreferenced_anchor_fails_check_2(self):
        profile = make_profile()
        strategy_config = _strategy_config(["EURUSD", "GBPUSD"])
        evidence_config = EvidenceEngineConfig(
            opening_range_anchors=((SessionName.LONDON, 7, 0), (SessionName.EARLY_NEW_YORK, 13, 0)),
        )
        selection_config = OpportunitySelectionEngineConfig(
            enabled_windows=(EnabledOpportunityWindow(session_name=SessionName.LONDON, anchor_hour_utc=7, anchor_minute_utc=0),),
            cross_pair_selection_enabled=True,
        )
        result = validate_profile(profile, strategy_config, ComplianceEngineConfig(), evidence_config, selection_config)
        self.assertFalse(result.valid)

    def test_enabled_true_with_gate_a_width_one_fails_check_4(self):
        profile = make_profile()
        strategy_config = _strategy_config(["EURUSD"])
        evidence_config = EvidenceEngineConfig(opening_range_anchors=((SessionName.LONDON, 7, 0),))
        selection_config = OpportunitySelectionEngineConfig(
            enabled_windows=(EnabledOpportunityWindow(session_name=SessionName.LONDON, anchor_hour_utc=7, anchor_minute_utc=0),),
            cross_pair_selection_enabled=True,
        )
        result = validate_profile(profile, strategy_config, ComplianceEngineConfig(), evidence_config, selection_config)
        self.assertFalse(result.valid)

    def test_enabled_true_gate_a_width_zero_also_fails_check_4(self):
        profile = make_profile()
        strategy_config = _strategy_config([])
        evidence_config = EvidenceEngineConfig(opening_range_anchors=((SessionName.LONDON, 7, 0),))
        selection_config = OpportunitySelectionEngineConfig(
            enabled_windows=(EnabledOpportunityWindow(session_name=SessionName.LONDON, anchor_hour_utc=7, anchor_minute_utc=0),),
            cross_pair_selection_enabled=True,
        )
        result = validate_profile(profile, strategy_config, ComplianceEngineConfig(), evidence_config, selection_config)
        self.assertFalse(result.valid)

    def test_fully_valid_active_configuration_passes_all_four_checks(self):
        profile = make_profile()
        strategy_config = _strategy_config(["EURUSD", "GBPUSD"])
        evidence_config = EvidenceEngineConfig(
            opening_range_anchors=((SessionName.LONDON, 7, 0), (SessionName.EARLY_NEW_YORK, 13, 0)),
        )
        selection_config = OpportunitySelectionEngineConfig(
            enabled_windows=(
                EnabledOpportunityWindow(session_name=SessionName.LONDON, anchor_hour_utc=7, anchor_minute_utc=0),
                EnabledOpportunityWindow(session_name=SessionName.EARLY_NEW_YORK, anchor_hour_utc=13, anchor_minute_utc=0),
            ),
            cross_pair_selection_enabled=True,
        )
        result = validate_profile(profile, strategy_config, ComplianceEngineConfig(), evidence_config, selection_config)
        self.assertTrue(result.valid, f"unexpected issues: {result.issues}")


class TestValidateProfilesPropagation(unittest.TestCase):
    def test_validate_profiles_propagates_the_two_new_parameters(self):
        from titan_protocol.runtime.validation import validate_profiles

        profiles = (make_profile(),)
        strategy_config = _strategy_config(["EURUSD"])
        evidence_config = EvidenceEngineConfig(opening_range_anchors=())
        selection_config = OpportunitySelectionEngineConfig(enabled_windows=(), cross_pair_selection_enabled=True)
        results = validate_profiles(profiles, strategy_config, ComplianceEngineConfig(), evidence_config, selection_config)
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].valid)  # check 3 fails: enabled=True, enabled_windows empty


if __name__ == "__main__":
    unittest.main()
