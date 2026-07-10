"""Unit tests: Market Intelligence Review, Risk Review, and Compliance
Effectiveness (ADR-029 §5) -- all built on the shared bucket-comparison
helper."""

from __future__ import annotations

import unittest

from phantom.compliance_engine.models import ComplianceDecision
from phantom.research_engine.reviews import review_compliance, review_market_intelligence, review_risk
from tests.phantom.research_engine._fixtures import make_config, make_executed_trade, make_rejected_trade


class TestMarketIntelligenceReview(unittest.TestCase):
    def test_news_blackout_effectiveness_computed(self):
        config = make_config(effectiveness_min_sample_size=3)
        trades = [make_executed_trade(index=i, news_blackout_was_active=False, won=True) for i in range(10)]
        trades += [make_executed_trade(index=i, news_blackout_was_active=True, won=False) for i in range(10, 20)]
        review = review_market_intelligence(trades, config)
        self.assertEqual(review.news_blackout_effectiveness.baseline_sample_size, 10)
        self.assertEqual(review.news_blackout_effectiveness.comparison_sample_size, 10)
        self.assertTrue(review.news_blackout_effectiveness.notable)

    def test_no_recommendations_when_nothing_notable(self):
        config = make_config()
        trades = [make_executed_trade(index=i, won=(i % 2 == 0)) for i in range(20)]
        review = review_market_intelligence(trades, config)
        self.assertEqual(review.recommendations, ())


class TestRiskReview(unittest.TestCase):
    def test_kelly_binding_effectiveness_computed(self):
        config = make_config(effectiveness_min_sample_size=3)
        trades = [make_executed_trade(index=i, kelly_was_binding=False, won=True) for i in range(10)]
        trades += [make_executed_trade(index=i, kelly_was_binding=True, won=False) for i in range(10, 20)]
        review = review_risk(trades, config)
        self.assertEqual(review.kelly_cap_effectiveness.comparison_sample_size, 10)

    def test_confidence_tier_buckets_present(self):
        config = make_config(effectiveness_min_sample_size=3)
        trades = [make_executed_trade(index=i, risk_confidence_tier="TIER_5") for i in range(10)]
        review = review_risk(trades, config)
        self.assertTrue(any(c.label.startswith("confidence_tier_TIER_5") for c in review.confidence_scaling_effectiveness))


class TestComplianceEffectiveness(unittest.TestCase):
    def test_rejection_rate_computed_from_full_history(self):
        config = make_config()
        trades = [make_executed_trade(index=i, compliance_decision=ComplianceDecision.APPROVE) for i in range(8)]
        trades += [make_rejected_trade(index=i) for i in range(8, 10)]
        effectiveness = review_compliance(trades, config)
        self.assertEqual(effectiveness.rejection_count, 2)
        self.assertAlmostEqual(effectiveness.rejection_rate, 0.2, places=6)

    def test_approve_vs_reduce_comparison(self):
        config = make_config(effectiveness_min_sample_size=3)
        approved = [make_executed_trade(index=i, compliance_decision=ComplianceDecision.APPROVE, won=True) for i in range(10)]
        reduced = [make_executed_trade(index=i, compliance_decision=ComplianceDecision.REDUCE, won=False) for i in range(10, 20)]
        effectiveness = review_compliance(approved + reduced, config)
        self.assertEqual(effectiveness.approve_vs_reduce.baseline_sample_size, 10)
        self.assertEqual(effectiveness.approve_vs_reduce.comparison_sample_size, 10)


if __name__ == "__main__":
    unittest.main()
