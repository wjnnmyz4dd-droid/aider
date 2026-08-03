"""Bar construction correctness, multi-timeframe correctness
(VALIDATION_MATRIX.md §1 / ADR-013 §16)."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from phantom_pipeline.data_pipeline.bars import BarBuilder, aggregate_bars
from phantom_pipeline.data_pipeline.config import PipelineConfig
from phantom_pipeline.data_pipeline.ingest import TickIngestor

T0 = datetime(2026, 7, 4, 12, 0, 0, tzinfo=timezone.utc)


def _ticks(count: int, start=T0, step_seconds=10, base_price=1.1000):
    return [
        (start + timedelta(seconds=i * step_seconds), base_price + i * 0.0001)
        for i in range(count)
    ]


class TestBarConstruction(unittest.TestCase):
    def setUp(self):
        self.config = PipelineConfig()
        self.ingestor = TickIngestor(self.config)
        self.builder = BarBuilder(self.config, "M1")

    def _feed(self, timestamp, price):
        # last=price (bid/ask omitted) so the bar's OHLC values equal the
        # intended test price exactly, rather than a bid/ask midpoint.
        result = self.ingestor.ingest(
            "EURUSD", timestamp, None, None, price, 1.0, "test"
        )
        self.assertIsNotNone(result.tick)
        return self.builder.add_tick(result.tick)

    def test_ticks_within_one_minute_form_one_bar(self):
        finalized = None
        for ts, price in _ticks(5, step_seconds=10):
            finalized = self._feed(ts, price) or finalized
        self.assertIsNone(finalized)  # bucket not yet closed
        bar = self.builder.flush("EURUSD")
        self.assertIsNotNone(bar)
        self.assertEqual(bar.open, 1.1000)
        self.assertEqual(bar.close, 1.1000 + 4 * 0.0001)
        self.assertEqual(bar.high, max(p for _, p in _ticks(5, step_seconds=10)))
        self.assertEqual(bar.low, min(p for _, p in _ticks(5, step_seconds=10)))
        self.assertAlmostEqual(bar.volume, 5.0)

    def test_new_minute_finalizes_previous_bar(self):
        self._feed(T0, 1.1000)
        self._feed(T0 + timedelta(seconds=30), 1.1005)
        finalized = self._feed(T0 + timedelta(minutes=1, seconds=1), 1.1010)
        self.assertIsNotNone(finalized)
        self.assertEqual(finalized.open, 1.1000)
        self.assertEqual(finalized.close, 1.1005)

    def test_bar_carries_trace_id_and_schema_version(self):
        self._feed(T0, 1.1000)
        bar = self.builder.flush("EURUSD")
        self.assertTrue(bar.trace_id)
        self.assertEqual(bar.schema_version, 1)

    def test_identical_tick_sequence_produces_identical_bars(self):
        b1 = BarBuilder(self.config, "M1")
        b2 = BarBuilder(self.config, "M1")
        i1 = TickIngestor(self.config)
        i2 = TickIngestor(self.config)
        bars1, bars2 = [], []
        for ts, price in _ticks(5, step_seconds=10):
            r1 = i1.ingest("EURUSD", ts, price, price + 0.0002, None, 1.0, "test")
            r2 = i2.ingest("EURUSD", ts, price, price + 0.0002, None, 1.0, "test")
            f1 = b1.add_tick(r1.tick)
            f2 = b2.add_tick(r2.tick)
            if f1:
                bars1.append(f1)
            if f2:
                bars2.append(f2)
        bars1.append(b1.flush("EURUSD"))
        bars2.append(b2.flush("EURUSD"))
        self.assertEqual(bars1, bars2)


class TestMultiTimeframeAggregation(unittest.TestCase):
    def setUp(self):
        self.config = PipelineConfig()

    def _make_m1_bars(self, count, start=T0):
        bars = []
        ingestor = TickIngestor(self.config)
        builder = BarBuilder(self.config, "M1")
        for minute in range(count):
            ts = start + timedelta(minutes=minute)
            price = 1.1000 + minute * 0.0005
            result = ingestor.ingest(
                "EURUSD", ts, price, price + 0.0002, None, 1.0, "test"
            )
            finalized = builder.add_tick(result.tick)
            if finalized:
                bars.append(finalized)
        last = builder.flush("EURUSD")
        if last:
            bars.append(last)
        return bars

    def test_five_m1_bars_aggregate_to_one_m5_bar(self):
        m1_bars = self._make_m1_bars(5)
        self.assertEqual(len(m1_bars), 5)
        m5_bars = aggregate_bars(m1_bars, "M5", self.config)
        self.assertEqual(len(m5_bars), 1)
        agg = m5_bars[0]
        self.assertEqual(agg.timeframe, "M5")
        self.assertEqual(agg.open, m1_bars[0].open)
        self.assertEqual(agg.close, m1_bars[-1].close)
        self.assertEqual(agg.high, max(b.high for b in m1_bars))
        self.assertEqual(agg.low, min(b.low for b in m1_bars))
        self.assertAlmostEqual(agg.volume, sum(b.volume for b in m1_bars))

    def test_partial_final_bucket_is_still_emitted(self):
        m1_bars = self._make_m1_bars(7)  # 5 + 2 leftover
        m5_bars = aggregate_bars(m1_bars, "M5", self.config)
        self.assertEqual(len(m5_bars), 2)
        self.assertEqual(m5_bars[1].close, m1_bars[-1].close)

    def test_non_multiple_timeframe_raises(self):
        m1_bars = self._make_m1_bars(3)
        with self.assertRaises(ValueError):
            aggregate_bars(m1_bars, "H1", PipelineConfig(
                timeframe_seconds={"M1": 60, "H1": 90}
            ))

    def test_aggregation_is_deterministic(self):
        m1_bars = self._make_m1_bars(10)
        first = aggregate_bars(m1_bars, "M5", self.config)
        second = aggregate_bars(m1_bars, "M5", self.config)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
