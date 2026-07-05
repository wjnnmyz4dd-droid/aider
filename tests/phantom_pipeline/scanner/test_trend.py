"""Per-timeframe trend facts (ADR-002 §5, §9's warm-up failure mode)."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from phantom_pipeline.data_pipeline.models import DataQuality, NormalizedBar, SCHEMA_VERSION
from phantom_pipeline.scanner.config import ScannerConfig
from phantom_pipeline.scanner.models import Direction
from phantom_pipeline.scanner.trend import compute_trend

T0 = datetime(2026, 7, 4, 12, 0, 0, tzinfo=timezone.utc)


def _bars(closes):
    return [
        NormalizedBar(
            schema_version=SCHEMA_VERSION,
            trace_id=f"b{i}",
            symbol="EURUSD",
            timeframe="M1",
            timestamp=T0 + timedelta(minutes=i),
            open=c,
            high=c + 0.0005,
            low=c - 0.0005,
            close=c,
            volume=1.0,
            quality=DataQuality.NOMINAL,
            is_repaired=False,
            source="test",
        )
        for i, c in enumerate(closes)
    ]


class TestTrend(unittest.TestCase):
    def setUp(self):
        self.config = ScannerConfig()

    def test_insufficient_bars_yields_unknown_direction(self):
        bars = _bars([1.1000] * 10)
        result = compute_trend(bars, self.config)
        self.assertEqual(result.reading.direction, Direction.UNKNOWN)
        self.assertIsNone(result.reading.strength)
        self.assertEqual(result.strength_history, ())

    def test_steadily_rising_closes_yield_up_direction(self):
        closes = [1.1000 + i * 0.0005 for i in range(self.config.min_bars_for_trend + 5)]
        bars = _bars(closes)
        result = compute_trend(bars, self.config)
        self.assertEqual(result.reading.direction, Direction.UP)
        self.assertGreater(result.reading.strength, 0)

    def test_steadily_falling_closes_yield_down_direction(self):
        closes = [1.2000 - i * 0.0005 for i in range(self.config.min_bars_for_trend + 5)]
        bars = _bars(closes)
        result = compute_trend(bars, self.config)
        self.assertEqual(result.reading.direction, Direction.DOWN)
        self.assertLess(result.reading.strength, 0)

    def test_flat_closes_yield_neutral_direction(self):
        closes = [1.1000] * (self.config.min_bars_for_trend + 5)
        bars = _bars(closes)
        result = compute_trend(bars, self.config)
        self.assertEqual(result.reading.direction, Direction.NEUTRAL)

    def test_strength_history_grows_with_more_bars(self):
        closes = [1.1000 + i * 0.0005 for i in range(self.config.min_bars_for_trend + 5)]
        bars = _bars(closes)
        result = compute_trend(bars, self.config)
        self.assertGreater(len(result.strength_history), 0)
        self.assertEqual(result.strength_history[-1], result.reading.strength)


if __name__ == "__main__":
    unittest.main()
