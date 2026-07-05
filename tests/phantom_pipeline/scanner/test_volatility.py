"""Volatility facts (ADR-002 §5, §9's warm-up failure mode)."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from phantom_pipeline.data_pipeline.models import DataQuality, NormalizedBar, SCHEMA_VERSION
from phantom_pipeline.scanner.config import ScannerConfig
from phantom_pipeline.scanner.models import VolatilityLabel
from phantom_pipeline.scanner.volatility import atr, compute_volatility

T0 = datetime(2026, 7, 4, 12, 0, 0, tzinfo=timezone.utc)


def _bar(i: int, high: float, low: float, close: float) -> NormalizedBar:
    return NormalizedBar(
        schema_version=SCHEMA_VERSION,
        trace_id=f"b{i}",
        symbol="EURUSD",
        timeframe="M1",
        timestamp=T0 + timedelta(minutes=i),
        open=close,
        high=high,
        low=low,
        close=close,
        volume=1.0,
        quality=DataQuality.NOMINAL,
        is_repaired=False,
        source="test",
    )


def _constant_range_bars(count: int, rng: float) -> list:
    bars = []
    price = 1.1000
    for i in range(count):
        bars.append(_bar(i, price + rng / 2, price - rng / 2, price))
    return bars


class TestAtr(unittest.TestCase):
    def test_insufficient_bars_returns_none(self):
        bars = _constant_range_bars(5, 0.001)
        self.assertIsNone(atr(bars, period=14))

    def test_constant_range_atr_equals_the_range(self):
        bars = _constant_range_bars(20, 0.0010)
        result = atr(bars, period=14)
        self.assertAlmostEqual(result, 0.0010, places=6)


class TestVolatilityClassification(unittest.TestCase):
    def setUp(self):
        self.config = ScannerConfig()

    def test_insufficient_bars_yields_unknown(self):
        bars = _constant_range_bars(10, 0.001)
        result = compute_volatility(bars, self.config)
        self.assertEqual(result.state.label, VolatilityLabel.UNKNOWN)
        self.assertIsNone(result.state.ratio)

    def test_uniform_history_yields_normal(self):
        bars = _constant_range_bars(self.config.atr_baseline_period + 1, 0.0010)
        result = compute_volatility(bars, self.config)
        self.assertEqual(result.state.label, VolatilityLabel.NORMAL)
        self.assertAlmostEqual(result.state.ratio, 1.0, places=6)

    def test_recent_expansion_yields_elevated_or_extreme(self):
        baseline = _constant_range_bars(self.config.atr_baseline_period, 0.0005)
        recent = _constant_range_bars(self.config.atr_period + 1, 0.0025)
        # Re-timestamp the recent block to continue after the baseline block.
        offset = len(baseline)
        recent = [
            _bar(offset + i, b.high, b.low, b.close) for i, b in enumerate(recent)
        ]
        bars = baseline + recent
        result = compute_volatility(bars, self.config)
        self.assertIn(result.state.label, (VolatilityLabel.ELEVATED, VolatilityLabel.EXTREME))
        self.assertIsNotNone(result.atr_current)


if __name__ == "__main__":
    unittest.main()
