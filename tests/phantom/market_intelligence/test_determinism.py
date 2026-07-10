"""Determinism tests: same input always produces the same output."""

from __future__ import annotations

import unittest
from datetime import timedelta

from phantom.market_intelligence.engine import MarketIntelligenceEngine
from phantom.market_intelligence.models import MarketSafetyInputs, NewsCategory, NewsEvent, NewsImpact
from tests.phantom.market_intelligence._fixtures import T0, make_config, make_evidence_report


class TestDeterminism(unittest.TestCase):
    def test_repeated_evaluate_calls_produce_identical_snapshots(self):
        engine = MarketIntelligenceEngine(make_config())
        evidence = make_evidence_report("EURUSD")
        events = [NewsEvent("e1", "USD", NewsCategory.CPI, NewsImpact.MEDIUM, T0 + timedelta(hours=2), released=False)]
        r1 = engine.evaluate("EURUSD", evidence, events, 1.1, 1.0, MarketSafetyInputs())
        r2 = engine.evaluate("EURUSD", evidence, events, 1.1, 1.0, MarketSafetyInputs())
        self.assertEqual(r1, r2)

    def test_two_separate_engine_instances_agree(self):
        evidence = make_evidence_report("EURUSD")
        events = [NewsEvent("e1", "EUR", NewsCategory.ECB, NewsImpact.HIGH, T0 + timedelta(minutes=20), released=False)]
        engine_a = MarketIntelligenceEngine(make_config())
        engine_b = MarketIntelligenceEngine(make_config())
        r1 = engine_a.evaluate("EURUSD", evidence, events, 1.2, 1.0, MarketSafetyInputs())
        r2 = engine_b.evaluate("EURUSD", evidence, events, 1.2, 1.0, MarketSafetyInputs())
        self.assertEqual(r1, r2)

    def test_evaluate_batch_result_order_and_values_stable(self):
        engine = MarketIntelligenceEngine(make_config())
        pairs = {p: make_evidence_report(p) for p in ("EURUSD", "GBPUSD", "USDJPY")}
        spreads = {p: (1.0, 1.0) for p in pairs}
        r1 = engine.evaluate_batch(pairs, [], spreads, MarketSafetyInputs())
        r2 = engine.evaluate_batch(pairs, [], spreads, MarketSafetyInputs())
        self.assertEqual(r1, r2)


if __name__ == "__main__":
    unittest.main()
