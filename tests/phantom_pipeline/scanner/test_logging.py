"""Structured logging emission (ADR-002 §11)."""

from __future__ import annotations

import logging
import unittest
from datetime import datetime, timedelta, timezone

from phantom_pipeline.data_pipeline.models import DataQuality, MarketSnapshot, NormalizedBar, SCHEMA_VERSION
from phantom_pipeline.scanner.config import SCANNER_VERSION, ScannerConfig
from phantom_pipeline.scanner.logging_sink import log_observation, logger
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


class _CapturingHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


class TestLogObservation(unittest.TestCase):
    def setUp(self):
        self.handler = _CapturingHandler()
        logger.addHandler(self.handler)
        logger.setLevel(logging.DEBUG)
        self.previous_propagate = logger.propagate
        logger.propagate = False

    def tearDown(self):
        logger.removeHandler(self.handler)
        logger.propagate = self.previous_propagate

    def test_observation_log_carries_all_required_fields(self):
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
        observation = Scanner(ScannerConfig()).scan(
            "EURUSD", {"M1": bars}, snapshot, bars[-1].timestamp, "M1"
        )
        self.handler.records.clear()
        log_observation(observation, level=logging.INFO)

        self.assertEqual(len(self.handler.records), 1)
        record = self.handler.records[0]
        self.assertEqual(record.trace_id, observation.trace_id)
        self.assertEqual(record.schema_version, observation.schema_version)
        self.assertEqual(record.scanner_version, SCANNER_VERSION)
        self.assertEqual(record.symbol, "EURUSD")
        self.assertEqual(record.timestamp, observation.timestamp.isoformat())
        self.assertEqual(record.data_quality_flag, observation.data_quality_flag.value)
        self.assertTrue(hasattr(record, "trend_summary"))
        self.assertTrue(hasattr(record, "structure_summary"))
        self.assertTrue(hasattr(record, "volatility_summary"))
        self.assertTrue(hasattr(record, "session_summary"))

    def test_configurable_log_level_is_honored(self):
        bars = [_bar(i) for i in range(3)]
        observation = Scanner(ScannerConfig()).scan(
            "EURUSD",
            {"M1": bars},
            None,
            bars[-1].timestamp,
            "M1",
        )
        self.handler.records.clear()
        logger.setLevel(logging.WARNING)
        log_observation(observation, level=logging.INFO)
        self.assertEqual(len(self.handler.records), 0)

        log_observation(observation, level=logging.WARNING)
        self.assertEqual(len(self.handler.records), 1)

    def test_logging_failure_never_raises(self):
        class _ExplodingObservation:
            trace_id = "x"
            schema_version = 1
            symbol = "EURUSD"
            timestamp = None  # .isoformat() will raise AttributeError

        try:
            log_observation(_ExplodingObservation(), level=logging.INFO)  # type: ignore[arg-type]
        except Exception as exc:  # pragma: no cover - test fails if this triggers
            self.fail(f"log_observation must never raise, but raised: {exc!r}")

    def test_scanner_scan_emits_exactly_one_log_record(self):
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
        self.handler.records.clear()
        Scanner(ScannerConfig()).scan("EURUSD", {"M1": bars}, snapshot, bars[-1].timestamp, "M1")
        self.assertEqual(len(self.handler.records), 1)


if __name__ == "__main__":
    unittest.main()
