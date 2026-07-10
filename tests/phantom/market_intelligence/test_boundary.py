"""Boundary tests: empty inputs, extreme spreads, midnight/session
edges, empty pair batches."""

from __future__ import annotations

import unittest
from datetime import timedelta

from phantom.market_intelligence.engine import MarketIntelligenceEngine
from phantom.market_intelligence.liquidity_intelligence import evaluate_liquidity
from phantom.market_intelligence.models import MarketSafetyInputs
from phantom.market_intelligence.news import build_pair_news_intelligence
from tests.phantom.market_intelligence._fixtures import T0, make_config, make_evidence_report


class TestEmptyInputs(unittest.TestCase):
    def test_no_events_produces_full_score(self):
        result = build_pair_news_intelligence("EURUSD", [], T0, make_config())
        self.assertEqual(result.news_score, 100.0)
        self.assertFalse(result.blackout_active)

    def test_empty_batch_returns_empty(self):
        engine = MarketIntelligenceEngine(make_config())
        results = engine.evaluate_batch({}, [], {}, MarketSafetyInputs())
        self.assertEqual(results, ())


class TestExtremeSpreads(unittest.TestCase):
    def test_zero_spreads_do_not_raise(self):
        result = evaluate_liquidity(0.0, 0.0, make_config())
        self.assertTrue(0.0 <= result.liquidity_score <= 100.0)

    def test_huge_spread_does_not_raise(self):
        result = evaluate_liquidity(1_000_000.0, 1.0, make_config())
        self.assertEqual(result.liquidity_score, 0.0)

    def test_negative_spread_does_not_raise(self):
        # Should never happen in practice, but must not crash the engine.
        result = evaluate_liquidity(-1.0, 1.0, make_config())
        self.assertTrue(0.0 <= result.liquidity_score <= 100.0)


class TestSessionBoundaryEdges(unittest.TestCase):
    def test_midnight_evaluates_without_error(self):
        engine = MarketIntelligenceEngine(make_config())
        evidence = make_evidence_report("EURUSD", now=T0.replace(hour=0, minute=0))
        snapshot = engine.evaluate("EURUSD", evidence, [], 1.0, 1.0, MarketSafetyInputs(), now=T0.replace(hour=0, minute=0))
        self.assertTrue(0.0 <= snapshot.pair_safety.pair_safety_score <= 100.0)

    def test_exact_session_boundary_hour_does_not_raise(self):
        engine = MarketIntelligenceEngine(make_config())
        boundary = T0.replace(hour=7, minute=0)  # London session start
        evidence = make_evidence_report("EURUSD", now=boundary)
        snapshot = engine.evaluate("EURUSD", evidence, [], 1.0, 1.0, MarketSafetyInputs(), now=boundary)
        self.assertTrue(0.0 <= snapshot.pair_safety.pair_safety_score <= 100.0)


class TestEventAtExactWindowEdge(unittest.TestCase):
    def test_event_exactly_at_blackout_boundary_is_included(self):
        from phantom.market_intelligence.models import NewsCategory, NewsEvent, NewsImpact
        from phantom.market_intelligence.news import compute_blackout

        config = make_config()
        event = NewsEvent("e1", "USD", NewsCategory.NFP, NewsImpact.HIGH, T0 + timedelta(minutes=config.pre_news_blackout_minutes), released=False)
        active, _ = compute_blackout("EURUSD", [event], T0, config)
        self.assertTrue(active)

    def test_event_just_past_blackout_boundary_is_excluded(self):
        from phantom.market_intelligence.models import NewsCategory, NewsEvent, NewsImpact
        from phantom.market_intelligence.news import compute_blackout

        config = make_config()
        event = NewsEvent("e1", "USD", NewsCategory.NFP, NewsImpact.HIGH, T0 + timedelta(minutes=config.pre_news_blackout_minutes + 1), released=False)
        active, _ = compute_blackout("EURUSD", [event], T0, config)
        self.assertFalse(active)


if __name__ == "__main__":
    unittest.main()
