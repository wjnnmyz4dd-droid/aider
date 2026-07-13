"""Failure-mode tests: fail-closed behavior when required market
intelligence cannot be trusted (ADR-025 Hard Rule 5 / §12)."""

from __future__ import annotations

import unittest

from titan_protocol.market_intelligence.engine import MarketIntelligenceEngine
from titan_protocol.market_intelligence.models import MarketSafetyInputs
from tests.titan_protocol.market_intelligence._fixtures import make_config, make_evidence_report


class TestUntrustedNewsFeed(unittest.TestCase):
    def test_untrusted_feed_forces_blackout_not_a_default_safe_state(self):
        engine = MarketIntelligenceEngine(make_config())
        evidence = make_evidence_report("EURUSD")
        snapshot = engine.evaluate(
            "EURUSD", evidence, [], 1.0, 1.0, MarketSafetyInputs(), news_feed_trusted=False,
        )
        self.assertTrue(snapshot.pair_safety.news.blackout_active)
        self.assertEqual(snapshot.pair_safety.news.news_score, 0.0)
        self.assertEqual(snapshot.trade_readiness.readiness_score, 0.0)
        self.assertIn("untrusted", snapshot.pair_safety.news.blackout_reason)

    def test_untrusted_feed_never_silently_reports_events(self):
        # Even if the caller happened to pass real-looking events along
        # with news_feed_trusted=False, the engine must not use them --
        # an untrusted feed's *content* is exactly what can't be relied
        # on, so it is discarded, not partially trusted.
        from datetime import timedelta

        from titan_protocol.market_intelligence.models import NewsCategory, NewsEvent, NewsImpact
        from tests.titan_protocol.market_intelligence._fixtures import T0

        engine = MarketIntelligenceEngine(make_config())
        evidence = make_evidence_report("EURUSD", now=T0)
        events = [NewsEvent("e1", "USD", NewsCategory.CPI, NewsImpact.LOW, T0 + timedelta(days=10), released=False)]
        snapshot = engine.evaluate(
            "EURUSD", evidence, events, 1.0, 1.0, MarketSafetyInputs(), now=T0, news_feed_trusted=False,
        )
        self.assertEqual(snapshot.pair_safety.news.upcoming_events, ())


class TestAbsoluteBlockersFailClosed(unittest.TestCase):
    def test_broker_maintenance_forces_zero_regardless_of_everything_else(self):
        engine = MarketIntelligenceEngine(make_config())
        evidence = make_evidence_report("EURUSD")
        snapshot = engine.evaluate(
            "EURUSD", evidence, [], 1.0, 1.0, MarketSafetyInputs(broker_maintenance_active=True),
        )
        self.assertEqual(snapshot.pair_safety.pair_safety_score, 0.0)
        self.assertEqual(snapshot.trade_readiness.readiness_score, 0.0)

    def test_market_closed_forces_zero(self):
        engine = MarketIntelligenceEngine(make_config())
        evidence = make_evidence_report("EURUSD")
        snapshot = engine.evaluate(
            "EURUSD", evidence, [], 1.0, 1.0, MarketSafetyInputs(market_closed=True),
        )
        self.assertEqual(snapshot.pair_safety.pair_safety_score, 0.0)


if __name__ == "__main__":
    unittest.main()
