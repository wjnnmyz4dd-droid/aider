"""Unit tests for pair-specific news intelligence, classification, and
blackout rules."""

from __future__ import annotations

import unittest
from datetime import timedelta

from titan_protocol.market_intelligence.models import NewsCategory, NewsEvent, NewsImpact
from titan_protocol.market_intelligence.news import (
    bucket_events,
    build_pair_news_intelligence,
    compute_blackout,
    compute_news_score,
    pair_currencies,
)
from tests.titan_protocol.market_intelligence._fixtures import T0, make_config


def _event(event_id, currency, category, impact, scheduled_at, released=False, released_at=None):
    return NewsEvent(event_id, currency, category, impact, scheduled_at, released, released_at)


class TestPairCurrencies(unittest.TestCase):
    def test_splits_base_and_quote(self):
        self.assertEqual(pair_currencies("EURUSD"), ("EUR", "USD"))
        self.assertEqual(pair_currencies("usdjpy"), ("USD", "JPY"))


class TestEventFiltering(unittest.TestCase):
    def test_only_relevant_currency_events_included(self):
        events = [
            _event("e1", "EUR", NewsCategory.CPI, NewsImpact.LOW, T0 + timedelta(hours=1)),
            _event("e2", "JPY", NewsCategory.CPI, NewsImpact.LOW, T0 + timedelta(hours=1)),
        ]
        upcoming, active, recent = bucket_events("EURUSD", events, T0, make_config())
        ids = {e.event_id for e in upcoming + active + recent}
        self.assertIn("e1", ids)
        self.assertNotIn("e2", ids)

    def test_far_future_event_not_in_upcoming(self):
        events = [_event("e1", "EUR", NewsCategory.CPI, NewsImpact.LOW, T0 + timedelta(days=30))]
        upcoming, active, recent = bucket_events("EURUSD", events, T0, make_config())
        self.assertEqual((upcoming, active, recent), ((), (), ()))


class TestBlackout(unittest.TestCase):
    def test_pre_news_blackout_for_high_impact_event(self):
        config = make_config()
        events = [_event("e1", "USD", NewsCategory.NFP, NewsImpact.HIGH, T0 + timedelta(minutes=10))]
        active, reason = compute_blackout("EURUSD", events, T0, config)
        self.assertTrue(active)
        self.assertIn("pre-news", reason)

    def test_no_blackout_for_low_impact_event(self):
        config = make_config()
        events = [_event("e1", "USD", NewsCategory.RETAIL_SALES, NewsImpact.LOW, T0 + timedelta(minutes=10))]
        active, reason = compute_blackout("EURUSD", events, T0, config)
        self.assertFalse(active)
        self.assertIsNone(reason)

    def test_post_news_blackout_after_release(self):
        config = make_config()
        events = [_event("e1", "USD", NewsCategory.NFP, NewsImpact.HIGH, T0 - timedelta(minutes=5), released=True, released_at=T0 - timedelta(minutes=5))]
        active, reason = compute_blackout("EURUSD", events, T0, config)
        self.assertTrue(active)
        self.assertIn("post-news", reason)

    def test_central_bank_category_triggers_blackout_even_if_medium_impact(self):
        config = make_config()
        events = [_event("e1", "EUR", NewsCategory.ECB, NewsImpact.MEDIUM, T0 + timedelta(minutes=5))]
        active, reason = compute_blackout("EURUSD", events, T0, config)
        self.assertTrue(active)

    def test_no_blackout_outside_the_window(self):
        config = make_config()
        events = [_event("e1", "USD", NewsCategory.NFP, NewsImpact.HIGH, T0 + timedelta(hours=5))]
        active, reason = compute_blackout("EURUSD", events, T0, config)
        self.assertFalse(active)

    def test_pair_specific_override_widens_blackout_window(self):
        config = make_config(pair_specific_blackout_overrides_minutes=(("EURUSD", 120.0),))
        events = [_event("e1", "USD", NewsCategory.NFP, NewsImpact.HIGH, T0 + timedelta(minutes=90))]
        active, _ = compute_blackout("EURUSD", events, T0, config)
        self.assertTrue(active)
        # Default window (30 min) would not have caught this.
        default_config = make_config()
        active_default, _ = compute_blackout("EURUSD", events, T0, default_config)
        self.assertFalse(active_default)


class TestNewsScore(unittest.TestCase):
    def test_active_priority_event_costs_more_than_upcoming(self):
        config = make_config()
        priority = _event("e1", "USD", NewsCategory.NFP, NewsImpact.HIGH, T0)
        score_active = compute_news_score([], [priority], [], config)
        score_upcoming = compute_news_score([priority], [], [], config)
        self.assertLess(score_active, score_upcoming)

    def test_score_bounded_0_100(self):
        config = make_config()
        many = [_event(f"e{i}", "USD", NewsCategory.NFP, NewsImpact.HIGH, T0) for i in range(10)]
        score = compute_news_score([], many, [], config)
        self.assertTrue(0.0 <= score <= 100.0)

    def test_no_events_scores_100(self):
        config = make_config()
        self.assertEqual(compute_news_score([], [], [], config), 100.0)


class TestBuildPairNewsIntelligence(unittest.TestCase):
    def test_produces_fully_populated_result(self):
        config = make_config()
        events = [_event("e1", "USD", NewsCategory.NFP, NewsImpact.HIGH, T0 + timedelta(minutes=10))]
        result = build_pair_news_intelligence("EURUSD", events, T0, config)
        self.assertEqual(result.pair, "EURUSD")
        self.assertTrue(result.blackout_active)
        self.assertTrue(0.0 <= result.news_score <= 100.0)


if __name__ == "__main__":
    unittest.main()
