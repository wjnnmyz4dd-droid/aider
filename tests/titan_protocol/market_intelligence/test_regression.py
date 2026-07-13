"""Regression tests: fixed input/output anchors for scenarios worked
through during development, so a future refactor that silently changes
this behavior gets caught."""

from __future__ import annotations

import unittest
from datetime import timedelta

from titan_protocol.market_intelligence.engine import MarketIntelligenceEngine
from titan_protocol.market_intelligence.models import MarketSafetyInputs, NewsCategory, NewsEvent, NewsImpact
from tests.titan_protocol.market_intelligence._fixtures import T0, make_config, make_evidence_report


class TestKnownGoodEvaluation(unittest.TestCase):
    def test_no_news_no_concerns_scores_stable(self):
        engine = MarketIntelligenceEngine(make_config())
        evidence = make_evidence_report("EURUSD", now=T0)
        snapshot = engine.evaluate("EURUSD", evidence, [], 1.0, 1.0, MarketSafetyInputs(), now=T0)
        # T0 is the London/NY overlap hour with no news/spread/safety
        # concerns -- this is the "everything is fine" anchor case.
        self.assertAlmostEqual(snapshot.pair_safety.pair_safety_score, 100.0, places=6)
        self.assertAlmostEqual(snapshot.trade_readiness.readiness_score, 100.0, places=6)

    def test_nfp_high_impact_10_minutes_out_blocks_readiness(self):
        # The exact pre-news-blackout scenario used to verify
        # compute_blackout() by hand during development.
        engine = MarketIntelligenceEngine(make_config())
        evidence = make_evidence_report("EURUSD", now=T0)
        events = [NewsEvent("e1", "USD", NewsCategory.NFP, NewsImpact.HIGH, T0 + timedelta(minutes=10), released=False)]
        snapshot = engine.evaluate("EURUSD", evidence, events, 1.0, 1.0, MarketSafetyInputs(), now=T0)
        self.assertTrue(snapshot.pair_safety.news.blackout_active)
        self.assertEqual(snapshot.trade_readiness.readiness_score, 0.0)
        self.assertAlmostEqual(snapshot.pair_safety.news.news_score, 70.0, places=6)


if __name__ == "__main__":
    unittest.main()
