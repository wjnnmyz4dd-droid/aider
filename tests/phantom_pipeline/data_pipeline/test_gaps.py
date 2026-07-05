"""Gap detection correctness (VALIDATION_MATRIX.md §1 / ADR-013 §16)."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from phantom_pipeline.data_pipeline.config import PipelineConfig
from phantom_pipeline.data_pipeline.gaps import detect_gaps
from phantom_pipeline.data_pipeline.models import DataQuality, NormalizedBar, SCHEMA_VERSION

T0 = datetime(2026, 7, 4, 12, 0, 0, tzinfo=timezone.utc)


def _bar(minute_offset: int, timeframe="M1") -> NormalizedBar:
    ts = T0 + timedelta(minutes=minute_offset)
    return NormalizedBar(
        schema_version=SCHEMA_VERSION,
        trace_id=f"trace-{minute_offset}",
        symbol="EURUSD",
        timeframe=timeframe,
        timestamp=ts,
        open=1.1000,
        high=1.1005,
        low=1.0995,
        close=1.1002,
        volume=10.0,
        quality=DataQuality.NOMINAL,
        is_repaired=False,
        source="test",
    )


class TestGapDetection(unittest.TestCase):
    def setUp(self):
        self.config = PipelineConfig()

    def test_no_gap_in_continuous_series(self):
        bars = [_bar(i) for i in range(5)]
        self.assertEqual(detect_gaps(bars, self.config), [])

    def test_single_missing_bar_detected(self):
        bars = [_bar(0), _bar(2)]  # bar at minute 1 missing
        gaps = detect_gaps(bars, self.config)
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].missing_bar_count, 1)

    def test_multiple_consecutive_missing_bars_detected(self):
        bars = [_bar(0), _bar(4)]  # minutes 1, 2, 3 missing
        gaps = detect_gaps(bars, self.config)
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].missing_bar_count, 3)

    def test_multiple_separate_gaps_detected(self):
        bars = [_bar(0), _bar(2), _bar(3), _bar(6)]
        gaps = detect_gaps(bars, self.config)
        self.assertEqual(len(gaps), 2)
        self.assertEqual(gaps[0].missing_bar_count, 1)
        self.assertEqual(gaps[1].missing_bar_count, 2)

    def test_single_bar_has_no_gap(self):
        self.assertEqual(detect_gaps([_bar(0)], self.config), [])

    def test_empty_series_has_no_gap(self):
        self.assertEqual(detect_gaps([], self.config), [])

    def test_unsorted_input_raises_rather_than_returning_wrong_results(self):
        bars = [_bar(2), _bar(0)]  # descending — not ascending
        with self.assertRaises(ValueError):
            detect_gaps(bars, self.config)

    def test_never_fabricates_a_replacement_bar(self):
        bars = [_bar(0), _bar(2)]
        gaps = detect_gaps(bars, self.config)
        self.assertEqual(len(bars), 2)  # detection never appends a bar
        self.assertTrue(gaps)


if __name__ == "__main__":
    unittest.main()
