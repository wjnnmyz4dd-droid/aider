"""Unit tests: position sizing methods (fixed fractional, confidence
scaling, volatility scaling, fractional-capped Kelly, min/max clamp, lot
normalization) and the "smallest method always wins" rule (ADR-027 §1)."""

from __future__ import annotations

import unittest

from titan_protocol.risk_engine.config import RiskEngineConfig
from titan_protocol.risk_engine.models import ConfidenceTier, StatisticalMetrics, VolatilityAdjustment
from titan_protocol.risk_engine.position_sizing import compute_position_size
from tests.titan_protocol.risk_engine._fixtures import make_config

INSUFFICIENT = StatisticalMetrics(sufficient_data=False, sample_size=3)
SUFFICIENT_NO_KELLY = StatisticalMetrics(sufficient_data=True, sample_size=30)
TIER_5 = ConfidenceTier(label="TIER_5", min_score=90.0, max_score=100.0, base_r=1.25)
NORMAL_VOL = VolatilityAdjustment(atr=0.001, volatility_label="NORMAL", sizing_multiplier=1.0, reason="normal")


class TestFailClosedSizing(unittest.TestCase):
    def test_insufficient_data_caps_at_fail_closed_tier(self):
        config = make_config()
        rec = compute_position_size(TIER_5, NORMAL_VOL, INSUFFICIENT, config)
        self.assertEqual(rec.confidence_scaled_r, config.fail_closed_tier.base_r)
        self.assertEqual(rec.final_r, config.fail_closed_tier.base_r)
        self.assertIsNone(rec.kelly_r)


class TestVolatilityScaling(unittest.TestCase):
    def test_multiplier_applied_to_confidence_scaled_r(self):
        config = make_config()
        vol = VolatilityAdjustment(atr=0.002, volatility_label="ABNORMAL", sizing_multiplier=0.5, reason="abnormal")
        rec = compute_position_size(TIER_5, vol, SUFFICIENT_NO_KELLY, config)
        self.assertAlmostEqual(rec.volatility_scaled_r, TIER_5.base_r * 0.5)


class TestKellyCeiling(unittest.TestCase):
    def test_kelly_never_increases_size_above_schedule(self):
        config = make_config(kelly_fraction_cap=1.0, kelly_max_r=100.0)  # deliberately generous cap
        metrics = StatisticalMetrics(sufficient_data=True, sample_size=30, kelly_fraction=5.0)  # absurdly large edge
        rec = compute_position_size(TIER_5, NORMAL_VOL, metrics, config)
        # Even with an enormous Kelly fraction, final_r is capped by max_position_r, never
        # inflated beyond the engine's own configured ceiling.
        self.assertLessEqual(rec.final_r, config.max_position_r)

    def test_kelly_can_shrink_below_confidence_schedule(self):
        config = make_config(kelly_fraction_cap=0.25, kelly_max_r=1.0)
        metrics = StatisticalMetrics(sufficient_data=True, sample_size=30, kelly_fraction=0.04)  # tiny edge
        rec = compute_position_size(TIER_5, NORMAL_VOL, metrics, config)
        self.assertLess(rec.final_r, TIER_5.base_r)
        self.assertAlmostEqual(rec.kelly_r, 0.04 * 0.25, places=6)

    def test_negative_kelly_fraction_never_contributes_positive_risk(self):
        config = make_config()
        metrics = StatisticalMetrics(sufficient_data=True, sample_size=30, kelly_fraction=-0.5)
        rec = compute_position_size(TIER_5, NORMAL_VOL, metrics, config)
        self.assertEqual(rec.kelly_r, 0.0)


class TestClamps(unittest.TestCase):
    def test_max_position_cap_applied(self):
        config = make_config(max_position_r=0.5)
        rec = compute_position_size(TIER_5, NORMAL_VOL, SUFFICIENT_NO_KELLY, config)
        self.assertEqual(rec.final_r, 0.5)
        self.assertTrue(rec.capped)

    def test_min_position_floor_applied(self):
        config = make_config(min_position_r=0.5)
        tiny_tier = ConfidenceTier(label="TINY", min_score=65.0, max_score=69.9, base_r=0.05)
        rec = compute_position_size(tiny_tier, NORMAL_VOL, SUFFICIENT_NO_KELLY, config)
        self.assertEqual(rec.final_r, 0.5)
        self.assertTrue(rec.capped)

    def test_lot_size_normalized_to_lot_step(self):
        config = make_config(lot_step=0.01, r_to_lot_multiplier=1.0)
        rec = compute_position_size(TIER_5, NORMAL_VOL, SUFFICIENT_NO_KELLY, config)
        scaled = rec.lot_size / config.lot_step
        self.assertAlmostEqual(scaled, round(scaled), places=6)


if __name__ == "__main__":
    unittest.main()
