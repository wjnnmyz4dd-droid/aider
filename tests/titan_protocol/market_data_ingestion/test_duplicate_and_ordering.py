"""Duplicate-bar and out-of-order categories, exercised through the
real engine (not just the pure `ordering.py` functions -- proves the
retention buffer/warmup counters are correctly protected too)."""

from __future__ import annotations

import unittest
from datetime import timedelta

from titan_protocol.market_data_ingestion.engine import MarketDataIngestionEngine
from titan_protocol.market_data_ingestion.models import RejectionReason, Timeframe
from tests.titan_protocol.market_data_ingestion._fixtures import T0, make_bar, make_config


class TestDuplicateBars(unittest.TestCase):
    def test_exact_duplicate_rejected_and_not_double_counted(self):
        engine = MarketDataIngestionEngine(make_config())
        bar = make_bar(sequence_number=1, bar_open_time=T0)
        first = engine.ingest_bar(bar, T0)
        second = engine.ingest_bar(bar, T0)
        self.assertTrue(first.accepted)
        self.assertFalse(second.accepted)
        self.assertEqual(second.rejection_reason, RejectionReason.DUPLICATE)
        self.assertEqual(len(engine.get_bars("EURUSD", Timeframe.M15)), 1)
        self.assertEqual(engine.warmup_status("EURUSD", Timeframe.M15).bars_received, 1)


class TestOutOfOrderBars(unittest.TestCase):
    def test_timestamp_regression_rejected(self):
        engine = MarketDataIngestionEngine(make_config())
        engine.ingest_bar(make_bar(sequence_number=1, bar_open_time=T0), T0)
        earlier = make_bar(sequence_number=2, bar_open_time=T0 - timedelta(minutes=30))
        result = engine.ingest_bar(earlier, T0)
        self.assertFalse(result.accepted)
        self.assertEqual(result.rejection_reason, RejectionReason.OUT_OF_ORDER)

    def test_sequence_number_regression_rejected(self):
        engine = MarketDataIngestionEngine(make_config())
        engine.ingest_bar(make_bar(sequence_number=10, bar_open_time=T0), T0)
        later_time = T0 + timedelta(minutes=15)
        corrupted = make_bar(sequence_number=2, bar_open_time=later_time)
        result = engine.ingest_bar(corrupted, T0)
        self.assertFalse(result.accepted)
        self.assertEqual(result.rejection_reason, RejectionReason.OUT_OF_SEQUENCE)

    def test_rejected_bar_does_not_advance_sequence_state(self):
        engine = MarketDataIngestionEngine(make_config())
        engine.ingest_bar(make_bar(sequence_number=1, bar_open_time=T0), T0)
        engine.ingest_bar(make_bar(sequence_number=1, bar_open_time=T0), T0)  # rejected duplicate
        # A genuinely new, correctly-ordered bar must still be accepted afterward.
        next_bar = make_bar(sequence_number=2, bar_open_time=T0 + timedelta(minutes=15))
        result = engine.ingest_bar(next_bar, T0 + timedelta(minutes=15))
        self.assertTrue(result.accepted)


if __name__ == "__main__":
    unittest.main()
