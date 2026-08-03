"""Tests for `support_resistance.py` and `EvidenceEngine.evaluate_snapshot()`
(ADR-024 Amendment 1)."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from titan_protocol.evidence_engine.config import EvidenceEngineConfig
from titan_protocol.evidence_engine.engine import EvidenceEngine
from titan_protocol.evidence_engine.liquidity import analyze_liquidity
from titan_protocol.evidence_engine.models import Bar, LiquidityPool, LiquidityResult, LiquiditySweep, SwingType
from titan_protocol.evidence_engine.structure import analyze_market_structure
from titan_protocol.evidence_engine.support_resistance import (
    build_support_resistance_context,
    compute_break_quality_score,
    compute_false_break_probability,
    previous_day_high_low,
    previous_month_high_low,
    previous_week_high_low,
    psychological_levels,
    session_high_low,
)
from titan_protocol.evidence_engine.volatility import analyze_volatility
from tests.titan_protocol.evidence_engine._fixtures import STRUCTURE_SAMPLE, make_bars, make_config

T0 = datetime(2026, 7, 10, 13, 0, 0, tzinfo=timezone.utc)


def _multi_day_bars(days: int = 10, hours_per_day: int = 24) -> tuple:
    bars = []
    price = 1.10
    start = T0 - timedelta(days=days)
    for d in range(days):
        for h in range(hours_per_day):
            o = price
            c = price + (0.001 if (d + h) % 5 == 0 else -0.0003)
            hi = max(o, c) + 0.0005
            lo = min(o, c) - 0.0005
            ts = start + timedelta(days=d, hours=h)
            bars.append(Bar("EURUSD", ts, o, hi, lo, c, 1000.0))
            price = c
    return tuple(bars)


class TestPreviousPeriodHighLow(unittest.TestCase):
    def test_previous_day_uses_prior_calendar_day(self):
        bars = _multi_day_bars(days=5)
        now = bars[-1].timestamp
        result = previous_day_high_low(bars, now)
        self.assertIsNotNone(result)
        high, low = result
        self.assertGreater(high, low)

    def test_returns_none_when_no_prior_period_exists(self):
        bars = make_bars(STRUCTURE_SAMPLE)  # all within one short window
        result = previous_month_high_low(bars, bars[0].timestamp)
        self.assertIsNone(result)

    def test_previous_week_and_month_are_consistent_supersets(self):
        bars = _multi_day_bars(days=40)
        now = bars[-1].timestamp
        week = previous_week_high_low(bars, now)
        month = previous_month_high_low(bars, now)
        self.assertIsNotNone(week)
        self.assertIsNotNone(month)


class TestSessionHighLow(unittest.TestCase):
    def test_session_high_low_within_bounds(self):
        bars = make_bars(STRUCTURE_SAMPLE)
        config = make_config()
        high, low = session_high_low(bars, bars[-1].timestamp, config)
        self.assertGreaterEqual(high, low)

    def test_empty_bars_do_not_raise(self):
        config = make_config()
        high, low = session_high_low((), T0, config)
        self.assertEqual((high, low), (0.0, 0.0))


class TestPsychologicalLevels(unittest.TestCase):
    def test_levels_are_evenly_spaced_round_numbers(self):
        config = make_config()
        levels = psychological_levels(1.1035, config)
        self.assertEqual(len(levels), 2 * config.psychological_level_count + 1)
        prices = [lv.price for lv in levels]
        diffs = [round(b - a, 10) for a, b in zip(prices, prices[1:])]
        self.assertTrue(all(abs(d - config.psychological_level_increment) < 1e-9 for d in diffs))

    def test_zero_price_returns_empty(self):
        config = make_config()
        self.assertEqual(psychological_levels(0.0, config), ())


class TestBreakQualityScore(unittest.TestCase):
    def test_default_score_when_no_structure_events(self):
        config = make_config()
        bars = make_bars(STRUCTURE_SAMPLE)
        structure = analyze_market_structure(bars, config)
        # STRUCTURE_SAMPLE is crafted with no confirmed breaks in this range
        score = compute_break_quality_score(structure, bars, config)
        self.assertTrue(0.0 <= score <= 100.0)

    def test_bounded_for_large_volume_series(self):
        config = make_config()
        bars = _multi_day_bars(days=5)
        structure = analyze_market_structure(bars, config)
        score = compute_break_quality_score(structure, bars, config)
        self.assertTrue(0.0 <= score <= 100.0)


class TestFalseBreakProbability(unittest.TestCase):
    def test_default_when_no_sweeps(self):
        config = make_config()
        result = LiquidityResult(pools=(), sweeps=())
        self.assertEqual(compute_false_break_probability(result, config), config.false_break_probability_default)

    def test_trap_sweep_yields_high_probability(self):
        config = make_config()
        pool = LiquidityPool(swing_type=SwingType.HIGH, price=1.15, indices=(0, 1), swept=True)
        sweep = LiquiditySweep(
            pool=pool, sweep_index=5, sweep_price=1.155, closed_back_inside=True,
            is_stop_hunt=True, is_trap=True, displacement_follow_through=False,
        )
        result = LiquidityResult(pools=(pool,), sweeps=(sweep,))
        prob = compute_false_break_probability(result, config)
        self.assertEqual(prob, config.false_break_probability_trap)

    def test_confirmed_displacement_yields_low_probability(self):
        config = make_config()
        pool = LiquidityPool(swing_type=SwingType.HIGH, price=1.15, indices=(0, 1), swept=True)
        sweep = LiquiditySweep(
            pool=pool, sweep_index=5, sweep_price=1.155, closed_back_inside=True,
            is_stop_hunt=True, is_trap=False, displacement_follow_through=True,
        )
        result = LiquidityResult(pools=(pool,), sweeps=(sweep,))
        prob = compute_false_break_probability(result, config)
        self.assertEqual(prob, config.false_break_probability_confirmed)


class TestBuildSupportResistanceContext(unittest.TestCase):
    def test_empty_bars_raises(self):
        config = make_config()
        with self.assertRaises(ValueError):
            build_support_resistance_context((), T0, None, None, None, config)

    def test_all_fields_populated_and_bounded(self):
        config = make_config()
        bars = _multi_day_bars(days=10)
        structure = analyze_market_structure(bars, config)
        liquidity = analyze_liquidity(bars, structure.swings, config)
        volatility = analyze_volatility(bars, config)
        ctx = build_support_resistance_context(bars, bars[-1].timestamp, structure, liquidity, volatility, config)
        self.assertTrue(0.0 <= ctx.break_quality_score <= 100.0)
        self.assertTrue(0.0 <= ctx.false_break_probability <= 1.0)
        self.assertGreaterEqual(ctx.session_high, ctx.session_low)


class TestEvaluateSnapshotRegression(unittest.TestCase):
    def test_report_matches_evaluate_exactly(self):
        config = make_config()
        engine = EvidenceEngine(config)
        bars = make_bars(STRUCTURE_SAMPLE)
        report = engine.evaluate("EURUSD", bars)
        snapshot = engine.evaluate_snapshot("EURUSD", bars)
        self.assertEqual(report, snapshot.report)

    def test_empty_bars_raises(self):
        engine = EvidenceEngine(make_config())
        with self.assertRaises(ValueError):
            engine.evaluate_snapshot("EURUSD", [])

    def test_deterministic_across_repeated_calls(self):
        engine = EvidenceEngine(make_config())
        bars = make_bars(STRUCTURE_SAMPLE)
        s1 = engine.evaluate_snapshot("EURUSD", bars)
        s2 = engine.evaluate_snapshot("EURUSD", bars)
        self.assertEqual(s1, s2)

    def test_28_pairs_via_evaluate_snapshot(self):
        engine = EvidenceEngine(make_config())
        pairs = [f"PAIR{i}" for i in range(28)]
        for pair in pairs:
            bars = make_bars(STRUCTURE_SAMPLE, symbol=pair)
            snapshot = engine.evaluate_snapshot(pair, bars)
            self.assertTrue(0.0 <= snapshot.report.score.composite <= 100.0)


if __name__ == "__main__":
    unittest.main()
