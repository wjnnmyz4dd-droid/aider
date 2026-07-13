"""Unit tests for candlestick pattern recognition -- one crafted case
per pattern (21 patterns total: 6 single, 7 two-candle, 8 three-candle)."""

from __future__ import annotations

import unittest

from titan_protocol.evidence_engine.candlesticks import recognize_patterns
from titan_protocol.evidence_engine.models import CandlestickPattern, PatternContext
from tests.titan_protocol.evidence_engine._fixtures import make_bars, make_config


def _patterns_at(bars, config, contexts=None):
    matches = recognize_patterns(bars, config, contexts)
    return {m.pattern for m in matches}


class TestSingleCandlePatterns(unittest.TestCase):
    def setUp(self):
        self.config = make_config()

    def test_doji(self):
        bars = make_bars([(1.10, 1.102, 1.098, 1.1001)])
        self.assertIn(CandlestickPattern.DOJI, _patterns_at(bars, self.config))

    def test_marubozu(self):
        bars = make_bars([(1.10, 1.12, 1.10, 1.12)])
        self.assertIn(CandlestickPattern.MARUBOZU, _patterns_at(bars, self.config))

    def test_hammer_at_downtrend_extreme(self):
        bars = make_bars([(1.105, 1.11, 1.08, 1.108)])
        patterns = _patterns_at(bars, self.config, [PatternContext.AT_DOWNTREND_EXTREME])
        self.assertIn(CandlestickPattern.HAMMER, patterns)

    def test_hanging_man_at_uptrend_extreme(self):
        # Same shape as a Hammer, but context is at an uptrend extreme.
        bars = make_bars([(1.105, 1.11, 1.08, 1.108)])
        patterns = _patterns_at(bars, self.config, [PatternContext.AT_UPTREND_EXTREME])
        self.assertIn(CandlestickPattern.HANGING_MAN, patterns)

    def test_shooting_star(self):
        bars = make_bars([(1.10, 1.13, 1.098, 1.102)])
        self.assertIn(CandlestickPattern.SHOOTING_STAR, _patterns_at(bars, self.config))

    def test_spinning_top(self):
        # body_ratio=0.2 (between doji's 0.1 and small-body's 0.3
        # thresholds), with two significant, roughly balanced wicks.
        bars = make_bars([(1.10, 1.115, 1.085, 1.106)])
        self.assertIn(CandlestickPattern.SPINNING_TOP, _patterns_at(bars, self.config))


class TestTwoCandlePatterns(unittest.TestCase):
    def setUp(self):
        self.config = make_config()

    def test_bullish_engulfing(self):
        bars = make_bars([(1.12, 1.125, 1.10, 1.105), (1.10, 1.14, 1.095, 1.13)])
        self.assertIn(CandlestickPattern.BULLISH_ENGULFING, _patterns_at(bars, self.config))

    def test_bearish_engulfing(self):
        bars = make_bars([(1.10, 1.125, 1.098, 1.12), (1.125, 1.13, 1.09, 1.10)])
        self.assertIn(CandlestickPattern.BEARISH_ENGULFING, _patterns_at(bars, self.config))

    def test_harami(self):
        bars = make_bars([(1.20, 1.205, 1.10, 1.105), (1.15, 1.155, 1.145, 1.15)])
        self.assertIn(CandlestickPattern.HARAMI, _patterns_at(bars, self.config))

    def test_piercing_pattern(self):
        bars = make_bars([(1.20, 1.205, 1.10, 1.105), (1.09, 1.16, 1.085, 1.16)])
        self.assertIn(CandlestickPattern.PIERCING_PATTERN, _patterns_at(bars, self.config))

    def test_dark_cloud_cover(self):
        bars = make_bars([(1.10, 1.205, 1.095, 1.20), (1.21, 1.215, 1.14, 1.14)])
        self.assertIn(CandlestickPattern.DARK_CLOUD_COVER, _patterns_at(bars, self.config))

    def test_tweezer_top(self):
        bars = make_bars([(1.10, 1.15, 1.09, 1.145), (1.145, 1.1502, 1.10, 1.105)])
        self.assertIn(CandlestickPattern.TWEEZER_TOP, _patterns_at(bars, self.config))

    def test_tweezer_bottom(self):
        bars = make_bars([(1.15, 1.16, 1.10, 1.105), (1.105, 1.15, 1.0998, 1.145)])
        self.assertIn(CandlestickPattern.TWEEZER_BOTTOM, _patterns_at(bars, self.config))


