"""Performance sanity tests (Phase 3E mission's own TESTING list).
Not a benchmark suite -- just a floor confirming the failover/adapter
seam adds no meaningful overhead over a typical fetch cadence (news
providers are polled on the order of minutes, never per-tick)."""

from __future__ import annotations

import time
import unittest
from datetime import datetime, timedelta, timezone

from titan_protocol.news_ingestion.adapter import to_market_intelligence_event
from titan_protocol.news_ingestion.failover import NewsFailoverEngine
from titan_protocol.news_ingestion.models import ProviderName

from ._fixtures import FakeProvider, make_config, make_normalized_event

T0 = datetime(2026, 7, 14, 12, 0, 0, tzinfo=timezone.utc)


class TestFetchEventsLatency(unittest.TestCase):
    def test_100_events_per_fetch_completes_well_under_100ms(self):
        events = tuple(make_normalized_event(event_id=f"e{i}", currency="USD") for i in range(100))
        primary = FakeProvider(ProviderName.TRADING_ECONOMICS, [events] * 20)
        backup = FakeProvider(ProviderName.FOREX_FACTORY, [])
        engine = NewsFailoverEngine(make_config(), primary, backup)

        start = time.monotonic()
        for i in range(20):
            engine.fetch_events(T0 + timedelta(minutes=i))
        elapsed_ms = (time.monotonic() - start) * 1000.0
        self.assertLess(elapsed_ms, 100.0, f"20 fetches of 100 events took {elapsed_ms:.2f}ms")

    def test_adapter_conversion_of_100_events_is_fast(self):
        events = [make_normalized_event(event_id=f"e{i}") for i in range(100)]
        start = time.monotonic()
        converted = [to_market_intelligence_event(e) for e in events]
        elapsed_ms = (time.monotonic() - start) * 1000.0
        self.assertEqual(len(converted), 100)
        self.assertLess(elapsed_ms, 50.0, f"converting 100 events took {elapsed_ms:.2f}ms")


if __name__ == "__main__":
    unittest.main()
