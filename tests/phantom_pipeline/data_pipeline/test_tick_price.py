"""Shared price-selection helper (`tick_price`) — remediation for the
duplicated BarBuilder/DataPipeline price-selection logic found during
the ADR-013 Phase 1 audit."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from phantom_pipeline.data_pipeline.bars import BarBuilder
from phantom_pipeline.data_pipeline.config import PipelineConfig
from phantom_pipeline.data_pipeline.ingest import TickIngestor
from phantom_pipeline.data_pipeline.models import SCHEMA_VERSION, NormalizedTick, tick_price
from phantom_pipeline.data_pipeline.pipeline import DataPipeline

T0 = datetime(2026, 7, 4, 12, 0, 0, tzinfo=timezone.utc)


def _tick(bid=None, ask=None, last=None) -> NormalizedTick:
    return NormalizedTick(
        schema_version=SCHEMA_VERSION,
        trace_id="t",
        symbol="EURUSD",
        timestamp=T0,
        bid=bid,
        ask=ask,
        last=last,
        volume=1.0,
        source="test",
    )


class TestTickPrice(unittest.TestCase):
    def test_prefers_last_when_present(self):
        tick = _tick(bid=1.1000, ask=1.1002, last=1.1005)
        self.assertEqual(tick_price(tick), 1.1005)

    def test_falls_back_to_bid_ask_midpoint(self):
        tick = _tick(bid=1.1000, ask=1.1002, last=None)
        self.assertEqual(tick_price(tick), 1.1001)

    def test_none_when_no_price_information(self):
        tick = _tick(bid=None, ask=None, last=None)
        self.assertIsNone(tick_price(tick))

    def test_none_when_only_bid_present(self):
        tick = _tick(bid=1.1000, ask=None, last=None)
        self.assertIsNone(tick_price(tick))


class TestSharedImplementationConsistency(unittest.TestCase):
    """BarBuilder and DataPipeline must agree on price because both call
    the same `tick_price` function — not because two independent
    implementations happen to produce the same result."""

    def test_bar_open_and_snapshot_price_agree_for_the_same_tick(self):
        config = PipelineConfig()
        pipeline = DataPipeline(config)
        ingestor = TickIngestor(config)
        builder = BarBuilder(config, "M1")

        result = ingestor.ingest("EURUSD", T0, 1.1000, 1.1002, None, 1.0, "test")
        self.assertIsNotNone(result.tick)
        expected_price = tick_price(result.tick)

        builder.add_tick(result.tick)
        bar = builder.flush("EURUSD")
        self.assertEqual(bar.open, expected_price)

        pipeline.process_raw_tick("EURUSD", T0, 1.1000, 1.1002, None, 1.0, "test")
        snapshot = pipeline.get_snapshot("EURUSD")
        self.assertEqual(snapshot.price, expected_price)

    def test_bar_builder_no_longer_has_its_own_price_method(self):
        # The private duplicate implementation must be gone, not merely
        # unused — confirms the remediation actually removed it rather
        # than leaving dead code behind.
        self.assertFalse(hasattr(BarBuilder, "_tick_price"))


if __name__ == "__main__":
    unittest.main()
