"""Explicit cache invalidation events (ADR-013 §11, Phase 1 Completion
item 4) — structured logging only, complete audit trail, never a silent
clear."""

from __future__ import annotations

import logging
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from phantom_pipeline.data_pipeline.config import PipelineConfig
from phantom_pipeline.data_pipeline.logging_sink import log_cache_invalidation
from phantom_pipeline.data_pipeline.models import DataQuality, NormalizedBar, SCHEMA_VERSION
from phantom_pipeline.data_pipeline.pipeline import DataPipeline

T0 = datetime(2026, 7, 4, 12, 0, 0, tzinfo=timezone.utc)


def _bar(minute_offset: int) -> NormalizedBar:
    return NormalizedBar(
        SCHEMA_VERSION, f"t{minute_offset}", "GBPUSD", "M1", T0 + timedelta(minutes=minute_offset),
        1.30, 1.3005, 1.2995, 1.3002, 10.0, DataQuality.NOMINAL, False, "bulk",
    )


class TestCacheInvalidationLogging(unittest.TestCase):
    def test_log_cache_invalidation_does_not_raise(self):
        log_cache_invalidation("GBPUSD", "M1", "vendor data revision", 5, T0)

    def test_logging_failure_is_swallowed_not_propagated(self):
        with patch("phantom_pipeline.data_pipeline.logging_sink.logger.log", side_effect=RuntimeError("boom")):
            log_cache_invalidation("GBPUSD", "M1", "vendor data revision", 5, T0)  # must not raise

    def test_invalidation_event_is_logged_with_full_audit_fields(self):
        pipeline = DataPipeline(PipelineConfig())
        pipeline.load_historical_bars("GBPUSD", "M1", [_bar(i) for i in range(3)])
        with self.assertLogs("phantom_pipeline.data_pipeline", level="WARNING") as captured:
            pipeline.invalidate_cache("GBPUSD", "M1", "configuration change to timeframe set", T0)
        self.assertTrue(any("cache_invalidation" in record.message for record in captured.records))
        record = captured.records[0]
        self.assertEqual(record.symbol, "GBPUSD")
        self.assertEqual(record.timeframe, "M1")
        self.assertEqual(record.reason, "configuration change to timeframe set")
        self.assertEqual(record.bars_cleared, 3)
        self.assertTrue(record.timestamp)

    def test_invalidation_of_empty_key_still_logs_zero_bars_cleared(self):
        pipeline = DataPipeline(PipelineConfig())
        with self.assertLogs("phantom_pipeline.data_pipeline", level="WARNING") as captured:
            cleared = pipeline.invalidate_cache("NEVERSEEN", "M1", "detected vendor data revision", T0)
        self.assertEqual(cleared, 0)
        self.assertEqual(captured.records[0].bars_cleared, 0)

    def test_invalidate_cache_actually_clears_the_series(self):
        pipeline = DataPipeline(PipelineConfig())
        pipeline.load_historical_bars("GBPUSD", "M1", [_bar(i) for i in range(3)])
        pipeline.invalidate_cache("GBPUSD", "M1", "vendor data revision", T0)
        self.assertEqual(pipeline.get_historical_series("GBPUSD", "M1").bars, ())


if __name__ == "__main__":
    unittest.main()
