"""Unit, boundary, negative, model-integrity, and snapshot tests for the
opening range computation (ADR-035 §3, Phase 0 -- ADR-024 Amendment 2)."""

from __future__ import annotations

import ast
import unittest
from dataclasses import FrozenInstanceError
from datetime import timedelta
from pathlib import Path

from titan_protocol.evidence_engine.config import EvidenceEngineConfig
from titan_protocol.evidence_engine.engine import EvidenceEngine
from titan_protocol.evidence_engine.models import OpeningRangeState, SessionName
from titan_protocol.evidence_engine.opening_range import compute_opening_ranges
from tests.titan_protocol.evidence_engine._fixtures import T0, make_bar, make_config

ANCHOR_HOUR, ANCHOR_MINUTE = T0.hour, T0.minute  # 13:00, matches T0's own "overlap hour"
BASE = T0.replace(minute=0)


def _bars_at(offsets_minutes, highs, lows, start=BASE):
    return tuple(
        make_bar(h - 0.01, h, l, h - 0.005, timestamp=start + timedelta(minutes=offset))
        for offset, h, l in zip(offsets_minutes, highs, lows)
    )


class TestRangeCalculation(unittest.TestCase):
    def test_high_low_midpoint_and_indices_from_included_bars_only(self):
        # 7 bars at 0,5,10,15,20,25,30 minutes; the 30-minute bar sits
        # exactly at range_end and must be excluded (half-open window).
        bars = _bars_at(
            [0, 5, 10, 15, 20, 25, 30],
            highs=[1.10, 1.12, 1.11, 1.15, 1.10, 1.09, 1.30],
            lows=[1.05, 1.04, 1.06, 1.03, 1.05, 1.02, 0.50],
        )
        config = make_config(
            opening_range_anchors=((SessionName.LONDON_NEW_YORK_OVERLAP, ANCHOR_HOUR, ANCHOR_MINUTE),),
            opening_range_duration_minutes=30,
            opening_range_min_bars=3,
            expected_bar_interval_seconds=600,
        )
        now = BASE + timedelta(minutes=30)
        ranges = compute_opening_ranges(bars, now, config)
        self.assertEqual(len(ranges), 1)
        state = ranges[0]
        self.assertEqual(state.range_start_index, 0)
        self.assertEqual(state.range_end_index, 6)
        self.assertAlmostEqual(state.range_high, 1.15)
        self.assertAlmostEqual(state.range_low, 1.02)
        self.assertAlmostEqual(state.range_midpoint, (1.15 + 1.02) / 2.0)
        self.assertTrue(state.is_formed)
        self.assertTrue(state.is_valid)

    def test_indices_are_offset_when_range_does_not_start_at_bars_index_zero(self):
        # 3 bars strictly before range_start, 4 inside [start, end), 2 after.
        before = _bars_at([-15, -10, -5], highs=[1.0, 1.0, 1.0], lows=[0.9, 0.9, 0.9])
        inside = _bars_at([0, 5, 10, 15], highs=[1.1, 1.1, 1.1, 1.1], lows=[0.95, 0.95, 0.95, 0.95])
        after = _bars_at([30, 35], highs=[2.0, 2.0], lows=[0.1, 0.1])
        bars = before + inside + after
        config = make_config(
            opening_range_anchors=((SessionName.LONDON_NEW_YORK_OVERLAP, ANCHOR_HOUR, ANCHOR_MINUTE),),
            opening_range_duration_minutes=20,
            opening_range_min_bars=2,
            expected_bar_interval_seconds=600,
        )
        now = BASE + timedelta(minutes=35)
        ranges = compute_opening_ranges(bars, now, config)
        self.assertEqual(len(ranges), 1)
        state = ranges[0]
        self.assertEqual(state.range_start_index, 3)
        self.assertEqual(state.range_end_index, 7)


class TestIsFormedTransitions(unittest.TestCase):
    def _range_for(self, now):
        bars = _bars_at([0, 5, 10], highs=[1.1, 1.1, 1.1], lows=[1.0, 1.0, 1.0])
        config = make_config(
            opening_range_anchors=((SessionName.LONDON_NEW_YORK_OVERLAP, ANCHOR_HOUR, ANCHOR_MINUTE),),
            opening_range_duration_minutes=30,
            opening_range_min_bars=1,
            expected_bar_interval_seconds=600,
        )
        ranges = compute_opening_ranges(bars, now, config)
        return ranges[0] if ranges else None

    def test_not_formed_before_range_end(self):
        state = self._range_for(BASE + timedelta(minutes=29))
        self.assertFalse(state.is_formed)

    def test_formed_exactly_at_range_end(self):
        state = self._range_for(BASE + timedelta(minutes=30))
        self.assertTrue(state.is_formed)

    def test_formed_after_range_end(self):
        state = self._range_for(BASE + timedelta(minutes=45))
        self.assertTrue(state.is_formed)


