"""Duplicate tick detection, out-of-order tick handling
(VALIDATION_MATRIX.md §1 / ADR-013 §16)."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from phantom_pipeline.data_pipeline.config import PipelineConfig
from phantom_pipeline.data_pipeline.ingest import TickIngestor

T0 = datetime(2026, 7, 4, 12, 0, 0, tzinfo=timezone.utc)


class TestDuplicateDetection(unittest.TestCase):
    def setUp(self):
        self.ingestor = TickIngestor(PipelineConfig())

    def test_identical_tick_is_flagged_duplicate(self):
        first = self.ingestor.ingest("EURUSD", T0, 1.1000, 1.1002, None, 10.0, "test")
        second = self.ingestor.ingest("EURUSD", T0, 1.1000, 1.1002, None, 10.0, "test")
        self.assertIsNotNone(first.tick)
        self.assertFalse(first.duplicate)
        self.assertIsNone(second.tick)
        self.assertTrue(second.duplicate)
        self.assertEqual(self.ingestor.duplicate_count, 1)

    def test_different_price_is_not_duplicate(self):
        first = self.ingestor.ingest("EURUSD", T0, 1.1000, 1.1002, None, 10.0, "test")
        second = self.ingestor.ingest(
            "EURUSD", T0, 1.1001, 1.1003, None, 10.0, "test"
        )
        self.assertIsNotNone(first.tick)
        self.assertIsNotNone(second.tick)
        self.assertEqual(self.ingestor.duplicate_count, 0)

    def test_duplicate_history_is_bounded(self):
        # A generous out-of-order tolerance isolates the behavior under
        # test (bounded duplicate history) from out-of-order dropping.
        config = PipelineConfig(duplicate_tick_history=2, out_of_order_tolerance_seconds=10.0)
        ingestor = TickIngestor(config)
        t1 = T0
        t2 = T0 + timedelta(seconds=1)
        t3 = T0 + timedelta(seconds=2)
        ingestor.ingest("EURUSD", t1, 1.1000, 1.1002, None, 1.0, "test")
        ingestor.ingest("EURUSD", t2, 1.1001, 1.1003, None, 1.0, "test")
        ingestor.ingest("EURUSD", t3, 1.1002, 1.1004, None, 1.0, "test")
        # t1's key has been evicted from the bounded (maxlen=2) history.
        result = ingestor.ingest("EURUSD", t1, 1.1000, 1.1002, None, 1.0, "test")
        self.assertIsNotNone(result.tick)
        self.assertFalse(result.duplicate)


class TestOutOfOrderHandling(unittest.TestCase):
    def test_tick_within_tolerance_is_accepted(self):
        config = PipelineConfig(out_of_order_tolerance_seconds=2.0)
        ingestor = TickIngestor(config)
        ingestor.ingest("EURUSD", T0, 1.1000, 1.1002, None, 1.0, "test")
        late_but_tolerable = T0 - timedelta(seconds=1)
        result = ingestor.ingest(
            "EURUSD", late_but_tolerable, 1.0999, 1.1001, None, 1.0, "test"
        )
        self.assertIsNotNone(result.tick)
        self.assertFalse(result.out_of_order_dropped)
        self.assertEqual(ingestor.out_of_order_dropped_count, 0)

    def test_tick_beyond_tolerance_is_dropped(self):
        config = PipelineConfig(out_of_order_tolerance_seconds=1.0)
        ingestor = TickIngestor(config)
        ingestor.ingest("EURUSD", T0, 1.1000, 1.1002, None, 1.0, "test")
        too_late = T0 - timedelta(seconds=5)
        result = ingestor.ingest(
            "EURUSD", too_late, 1.0999, 1.1001, None, 1.0, "test"
        )
        self.assertIsNone(result.tick)
        self.assertTrue(result.out_of_order_dropped)
        self.assertEqual(ingestor.out_of_order_dropped_count, 1)

    def test_forward_progress_is_never_flagged(self):
        config = PipelineConfig()
        ingestor = TickIngestor(config)
        for i in range(5):
            result = ingestor.ingest(
                "EURUSD", T0 + timedelta(seconds=i), 1.1000 + i * 0.0001,
                1.1002 + i * 0.0001, None, 1.0, "test",
            )
            self.assertIsNotNone(result.tick)
        self.assertEqual(ingestor.out_of_order_dropped_count, 0)


class TestMalformedInput(unittest.TestCase):
    def test_naive_timestamp_degrades_gracefully(self):
        ingestor = TickIngestor(PipelineConfig())
        result = ingestor.ingest(
            "EURUSD", datetime(2026, 7, 4, 12, 0, 0), 1.1000, 1.1002, None, 1.0, "test"
        )
        self.assertIsNone(result.tick)
        self.assertIsNotNone(result.malformed_reason)
        self.assertEqual(ingestor.malformed_count, 1)


if __name__ == "__main__":
    unittest.main()
