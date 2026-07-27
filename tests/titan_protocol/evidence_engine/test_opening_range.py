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
from titan_protocol.evidence_engine.models import OpeningRangeBarObservation, OpeningRangeState, SessionName
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
            # ADR-035 Phase 5: duration widened from 30 to 180 minutes so this
            # fixture's own deliberately-large expected_bar_interval_seconds
            # (still large enough to isolate the count check from the gap
            # check -- every real bar spacing here stays well under 3600s)
            # remains feasible under the new opening_range_min_bars/duration
            # cross-field check (max_possible_bars=ceil(10800/3600)=3).
            opening_range_duration_minutes=180,
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
            # ADR-035 Phase 5: same widening as above, same reason.
            opening_range_duration_minutes=180,
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


class TestRangeDurationFeasibility(unittest.TestCase):
    """ADR-035 Phase 5 -- range-duration/bar-count feasibility cross-field
    check (docs/plans/adr-035-phase5-configuration.md §15 item 2)."""

    def test_range_duration_feasibility_exact_boundary_passes(self):
        # duration=30min=1800s, interval=300s -> max_possible_bars=6 exactly.
        make_config(
            opening_range_duration_minutes=30, expected_bar_interval_seconds=300, opening_range_min_bars=6,
        )  # must not raise

    def test_range_duration_feasibility_one_above_boundary_raises(self):
        with self.assertRaises(ValueError):
            make_config(
                opening_range_duration_minutes=30, expected_bar_interval_seconds=300, opening_range_min_bars=7,
            )

    def test_range_duration_feasibility_non_exact_division_boundary(self):
        # duration=22min=1320s, interval=300s -> ceil(1320/300)=5.
        make_config(
            opening_range_duration_minutes=22, expected_bar_interval_seconds=300, opening_range_min_bars=5,
        )  # must not raise
        with self.assertRaises(ValueError):
            make_config(
                opening_range_duration_minutes=22, expected_bar_interval_seconds=300, opening_range_min_bars=6,
            )


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

    def test_opening_range_state_post_range_bars_defaults_to_empty_tuple(self):
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
        self.assertEqual(state.post_range_bars, ())

    def test_opening_range_bar_observation_is_frozen(self):
        observation = OpeningRangeBarObservation(
            index=6, timestamp=BASE, open=1.10, high=1.11, low=1.09, close=1.105,
        )
        with self.assertRaises(FrozenInstanceError):
            observation.close = 2.0  # type: ignore[misc]

    def test_opening_range_bar_observation_field_shape(self):
        observation = OpeningRangeBarObservation(
            index=6, timestamp=BASE, open=1.10, high=1.11, low=1.09, close=1.105,
        )
        self.assertEqual(observation.index, 6)
        self.assertEqual(observation.timestamp, BASE)
        self.assertEqual(observation.open, 1.10)
        self.assertEqual(observation.high, 1.11)
        self.assertEqual(observation.low, 1.09)
        self.assertEqual(observation.close, 1.105)


