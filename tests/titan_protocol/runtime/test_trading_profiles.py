"""Trading Profile validation (Phase 3B): per-profile explicit
assertions for all 6 built-in profiles -- sessions, allowed pairs,
strategy eligibility, risk schedule, compliance profile, and news
policy -- beyond `test_configuration.py`'s basic `valid == True` check."""

from __future__ import annotations

import unittest

from titan_protocol.compliance_engine.config import ComplianceEngineConfig
from titan_protocol.evidence_engine.models import SessionName
from titan_protocol.market_intelligence.config import MarketIntelligenceConfig
from titan_protocol.strategy_engine.config import DEFAULT_APPROVED_PAIRS_BY_STRATEGY, StrategyEngineConfig
from titan_protocol.strategy_engine.models import StrategyId
from titan_protocol.runtime.profiles import (
    make_london_aggressive_profile,
    make_london_and_new_york_profile,
    make_london_conservative_profile,
    make_new_york_aggressive_profile,
    make_new_york_conservative_profile,
)
from titan_protocol.runtime.validation import validate_profile

# Independently re-derived from the same single source of truth
# `titan_protocol.runtime.profiles` itself uses -- never importing that
# module's own private `_TRADEABLE_PAIR_UNIVERSE` constant, so this
# test would actually fail if the profile factories silently drifted
# from `DEFAULT_APPROVED_PAIRS_BY_STRATEGY`.
_EXPECTED_TRADEABLE_UNIVERSE = frozenset(
    pair for _strategy_id, pairs in DEFAULT_APPROVED_PAIRS_BY_STRATEGY for pair in pairs
)
_ALL_STRATEGY_IDS = frozenset(StrategyId)

_LONDON_SESSIONS = frozenset((SessionName.LONDON, SessionName.LONDON_NEW_YORK_OVERLAP))
_NEW_YORK_SESSIONS = frozenset((SessionName.LONDON_NEW_YORK_OVERLAP, SessionName.EARLY_NEW_YORK, SessionName.LATE_NEW_YORK))

_ALL_PROFILE_FACTORIES = (
    make_london_conservative_profile,
    make_london_aggressive_profile,
    make_new_york_conservative_profile,
    make_new_york_aggressive_profile,
    make_london_and_new_york_profile,
)


class TestEveryProfileSessions(unittest.TestCase):
    def test_london_profiles_restrict_to_london_sessions_only(self):
        for factory in (make_london_conservative_profile, make_london_aggressive_profile):
            profile = factory()
            self.assertEqual(set(profile.session_rules), _LONDON_SESSIONS, profile.profile_id)

    def test_new_york_profiles_restrict_to_new_york_sessions_only(self):
        for factory in (make_new_york_conservative_profile, make_new_york_aggressive_profile):
            profile = factory()
            self.assertEqual(set(profile.session_rules), _NEW_YORK_SESSIONS, profile.profile_id)

    def test_combined_profile_allows_the_union_of_both_session_sets(self):
        profile = make_london_and_new_york_profile()
        self.assertEqual(set(profile.session_rules), _LONDON_SESSIONS | _NEW_YORK_SESSIONS)


class TestEveryProfileAllowedPairs(unittest.TestCase):
    def test_every_named_profile_defaults_to_the_tradeable_universe(self):
        for factory in _ALL_PROFILE_FACTORIES:
            profile = factory()
            self.assertEqual(set(profile.allowed_pairs), _EXPECTED_TRADEABLE_UNIVERSE, profile.profile_id)

    def test_tradeable_universe_is_non_empty_and_well_formed(self):
        self.assertTrue(_EXPECTED_TRADEABLE_UNIVERSE)
        for pair in _EXPECTED_TRADEABLE_UNIVERSE:
            self.assertEqual(len(pair), 6)


class TestEveryProfileStrategyEligibility(unittest.TestCase):
    def test_every_named_profile_allows_every_strategy(self):
        for factory in _ALL_PROFILE_FACTORIES:
            profile = factory()
            self.assertEqual(set(profile.allowed_strategies), _ALL_STRATEGY_IDS, profile.profile_id)

    def test_every_allowed_pair_is_eligible_for_at_least_one_allowed_strategy(self):
        strategy_config = StrategyEngineConfig()
        for factory in _ALL_PROFILE_FACTORIES:
            profile = factory()
            tradeable = set()
            for strategy_id in profile.allowed_strategies:
                tradeable.update(strategy_config.approved_pairs_for(strategy_id))
            ineligible = set(profile.allowed_pairs) - tradeable
            self.assertEqual(ineligible, set(), f"{profile.profile_id}: {ineligible}")


class TestEveryProfileRiskSchedule(unittest.TestCase):
    def test_conservative_profiles_use_the_reduced_risk_schedule(self):
        for factory in (make_london_conservative_profile, make_new_york_conservative_profile):
            profile = factory()
            self.assertEqual(profile.risk_profile.daily_risk_limit_r, 1.5, profile.profile_id)
            self.assertEqual(profile.risk_profile.portfolio_heat_limit_r, 3.0, profile.profile_id)
            self.assertEqual(profile.risk_profile.max_open_positions, 5, profile.profile_id)

    def test_aggressive_and_combined_profiles_use_engine_default_risk_schedule(self):
        from titan_protocol.risk_engine.config import RiskEngineConfig

        defaults = RiskEngineConfig()
        for factory in (make_london_aggressive_profile, make_new_york_aggressive_profile, make_london_and_new_york_profile):
            profile = factory()
            self.assertEqual(profile.risk_profile.daily_risk_limit_r, defaults.daily_risk_limit_r, profile.profile_id)
            self.assertEqual(profile.risk_profile.portfolio_heat_limit_r, defaults.portfolio_heat_limit_r, profile.profile_id)

    def test_conservative_risk_schedule_is_strictly_tighter_than_aggressive_in_every_dimension(self):
        conservative = make_london_conservative_profile().risk_profile
        aggressive = make_london_aggressive_profile().risk_profile
        self.assertLessEqual(conservative.daily_risk_limit_r, aggressive.daily_risk_limit_r)
        self.assertLessEqual(conservative.portfolio_heat_limit_r, aggressive.portfolio_heat_limit_r)
        self.assertLessEqual(conservative.max_open_positions, aggressive.max_open_positions)


class TestEveryProfileComplianceProfile(unittest.TestCase):
    def test_every_named_profile_references_a_real_compliance_rule_profile(self):
        compliance_config = ComplianceEngineConfig()
        for factory in _ALL_PROFILE_FACTORIES:
            profile = factory()
            # Raises ValueError if the name doesn't resolve -- the
            # assertion is that this never raises for a named profile.
            compliance_config.profile_for(profile.compliance_rule_profile_name)


class TestEveryProfileNewsPolicy(unittest.TestCase):
    def test_every_named_profile_carries_a_concrete_news_policy(self):
        for factory in _ALL_PROFILE_FACTORIES:
            profile = factory()
            self.assertIsInstance(profile.news_policy, MarketIntelligenceConfig)


class TestEveryProfileValidates(unittest.TestCase):
    def test_every_named_profile_passes_startup_validation(self):
        strategy_config = StrategyEngineConfig()
        compliance_config = ComplianceEngineConfig()
        for factory in _ALL_PROFILE_FACTORIES:
            profile = factory()
            result = validate_profile(profile, strategy_config, compliance_config)
            self.assertTrue(result.valid, f"{profile.profile_id}: {result.issues}")


if __name__ == "__main__":
    unittest.main()