class TestThreeCandlePatterns(unittest.TestCase):
    def setUp(self):
        self.config = make_config()

    def test_morning_star(self):
        bars = make_bars([
            (1.20, 1.205, 1.10, 1.105),
            (1.09, 1.095, 1.08, 1.088),
            (1.09, 1.20, 1.085, 1.19),
        ])
        self.assertIn(CandlestickPattern.MORNING_STAR, _patterns_at(bars, self.config))

    def test_evening_star(self):
        bars = make_bars([
            (1.10, 1.205, 1.095, 1.20),
            (1.21, 1.215, 1.205, 1.212),
            (1.21, 1.215, 1.10, 1.11),
        ])
        self.assertIn(CandlestickPattern.EVENING_STAR, _patterns_at(bars, self.config))

    def test_three_white_soldiers(self):
        bars = make_bars([
            (1.10, 1.125, 1.098, 1.12),
            (1.12, 1.145, 1.118, 1.14),
            (1.14, 1.165, 1.138, 1.16),
        ])
        self.assertIn(CandlestickPattern.THREE_WHITE_SOLDIERS, _patterns_at(bars, self.config))

    def test_three_black_crows(self):
        bars = make_bars([
            (1.20, 1.202, 1.175, 1.18),
            (1.18, 1.182, 1.155, 1.16),
            (1.16, 1.162, 1.135, 1.14),
        ])
        self.assertIn(CandlestickPattern.THREE_BLACK_CROWS, _patterns_at(bars, self.config))

    def test_three_inside_up(self):
        bars = make_bars([
            (1.20, 1.205, 1.10, 1.105),
            (1.15, 1.155, 1.145, 1.15),
            (1.15, 1.21, 1.145, 1.205),  # closes above a.open (1.20)
        ])
        self.assertIn(CandlestickPattern.THREE_INSIDE_UP, _patterns_at(bars, self.config))

    def test_three_inside_down(self):
        bars = make_bars([
            (1.10, 1.205, 1.095, 1.20),
            (1.15, 1.155, 1.145, 1.15),
            (1.15, 1.155, 1.09, 1.095),  # closes below a.open (1.10)
        ])
        self.assertIn(CandlestickPattern.THREE_INSIDE_DOWN, _patterns_at(bars, self.config))

    def test_three_outside_up(self):
        bars = make_bars([
            (1.12, 1.125, 1.10, 1.105),
            (1.10, 1.14, 1.095, 1.13),   # bullish engulfing of bar a
            (1.13, 1.16, 1.125, 1.155),  # closes above bar b's close
        ])
        self.assertIn(CandlestickPattern.THREE_OUTSIDE_UP, _patterns_at(bars, self.config))

    def test_three_outside_down(self):
        bars = make_bars([
            (1.10, 1.125, 1.098, 1.12),
            (1.125, 1.13, 1.09, 1.10),   # bearish engulfing of bar a
            (1.10, 1.105, 1.07, 1.075),  # closes below bar b's close
        ])
        self.assertIn(CandlestickPattern.THREE_OUTSIDE_DOWN, _patterns_at(bars, self.config))


class TestRecognizePatternsGeneral(unittest.TestCase):
    def test_every_match_has_reason_quality_context_confidence(self):
        bars = make_bars([
            (1.20, 1.205, 1.10, 1.105),
            (1.09, 1.095, 1.08, 1.088),
            (1.09, 1.20, 1.085, 1.19),
        ])
        matches = recognize_patterns(bars, make_config())
        self.assertTrue(matches)
        for m in matches:
            self.assertTrue(0.0 <= m.quality <= 1.0)
            self.assertTrue(0.0 <= m.confidence <= 1.0)
            self.assertIsInstance(m.context, PatternContext)

    def test_no_patterns_on_empty_series(self):
        self.assertEqual(recognize_patterns((), make_config()), ())


if __name__ == "__main__":
    unittest.main()
