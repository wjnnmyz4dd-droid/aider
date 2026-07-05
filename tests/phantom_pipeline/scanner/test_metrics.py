"""Scanner-only metrics surface (ADR-002 §12) — export-only, additive,
zero effect on the returned observation."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from phantom_pipeline.data_pipeline.models import DataQuality, MarketSnapshot, NormalizedBar, SCHEMA_VERSION
from phantom_pipeline.scanner.config import ScannerConfig
from phantom_pipeline.scanner.metrics import ScannerMetrics
from phantom_pipeline.scanner.models import DataQualityFlag
from phantom_pipeline.scanner.scanner import Scanner

T0 = datetime(2026, 7, 4, 12, 0, 0, tzinfo=timezone.utc)


def _bar(i: int) -> NormalizedBar:
    close = 1.1000 + (i % 24) * 0.0003
    return NormalizedBar(
        schema_version=SCHEMA_VERSION,
        trace_id=f"b{i}",
        symbol="EURUSD",
        timeframe="M1",
        timestamp=T0 + timedelta(minutes=i),
        open=close,
        high=close + 0.0007,
        low=close - 0.0007,
        close=close,
        volume=1.0,
        quality=DataQuality.NOMINAL,
        is_repaired=False,
        source="test",
    )


class TestScannerMetrics(unittest.TestCase):
    def test_observations_total_counted_by_quality_flag(self):
        metrics = ScannerMetrics()
        bars = [_bar(i) for i in range(3)]  # WARM_UP
        Scanner(ScannerConfig(), metrics=metrics).scan(
            "EURUSD", {"M1": bars}, None, bars[-1].timestamp, "M1"
        )
        self.assertEqual(metrics.observations_total[DataQualityFlag.WARM_UP.value], 1)

    def test_structural_signals_counted_by_kind_and_direction(self):
        metrics = ScannerMetrics()
        bars = [_bar(i) for i in range(120)]
        snapshot = MarketSnapshot(
            schema_version=SCHEMA_VERSION,
            trace_id="s1",
            symbol="EURUSD",
            timestamp=bars[-1].timestamp,
            price=1.1,
            spread=0.0002,
            market_status="OPEN",
        )
        observation = Scanner(ScannerConfig(), metrics=metrics).scan(
            "EURUSD", {"M1": bars}, snapshot, bars[-1].timestamp, "M1"
        )
        totals = metrics.structural_signals_total
        for signal in observation.structure:
            self.assertGreaterEqual(totals[(signal.kind.value, signal.direction.value)], 1)

    def test_scan_latency_recorded_per_symbol(self):
        metrics = ScannerMetrics()
        bars = [_bar(i) for i in range(3)]
        Scanner(ScannerConfig(), metrics=metrics).scan(
            "EURUSD", {"M1": bars}, None, bars[-1].timestamp, "M1"
        )
        self.assertIn("EURUSD", metrics.scan_latency_seconds)
        self.assertGreaterEqual(metrics.scan_latency_seconds["EURUSD"], 0.0)

    def test_recording_metrics_never_alters_the_returned_observation(self):
        bars = [_bar(i) for i in range(120)]
        snapshot = MarketSnapshot(
            schema_version=SCHEMA_VERSION,
            trace_id="s1",
            symbol="EURUSD",
            timestamp=bars[-1].timestamp,
            price=1.1,
            spread=0.0002,
            market_status="OPEN",
        )
        without_metrics = Scanner(ScannerConfig()).scan(
            "EURUSD", {"M1": bars}, snapshot, bars[-1].timestamp, "M1"
        )
        with_metrics = Scanner(ScannerConfig(), metrics=ScannerMetrics()).scan(
            "EURUSD", {"M1": bars}, snapshot, bars[-1].timestamp, "M1"
        )
        self.assertEqual(without_metrics, with_metrics)

    def test_snapshots_are_copies_not_live_views(self):
        metrics = ScannerMetrics()
        bars = [_bar(i) for i in range(3)]
        Scanner(ScannerConfig(), metrics=metrics).scan(
            "EURUSD", {"M1": bars}, None, bars[-1].timestamp, "M1"
        )
        snapshot = metrics.observations_total
        snapshot["INJECTED"] = 999
        self.assertNotIn("INJECTED", metrics.observations_total)


if __name__ == "__main__":
    unittest.main()
