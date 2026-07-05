"""Historical consistency (VALIDATION_MATRIX.md §1 / ADR-013 §16)."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from phantom_pipeline.data_pipeline.config import PipelineConfig
from phantom_pipeline.data_pipeline.historical import HistoricalCache
from phantom_pipeline.data_pipeline.models import DataQuality, NormalizedBar, SCHEMA_VERSION

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


class TestHistoricalCache(unittest.TestCase):
    def test_repeated_loads_are_identical(self):
        cache = HistoricalCache(PipelineConfig())
        for i in range(10):
            cache.add_bar(_bar(i))
        first = cache.get_series("EURUSD", "M1")
        second = cache.get_series("EURUSD", "M1")
        self.assertEqual(first, second)
        self.assertEqual(len(first.bars), 10)

    def test_bounded_by_max_bars(self):
        config = PipelineConfig(historical_cache_max_bars_per_series=5)
        cache = HistoricalCache(config)
        for i in range(10):
            cache.add_bar(_bar(i))
        series = cache.get_series("EURUSD", "M1")
        self.assertEqual(len(series.bars), 5)
        self.assertEqual(series.bars[0].timestamp, T0 + timedelta(minutes=5))

    def test_ttl_eviction(self):
        config = PipelineConfig(historical_cache_ttl_seconds=120.0)
        cache = HistoricalCache(config)
        for i in range(5):
            cache.add_bar(_bar(i))
        now = T0 + timedelta(minutes=4)
        cache.evict_expired(now)
        series = cache.get_series("EURUSD", "M1")
        # Bars older than 120s (2 minutes) before `now` are evicted.
        self.assertTrue(all(now - b.timestamp <= timedelta(seconds=120) for b in series.bars))

    def test_empty_series_for_unknown_symbol(self):
        cache = HistoricalCache(PipelineConfig())
        series = cache.get_series("GBPUSD", "M1")
        self.assertEqual(series.bars, ())
        self.assertTrue(series.trace_id)


if __name__ == "__main__":
    unittest.main()
