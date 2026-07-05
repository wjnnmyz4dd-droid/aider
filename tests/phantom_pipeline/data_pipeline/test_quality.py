"""DataQualityReport correctness (VALIDATION_MATRIX.md §1 / ADR-013 §16)."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from phantom_pipeline.data_pipeline.config import PipelineConfig
from phantom_pipeline.data_pipeline.models import DataQuality, NormalizedBar, SCHEMA_VERSION
from phantom_pipeline.data_pipeline.quality import compute_quality_report

T0 = datetime(2026, 7, 4, 12, 0, 0, tzinfo=timezone.utc)


def _bar(minute_offset: int) -> NormalizedBar:
    return NormalizedBar(
        schema_version=SCHEMA_VERSION,
        trace_id=f"trace-{minute_offset}",
        symbol="EURUSD",
        timeframe="M1",
        timestamp=T0 + timedelta(minutes=minute_offset),
        open=1.1000,
        high=1.1005,
        low=1.0995,
        close=1.1002,
        volume=10.0,
        quality=DataQuality.NOMINAL,
        is_repaired=False,
        source="test",
    )


class TestDataQualityReport(unittest.TestCase):
    def setUp(self):
        self.config = PipelineConfig()

    def test_complete_continuous_window_is_nominal(self):
        bars = [_bar(i) for i in range(5)]
        report = compute_quality_report(
            symbol="EURUSD",
            timeframe="M1",
            bars=bars,
            window_start=T0,
            window_end=T0 + timedelta(minutes=5),
            now=T0 + timedelta(minutes=4),
            config=self.config,
            duplicate_count=0,
            out_of_order_count=0,
        )
        self.assertTrue(report.continuity)
        self.assertEqual(report.gap_count, 0)
        self.assertEqual(report.confidence, "NOMINAL")
        self.assertGreaterEqual(report.completeness, 0.9)

    def test_gap_reduces_completeness_and_continuity(self):
        bars = [_bar(0), _bar(4)]  # 3 missing bars in a 5-minute window
        report = compute_quality_report(
            symbol="EURUSD",
            timeframe="M1",
            bars=bars,
            window_start=T0,
            window_end=T0 + timedelta(minutes=5),
            now=T0 + timedelta(minutes=4),
            config=self.config,
            duplicate_count=0,
            out_of_order_count=0,
        )
        self.assertFalse(report.continuity)
        self.assertEqual(report.gap_count, 3)
        self.assertEqual(report.confidence, "DEGRADED")
        self.assertLess(report.completeness, 1.0)

    def test_empty_series_is_insufficient(self):
        report = compute_quality_report(
            symbol="EURUSD",
            timeframe="M1",
            bars=[],
            window_start=T0,
            window_end=T0 + timedelta(minutes=5),
            now=T0 + timedelta(minutes=5),
            config=self.config,
            duplicate_count=0,
            out_of_order_count=0,
        )
        self.assertEqual(report.confidence, "INSUFFICIENT")
        self.assertEqual(report.completeness, 0.0)

    def test_stale_data_is_degraded(self):
        bars = [_bar(0)]
        report = compute_quality_report(
            symbol="EURUSD",
            timeframe="M1",
            bars=bars,
            window_start=T0,
            window_end=T0 + timedelta(minutes=1),
            now=T0 + timedelta(hours=1),
            config=self.config,
            duplicate_count=0,
            out_of_order_count=0,
        )
        self.assertEqual(report.confidence, "DEGRADED")
        self.assertGreater(report.freshness_seconds, self.config.freshness_stale_after_seconds)

    def test_latency_is_honestly_unmeasured_in_phase_1(self):
        # No live broker feed adapter exists yet (ADR-015 §6), so there is
        # no genuine ingestion-receipt time to measure latency against.
        # None is the correct, honest value here, not a fabricated number.
        report = compute_quality_report(
            symbol="EURUSD",
            timeframe="M1",
            bars=[_bar(0)],
            window_start=T0,
            window_end=T0 + timedelta(minutes=1),
            now=T0,
            config=self.config,
            duplicate_count=0,
            out_of_order_count=0,
        )
        self.assertIsNone(report.latency_seconds)

    def test_duplicate_and_out_of_order_counts_are_passed_through(self):
        report = compute_quality_report(
            symbol="EURUSD",
            timeframe="M1",
            bars=[_bar(0)],
            window_start=T0,
            window_end=T0 + timedelta(minutes=1),
            now=T0,
            config=self.config,
            duplicate_count=3,
            out_of_order_count=2,
        )
        self.assertEqual(report.duplicate_count, 3)
        self.assertEqual(report.out_of_order_count, 2)


if __name__ == "__main__":
    unittest.main()
