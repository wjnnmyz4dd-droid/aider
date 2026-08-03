"""Data-Pipeline-only metrics (ADR-013 §15, Phase 1 Completion item 3) —
export-only, additive, zero effect on returned outputs."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from phantom_pipeline.data_pipeline.config import PipelineConfig
from phantom_pipeline.data_pipeline.metrics import DataPipelineMetrics
from phantom_pipeline.data_pipeline.models import DataQuality, NormalizedBar, SCHEMA_VERSION
from phantom_pipeline.data_pipeline.pipeline import DataPipeline

T0 = datetime(2026, 7, 4, 12, 0, 0, tzinfo=timezone.utc)


def _bar(minute_offset: int, symbol: str = "GBPUSD") -> NormalizedBar:
    return NormalizedBar(
        SCHEMA_VERSION, f"t{minute_offset}", symbol, "M1", T0 + timedelta(minutes=minute_offset),
        1.30, 1.3005, 1.2995, 1.3002, 10.0, DataQuality.NOMINAL, False, "bulk",
    )


class TestDataPipelineMetricsUnit(unittest.TestCase):
    def test_gap_count_and_gap_repair_count_accumulate(self):
        metrics = DataPipelineMetrics()
        metrics.record_gap_detected(3)
        metrics.record_gap_detected(1)
        metrics.record_gap_repaired()
        self.assertEqual(metrics.gap_count, 4)
        self.assertEqual(metrics.gap_repair_count, 1)

    def test_duplicate_dropped_out_of_order_counts(self):
        metrics = DataPipelineMetrics()
        metrics.record_duplicate_tick()
        metrics.record_duplicate_tick()
        metrics.record_dropped_tick()
        metrics.record_out_of_order_tick()
        self.assertEqual(metrics.duplicate_tick_count, 2)
        self.assertEqual(metrics.dropped_tick_count, 1)
        self.assertEqual(metrics.out_of_order_tick_count, 1)

    def test_cache_hit_ratio(self):
        metrics = DataPipelineMetrics()
        metrics.record_cache_access(hit=True)
        metrics.record_cache_access(hit=True)
        metrics.record_cache_access(hit=False)
        self.assertEqual(metrics.cache_hit_ratio, 2 / 3)

    def test_cache_hit_ratio_zero_when_no_accesses(self):
        metrics = DataPipelineMetrics()
        self.assertEqual(metrics.cache_hit_ratio, 0.0)

    def test_replay_readiness_ratio(self):
        metrics = DataPipelineMetrics()
        metrics.record_replay_readiness(True)
        metrics.record_replay_readiness(False)
        metrics.record_replay_readiness(True)
        self.assertAlmostEqual(metrics.replay_readiness_ratio, 2 / 3)

    def test_average_latency_seconds(self):
        metrics = DataPipelineMetrics()
        metrics.record_latency(1.0)
        metrics.record_latency(3.0)
        self.assertEqual(metrics.average_latency_seconds, 2.0)

    def test_average_latency_zero_when_never_recorded(self):
        metrics = DataPipelineMetrics()
        self.assertEqual(metrics.average_latency_seconds, 0.0)


class TestDataPipelineMetricsIntegration(unittest.TestCase):
    def test_recording_metrics_never_alters_returned_outputs(self):
        without_metrics = DataPipeline(PipelineConfig())
        with_metrics = DataPipeline(PipelineConfig(), metrics=DataPipelineMetrics())
        bars = [_bar(i) for i in range(5)]
        without_metrics.load_historical_bars("GBPUSD", "M1", bars)
        with_metrics.load_historical_bars("GBPUSD", "M1", bars)
        self.assertEqual(
            without_metrics.get_historical_series("GBPUSD", "M1"),
            with_metrics.get_historical_series("GBPUSD", "M1"),
        )

    def test_duplicate_tick_metric_recorded_during_ingestion(self):
        metrics = DataPipelineMetrics()
        pipeline = DataPipeline(PipelineConfig(), metrics=metrics)
        pipeline.process_raw_tick("EURUSD", T0, 1.1000, 1.1002, None, 1.0, "test")
        pipeline.process_raw_tick("EURUSD", T0, 1.1000, 1.1002, None, 1.0, "test")
        self.assertEqual(metrics.duplicate_tick_count, 1)

    def test_gap_repair_metric_recorded_via_get_historical_series_repaired(self):
        metrics = DataPipelineMetrics()
        pipeline = DataPipeline(PipelineConfig(), metrics=metrics)
        pipeline.load_historical_bars("GBPUSD", "M1", [_bar(0), _bar(2)])
        pipeline.get_historical_series_repaired("GBPUSD", "M1")
        self.assertEqual(metrics.gap_repair_count, 1)

    def test_replay_readiness_metric_recorded_via_capture_replay(self):
        metrics = DataPipelineMetrics()
        pipeline = DataPipeline(PipelineConfig(), metrics=metrics)
        pipeline.process_raw_tick("EURUSD", T0, 1.1000, 1.1002, None, 1.0, "test")
        pipeline.flush("EURUSD")
        pipeline.capture_replay("EURUSD")
        self.assertEqual(metrics.replay_readiness_ratio, 1.0)

    def test_cache_access_metric_recorded_via_get_historical_series(self):
        metrics = DataPipelineMetrics()
        pipeline = DataPipeline(PipelineConfig(), metrics=metrics)
        pipeline.get_historical_series("NEVERSEEN", "M1")  # miss
        pipeline.load_historical_bars("GBPUSD", "M1", [_bar(0)])
        pipeline.get_historical_series("GBPUSD", "M1")  # hit
        self.assertEqual(metrics.cache_hit_ratio, 0.5)

    def test_metrics_snapshots_reflect_live_counters_not_frozen_copies(self):
        # Unlike other stages' dict-returning snapshot properties, these
        # are plain int/float properties — verify they update live.
        metrics = DataPipelineMetrics()
        metrics.record_duplicate_tick()
        self.assertEqual(metrics.duplicate_tick_count, 1)
        metrics.record_duplicate_tick()
        self.assertEqual(metrics.duplicate_tick_count, 2)


if __name__ == "__main__":
    unittest.main()
