"""Integration tests for `MarketIntelligenceEngine.evaluate()` /
`evaluate_batch()`."""

from __future__ import annotations

import unittest
from datetime import timedelta

from titan_protocol.market_intelligence.engine import MarketIntelligenceEngine
from titan_protocol.market_intelligence.metrics import MarketIntelligenceMetrics
from titan_protocol.market_intelligence.models import (
    MarketIntelligenceSnapshot,
    MarketSafetyInputs,
    NewsCategory,
    NewsEvent,
    NewsImpact,
    PegPolicyEventType,
)
from titan_protocol.market_intelligence.peg_policy import PegPolicyRegistry
from tests.titan_protocol.market_intelligence._fixtures import T0, make_config, make_evidence_report


class TestEvaluate(unittest.TestCase):
    def test_returns_a_fully_populated_snapshot(self):
        engine = MarketIntelligenceEngine(make_config())
        evidence = make_evidence_report("EURUSD")
        snapshot = engine.evaluate("EURUSD", evidence, [], 1.0, 1.0, MarketSafetyInputs())
        self.assertIsInstance(snapshot, MarketIntelligenceSnapshot)
        self.assertEqual(snapshot.pair, "EURUSD")
        self.assertTrue(0.0 <= snapshot.pair_safety.pair_safety_score <= 100.0)
        self.assertTrue(0.0 <= snapshot.trade_readiness.readiness_score <= 100.0)

    def test_evidence_symbol_mismatch_raises(self):
        engine = MarketIntelligenceEngine(make_config())
        evidence = make_evidence_report("EURUSD")
        with self.assertRaises(ValueError):
            engine.evaluate("GBPUSD", evidence, [], 1.0, 1.0, MarketSafetyInputs())

    def test_uses_evidence_generated_at_when_now_not_supplied(self):
        engine = MarketIntelligenceEngine(make_config())
        evidence = make_evidence_report("EURUSD")
        snapshot = engine.evaluate("EURUSD", evidence, [], 1.0, 1.0, MarketSafetyInputs())
        self.assertEqual(snapshot.generated_at, evidence.generated_at)

    def test_peg_policy_registry_wired_through(self):
        registry = PegPolicyRegistry()
        registry.activate("EURUSD", PegPolicyEventType.CURRENCY_PEG, "test", T0)
        engine = MarketIntelligenceEngine(make_config(), peg_policy_registry=registry)
        evidence = make_evidence_report("EURUSD")
        snapshot = engine.evaluate("EURUSD", evidence, [], 1.0, 1.0, MarketSafetyInputs())
        self.assertTrue(snapshot.pair_safety.peg_policy.active)
        self.assertEqual(snapshot.pair_safety.pair_safety_score, 0.0)
        self.assertEqual(snapshot.trade_readiness.readiness_score, 0.0)

    def test_metrics_recorded_on_evaluate(self):
        metrics = MarketIntelligenceMetrics()
        engine = MarketIntelligenceEngine(make_config(), metrics=metrics)
        evidence = make_evidence_report("EURUSD")
        engine.evaluate("EURUSD", evidence, [], 1.0, 1.0, MarketSafetyInputs())
        engine.evaluate("EURUSD", evidence, [], 1.0, 1.0, MarketSafetyInputs())
        self.assertEqual(metrics.evaluation_count, 2)

    def test_high_impact_news_blocks_readiness_end_to_end(self):
        engine = MarketIntelligenceEngine(make_config())
        evidence = make_evidence_report("EURUSD", now=T0)
        events = [NewsEvent("e1", "USD", NewsCategory.NFP, NewsImpact.HIGH, T0 + timedelta(minutes=5), released=False)]
        snapshot = engine.evaluate("EURUSD", evidence, events, 1.0, 1.0, MarketSafetyInputs(), now=T0)
        self.assertTrue(snapshot.pair_safety.news.blackout_active)
        self.assertEqual(snapshot.trade_readiness.readiness_score, 0.0)


class TestEvaluateBatch(unittest.TestCase):
    def test_evaluates_multiple_pairs(self):
        engine = MarketIntelligenceEngine(make_config())
        pairs = {"EURUSD": make_evidence_report("EURUSD"), "GBPUSD": make_evidence_report("GBPUSD")}
        spreads = {"EURUSD": (1.0, 1.0), "GBPUSD": (1.2, 1.0)}
        results = engine.evaluate_batch(pairs, [], spreads, MarketSafetyInputs())
        self.assertEqual(len(results), 2)
        self.assertEqual({r.pair for r in results}, {"EURUSD", "GBPUSD"})

    def test_batch_metric_counts_once_per_call(self):
        metrics = MarketIntelligenceMetrics()
        engine = MarketIntelligenceEngine(make_config(), metrics=metrics)
        pairs = {"EURUSD": make_evidence_report("EURUSD"), "GBPUSD": make_evidence_report("GBPUSD")}
        spreads = {"EURUSD": (1.0, 1.0), "GBPUSD": (1.0, 1.0)}
        engine.evaluate_batch(pairs, [], spreads, MarketSafetyInputs())
        self.assertEqual(metrics.batch_evaluation_count, 1)
        self.assertEqual(metrics.evaluation_count, 2)


if __name__ == "__main__":
    unittest.main()
