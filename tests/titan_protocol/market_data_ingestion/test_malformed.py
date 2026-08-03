"""Malformed-data category: every named malformed condition is
rejected by the real engine, with an explicit reason code -- never a
silent drop, never a crash."""

from __future__ import annotations

import unittest
from datetime import timedelta

from titan_protocol.market_data_ingestion.engine import MarketDataIngestionEngine
from titan_protocol.market_data_ingestion.models import RejectionReason, Timeframe
from tests.titan_protocol.market_data_ingestion._fixtures import T0, make_bar, make_config


class TestMalformedBarsRejected(unittest.TestCase):
    def setUp(self):
        self.engine = MarketDataIngestionEngine(make_config())

    def test_impossible_high_low_relationship(self):
        result = self.engine.ingest_bar(make_bar(high=1.05, low=1.10), T0)
        self.assertFalse(result.accepted)
        self.assertEqual(result.rejection_reason, RejectionReason.MALFORMED)

    def test_negative_volume(self):
        result = self.engine.ingest_bar(make_bar(volume=-5.0), T0)
        self.assertFalse(result.accepted)
        self.assertEqual(result.rejection_reason, RejectionReason.MALFORMED)

    def test_crossed_bid_ask(self):
        result = self.engine.ingest_bar(make_bar(bid=1.20, ask=1.10), T0)
        self.assertFalse(result.accepted)
        self.assertEqual(result.rejection_reason, RejectionReason.MALFORMED)

    def test_unknown_symbol(self):
        result = self.engine.ingest_bar(make_bar(symbol="XAUUSD"), T0)
        self.assertFalse(result.accepted)
        self.assertEqual(result.rejection_reason, RejectionReason.UNKNOWN_SYMBOL)

    def test_unknown_timeframe(self):
        result = self.engine.ingest_bar(make_bar(timeframe=Timeframe.D1), T0)
        self.assertFalse(result.accepted)
        self.assertEqual(result.rejection_reason, RejectionReason.UNKNOWN_TIMEFRAME)

    def test_untrusted_clock_skew(self):
        config = make_config(max_clock_skew_seconds=1.0)
        engine = MarketDataIngestionEngine(config)
        bar = make_bar(broker_timestamp=T0, source_timestamp=T0 - timedelta(minutes=5))
        result = engine.ingest_bar(bar, T0)
        self.assertFalse(result.accepted)
        self.assertEqual(result.rejection_reason, RejectionReason.CLOCK_SKEW)

    def test_malformed_bar_never_enters_retention_buffer(self):
        self.engine.ingest_bar(make_bar(volume=-1.0), T0)
        self.assertEqual(self.engine.get_bars("EURUSD", Timeframe.M15), ())

    def test_malformed_tick_rejected(self):
        from tests.titan_protocol.market_data_ingestion._fixtures import make_tick
        result = self.engine.ingest_tick(make_tick(bid=1.20, ask=1.10), T0)
        self.assertFalse(result.accepted)
        self.assertEqual(result.rejection_reason, RejectionReason.MALFORMED)


if __name__ == "__main__":
    unittest.main()
