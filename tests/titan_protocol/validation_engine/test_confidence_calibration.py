"""Unit category (ADR-030 §5.11): Confidence Calibration -- higher
confidence tiers must not show materially worse expectancy than lower
tiers."""

from __future__ import annotations

import unittest

from titan_protocol.research_engine.config import ResearchEngineConfig
from titan_protocol.risk_engine.config import DEFAULT_CONFIDENCE_SCHEDULE
from titan_protocol.validation_engine.confidence_calibration import run_confidence_calibration
from tests.titan_protocol.validation_engine._fixtures import make_config, make_executed_trade


class TestConfidenceCalibration(unittest.TestCase):
    def test_well_calibrated_when_higher_tier_performs_at_least_as_well(self):
        config = make_config(research_config=ResearchEngineConfig(bucket_statistics_min_sample_size=1), min_sample_size_for_calibration_tier=5)
        low_tier, high_tier = DEFAULT_CONFIDENCE_SCHEDULE[0].label, DEFAULT_CONFIDENCE_SCHEDULE[-1].label
        low = [make_executed_trade(index=i, risk_confidence_tier=low_tier, won=True, r_multiple=1.0) for i in range(10)]
        high = [make_executed_trade(index=i + 20, risk_confidence_tier=high_tier, won=True, r_multiple=2.0) for i in range(10)]
        result = run_confidence_calibration(low + high, config)
        self.assertTrue(result.well_calibrated)

    def test_miscalibration_detected_when_higher_tier_underperforms(self):
        config = make_config(
            research_config=ResearchEngineConfig(bucket_statistics_min_sample_size=1),
            min_sample_size_for_calibration_tier=5, degradation_expectancy_delta_threshold=0.3,
        )
        low_tier, high_tier = DEFAULT_CONFIDENCE_SCHEDULE[0].label, DEFAULT_CONFIDENCE_SCHEDULE[-1].label
        low = [make_executed_trade(index=i, risk_confidence_tier=low_tier, won=True, r_multiple=3.0) for i in range(10)]
        high = [make_executed_trade(index=i + 20, risk_confidence_tier=high_tier, won=False, r_multiple=-2.0) for i in range(10)]
        result = run_confidence_calibration(low + high, config)
        self.assertFalse(result.well_calibrated)
        self.assertTrue(result.notes)

    def test_excludes_trades_with_no_confidence_tier(self):
        config = make_config()
        trades = [make_executed_trade(index=i, risk_confidence_tier=None) for i in range(10)]
        result = run_confidence_calibration(trades, config)
        self.assertEqual(result.tier_statistics, ())
        self.assertTrue(result.well_calibrated)


if __name__ == "__main__":
    unittest.main()