class TestPostRangeBars(unittest.TestCase):
    """(ADR-024 Amendment 4) `OpeningRangeState.post_range_bars` --
    exact first-candidate anchoring, exact subsequent continuity,
    self-derived completion, bounded retention, no skip-and-resume."""

    _CONFIG_KWARGS = dict(
        opening_range_anchors=((SessionName.LONDON_NEW_YORK_OVERLAP, ANCHOR_HOUR, ANCHOR_MINUTE),),
        opening_range_duration_minutes=30,
        opening_range_min_bars=3,
        expected_bar_interval_seconds=300,  # 5 minutes
    )

    def _in_range_bars(self):
        # 6 bars at 0,5,...,25 minutes -- fully inside [0, 30), gap-free.
        return _bars_at([0, 5, 10, 15, 20, 25], highs=[1.10] * 6, lows=[1.05] * 6)

    def test_first_candidate_exactly_at_range_end_is_eligible(self):
        post_range = (make_bar(1.10, 1.12, 1.09, 1.115, timestamp=BASE + timedelta(minutes=30)),)
        bars = self._in_range_bars() + post_range
        config = make_config(**self._CONFIG_KWARGS, opening_range_post_range_bar_window=5)
        now = BASE + timedelta(minutes=35)  # 30 + 5 <= 35
        state = compute_opening_ranges(bars, now, config)[0]
        self.assertEqual(len(state.post_range_bars), 1)
        self.assertEqual(state.post_range_bars[0].timestamp, BASE + timedelta(minutes=30))
        self.assertEqual(state.post_range_bars[0].index, 6)

    def test_first_candidate_later_than_range_end_yields_empty_tuple(self):
        # range_end bar (offset 30) is entirely absent; first real bar is offset 35.
        post_range = (make_bar(1.10, 1.12, 1.09, 1.115, timestamp=BASE + timedelta(minutes=35)),)
        bars = self._in_range_bars() + post_range
        config = make_config(**self._CONFIG_KWARGS, opening_range_post_range_bar_window=5)
        now = BASE + timedelta(minutes=45)
        state = compute_opening_ranges(bars, now, config)[0]
        self.assertEqual(state.post_range_bars, ())

    def test_first_candidate_earlier_than_range_end_yields_empty_tuple(self):
        # Pathological/out-of-order input: the bar occupying the array
        # position range_end_index would land on has a timestamp well
        # before range_start, not merely before range_end. A normal,
        # later bar follows it so the anchor's own "has this window
        # started yet" guard (based on the array's last timestamp) still
        # passes -- isolating the first-candidate check being exercised.
        stray = make_bar(1.10, 1.12, 1.09, 1.115, timestamp=BASE - timedelta(minutes=100))
        later = make_bar(1.10, 1.12, 1.09, 1.115, timestamp=BASE + timedelta(minutes=40))
        bars = self._in_range_bars() + (stray, later)
        config = make_config(**self._CONFIG_KWARGS, opening_range_post_range_bar_window=5)
        now = BASE + timedelta(minutes=45)
        state = compute_opening_ranges(bars, now, config)[0]
        self.assertEqual(state.range_end_index, 6)
        self.assertEqual(state.post_range_bars, ())

    def test_missing_boundary_candle_scenario(self):
        # range_end=BASE+30min absent; next available bar is BASE+35min.
        # The 35-minute bar must NOT be accepted as the first observation.
        post_range = (make_bar(1.10, 1.12, 1.09, 1.115, timestamp=BASE + timedelta(minutes=35)),)
        bars = self._in_range_bars() + post_range
        config = make_config(**self._CONFIG_KWARGS, opening_range_post_range_bar_window=5)
        now = BASE + timedelta(minutes=45)
        state = compute_opening_ranges(bars, now, config)[0]
        self.assertEqual(state.post_range_bars, ())

    def test_exact_subsequent_continuity_accepts_full_contiguous_run(self):
        post_range = _bars_at([30, 35, 40], highs=[1.10, 1.11, 1.12], lows=[1.05, 1.06, 1.07])
        bars = self._in_range_bars() + post_range
        config = make_config(**self._CONFIG_KWARGS, opening_range_post_range_bar_window=5)
        now = BASE + timedelta(minutes=50)  # 40 + 5 <= 50
        state = compute_opening_ranges(bars, now, config)[0]
        self.assertEqual(len(state.post_range_bars), 3)
        self.assertEqual(
            [obs.timestamp for obs in state.post_range_bars],
            [BASE + timedelta(minutes=m) for m in (30, 35, 40)],
        )
        self.assertEqual([obs.index for obs in state.post_range_bars], [6, 7, 8])

    def test_internal_gap_retains_only_the_contiguous_prefix(self):
        # 40-minute bar missing; 45-minute bar exists but must never be
        # reached (no skip-and-resume).
        post_range = _bars_at([30, 35, 45], highs=[1.10, 1.11, 1.30], lows=[1.05, 1.06, 0.90])
        bars = self._in_range_bars() + post_range
        config = make_config(**self._CONFIG_KWARGS, opening_range_post_range_bar_window=5)
        now = BASE + timedelta(minutes=55)
        state = compute_opening_ranges(bars, now, config)[0]
        self.assertEqual(len(state.post_range_bars), 2)
        self.assertEqual(
            [obs.timestamp for obs in state.post_range_bars],
            [BASE + timedelta(minutes=m) for m in (30, 35)],
        )

    def test_incomplete_first_candidate_yields_empty_tuple(self):
        post_range = (make_bar(1.10, 1.12, 1.09, 1.115, timestamp=BASE + timedelta(minutes=30)),)
        bars = self._in_range_bars() + post_range
        config = make_config(**self._CONFIG_KWARGS, opening_range_post_range_bar_window=5)
        now = BASE + timedelta(minutes=34)  # 30 + 5 = 35 > 34 -- not yet complete
        state = compute_opening_ranges(bars, now, config)[0]
        self.assertEqual(state.post_range_bars, ())

    def test_incomplete_later_candidate_retains_accepted_prefix_only_no_resume(self):
        # A bar at offset 40 exists and is fully complete/contiguous, but
        # must never be inspected once offset 35 fails completion.
        post_range = _bars_at([30, 35, 40], highs=[1.10, 1.11, 1.12], lows=[1.05, 1.06, 1.07])
        bars = self._in_range_bars() + post_range
        config = make_config(**self._CONFIG_KWARGS, opening_range_post_range_bar_window=5)
        now = BASE + timedelta(minutes=39)  # 30+5=35<=39 (complete); 35+5=40>39 (incomplete)
        state = compute_opening_ranges(bars, now, config)[0]
        self.assertEqual(len(state.post_range_bars), 1)
        self.assertEqual(state.post_range_bars[0].timestamp, BASE + timedelta(minutes=30))

    def test_completion_exactly_at_boundary_is_eligible(self):
        post_range = (make_bar(1.10, 1.12, 1.09, 1.115, timestamp=BASE + timedelta(minutes=30)),)
        bars = self._in_range_bars() + post_range
        config = make_config(**self._CONFIG_KWARGS, opening_range_post_range_bar_window=5)
        now = BASE + timedelta(minutes=35)  # 30 + 5 == 35 exactly
        state = compute_opening_ranges(bars, now, config)[0]
        self.assertEqual(len(state.post_range_bars), 1)

    def test_incomplete_one_second_before_boundary_yields_empty_tuple(self):
        post_range = (make_bar(1.10, 1.12, 1.09, 1.115, timestamp=BASE + timedelta(minutes=30)),)
        bars = self._in_range_bars() + post_range
        config = make_config(**self._CONFIG_KWARGS, opening_range_post_range_bar_window=5)
        now = BASE + timedelta(minutes=30, seconds=299)  # one second short of 30+5min
        state = compute_opening_ranges(bars, now, config)[0]
        self.assertEqual(state.post_range_bars, ())

    def test_retention_bound_enforced(self):
        post_range = _bars_at([30, 35, 40, 45], highs=[1.10] * 4, lows=[1.05] * 4)
        bars = self._in_range_bars() + post_range
        config = make_config(**self._CONFIG_KWARGS, opening_range_post_range_bar_window=2)
        now = BASE + timedelta(minutes=55)
        state = compute_opening_ranges(bars, now, config)[0]
        self.assertEqual(len(state.post_range_bars), 2)
        self.assertEqual(
            [obs.timestamp for obs in state.post_range_bars],
            [BASE + timedelta(minutes=m) for m in (30, 35)],
        )

    def test_exact_ohlc_preservation(self):
        post_range = (make_bar(1.101, 1.123, 1.091, 1.117, timestamp=BASE + timedelta(minutes=30)),)
        bars = self._in_range_bars() + post_range
        config = make_config(**self._CONFIG_KWARGS, opening_range_post_range_bar_window=5)
        now = BASE + timedelta(minutes=40)
        observation = compute_opening_ranges(bars, now, config)[0].post_range_bars[0]
        self.assertEqual(observation.open, 1.101)
        self.assertEqual(observation.high, 1.123)
        self.assertEqual(observation.low, 1.091)
        self.assertEqual(observation.close, 1.117)

    def test_invalid_window_raises_value_error(self):
        with self.assertRaises(ValueError):
            make_config(opening_range_post_range_bar_window=0)

    def test_window_default_is_five(self):
        config = make_config()
        self.assertEqual(config.opening_range_post_range_bar_window, 5)


