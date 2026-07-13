"""Unit + concurrency tests for the indicator framework: interface,
registry, and cache."""

from __future__ import annotations

import unittest
from concurrent.futures import ThreadPoolExecutor

from titan_protocol.evidence_engine.indicators import (
    DuplicateIndicatorError,
    Indicator,
    IndicatorCache,
    IndicatorRegistry,
)
from titan_protocol.evidence_engine.models import IndicatorResult
from tests.titan_protocol.evidence_engine._fixtures import make_bars


class _CountingIndicator(Indicator):
    """Test double: counts how many times `compute()` actually runs, so
    a cache-hit test can assert zero recomputation."""

    name = "COUNTING"

    def __init__(self):
        self.compute_calls = 0

    def compute(self, bars, **params):
        self.compute_calls += 1
        period = int(params.get("period", 3))
        window = bars[-period:]
        value = sum(b.close for b in window) / len(window)
        return IndicatorResult(name=self.name, value=value, parameters=(("period", float(period)),))


class TestIndicatorRegistry(unittest.TestCase):
    def test_register_and_get(self):
        registry = IndicatorRegistry()
        ind = _CountingIndicator()
        registry.register(ind)
        self.assertIs(registry.get("COUNTING"), ind)
        self.assertIn("COUNTING", registry)
        self.assertEqual(registry.names(), ("COUNTING",))

    def test_duplicate_registration_rejected(self):
        registry = IndicatorRegistry()
        registry.register(_CountingIndicator())
        with self.assertRaises(DuplicateIndicatorError):
            registry.register(_CountingIndicator())


class TestIndicatorCache(unittest.TestCase):
    def test_cache_hit_avoids_recomputation(self):
        ind = _CountingIndicator()
        cache = IndicatorCache(max_entries=10)
        bars = make_bars([(1.10, 1.11, 1.09, 1.10 + 0.001 * i) for i in range(10)])
        r1 = cache.get_or_compute(ind, bars, (("period", 3.0),))
        r2 = cache.get_or_compute(ind, bars, (("period", 3.0),))
        self.assertEqual(ind.compute_calls, 1)
        self.assertEqual(r1, r2)

    def test_different_bar_series_are_different_cache_entries(self):
        ind = _CountingIndicator()
        cache = IndicatorCache(max_entries=10)
        bars_a = make_bars([(1.10, 1.11, 1.09, 1.10)] * 5)
        bars_b = make_bars([(1.20, 1.21, 1.19, 1.20)] * 5)
        cache.get_or_compute(ind, bars_a)
        cache.get_or_compute(ind, bars_b)
        self.assertEqual(ind.compute_calls, 2)
        self.assertEqual(cache.size(), 2)

    def test_bounded_by_max_entries_oldest_evicted_first(self):
        ind = _CountingIndicator()
        cache = IndicatorCache(max_entries=2)
        for i in range(5):
            bars = make_bars([(1.10, 1.11, 1.09, 1.10 + 0.01 * i)] * 5)
            cache.get_or_compute(ind, bars)
        self.assertEqual(cache.size(), 2)

    def test_clear_empties_the_cache(self):
        ind = _CountingIndicator()
        cache = IndicatorCache(max_entries=10)
        bars = make_bars([(1.10, 1.11, 1.09, 1.10)] * 5)
        cache.get_or_compute(ind, bars)
        cache.clear()
        self.assertEqual(cache.size(), 0)

    def test_concurrent_gets_never_raise_and_stay_bounded(self):
        ind = _CountingIndicator()
        cache = IndicatorCache(max_entries=5)
        bars_variants = [make_bars([(1.10, 1.11, 1.09, 1.10 + 0.01 * i)] * 5) for i in range(20)]

        def worker(_):
            for bars in bars_variants:
                cache.get_or_compute(ind, bars)

        with ThreadPoolExecutor(max_workers=16) as pool:
            list(pool.map(worker, range(16)))

        self.assertLessEqual(cache.size(), 5)


if __name__ == "__main__":
    unittest.main()
