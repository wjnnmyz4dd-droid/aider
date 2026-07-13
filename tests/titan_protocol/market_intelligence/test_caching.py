"""Caching tests: the news-feed cache avoids recomputation and stays
bounded (ADR-025 §12 "cache external data responsibly")."""

from __future__ import annotations

import unittest
from datetime import timedelta

from titan_protocol.market_intelligence.config import MarketIntelligenceConfig
from titan_protocol.market_intelligence.engine import _NewsFeedCache
from titan_protocol.market_intelligence.models import NewsCategory, NewsEvent, NewsImpact
from tests.titan_protocol.market_intelligence._fixtures import T0, make_config


class TestNewsFeedCache(unittest.TestCase):
    def test_repeated_lookup_within_same_minute_returns_cached_result(self):
        cache = _NewsFeedCache(max_entries=10)
        config = make_config()
        events = (NewsEvent("e1", "USD", NewsCategory.NFP, NewsImpact.HIGH, T0 + timedelta(minutes=5), released=False),)
        r1 = cache.get_or_compute("EURUSD", events, T0, config)
        r2 = cache.get_or_compute("EURUSD", events, T0 + timedelta(seconds=30), config)
        self.assertEqual(r1, r2)
        self.assertEqual(cache.size(), 1)

    def test_different_minute_is_a_different_entry(self):
        cache = _NewsFeedCache(max_entries=10)
        config = make_config()
        cache.get_or_compute("EURUSD", (), T0, config)
        cache.get_or_compute("EURUSD", (), T0 + timedelta(minutes=1), config)
        self.assertEqual(cache.size(), 2)

    def test_different_pair_is_a_different_entry(self):
        cache = _NewsFeedCache(max_entries=10)
        config = make_config()
        cache.get_or_compute("EURUSD", (), T0, config)
        cache.get_or_compute("GBPUSD", (), T0, config)
        self.assertEqual(cache.size(), 2)

    def test_different_events_content_is_a_different_entry(self):
        cache = _NewsFeedCache(max_entries=10)
        config = make_config()
        events_a = (NewsEvent("e1", "USD", NewsCategory.NFP, NewsImpact.HIGH, T0, released=False),)
        events_b = (NewsEvent("e2", "USD", NewsCategory.CPI, NewsImpact.LOW, T0, released=False),)
        cache.get_or_compute("EURUSD", events_a, T0, config)
        cache.get_or_compute("EURUSD", events_b, T0, config)
        self.assertEqual(cache.size(), 2)

    def test_bounded_by_max_entries(self):
        cache = _NewsFeedCache(max_entries=3)
        config = make_config()
        for i in range(10):
            cache.get_or_compute(f"PAIR{i}", (), T0, config)
        self.assertEqual(cache.size(), 3)


if __name__ == "__main__":
    unittest.main()
