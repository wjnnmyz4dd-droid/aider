"""Performance tests: 28+ pairs simultaneously, and thread-safety under
concurrent `evaluate()` calls against one shared engine instance."""

from __future__ import annotations

import random
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from phantom.evidence_engine.engine import EvidenceEngine
from phantom.evidence_engine.models import Bar
from tests.phantom.evidence_engine._fixtures import make_config

T0 = datetime(2026, 7, 10, tzinfo=timezone.utc)

# The task's own list names 28+ Forex pairs; used verbatim as the
# performance target rather than an arbitrary round number.
MAJOR_AND_CROSS_PAIRS = [
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD",
    "EURGBP", "EURJPY", "EURCHF", "EURCAD", "EURAUD", "EURNZD",
    "GBPJPY", "GBPCHF", "GBPCAD", "GBPAUD", "GBPNZD",
    "AUDJPY", "AUDCHF", "AUDCAD", "AUDNZD",
    "NZDJPY", "NZDCHF", "NZDCAD",
    "CADJPY", "CADCHF",
    "CHFJPY",
]


def _bars_for(symbol: str, count: int = 100) -> tuple:
    rng = random.Random(hash(symbol) & 0xFFFFFFFF)
    bars = []
    price = rng.uniform(0.8, 150.0)
    for i in range(count):
        o = price
        c = max(0.0001, price + rng.uniform(-price * 0.01, price * 0.01))
        h = max(o, c) + rng.uniform(0.0, price * 0.005)
        l = max(0.00001, min(o, c) - rng.uniform(0.0, price * 0.005))
        bars.append(Bar(symbol, T0 + timedelta(minutes=i), o, h, l, c, rng.uniform(1.0, 5000.0)))
        price = c
    return tuple(bars)


class TestBatchPerformance(unittest.TestCase):
    def test_28_plus_pairs_evaluated_in_one_batch_call(self):
        self.assertGreaterEqual(len(MAJOR_AND_CROSS_PAIRS), 28)
        engine = EvidenceEngine(make_config())
        pairs = {symbol: _bars_for(symbol) for symbol in MAJOR_AND_CROSS_PAIRS}

        start = time.perf_counter()
        ranking = engine.evaluate_batch(pairs)
        elapsed = time.perf_counter() - start

        self.assertEqual(len(ranking), len(MAJOR_AND_CROSS_PAIRS))
        # Generous bound (not a tight perf assertion, which would be
        # flaky under CI/sandbox load) -- this asserts "doesn't fall
        # over," not "meets a tight SLA."
        self.assertLess(elapsed, 10.0, f"28+ pair batch took {elapsed:.2f}s, expected well under 10s")


class TestConcurrentEvaluate(unittest.TestCase):
    def test_concurrent_evaluate_across_many_threads_no_errors_no_corruption(self):
        engine = EvidenceEngine(make_config())
        pairs = {symbol: _bars_for(symbol) for symbol in MAJOR_AND_CROSS_PAIRS}
        errors = []

        def worker(symbol):
            try:
                for _ in range(5):
                    report = engine.evaluate(symbol, pairs[symbol])
                    assert 0.0 <= report.score.composite <= 100.0
            except Exception as exc:  # noqa: BLE001 -- captured for the assertion below
                errors.append(repr(exc))

        with ThreadPoolExecutor(max_workers=len(pairs)) as pool:
            list(pool.map(worker, pairs.keys()))

        self.assertEqual(errors, [])

    def test_concurrent_evaluate_of_the_same_symbol_is_consistent(self):
        engine = EvidenceEngine(make_config())
        bars = _bars_for("EURUSD")
        results = []

        def worker(_):
            results.append(engine.evaluate("EURUSD", bars))

        with ThreadPoolExecutor(max_workers=16) as pool:
            list(pool.map(worker, range(64)))

        self.assertTrue(all(r == results[0] for r in results))


if __name__ == "__main__":
    unittest.main()
