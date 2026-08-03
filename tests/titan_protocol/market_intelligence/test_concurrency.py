"""Concurrency tests: 28+ pairs simultaneously, concurrent evaluate()
against one shared engine, and concurrent peg/policy registry access."""

from __future__ import annotations

import unittest
from concurrent.futures import ThreadPoolExecutor

from titan_protocol.market_intelligence.engine import MarketIntelligenceEngine
from titan_protocol.market_intelligence.models import MarketSafetyInputs, PegPolicyEventType
from titan_protocol.market_intelligence.peg_policy import PegPolicyRegistry
from tests.titan_protocol.market_intelligence._fixtures import T0, make_config, make_evidence_report

PAIRS = [
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD",
    "EURGBP", "EURJPY", "EURCHF", "EURCAD", "EURAUD", "EURNZD",
    "GBPJPY", "GBPCHF", "GBPCAD", "GBPAUD", "GBPNZD",
    "AUDJPY", "AUDCHF", "AUDCAD", "AUDNZD",
    "NZDJPY", "NZDCHF", "NZDCAD",
    "CADJPY", "CADCHF",
    "CHFJPY",
]


class TestConcurrentEvaluate(unittest.TestCase):
    def test_28_plus_pairs_evaluated_concurrently_no_errors(self):
        self.assertGreaterEqual(len(PAIRS), 28)
        engine = MarketIntelligenceEngine(make_config())
        evidences = {pair: make_evidence_report(pair) for pair in PAIRS}
        errors = []

        def worker(pair):
            try:
                snapshot = engine.evaluate(pair, evidences[pair], [], 1.0, 1.0, MarketSafetyInputs())
                assert 0.0 <= snapshot.pair_safety.pair_safety_score <= 100.0
            except Exception as exc:  # noqa: BLE001
                errors.append(repr(exc))

        with ThreadPoolExecutor(max_workers=len(PAIRS)) as pool:
            list(pool.map(worker, PAIRS))

        self.assertEqual(errors, [])

    def test_concurrent_evaluate_of_same_pair_consistent(self):
        engine = MarketIntelligenceEngine(make_config())
        evidence = make_evidence_report("EURUSD")
        results = []

        def worker(_):
            results.append(engine.evaluate("EURUSD", evidence, [], 1.0, 1.0, MarketSafetyInputs()))

        with ThreadPoolExecutor(max_workers=16) as pool:
            list(pool.map(worker, range(64)))

        self.assertTrue(all(r == results[0] for r in results))


class TestConcurrentPegPolicyRegistry(unittest.TestCase):
    def test_concurrent_activate_and_status_reads_never_raise(self):
        registry = PegPolicyRegistry()
        errors = []

        def worker(i):
            try:
                pair = f"PAIR{i % 5}"
                registry.activate(pair, PegPolicyEventType.CURRENCY_PEG, "reason", T0)
                registry.status_for(pair)
                registry.clear(pair, T0)
            except Exception as exc:  # noqa: BLE001
                errors.append(repr(exc))

        with ThreadPoolExecutor(max_workers=32) as pool:
            list(pool.map(worker, range(200)))

        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