class TestSessionIsDescriptiveOnly(unittest.TestCase):
    def test_two_anchors_sharing_a_session_name_produce_two_distinct_ranges(self):
        config = make_config(
            opening_range_anchors=(
                (SessionName.LONDON, 7, 0),
                (SessionName.LONDON, 9, 0),
            ),
            opening_range_duration_minutes=30,
            opening_range_min_bars=3,
            expected_bar_interval_seconds=600,
        )
        start = BASE.replace(hour=7, minute=0)
        now = start + timedelta(minutes=150)
        bars = tuple(
            make_bar(1.1, 1.11, 1.09, 1.105, timestamp=start + timedelta(minutes=5 * i))
            for i in range(31)
        )
        ranges = compute_opening_ranges(bars, now, config)
        self.assertEqual(len(ranges), 2)
        self.assertEqual(ranges[0].session, SessionName.LONDON)
        self.assertEqual(ranges[1].session, SessionName.LONDON)
        self.assertNotEqual(ranges[0].range_start, ranges[1].range_start)
        self.assertTrue(ranges[0].is_valid)
        self.assertTrue(ranges[1].is_valid)


class TestBoundaryConditions(unittest.TestCase):
    def test_exactly_minimum_bar_count_is_valid(self):
        bars = _bars_at([0, 10, 20], highs=[1.1, 1.1, 1.1], lows=[1.0, 1.0, 1.0])
        config = make_config(
            opening_range_anchors=((SessionName.LONDON_NEW_YORK_OVERLAP, ANCHOR_HOUR, ANCHOR_MINUTE),),
            opening_range_duration_minutes=30,
            opening_range_min_bars=3,
            expected_bar_interval_seconds=3600,  # large -- isolates the count check from the gap check
        )
        now = BASE + timedelta(minutes=30)
        state = compute_opening_ranges(bars, now, config)[0]
        self.assertTrue(state.is_valid)

    def test_one_fewer_than_minimum_bar_count_is_invalid(self):
        bars = _bars_at([0, 25], highs=[1.1, 1.1], lows=[1.0, 1.0])
        config = make_config(
            opening_range_anchors=((SessionName.LONDON_NEW_YORK_OVERLAP, ANCHOR_HOUR, ANCHOR_MINUTE),),
            opening_range_duration_minutes=30,
            opening_range_min_bars=3,
            expected_bar_interval_seconds=3600,  # large -- isolates the count check from the gap check
        )
        now = BASE + timedelta(minutes=30)
        state = compute_opening_ranges(bars, now, config)[0]
        self.assertFalse(state.is_valid)

    def test_gap_exactly_at_threshold_is_not_a_gap(self):
        bars = (
            make_bar(1.1, 1.11, 1.09, 1.105, timestamp=BASE),
            make_bar(1.1, 1.11, 1.09, 1.105, timestamp=BASE + timedelta(seconds=300)),
        )
        config = make_config(
            opening_range_anchors=((SessionName.LONDON_NEW_YORK_OVERLAP, ANCHOR_HOUR, ANCHOR_MINUTE),),
            opening_range_duration_minutes=30,
            opening_range_min_bars=2,
            expected_bar_interval_seconds=300,
        )
        now = BASE + timedelta(minutes=30)
        state = compute_opening_ranges(bars, now, config)[0]
        self.assertTrue(state.is_valid)

    def test_gap_one_second_beyond_threshold_is_a_gap(self):
        bars = (
            make_bar(1.1, 1.11, 1.09, 1.105, timestamp=BASE),
            make_bar(1.1, 1.11, 1.09, 1.105, timestamp=BASE + timedelta(seconds=301)),
        )
        config = make_config(
            opening_range_anchors=((SessionName.LONDON_NEW_YORK_OVERLAP, ANCHOR_HOUR, ANCHOR_MINUTE),),
            opening_range_duration_minutes=30,
            opening_range_min_bars=2,
            expected_bar_interval_seconds=300,
        )
        now = BASE + timedelta(minutes=30)
        state = compute_opening_ranges(bars, now, config)[0]
        self.assertFalse(state.is_valid)


