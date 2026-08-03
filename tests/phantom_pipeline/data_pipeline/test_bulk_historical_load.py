"""Bulk historical loading / warm-cache bootstrap (ADR-013 §4, §11,
Phase 1 Completion item 2)."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from phantom_pipeline.data_pipeline.config import PipelineConfig
from phantom_pipeline.data_pipeline.historical import HistoricalCache
from phantom_pipeline.data_pipeline.models import (
    SCHEMA_VERSION,
    DataQuality,
    HistoricalSeries,
    NormalizedBar,
)
from phantom_pipeline.data_pipeline.pipeline import DataPipeline

T0 = datetime(2026, 7, 4, 12, 0, 0, tzinfo=timezone.utc)


def _bar(minute_offset: int, symbol: str = "GBPUSD", timeframe: str = "M1") -> NormalizedBar:
    return NormalizedBar(
        schema_version=SCHEMA_VERSION,
        trace_id=f"bulk-{symbol}-{minute_offset}",
        symbol=symbol,
        timeframe=timeframe,
        timestamp=T0 + timedelta(minutes=minute_offset),
        open=1.3000,
        high=1.3005,
        low=1.2995,
        close=1.3002,
        volume=10.0,
        quality=DataQuality.NOMINAL,
        is_repaired=False,
        source="bulk",
    )


class TestHistoricalCacheLoadBulk(unittest.TestCase):
    def test_load_bulk_populates_series(self):
        cache = HistoricalCache(PipelineConfig())
        bars = [_bar(i) for i in range(5)]
        cache.load_bulk("GBPUSD", "M1", bars)
        series = cache.get_series("GBPUSD", "M1")
        self.assertEqual(len(series.bars), 5)

    def test_load_bulk_is_deterministic(self):
        cache = HistoricalCache(PipelineConfig())
        bars = [_bar(i) for i in range(5)]
        cache.load_bulk("GBPUSD", "M1", bars)
        first = cache.get_series("GBPUSD", "M1")
        cache.load_bulk("GBPUSD", "M1", bars)
        second = cache.get_series("GBPUSD", "M1")
        self.assertEqual(first.bars, second.bars)

    def test_load_bulk_respects_max_bars_bound(self):
        config = PipelineConfig(historical_cache_max_bars_per_series=3)
        cache = HistoricalCache(config)
        bars = [_bar(i) for i in range(10)]
        cache.load_bulk("GBPUSD", "M1", bars)
        series = cache.get_series("GBPUSD", "M1")
        self.assertEqual(len(series.bars), 3)
        self.assertEqual(series.bars[0].timestamp, T0 + timedelta(minutes=7))

    def test_load_bulk_rejects_non_ascending_timestamps(self):
        cache = HistoricalCache(PipelineConfig())
        bars = [_bar(2), _bar(0)]
        with self.assertRaises(ValueError):
            cache.load_bulk("GBPUSD", "M1", bars)

    def test_load_bulk_rejects_duplicate_timestamps(self):
        cache = HistoricalCache(PipelineConfig())
        bars = [_bar(0), _bar(0)]
        with self.assertRaises(ValueError):
            cache.load_bulk("GBPUSD", "M1", bars)

    def test_load_bulk_rejects_impossible_ohlc_ordering(self):
        cache = HistoricalCache(PipelineConfig())
        bad_bar = NormalizedBar(
            SCHEMA_VERSION, "bad", "GBPUSD", "M1", T0, 1.30, 1.29, 1.31, 1.30, 10.0,
            DataQuality.NOMINAL, False, "bulk",
        )  # low (1.31) > high (1.29)
        with self.assertRaises(ValueError):
            cache.load_bulk("GBPUSD", "M1", [bad_bar])

    def test_load_bulk_rejects_non_positive_price(self):
        cache = HistoricalCache(PipelineConfig())
        bad_bar = NormalizedBar(
            SCHEMA_VERSION, "bad", "GBPUSD", "M1", T0, 0.0, 1.30, 1.29, 1.30, 10.0,
            DataQuality.NOMINAL, False, "bulk",
        )
        with self.assertRaises(ValueError):
            cache.load_bulk("GBPUSD", "M1", [bad_bar])

    def test_invalidate_clears_series_and_returns_count(self):
        cache = HistoricalCache(PipelineConfig())
        cache.load_bulk("GBPUSD", "M1", [_bar(i) for i in range(4)])
        cleared = cache.invalidate("GBPUSD", "M1")
        self.assertEqual(cleared, 4)
        self.assertEqual(cache.get_series("GBPUSD", "M1").bars, ())

    def test_invalidate_unknown_key_is_a_no_op_returning_zero(self):
        cache = HistoricalCache(PipelineConfig())
        self.assertEqual(cache.invalidate("NEVERSEEN", "M1"), 0)

    def test_cache_hit_and_miss_counters(self):
        cache = HistoricalCache(PipelineConfig())
        cache.get_series("NEVERSEEN", "M1")  # miss
        cache.load_bulk("GBPUSD", "M1", [_bar(0)])
        cache.get_series("GBPUSD", "M1")  # hit
        self.assertEqual(cache.miss_count, 1)
        self.assertEqual(cache.hit_count, 1)


class TestDataPipelineWarmStart(unittest.TestCase):
    def test_load_historical_bars_available_immediately(self):
        pipeline = DataPipeline(PipelineConfig())
        bars = [_bar(i) for i in range(5)]
        pipeline.load_historical_bars("GBPUSD", "M1", bars)
        series = pipeline.get_historical_series("GBPUSD", "M1")
        self.assertEqual(len(series.bars), 5)

    def test_warm_start_bootstraps_multiple_symbols_at_once(self):
        pipeline = DataPipeline(PipelineConfig())
        gbp = HistoricalSeries(SCHEMA_VERSION, "t1", "GBPUSD", "M1", tuple(_bar(i, "GBPUSD") for i in range(3)))
        aud = HistoricalSeries(SCHEMA_VERSION, "t2", "AUDUSD", "M1", tuple(_bar(i, "AUDUSD") for i in range(4)))
        pipeline.warm_start([gbp, aud])
        self.assertEqual(len(pipeline.get_historical_series("GBPUSD", "M1").bars), 3)
        self.assertEqual(len(pipeline.get_historical_series("AUDUSD", "M1").bars), 4)

    def test_bulk_loaded_history_is_never_captured_into_replay(self):
        """Preserves replay determinism: warm-started history is not a
        live event and must not appear in a subsequent replay capture."""
        pipeline = DataPipeline(PipelineConfig())
        pipeline.load_historical_bars("GBPUSD", "M1", [_bar(i) for i in range(5)])
        replay_series = pipeline.capture_replay("GBPUSD")
        self.assertEqual(replay_series.ticks, ())
        self.assertEqual(replay_series.bars, ())

    def test_cold_start_symbol_never_warm_started_is_simply_empty(self):
        pipeline = DataPipeline(PipelineConfig())
        series = pipeline.get_historical_series("NEVERSEEN", "M1")
        self.assertEqual(series.bars, ())

    def test_invalidate_cache_clears_and_returns_count(self):
        pipeline = DataPipeline(PipelineConfig())
        pipeline.load_historical_bars("GBPUSD", "M1", [_bar(i) for i in range(5)])
        cleared = pipeline.invalidate_cache("GBPUSD", "M1", "vendor data revision", T0)
        self.assertEqual(cleared, 5)
        self.assertEqual(pipeline.get_historical_series("GBPUSD", "M1").bars, ())

    def test_repeated_historical_loads_of_same_range_are_identical(self):
        # ADR-013 §16's "historical consistency test," now backed by a
        # genuine bulk-load path rather than only in-memory cache reads.
        pipeline1 = DataPipeline(PipelineConfig())
        pipeline2 = DataPipeline(PipelineConfig())
        bars = [_bar(i) for i in range(10)]
        pipeline1.load_historical_bars("GBPUSD", "M1", bars)
        pipeline2.load_historical_bars("GBPUSD", "M1", bars)
        self.assertEqual(
            pipeline1.get_historical_series("GBPUSD", "M1").bars,
            pipeline2.get_historical_series("GBPUSD", "M1").bars,
        )


if __name__ == "__main__":
    unittest.main()
