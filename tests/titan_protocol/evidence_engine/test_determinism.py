"""Determinism tests: same input always produces the same output,
across every layer and across randomized synthetic inputs."""

from __future__ import annotations

import random
import unittest
from datetime import datetime, timedelta, timezone

from titan_protocol.evidence_engine.engine import EvidenceEngine
from titan_protocol.evidence_engine.models import Bar
from tests.titan_protocol.evidence_engine._fixtures import STRUCTURE_SAMPLE, make_bars, make_config

T0 = datetime(2026, 7, 10, 13, 0, 0, tzinfo=timezone.utc)


def _random_bars(seed: int, count: int) -> tuple:
    rng = random.Random(seed)
    bars = []
    price = 1.10
    for i in range(count):
        o = price
        c = price + rng.uniform(-0.01, 0.01)
        h = max(o, c) + rng.uniform(0.0, 0.005)
        l = min(o, c) - rng.uniform(0.0, 0.005)
        bars.append(Bar("EURUSD", T0 + timedelta(minutes=i), o, h, l, c, 1000.0))
        price = c
    return tuple(bars)


class TestDeterminism(unittest.TestCase):
    def test_repeated_evaluate_calls_produce_identical_reports(self):
        engine = EvidenceEngine(make_config())
        bars = make_bars(STRUCTURE_SAMPLE)
        r1 = engine.evaluate("EURUSD", bars)
        r2 = engine.evaluate("EURUSD", bars)
        self.assertEqual(r1, r2)

    def test_two_separate_engine_instances_agree(self):
        bars = make_bars(STRUCTURE_SAMPLE)
        engine_a = EvidenceEngine(make_config())
        engine_b = EvidenceEngine(make_config())
        self.assertEqual(engine_a.evaluate("EURUSD", bars), engine_b.evaluate("EURUSD", bars))

    def test_determinism_across_50_randomized_synthetic_series(self):
        config = make_config()
        for seed in range(50):
            bars = _random_bars(seed, 60)
            engine_a = EvidenceEngine(config)
            engine_b = EvidenceEngine(config)
            r1 = engine_a.evaluate("EURUSD", bars)
            r2 = engine_b.evaluate("EURUSD", bars)
            self.assertEqual(r1, r2, f"mismatch for seed={seed}")

    def test_evaluate_batch_ranking_order_is_stable_across_calls(self):
        engine = EvidenceEngine(make_config())
        pairs = {f"PAIR{i}": _random_bars(i, 40) for i in range(10)}
        r1 = engine.evaluate_batch(pairs)
        r2 = engine.evaluate_batch(pairs)
        self.assertEqual(r1, r2)


if __name__ == "__main__":
    unittest.main()