class TestMultipleOpeningRangeIndependence(unittest.TestCase):
    """A bar may legitimately be post-range evidence for one configured
    anchor while simultaneously being in-range formation evidence for a
    different, later-starting anchor -- each `OpeningRangeState` is
    derived independently, and neither computation mutates or suppresses
    the other's result."""

    def test_shared_bar_serves_both_roles_without_interference(self):
        anchor_a_hour, anchor_a_minute = 13, 0
        anchor_b_hour, anchor_b_minute = 13, 10  # starts exactly where A's post-range window begins
        config = make_config(
            opening_range_anchors=(
                (SessionName.LONDON, anchor_a_hour, anchor_a_minute),
                (SessionName.LONDON_NEW_YORK_OVERLAP, anchor_b_hour, anchor_b_minute),
            ),
            opening_range_duration_minutes=10,
            opening_range_min_bars=1,
            expected_bar_interval_seconds=600,  # 10 minutes
        )
        start = BASE.replace(hour=13, minute=0)
        shared_bar_timestamp = start + timedelta(minutes=10)  # 13:10
        bars = (
            make_bar(1.10, 1.11, 1.09, 1.105, timestamp=start),  # 13:00 -- in-range for A only
            make_bar(1.12, 1.13, 1.11, 1.125, timestamp=shared_bar_timestamp),  # 13:10 -- shared
            make_bar(1.14, 1.15, 1.13, 1.145, timestamp=start + timedelta(minutes=20)),  # 13:20
        )
        now = start + timedelta(minutes=30)
        ranges = compute_opening_ranges(bars, now, config)
        self.assertEqual(len(ranges), 2)
        range_a, range_b = ranges[0], ranges[1]

        # Range A: [13:00, 13:10) -- only the 13:00 bar is in-range; its
        # post_range_bars must start with the shared 13:10 bar (and,
        # since the 13:20 bar is also genuinely contiguous/complete
        # relative to A's own 10-minute interval, correctly extends to
        # include it too).
        self.assertEqual(range_a.range_start, start)
        self.assertTrue(range_a.is_valid)
        self.assertEqual(len(range_a.post_range_bars), 2)
        self.assertEqual(range_a.post_range_bars[0].timestamp, shared_bar_timestamp)

        # Range B: [13:10, 13:20) -- the shared 13:10 bar is B's own
        # in-range formation evidence (contributes to range_high/low),
        # completely independent of its role in A's post_range_bars.
        self.assertEqual(range_b.range_start, shared_bar_timestamp)
        self.assertTrue(range_b.is_valid)
        self.assertAlmostEqual(range_b.range_high, 1.13)
        self.assertAlmostEqual(range_b.range_low, 1.11)


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