class TestNegativeCases(unittest.TestCase):
    def test_missing_bar_inside_window_is_invalid(self):
        # Offsets 0,5,10,20,25 within a 30-minute window -- the 10->20
        # jump (600s) exceeds a 300s expected interval.
        bars = _bars_at([0, 5, 10, 20, 25], highs=[1.1] * 5, lows=[1.0] * 5)
        config = make_config(
            opening_range_anchors=((SessionName.LONDON_NEW_YORK_OVERLAP, ANCHOR_HOUR, ANCHOR_MINUTE),),
            opening_range_duration_minutes=30,
            opening_range_min_bars=3,
            expected_bar_interval_seconds=300,
        )
        now = BASE + timedelta(minutes=30)
        state = compute_opening_ranges(bars, now, config)[0]
        self.assertFalse(state.is_valid)

    def test_zero_configured_anchors_produces_empty_tuple_no_error(self):
        bars = _bars_at([0, 5, 10], highs=[1.1, 1.1, 1.1], lows=[1.0, 1.0, 1.0])
        config = make_config()  # opening_range_anchors defaults to ()
        ranges = compute_opening_ranges(bars, BASE + timedelta(minutes=30), config)
        self.assertEqual(ranges, ())

    def test_overlapping_anchors_raise_value_error_at_construction(self):
        with self.assertRaises(ValueError):
            make_config(
                opening_range_anchors=(
                    (SessionName.LONDON, 7, 0),
                    (SessionName.LONDON, 7, 15),
                ),
                opening_range_duration_minutes=30,
            )

    def test_anchor_whose_window_has_not_started_yet_produces_no_entry(self):
        bars = _bars_at([-20, -15, -10], highs=[1.1, 1.1, 1.1], lows=[1.0, 1.0, 1.0])
        config = make_config(
            opening_range_anchors=((SessionName.LONDON_NEW_YORK_OVERLAP, ANCHOR_HOUR, ANCHOR_MINUTE),),
            opening_range_duration_minutes=30,
            opening_range_min_bars=1,
        )
        ranges = compute_opening_ranges(bars, BASE + timedelta(minutes=-10), config)
        self.assertEqual(ranges, ())

    def test_invalid_duration_raises_value_error(self):
        with self.assertRaises(ValueError):
            make_config(opening_range_duration_minutes=0)

    def test_invalid_min_bars_raises_value_error(self):
        with self.assertRaises(ValueError):
            make_config(opening_range_min_bars=0)

    def test_invalid_expected_interval_raises_value_error(self):
        with self.assertRaises(ValueError):
            make_config(expected_bar_interval_seconds=0)


class TestModelIntegrity(unittest.TestCase):
    def test_opening_range_state_is_frozen(self):
        state = OpeningRangeState(
            session=SessionName.LONDON,
            range_start=BASE,
            range_end=BASE + timedelta(minutes=30),
            range_start_index=0,
            range_end_index=1,
            range_high=1.1,
            range_low=1.0,
            range_midpoint=1.05,
            is_formed=True,
            is_valid=True,
        )
        with self.assertRaises(FrozenInstanceError):
            state.range_high = 2.0  # type: ignore[misc]


class TestSnapshotIntegration(unittest.TestCase):
    def test_evaluate_snapshot_with_configured_anchor_populates_opening_ranges(self):
        bars = _bars_at([0, 5, 10, 15, 20, 25], highs=[1.1] * 6, lows=[1.0] * 6)
        config = make_config(
            opening_range_anchors=((SessionName.LONDON_NEW_YORK_OVERLAP, ANCHOR_HOUR, ANCHOR_MINUTE),),
            opening_range_duration_minutes=30,
            opening_range_min_bars=3,
            expected_bar_interval_seconds=600,
        )
        engine = EvidenceEngine(config)
        snapshot = engine.evaluate_snapshot("EURUSD", bars, now=BASE + timedelta(minutes=30))
        self.assertEqual(len(snapshot.opening_ranges), 1)
        self.assertTrue(snapshot.opening_ranges[0].is_valid)

    def test_evaluate_snapshot_with_no_anchors_produces_empty_tuple(self):
        bars = _bars_at([0, 5, 10], highs=[1.1, 1.1, 1.1], lows=[1.0, 1.0, 1.0])
        config = make_config()
        engine = EvidenceEngine(config)
        snapshot = engine.evaluate_snapshot("EURUSD", bars, now=BASE + timedelta(minutes=10))
        self.assertEqual(snapshot.opening_ranges, ())

    def test_evaluate_is_unaffected_by_configured_anchors(self):
        bars = _bars_at([0, 5, 10, 15, 20, 25], highs=[1.1] * 6, lows=[1.0] * 6)
        config_with_anchor = make_config(
            opening_range_anchors=((SessionName.LONDON_NEW_YORK_OVERLAP, ANCHOR_HOUR, ANCHOR_MINUTE),),
            opening_range_duration_minutes=30,
        )
        config_without_anchor = make_config()
        now = BASE + timedelta(minutes=30)
        report_with = EvidenceEngine(config_with_anchor).evaluate("EURUSD", bars, now)
        report_without = EvidenceEngine(config_without_anchor).evaluate("EURUSD", bars, now)
        self.assertEqual(report_with.score.composite, report_without.score.composite)


class TestNoMarketDataIngestionDependency(unittest.TestCase):
    def test_opening_range_module_does_not_import_market_data_ingestion(self):
        path = Path(__file__).resolve().parents[3] / "titan_protocol" / "evidence_engine" / "opening_range.py"
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                self.assertFalse(
                    name == "market_data_ingestion" or name.startswith("titan_protocol.market_data_ingestion"),
                    f"opening_range.py must not import market_data_ingestion, found: {name}",
                )


if __name__ == "__main__":
    unittest.main()
