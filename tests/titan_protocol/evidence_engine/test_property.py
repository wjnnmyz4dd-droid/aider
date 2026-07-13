"""Property tests: invariants that must hold across a wide range of
randomly generated synthetic inputs (stdlib `random`, seeded for
reproducibility -- this is test-input generation, not randomness inside
the engine itself, which remains fully deterministic per ADR-024 Hard
Rule 4)."""

from __future__ import annotations

import random
import unittest
from datetime import datetime, timedelta, timezone

from titan_protocol.evidence_engine.engine import EvidenceEngine
from titan_protocol.evidence_engine.models import Bar
from tests.titan_protocol.evidence_engine._fixtures import make_config

T0 = datetime(2026, 7, 10, tzinfo=timezone.utc)
SAMPLE_COUNT = 60


def _random_bars(seed: int, count: int, symbol: str = "EURUSD") -> tuple:
    rng = random.Random(seed)
    bars = []
    price = rng.uniform(0.5, 150.0)
    for i in range(count):
        o = price
        c = max(0.0001, price + rng.uniform(-price * 0.02, price * 0.02))
        h = max(o, c) + rng.uniform(0.0, price * 0.01)
        l = max(0.00001, min(o, c) - rng.uniform(0.0, price * 0.01))
        bars.append(Bar(symbol, T0 + timedelta(minutes=i), o, h, l, c, rng.uniform(1.0, 5000.0)))
        price = c
    return tuple(bars)


class TestScoreBoundsProperty(unittest.TestCase):
    def test_composite_score_always_bounded_0_100(self):
        engine = EvidenceEngine(make_config())
        for seed in range(SAMPLE_COUNT):
            bars = _random_bars(seed, 80)
            report = engine.evaluate("EURUSD", bars)
            self.assertTrue(0.0 <= report.score.composite <= 100.0, f"seed={seed}: {report.score.composite}")

    def test_every_component_score_always_bounded(self):
        engine = EvidenceEngine(make_config())
        for seed in range(SAMPLE_COUNT):
            bars = _random_bars(seed, 80)
            report = engine.evaluate("EURUSD", bars)
            for c in report.score.components:
                self.assertTrue(0.0 <= c.value <= 100.0, f"seed={seed} component={c.name} value={c.value}")
                self.assertTrue(0.0 <= c.weight <= 1.0)
                self.assertTrue(0.0 <= c.confidence <= 1.0)

    def test_weights_always_sum_to_one(self):
        engine = EvidenceEngine(make_config())
        bars = _random_bars(0, 50)
        report = engine.evaluate("EURUSD", bars)
        total_weight = sum(c.weight for c in report.score.components)
        self.assertAlmostEqual(total_weight, 1.0)

    def test_varying_bar_count_never_breaks_bounds(self):
        engine = EvidenceEngine(make_config())
        for count in (1, 2, 5, 10, 30, 100, 300):
            bars = _random_bars(count, count)
            report = engine.evaluate("EURUSD", bars)
            self.assertTrue(0.0 <= report.score.composite <= 100.0, f"count={count}")


class TestRankingProperty(unittest.TestCase):
    def test_ranking_is_always_sorted_descending(self):
        engine = EvidenceEngine(make_config())
        pairs = {f"PAIR{i}": _random_bars(i, 50, symbol=f"PAIR{i}") for i in range(30)}
        ranking = engine.evaluate_batch(pairs)
        scores = [r.score for r in ranking]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_ranking_assigns_contiguous_ranks_starting_at_1(self):
        engine = EvidenceEngine(make_config())
        pairs = {f"PAIR{i}": _random_bars(i, 50, symbol=f"PAIR{i}") for i in range(15)}
        ranking = engine.evaluate_batch(pairs)
        self.assertEqual([r.rank for r in ranking], list(range(1, len(ranking) + 1)))


if __name__ == "__main__":
    unittest.main()
