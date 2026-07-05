"""Swing-pivot detection and major/minor classification (ADR-002 §5, §13)."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from phantom_pipeline.data_pipeline.models import DataQuality, NormalizedBar, SCHEMA_VERSION
from phantom_pipeline.scanner.config import ScannerConfig
from phantom_pipeline.scanner.models import SwingKind
from phantom_pipeline.scanner.swing import swing_points

T0 = datetime(2026, 7, 4, 12, 0, 0, tzinfo=timezone.utc)


def _bar(i: int, high: float, low: float) -> NormalizedBar:
    close = (high + low) / 2
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


class TestSwingDetection(unittest.TestCase):
    def setUp(self):
        self.config = ScannerConfig(swing_lookback=2)

    def test_detects_swing_high(self):
        highs = [1.100, 1.101, 1.105, 1.101, 1.100]
        lows = [1.099, 1.0995, 1.100, 1.0995, 1.099]
        bars = [_bar(i, highs[i], lows[i]) for i in range(5)]

        swings = swing_points(bars, self.config, atr_value=None)

        self.assertEqual(len(swings), 1)
        self.assertEqual(swings[0].index, 2)
        self.assertEqual(swings[0].kind, SwingKind.HIGH)
        self.assertEqual(swings[0].price, 1.105)

    def test_detects_swing_low(self):
        highs = [1.101, 1.1005, 1.100, 1.1005, 1.101]
        lows = [1.0995, 1.099, 1.095, 1.099, 1.0995]
        bars = [_bar(i, highs[i], lows[i]) for i in range(5)]

        swings = swing_points(bars, self.config, atr_value=None)

        self.assertEqual(len(swings), 1)
        self.assertEqual(swings[0].kind, SwingKind.LOW)
        self.assertEqual(swings[0].price, 1.095)

    def test_no_swing_when_no_bar_edges_available(self):
        bars = [_bar(0, 1.100, 1.099), _bar(1, 1.101, 1.0995)]
        self.assertEqual(swing_points(bars, self.config, atr_value=None), ())

    def test_no_swing_in_flat_series(self):
        bars = [_bar(i, 1.100, 1.099) for i in range(6)]
        self.assertEqual(swing_points(bars, self.config, atr_value=None), ())

    def _two_swing_bars(self):
        # A clean swing high at index 2 (1.110), then a clean swing low at
        # index 6 (1.080) — a ~0.030 leg between them.
        highs = [1.100, 1.102, 1.110, 1.102, 1.095, 1.088, 1.083, 1.088, 1.095]
        lows = [1.099, 1.100, 1.105, 1.095, 1.088, 1.083, 1.080, 1.083, 1.088]
        return [_bar(i, highs[i], lows[i]) for i in range(len(highs))]

    def test_major_minor_classification_uses_atr_multiple(self):
        bars = self._two_swing_bars()

        # ~0.030 swing range against a small ATR clears the
        # major_swing_atr_multiple threshold (1.5 * 0.005 = 0.0075).
        swings = swing_points(bars, self.config, atr_value=0.005)
        majors = [s for s in swings if s.is_major]
        self.assertTrue(majors)

    def test_no_atr_reading_yields_no_major_swings(self):
        bars = self._two_swing_bars()

        swings = swing_points(bars, self.config, atr_value=None)
        self.assertFalse(any(s.is_major for s in swings))

    def test_never_mutates_input_bars(self):
        bars = [_bar(i, 1.100 + i * 0.001, 1.099) for i in range(6)]
        before = list(bars)
        swing_points(bars, self.config, atr_value=None)
        self.assertEqual(bars, before)


if __name__ == "__main__":
    unittest.main()
