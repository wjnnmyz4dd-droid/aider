"""Integration category: `MarketDataIngestionEngine` end to end --
ingest_bar/ingest_tick/backfill/get_bars/warmup_status/is_ready/
latest_spread/health_snapshot working together."""

from __future__ import annotations

import unittest
from datetime import timedelta

from titan_protocol.market_data_ingestion.engine import MarketDataIngestionEngine
from titan_protocol.market_data_ingestion.metrics import MarketDataIngestionMetrics
from titan_protocol.market_data_ingestion.models import Timeframe
from tests.titan_protocol.market_data_ingestion._fixtures import T0, make_bar, make_bar_sequence, make_config, make_tick


class TestEngineEndToEnd(unittest.TestCase):
    def test_ingest_bar_then_get_bars_round_trips(self):
        engine = MarketDataIngestionEngine(make_config())
        result = engine.ingest_bar(make_bar(), T0)
        self.assertTrue(result.accepted)
        bars = engine.get_bars("EURUSD", Timeframe.M15)
        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0].symbol, "EURUSD")

    def test_forming_bar_is_not_added_to_retention(self):
        engine = MarketDataIngestionEngine(make_config())
        engine.ingest_bar(make_bar(is_closed=False), T0)
        self.assertEqual(engine.get_bars("EURUSD", Timeframe.M15), ())

    def test_warmup_reaches_ready_after_enough_closed_bars(self):
        config = make_config(min_warmup_bars_by_timeframe={Timeframe.M15: 5})
        engine = MarketDataIngestionEngine(config)
        bars = make_bar_sequence(5)
        for bar in bars:
            engine.ingest_bar(bar, bar.bar_open_time)
        shortly_after_last_bar = bars[-1].bar_open_time + timedelta(minutes=5)
        self.assertTrue(engine.is_ready("EURUSD", Timeframe.M15, shortly_after_last_bar))

    def test_not_ready_when_warmed_up_but_feed_now_stale(self):
        config = make_config(min_warmup_bars_by_timeframe={Timeframe.M15: 3})
        engine = MarketDataIngestionEngine(config)
        for bar in make_bar_sequence(3):
            engine.ingest_bar(bar, T0)
        much_later = T0 + timedelta(days=1)
        self.assertFalse(engine.is_ready("EURUSD", Timeframe.M15, much_later))

    def test_backfill_populates_warmup_without_fabricating_bars(self):
        config = make_config(min_warmup_bars_by_timeframe={Timeframe.M15: 10})
        engine = MarketDataIngestionEngine(config)
        status = engine.backfill("EURUSD", Timeframe.M15, make_bar_sequence(4), T0)
        self.assertEqual(status.bars_received, 4)
        self.assertFalse(status.ready)  # honest -- backfill supplied fewer than required, nothing invented

    def test_tick_updates_latest_spread(self):
        engine = MarketDataIngestionEngine(make_config())
        self.assertIsNone(engine.latest_spread("EURUSD"))
        engine.ingest_tick(make_tick(bid=1.1000, ask=1.1002), T0)
        current, average = engine.latest_spread("EURUSD")
        self.assertAlmostEqual(current, 0.0002, places=6)
        self.assertAlmostEqual(average, 0.0002, places=6)

    def test_metrics_are_recorded_when_supplied(self):
        metrics = MarketDataIngestionMetrics()
        engine = MarketDataIngestionEngine(make_config(), metrics=metrics)
        engine.ingest_bar(make_bar(), T0)
        engine.ingest_bar(make_bar(symbol="XAUUSD"), T0)  # rejected -- unknown symbol
        self.assertEqual(metrics.accepted_count, 1)
        self.assertEqual(metrics.rejected_count, 1)

    def test_health_snapshot_reports_every_enabled_pair_and_timeframe(self):
        config = make_config(enabled_pairs=("EURUSD", "GBPUSD"), required_timeframes=(Timeframe.M15, Timeframe.H1))
        engine = MarketDataIngestionEngine(config)
        snapshot = engine.health_snapshot(T0)
        self.assertEqual(len(snapshot.warmup_statuses), 4)
        self.assertEqual(len(snapshot.freshness), 4)


if __name__ == "__main__":
    unittest.main()
