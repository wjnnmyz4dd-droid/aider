"""Boundary tests: single bar, exactly-at-lookback series, zero-range
bars, extreme prices."""

from __future__ import annotations

import unittest

from titan_protocol.evidence_engine.engine import EvidenceEngine
from titan_protocol.evidence_engine.liquidity import analyze_liquidity
from titan_protocol.evidence_engine.structure import analyze_market_structure, find_swing_points
from titan_protocol.evidence_engine.volatility import analyze_volatility
from tests.titan_protocol.evidence_engine._fixtures import make_bars, make_config


class TestSingleBar(unittest.TestCase):
    def test_engine_evaluate_handles_a_single_bar(self):
        engine = EvidenceEngine(make_config())
        bars = make_bars([(1.10, 1.11, 1.09, 1.105)])
        report = engine.evaluate("EURUSD", bars)
        self.assertTrue(0.0 <= report.score.composite <= 100.0)

    def test_structure_analysis_handles_a_single_bar(self):
        bars = make_bars([(1.10, 1.11, 1.09, 1.105)])
        result = analyze_market_structure(bars, make_config())
        self.assertEqual(result.swings, ())
        self.assertEqual(result.events, ())


class TestExactlyAtLookbackBoundary(unittest.TestCase):
    def test_series_exactly_2_times_lookback_plus_1_bars(self):
        config = make_config()
        n = 2 * config.swing_lookback + 1
        bars = make_bars([(1.10, 1.11 + 0.001 * i, 1.09, 1.10) for i in range(n)])
        swings = find_swing_points(bars, config.swing_lookback)
        # Must not raise, and any swing found must be within range.
        for s in swings:
            self.assertTrue(0 <= s.index < n)

    def test_series_one_shorter_than_boundary_produces_no_swings(self):
        config = make_config()
        n = 2 * config.swing_lookback
        bars = make_bars([(1.10, 1.11, 1.09, 1.10)] * n)
        self.assertEqual(find_swing_points(bars, config.swing_lookback), ())


class TestZeroRangeBars(unittest.TestCase):
    def test_flat_bars_never_divide_by_zero(self):
        # open == high == low == close on every bar -- every ratio
        # helper in candlesticks.py must guard range == 0.
        bars = make_bars([(1.10, 1.10, 1.10, 1.10)] * 10)
        engine = EvidenceEngine(make_config())
        report = engine.evaluate("EURUSD", bars)
        self.assertTrue(0.0 <= report.score.composite <= 100.0)

    def test_liquidity_analysis_handles_flat_bars(self):
        bars = make_bars([(1.10, 1.10, 1.10, 1.10)] * 10)
        config = make_config()
        swings = find_swing_points(bars, config.swing_lookback)
        result = analyze_liquidity(bars, swings, config)
        self.assertEqual(result.pools, ())

    def test_volatility_of_flat_bars_is_zero_score_region(self):
        bars = make_bars([(1.10, 1.10, 1.10, 1.10)] * 20)
        state = analyze_volatility(bars, make_config())
        self.assertEqual(state.atr, 0.0)


class TestExtremePrices(unittest.TestCase):
    def test_very_large_prices_do_not_overflow_or_raise(self):
        bars = make_bars([(1_000_000.0, 1_000_050.0, 999_950.0, 1_000_010.0)] * 10)
        engine = EvidenceEngine(make_config())
        report = engine.evaluate("XAUUSD", bars)
        self.assertTrue(0.0 <= report.score.composite <= 100.0)

    def test_very_small_prices_do_not_raise(self):
        bars = make_bars([(0.00001, 0.000012, 0.000009, 0.000011)] * 10)
        engine = EvidenceEngine(make_config())
        report = engine.evaluate("SHIBUSD", bars)
        self.assertTrue(0.0 <= report.score.composite <= 100.0)


if __name__ == "__main__":
    unittest.main()
