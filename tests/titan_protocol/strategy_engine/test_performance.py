"""Performance and concurrency tests: 28+ pairs simultaneously, thread
safety under concurrent `evaluate()` calls."""

from __future__ import annotations

import time
import unittest
from concurrent.futures import ThreadPoolExecutor

from titan_protocol.strategy_engine.engine import StrategyEngine
from tests.titan_protocol.strategy_engine._fixtures import make_config, make_evidence_snapshot, make_mi_snapshot

PAIRS = [
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD",
    "EURGBP", "EURJPY", "EURCHF", "EURCAD", "EURAUD", "EURNZD",
    "GBPJPY", "GBPCHF", "GBPCAD", "GBPAUD", "GBPNZD",
    "AUDJPY", "AUDCHF", "AUDCAD", "AUDNZD",
    "NZDJPY", "NZDCHF", "NZDCAD",
    "CADJPY", "CADCHF",
    "CHFJPY",
]


class TestBatchPerformance(unittest.TestCase):
    def test_28_plus_pairs_evaluated_in_one_batch_call(self):
        self.assertGreaterEqual(len(PAIRS), 28)
        engine = StrategyEngine(make_config())
        pairs = {p: (make_evidence_snapshot(symbol=p), make_mi_snapshot(pair=p)) for p in PAIRS}

        start = time.perf_counter()
        results = engine.evaluate_batch(pairs)
        elapsed = time.perf_counter() - start

        self.assertEqual(len(results), len(PAIRS))
        self.assertLess(elapsed, 5.0, f"28+ pair batch took {elapsed:.2f}s")


class TestConcurrentEvaluate(unittest.TestCase):
    def test_concurrent_evaluate_across_many_threads_no_errors(self):
        engine = StrategyEngine(make_config())
        snapshots = {p: (make_evidence_snapshot(symbol=p), make_mi_snapshot(pair=p)) for p in PAIRS}
        errors = []

        def worker(pair):
            try:
                evidence, mi = snapshots[pair]
                for _ in range(5):
                    engine.evaluate(pair, evidence, mi)
            except Exception as exc:  # noqa: BLE001
                errors.append(repr(exc))

        with ThreadPoolExecutor(max_workers=len(PAIRS)) as pool:
            list(pool.map(worker, PAIRS))

        self.assertEqual(errors, [])

    def test_concurrent_evaluate_of_same_pair_is_consistent(self):
        engine = StrategyEngine(make_config())
        evidence = make_evidence_snapshot()
        mi = make_mi_snapshot()
        results = []

        def worker(_):
            results.append(engine.evaluate("EURUSD", evidence, mi))

        with ThreadPoolExecutor(max_workers=16) as pool:
            list(pool.map(worker, range(64)))

        self.assertTrue(all(r == results[0] for r in results))


if __name__ == "__main__":
    unittest.main()
