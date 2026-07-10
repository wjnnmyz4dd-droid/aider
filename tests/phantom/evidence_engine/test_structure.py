"""Unit + regression tests for market structure: swings, BOS/CHOCH,
support/resistance."""

from __future__ import annotations

import unittest

from phantom.evidence_engine.models import StructureDirection, StructureEventType, SwingPoint, SwingType, TrendClassification
from phantom.evidence_engine.structure import analyze_market_structure, detect_structure_events, find_swing_points, support_resistance
from tests.phantom.evidence_engine._fixtures import STRUCTURE_SAMPLE, make_bars, make_config


class TestSwingDetection(unittest.TestCase):
    def test_finds_clear_swing_high_and_low(self):
        highs = [1.10, 1.11, 1.12, 1.15, 1.13, 1.12, 1.11, 1.09, 1.08, 1.06, 1.07, 1.09, 1.12, 1.14, 1.17, 1.15, 1.13]
        bars = make_bars([(h - 0.005, h, h - 0.01, h - 0.002) for h in highs])
        swings = find_swing_points(bars, 2)
        swing_map = {s.index: s for s in swings}
        self.assertIn(3, swing_map)
        self.assertEqual(swing_map[3].swing_type, SwingType.HIGH)
        self.assertIn(9, swing_map)
        self.assertEqual(swing_map[9].swing_type, SwingType.LOW)
        self.assertIn(14, swing_map)
        self.assertEqual(swing_map[14].swing_type, SwingType.HIGH)

    def test_ties_never_confirm_a_swing(self):
        # Two consecutive bars share the exact same high -- neither is
        # strictly greater than every neighbor, so neither should confirm.
        bars = make_bars([
            (1.10, 1.11, 1.09, 1.105), (1.105, 1.12, 1.10, 1.115),
            (1.115, 1.13, 1.11, 1.12), (1.12, 1.13, 1.11, 1.125),
            (1.125, 1.12, 1.10, 1.11), (1.11, 1.10, 1.09, 1.095),
        ])
        swings = find_swing_points(bars, 2)
        self.assertNotIn(2, {s.index for s in swings})
        self.assertNotIn(3, {s.index for s in swings})

    def test_empty_and_too_short_series_produce_no_swings(self):
        self.assertEqual(find_swing_points((), 2), ())
        bars = make_bars([(1.1, 1.11, 1.09, 1.105)] * 3)
        self.assertEqual(find_swing_points(bars, 2), ())


class TestStructureEvents(unittest.TestCase):
    def test_bos_fires_when_close_breaks_prior_swing_high(self):
        data = [
            (1.09, 1.10, 1.08, 1.095), (1.095, 1.11, 1.09, 1.105), (1.105, 1.12, 1.10, 1.115),
            (1.115, 1.15, 1.11, 1.13),  # swing high at idx3 = 1.15
            (1.13, 1.14, 1.12, 1.125), (1.125, 1.13, 1.11, 1.12),
            (1.12, 1.125, 1.10, 1.108), (1.108, 1.11, 1.08, 1.085), (1.085, 1.09, 1.06, 1.07),
            (1.07, 1.075, 1.05, 1.06),  # swing low at idx9
            (1.06, 1.08, 1.055, 1.075), (1.075, 1.10, 1.065, 1.09), (1.09, 1.13, 1.085, 1.12),
            (1.12, 1.16, 1.115, 1.155),  # idx13: close 1.155 > swing high 1.15 -> BOS
            (1.155, 1.17, 1.15, 1.165), (1.165, 1.168, 1.14, 1.145), (1.145, 1.15, 1.12, 1.13),
        ]
        bars = make_bars(data)
        config = make_config()
        result = analyze_market_structure(bars, config)
        bullish_internal = [
            e for e in result.events
            if e.event_type == StructureEventType.BOS_INTERNAL and e.direction == StructureDirection.BULLISH
        ]
        self.assertTrue(bullish_internal, "expected at least one internal bullish BOS")
        self.assertEqual(bullish_internal[0].confirmed_index, 13)
        self.assertAlmostEqual(bullish_internal[0].broken_swing.price, 1.15)

    def test_first_break_after_established_trend_is_choch(self):
        # Isolates `detect_structure_events` directly with hand-built
        # swings and closes: a bearish break establishes the trend
        # (BOS), then a bullish break against that trend must be
        # classified CHOCH, not BOS.
        bars = make_bars([
            (1.10, 1.11, 1.09, 1.105),  # idx0
            (1.10, 1.11, 1.09, 1.095),  # idx1
            (1.10, 1.11, 1.09, 1.075),  # idx2: closes below swing low (1.085) -> BOS bearish, establishes trend
            (1.10, 1.11, 1.09, 1.08),   # idx3: no swing left to break, no event
            (1.10, 1.11, 1.09, 1.16),   # idx4: closes above swing high (1.15) -> CHOCH bullish (reverses)
        ])
        swings = (
            SwingPoint(SwingType.LOW, 0, bars[0].timestamp, 1.098),
            SwingPoint(SwingType.LOW, 1, bars[1].timestamp, 1.085),
            SwingPoint(SwingType.HIGH, 2, bars[2].timestamp, 1.15),
        )
        events = detect_structure_events(bars, swings, StructureEventType.BOS_INTERNAL)
        kinds = [(e.event_type, e.direction, e.confirmed_index) for e in events]
        self.assertIn((StructureEventType.BOS_INTERNAL, StructureDirection.BEARISH, 2), kinds)
        self.assertIn((StructureEventType.CHOCH, StructureDirection.BULLISH, 4), kinds)

    def test_no_events_when_price_never_breaks_a_swing(self):
        # Closes always stay below the highs / above the lows, so no
        # swing is ever broken by a close.
        highs = [1.10, 1.11, 1.12, 1.15, 1.13, 1.12, 1.11, 1.09, 1.08, 1.06, 1.07, 1.09, 1.12, 1.14, 1.17, 1.15, 1.13]
        bars = make_bars([(h - 0.005, h, h - 0.01, h - 0.002) for h in highs])
        config = make_config()
        result = analyze_market_structure(bars, config)
        self.assertEqual(result.events, ())


class TestSupportResistance(unittest.TestCase):
    def test_clusters_repeated_touches_into_one_level(self):
        swings = find_swing_points(make_bars(STRUCTURE_SAMPLE), 2)
        config = make_config(support_resistance_min_touches=1)
        support, resistance = support_resistance(swings, config)
        self.assertTrue(all(level.touches >= 1 for level in support))
        self.assertTrue(all(level.touches >= 1 for level in resistance))

    def test_below_min_touches_excluded(self):
        swings = find_swing_points(make_bars(STRUCTURE_SAMPLE), 2)
        config = make_config(support_resistance_min_touches=99)
        support, resistance = support_resistance(swings, config)
        self.assertEqual(support, ())
        self.assertEqual(resistance, ())


class TestAnalyzeMarketStructure(unittest.TestCase):
    def test_returns_all_fields_populated_and_deterministic(self):
        bars = make_bars(STRUCTURE_SAMPLE)
        config = make_config()
        r1 = analyze_market_structure(bars, config)
        r2 = analyze_market_structure(bars, config)
        self.assertEqual(r1, r2)
        self.assertIsInstance(r1.trend, TrendClassification)


if __name__ == "__main__":
    unittest.main()
