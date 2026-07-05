"""Gap repair correctness (ADR-013 §7, Phase 1 Completion item 1)."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from phantom_pipeline.data_pipeline.config import PipelineConfig
from phantom_pipeline.data_pipeline.gaps import repair_gaps
from phantom_pipeline.data_pipeline.models import DataQuality, NormalizedBar, SCHEMA_VERSION

T0 = datetime(2026, 7, 4, 12, 0, 0, tzinfo=timezone.utc)


def _bar(minute_offset: int, close: float = 1.1002) -> NormalizedBar:
    return NormalizedBar(
        schema_version=SCHEMA_VERSION,
        trace_id=f"trace-{minute_offset}",
        symbol="EURUSD",
        timeframe="M1",
        timestamp=T0 + timedelta(minutes=minute_offset),
        open=1.1000,
        high=1.1005,
        low=1.0995,
        close=close,
        volume=10.0,
        quality=DataQuality.NOMINAL,
        is_repaired=False,
        source="test",
    )


class TestGapRepair(unittest.TestCase):
    def setUp(self):
        self.config = PipelineConfig()

    def test_single_missing_bar_is_repaired(self):
        bars = [_bar(0), _bar(2)]  # minute 1 missing
        repaired = repair_gaps(bars, self.config)
        self.assertEqual(len(repaired), 3)
        self.assertEqual(repaired[1].timestamp, T0 + timedelta(minutes=1))
        self.assertTrue(repaired[1].is_repaired)

    def test_repaired_bar_carries_is_repaired_flag_and_gap_quality(self):
        bars = [_bar(0), _bar(2)]
        repaired = repair_gaps(bars, self.config)
        self.assertTrue(repaired[1].is_repaired)
        self.assertEqual(repaired[1].quality, DataQuality.GAP)

    def test_repaired_bar_is_forward_filled_from_prior_close(self):
        bars = [_bar(0, close=1.1050), _bar(2, close=1.1090)]
        repaired = repair_gaps(bars, self.config)
        gap_bar = repaired[1]
        self.assertEqual(gap_bar.open, 1.1050)
        self.assertEqual(gap_bar.high, 1.1050)
        self.assertEqual(gap_bar.low, 1.1050)
        self.assertEqual(gap_bar.close, 1.1050)
        self.assertEqual(gap_bar.volume, 0.0)

    def test_consecutive_missing_bars_are_never_repaired(self):
        bars = [_bar(0), _bar(4)]  # minutes 1, 2, 3 missing
        repaired = repair_gaps(bars, self.config)
        self.assertEqual(len(repaired), 2)  # unchanged — never fabricated
        self.assertEqual(repaired, bars)

    def test_no_gap_returns_bars_unchanged(self):
        bars = [_bar(i) for i in range(5)]
        repaired = repair_gaps(bars, self.config)
        self.assertEqual(repaired, bars)

    def test_input_list_is_never_mutated(self):
        bars = [_bar(0), _bar(2)]
        original_length = len(bars)
        repair_gaps(bars, self.config)
        self.assertEqual(len(bars), original_length)

    def test_repair_never_occurs_below_two_bars_warm_up(self):
        # detect_gaps requires >= 2 bars; repair_gaps inherits that, so a
        # single bar (or none) is never "repaired" — there is nothing to
        # repair from yet (ADR-013 §7's warm-up exclusion).
        self.assertEqual(repair_gaps([_bar(0)], self.config), [_bar(0)])
        self.assertEqual(repair_gaps([], self.config), [])

    def test_repair_is_deterministic(self):
        bars = [_bar(0), _bar(2)]
        first = repair_gaps(bars, self.config)
        second = repair_gaps(bars, self.config)
        self.assertEqual(first, second)
        self.assertEqual(first[1].trace_id, second[1].trace_id)

    def test_repaired_trace_id_never_collides_with_an_observed_bar(self):
        bars = [_bar(0), _bar(2)]
        repaired = repair_gaps(bars, self.config)
        observed_trace_ids = {b.trace_id for b in bars}
        self.assertNotIn(repaired[1].trace_id, observed_trace_ids)

    def test_multiple_separate_single_bar_gaps_all_repaired(self):
        bars = [_bar(0), _bar(2), _bar(4)]  # minutes 1 and 3 both missing
        repaired = repair_gaps(bars, self.config)
        self.assertEqual(len(repaired), 5)
        self.assertTrue(repaired[1].is_repaired)
        self.assertTrue(repaired[3].is_repaired)

    def test_unsorted_input_raises(self):
        bars = [_bar(2), _bar(0)]
        with self.assertRaises(ValueError):
            repair_gaps(bars, self.config)


if __name__ == "__main__":
    unittest.main()
