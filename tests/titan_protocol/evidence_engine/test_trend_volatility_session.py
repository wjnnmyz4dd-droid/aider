"""Unit tests for trend classification, volatility, and session
awareness."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from titan_protocol.evidence_engine.models import (
    MarketStructureResult,
    SessionName,
    StructureDirection,
    StructureEvent,
    StructureEventType,
    SwingPoint,
    SwingType,
    TrendClassification,
    VolatilityState,
)
from titan_protocol.evidence_engine.session import analyze_session, session_for_hour
from titan_protocol.evidence_engine.trend import classify_trend
from titan_protocol.evidence_engine.volatility import analyze_volatility, atr, atr_series, true_ranges
from tests.titan_protocol.evidence_engine._fixtures import make_bars, make_config

T0 = datetime(2026, 7, 10, tzinfo=timezone.utc)


def _swing(price):
    return SwingPoint(SwingType.HIGH, 0, T0, price)


class TestTrendClassificationPriority(unittest.TestCase):
    def test_recent_choch_overrides_everything_else(self):
        structure = MarketStructureResult(
            swings=(), trend=TrendClassification.TRENDING_UP,
            events=(StructureEvent(StructureEventType.CHOCH, StructureDirection.BEARISH, _swing(1.1), 5, 1.09),),
            support_levels=(), resistance_levels=(),
        )
        volatility = VolatilityState(atr=0.01, is_expansion=True, is_compression=False, volatility_score=80.0)
        self.assertEqual(classify_trend(structure, volatility, make_config()), TrendClassification.REVERSAL)

    def test_compression_flag_wins_over_structural_trend(self):
        structure = MarketStructureResult(
            swings=(), trend=TrendClassification.TRENDING_UP, events=(), support_levels=(), resistance_levels=(),
        )
        volatility = VolatilityState(atr=0.01, is_expansion=False, is_compression=True, volatility_score=10.0)
        self.assertEqual(classify_trend(structure, volatility, make_config()), TrendClassification.COMPRESSION)

    def test_expansion_flag_wins_over_range(self):
        structure = MarketStructureResult(
            swings=(), trend=TrendClassification.RANGE, events=(), support_levels=(), resistance_levels=(),
        )
        volatility = VolatilityState(atr=0.05, is_expansion=True, is_compression=False, volatility_score=90.0)
        self.assertEqual(classify_trend(structure, volatility, make_config()), TrendClassification.EXPANSION)

    def test_falls_back_to_structural_trend(self):
        structure = MarketStructureResult(
            swings=(), trend=TrendClassification.TRENDING_DOWN, events=(), support_levels=(), resistance_levels=(),
        )
        volatility = VolatilityState(atr=0.02, is_expansion=False, is_compression=False, volatility_score=50.0)
        self.assertEqual(classify_trend(structure, volatility, make_config()), TrendClassification.TRENDING_DOWN)


class TestVolatility(unittest.TestCase):
    def test_true_range_uses_prior_close_gap(self):
        bars = make_bars([(1.10, 1.11, 1.09, 1.105), (1.20, 1.21, 1.19, 1.205)])
        ranges = true_ranges(bars)
        # bar1 gapped up from prior close 1.105 -- true range must
        # capture the gap, not just bar1's own high-low.
        self.assertAlmostEqual(ranges[1], max(1.21 - 1.19, abs(1.21 - 1.105), abs(1.19 - 1.105)))

    def test_atr_of_empty_series_is_zero(self):
        self.assertEqual(atr((), 14), 0.0)

    def test_expansion_flagged_when_atr_ratio_high(self):
        # Long flat run establishes a low baseline ATR, then one huge
        # bar spikes current ATR well above the expansion ratio.
        flat = [(1.10, 1.101, 1.099, 1.10)] * 20
        bars = make_bars(flat + [(1.10, 1.30, 1.05, 1.28)])
        config = make_config()
        state = analyze_volatility(bars, config)
        self.assertTrue(state.is_expansion)
        self.assertFalse(state.is_compression)

    def test_compression_flagged_when_atr_ratio_low(self):
        wide = [(1.10, 1.15, 1.05, 1.12)] * 5
        flat = [(1.10, 1.101, 1.099, 1.10)] * 10
        bars = make_bars(wide + flat)
        config = make_config(atr_period=15)
        state = analyze_volatility(bars, config)
        self.assertTrue(state.is_compression)

    def test_volatility_score_bounded(self):
        bars = make_bars([(1.10, 1.50, 0.80, 1.30)] * 5)
        state = analyze_volatility(bars, make_config())
        self.assertTrue(0.0 <= state.volatility_score <= 100.0)


class TestSession(unittest.TestCase):
    def test_session_for_hour_precedence(self):
        config = make_config()
        self.assertEqual(session_for_hour(13, config), SessionName.LONDON_NEW_YORK_OVERLAP)
        self.assertEqual(session_for_hour(9, config), SessionName.LONDON)
        self.assertEqual(session_for_hour(2, config), SessionName.ASIAN)
        self.assertEqual(session_for_hour(17, config), SessionName.EARLY_NEW_YORK)
        self.assertEqual(session_for_hour(19, config), SessionName.LATE_NEW_YORK)
        self.assertEqual(session_for_hour(22, config), SessionName.CLOSED)

    def test_overlap_has_highest_quality_score(self):
        config = make_config()
        overlap = analyze_session(T0.replace(hour=13), config)
        asian = analyze_session(T0.replace(hour=2), config)
        self.assertGreater(overlap.quality_score, asian.quality_score)

    def test_quality_score_bounded(self):
        config = make_config()
        for hour in range(24):
            state = analyze_session(T0.replace(hour=hour), config)
            self.assertTrue(0.0 <= state.quality_score <= 100.0)


if __name__ == "__main__":
    unittest.main()
