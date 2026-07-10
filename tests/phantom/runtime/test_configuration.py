"""Configuration category (ADR-031 SS4-5, SS11): Trading Profiles,
Configuration Versioning, and startup validation."""

from __future__ import annotations

import unittest

from phantom.compliance_engine.config import ComplianceEngineConfig
from phantom.strategy_engine.config import StrategyEngineConfig
from phantom.runtime.models import TradingWindow
from phantom.runtime.profiles import (
    make_london_aggressive_profile,
    make_london_and_new_york_profile,
    make_london_conservative_profile,
    make_new_york_aggressive_profile,
    make_new_york_conservative_profile,
)
from phantom.runtime.validation import validate_profile
from tests.phantom.runtime._fixtures import make_profile


class TestTradingProfiles(unittest.TestCase):
    def test_all_six_named_profiles_construct_and_validate(self):
        profiles = [
            make_london_conservative_profile(),
            make_london_aggressive_profile(),
            make_new_york_conservative_profile(),
            make_new_york_aggressive_profile(),
            make_london_and_new_york_profile(),
        ]
        strategy_config = StrategyEngineConfig()
        compliance_config = ComplianceEngineConfig()
        for profile in profiles:
            result = validate_profile(profile, strategy_config, compliance_config)
            self.assertTrue(result.valid, f"{profile.profile_id} invalid: {result.issues}")

    def test_conservative_has_lower_risk_limits_than_aggressive(self):
        conservative = make_london_conservative_profile()
        aggressive = make_london_aggressive_profile()
        self.assertLess(conservative.risk_profile.daily_risk_limit_r, aggressive.risk_profile.daily_risk_limit_r)


class TestConfigurationVersioning(unittest.TestCase):
    def test_profile_carries_versioning_fields(self):
        profile = make_london_conservative_profile()
        self.assertEqual(profile.profile_id, "london_conservative")
        self.assertEqual(profile.version, 1)
        self.assertIsNotNone(profile.created_at)
        self.assertIsNotNone(profile.modified_at)
        self.assertTrue(profile.author)
        self.assertTrue(profile.description)


class TestStartupValidation(unittest.TestCase):
    def test_valid_profile_passes(self):
        result = validate_profile(make_profile(), StrategyEngineConfig(), ComplianceEngineConfig())
        self.assertTrue(result.valid)

    def test_backwards_trading_window_is_invalid(self):
        profile = make_profile(trading_window=TradingWindow(start_hour_utc=20, end_hour_utc=5))
        result = validate_profile(profile, StrategyEngineConfig(), ComplianceEngineConfig())
        self.assertFalse(result.valid)
        self.assertTrue(any(i.field == "trading_window" for i in result.issues))

    def test_empty_allowed_pairs_is_invalid(self):
        profile = make_profile(allowed_pairs=())
        result = validate_profile(profile, StrategyEngineConfig(), ComplianceEngineConfig())
        self.assertFalse(result.valid)

    def test_malformed_pair_is_invalid(self):
        profile = make_profile(allowed_pairs=("EURUSD", "eur/usd"))
        result = validate_profile(profile, StrategyEngineConfig(), ComplianceEngineConfig())
        self.assertFalse(result.valid)

    def test_pair_ineligible_for_every_allowed_strategy_is_invalid(self):
        from phantom.strategy_engine.models import StrategyId

        profile = make_profile(allowed_pairs=("XAUUSD",), allowed_strategies=(StrategyId.TREND_CONTINUATION,))
        result = validate_profile(profile, StrategyEngineConfig(), ComplianceEngineConfig())
        self.assertFalse(result.valid)

    def test_unknown_compliance_rule_profile_is_invalid(self):
        profile = make_profile(compliance_rule_profile_name="nonexistent_profile")
        result = validate_profile(profile, StrategyEngineConfig(), ComplianceEngineConfig())
        self.assertFalse(result.valid)

    def test_negative_risk_limits_are_invalid(self):
        from phantom.risk_engine.config import RiskEngineConfig

        profile = make_profile(risk_profile=RiskEngineConfig(daily_risk_limit_r=-1.0))
        result = validate_profile(profile, StrategyEngineConfig(), ComplianceEngineConfig())
        self.assertFalse(result.valid)


if __name__ == "__main__":
    unittest.main()
