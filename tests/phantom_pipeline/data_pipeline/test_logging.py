"""Structured logging emission (ADR-013 §14) — remediation for the
missing logging sink found during the ADR-013 Phase 1 audit."""

from __future__ import annotations

import logging
import unittest
from datetime import datetime, timezone

from phantom_pipeline.data_pipeline.config import PipelineConfig
from phantom_pipeline.data_pipeline.logging_sink import log_ingestion_event, logger
from phantom_pipeline.data_pipeline.models import (
    DataQuality,
    NormalizedBar,
    NormalizedTick,
    SCHEMA_VERSION,
)
from phantom_pipeline.data_pipeline.pipeline import DataPipeline

T0 = datetime(2026, 7, 4, 12, 0, 0, tzinfo=timezone.utc)


def _tick() -> NormalizedTick:
    return NormalizedTick(
        schema_version=SCHEMA_VERSION,
        trace_id="tick-trace",
        symbol="EURUSD",
        timestamp=T0,
        bid=1.1000,
        ask=1.1002,
        last=None,
        volume=1.0,
        source="test",
    )


def _bar() -> NormalizedBar:
    return NormalizedBar(
        schema_version=SCHEMA_VERSION,
        trace_id="bar-trace",
        symbol="EURUSD",
        timeframe="M1",
        timestamp=T0,
        open=1.1000,
        high=1.1005,
        low=1.0995,
        close=1.1002,
        volume=10.0,
        quality=DataQuality.NOMINAL,
        is_repaired=False,
        source="test",
    )


class _CapturingHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


class TestLogIngestionEvent(unittest.TestCase):
    def setUp(self):
        self.handler = _CapturingHandler()
        logger.addHandler(self.handler)
        logger.setLevel(logging.DEBUG)
        self.previous_propagate = logger.propagate
        logger.propagate = False

    def tearDown(self):
        logger.removeHandler(self.handler)
        logger.propagate = self.previous_propagate

    def test_tick_event_carries_all_required_fields(self):
        log_ingestion_event(_tick(), level=logging.INFO)
        self.assertEqual(len(self.handler.records), 1)
        record = self.handler.records[0]
        self.assertEqual(record.trace_id, "tick-trace")
        self.assertEqual(record.schema_version, SCHEMA_VERSION)
        self.assertEqual(record.symbol, "EURUSD")
        self.assertIsNone(record.timeframe)  # ticks have no timeframe
        self.assertEqual(record.timestamp, T0.isoformat())
        self.assertEqual(record.source, "test")
        self.assertIsNone(record.quality)  # ticks carry no quality flag

    def test_bar_event_carries_all_required_fields_including_timeframe_and_quality(self):
        log_ingestion_event(_bar(), level=logging.INFO)
        self.assertEqual(len(self.handler.records), 1)
        record = self.handler.records[0]
        self.assertEqual(record.trace_id, "bar-trace")
        self.assertEqual(record.schema_version, SCHEMA_VERSION)
        self.assertEqual(record.symbol, "EURUSD")
        self.assertEqual(record.timeframe, "M1")
        self.assertEqual(record.timestamp, T0.isoformat())
        self.assertEqual(record.source, "test")
        self.assertEqual(record.quality, "NOMINAL")

    def test_configurable_log_level_is_honored(self):
        logger.setLevel(logging.WARNING)
        log_ingestion_event(_tick(), level=logging.INFO)
        self.assertEqual(len(self.handler.records), 0)  # INFO filtered out below WARNING

        log_ingestion_event(_tick(), level=logging.WARNING)
        self.assertEqual(len(self.handler.records), 1)

    def test_logging_is_deterministic(self):
        log_ingestion_event(_tick(), level=logging.INFO)
        log_ingestion_event(_tick(), level=logging.INFO)
        first, second = self.handler.records
        self.assertEqual(first.trace_id, second.trace_id)
        self.assertEqual(first.timestamp, second.timestamp)

    def test_logging_failure_never_raises(self):
        class _ExplodingEvent:
            trace_id = "x"
            schema_version = 1
            symbol = "EURUSD"
            timestamp = None  # .isoformat() will raise AttributeError

        try:
            log_ingestion_event(_ExplodingEvent(), level=logging.INFO)  # type: ignore[arg-type]
        except Exception as exc:  # pragma: no cover - test fails if this triggers
            self.fail(f"log_ingestion_event must never raise, but raised: {exc!r}")


class TestPipelineEmitsLogsForEveryIngestionEvent(unittest.TestCase):
    """Confirms DataPipeline actually calls the logging sink for every
    produced tick and bar, end to end — not just that the sink function
    works in isolation."""

    def setUp(self):
        self.handler = _CapturingHandler()
        logger.addHandler(self.handler)
        logger.setLevel(logging.DEBUG)
        self.previous_propagate = logger.propagate
        logger.propagate = False

    def tearDown(self):
        logger.removeHandler(self.handler)
        logger.propagate = self.previous_propagate

    def test_every_tick_and_finalized_bar_is_logged(self):
        pipeline = DataPipeline(PipelineConfig())
        from datetime import timedelta

        for minute in range(3):
            pipeline.process_raw_tick(
                "EURUSD",
                T0 + timedelta(minutes=minute),
                1.1000 + minute * 0.0005,
                1.1002 + minute * 0.0005,
                None,
                1.0,
                "test",
            )
        pipeline.flush("EURUSD")

        tick_records = [r for r in self.handler.records if r.timeframe is None]
        bar_records = [r for r in self.handler.records if r.timeframe is not None]
        self.assertEqual(len(tick_records), 3)
        self.assertEqual(len(bar_records), pipeline.bars_produced)
        self.assertGreater(len(bar_records), 0)

    def test_logging_never_alters_pipeline_output(self):
        # Same sequence with and without a handler attached must produce
        # identical pipeline state — logging is observability, not a gate.
        from datetime import timedelta

        config = PipelineConfig()

        logger.removeHandler(self.handler)
        silent = DataPipeline(config)
        for minute in range(4):
            silent.process_raw_tick(
                "EURUSD", T0 + timedelta(minutes=minute), 1.1000 + minute * 0.0005,
                1.1002 + minute * 0.0005, None, 1.0, "test",
            )
        silent.flush("EURUSD")

        logger.addHandler(self.handler)
        observed = DataPipeline(config)
        for minute in range(4):
            observed.process_raw_tick(
                "EURUSD", T0 + timedelta(minutes=minute), 1.1000 + minute * 0.0005,
                1.1002 + minute * 0.0005, None, 1.0, "test",
            )
        observed.flush("EURUSD")

        self.assertEqual(
            silent.get_historical_series("EURUSD", "M1").bars,
            observed.get_historical_series("EURUSD", "M1").bars,
        )


if __name__ == "__main__":
    unittest.main()
