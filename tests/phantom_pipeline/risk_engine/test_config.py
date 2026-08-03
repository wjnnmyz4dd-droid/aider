"""RiskEngineConfig immutability, safe defaults, and placeholder
configurability (ADR-005 §6)."""

from __future__ import annotations

import dataclasses
import unittest

from phantom_pipeline.risk_engine.config import RiskEngineConfig


class TestRiskEngineConfigImmutability(unittest.TestCase):
    def test_top_level_fields_cannot_be_reassigned(self):
        config = RiskEngineConfig()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            config.max_risk_percent_per_trade = 99.0  # type: ignore[misc]

    def test_correlation_buckets_cannot_be_mutated(self):
        config = RiskEngineConfig(correlation_buckets={"EURUSD": "A"})
        with self.assertRaises(TypeError):
            config.correlation_buckets["GBPUSD"] = "A"  # type: ignore[index]

    def test_volatility_multipliers_cannot_be_mutated(self):
        config = RiskEngineConfig()
        with self.assertRaises(TypeError):
            config.volatility_multipliers["EXTREME"] = 1.0  # type: ignore[index]

    def test_mutating_caller_supplied_dict_after_construction_does_not_affect_config(self):
        buckets = {"EURUSD": "A"}
        config = RiskEngineConfig(correlation_buckets=buckets)
        buckets["GBPUSD"] = "B"
        self.assertNotIn("GBPUSD", config.correlation_buckets)


class TestPlaceholderConfigurability(unittest.TestCase):
    """Every ceiling/threshold/multiplier is clearly a tunable, overridable
    placeholder — never hardcoded architecture."""

    def test_per_trade_ceiling_is_configurable(self):
        config = RiskEngineConfig(max_risk_percent_per_trade=2.5)
        self.assertEqual(config.max_risk_percent_per_trade, 2.5)

    def test_volatility_multiplier_unmapped_label_fails_closed_to_zero(self):
        config = RiskEngineConfig(volatility_multipliers={})
        self.assertEqual(config.volatility_multiplier("EXTREME"), 0.0)
        self.assertEqual(config.volatility_multiplier("UNKNOWN"), 0.0)

    def test_default_volatility_multipliers_never_include_unknown(self):
        config = RiskEngineConfig()
        self.assertNotIn("UNKNOWN", config.volatility_multipliers)
        self.assertEqual(config.volatility_multiplier("UNKNOWN"), 0.0)

    def test_correlation_bucket_unconfigured_symbol_is_none(self):
        config = RiskEngineConfig()
        self.assertIsNone(config.correlation_bucket_for("EURUSD"))

    def test_tier_multiplier_picks_highest_threshold_met(self):
        config = RiskEngineConfig(loss_streak_tiers=((3, 0.5), (5, 0.0)))
        self.assertEqual(config.tier_multiplier(config.loss_streak_tiers, 6), 0.0)
        self.assertEqual(config.tier_multiplier(config.loss_streak_tiers, 5), 0.0)
        self.assertEqual(config.tier_multiplier(config.loss_streak_tiers, 4), 0.5)
        self.assertEqual(config.tier_multiplier(config.loss_streak_tiers, 3), 0.5)
        self.assertEqual(config.tier_multiplier(config.loss_streak_tiers, 2), 1.0)

    def test_empty_tiers_never_reduce(self):
        config = RiskEngineConfig(loss_streak_tiers=())
        self.assertEqual(config.tier_multiplier(config.loss_streak_tiers, 100), 1.0)


if __name__ == "__main__":
    unittest.main()
