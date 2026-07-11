"""Unit category: the pure helper functions (validation, ordering,
freshness, warmup, normalization) in isolation."""

from __future__ import annotations

import unittest
import dataclasses
from datetime import timedelta

from phantom.evidence_engine.models import Bar
from phantom.market_data_ingestion.freshness import is_stale
from phantom.market_data_ingestion.models import RejectionReason, Timeframe
from phantom.market_data_ingestion.normalization import normalize
from phantom.market_data_ingestion.ordering import SequenceState, advance, check_ordering
from phantom.market_data_ingestion.validation import validate_bar
from phantom.market_data_ingestion.warmup import WarmupTracker
from tests.phantom.market_data_ingestion._fixtures import T0, make_bar, make_config


class TestValidation(unittest.TestCase):
    def test_valid_bar_passes(self):
        self.assertIsNone(validate_bar(make_bar(), make_config()))

    def test_unknown_symbol_rejected(self):
        self.assertEqual(validate_bar(make_bar(symbol="XAUUSD"), make_config()), RejectionReason.UNKNOWN_SYMBOL)

    def test_unknown_timeframe_rejected(self):
        self.assertEqual(validate_bar(make_bar(timeframe=Timeframe.D1), make_config()), RejectionReason.UNKNOWN_TIMEFRAME)

    def test_high_below_low_is_malformed(self):
        bar = make_bar(high=1.0, low=1.1)
        self.assertEqual(validate_bar(bar, make_config()), RejectionReason.MALFORMED)

    def test_high_below_open_is_malformed(self):
        bar = make_bar(high=1.05, open_=1.1)
        self.assertEqual(validate_bar(bar, make_config()), RejectionReason.MALFORMED)

    def test_negative_volume_is_malformed(self):
        bar = make_bar(volume=-1.0)
        self.assertEqual(validate_bar(bar, make_config()), RejectionReason.MALFORMED)

    def test_ask_below_bid_is_malformed(self):
        bar = make_bar(bid=1.10, ask=1.09)
        self.assertEqual(validate_bar(bar, make_config()), RejectionReason.MALFORMED)

    def test_clock_skew_beyond_threshold_rejected(self):
        """Clock skew compares `broker_timestamp` vs. `source_timestamp`
        -- two clocks that should agree at capture time -- never
        wall-clock `now`, since historical backfill legitimately has
        both far in the past relative to `now` (see validation.py's
        own docstring)."""
        bar = make_bar(broker_timestamp=T0, source_timestamp=T0 - timedelta(seconds=30))
        config = make_config(max_clock_skew_seconds=5.0)
        self.assertEqual(validate_bar(bar, config), RejectionReason.CLOCK_SKEW)

    def test_clock_skew_within_threshold_passes(self):
        bar = make_bar(broker_timestamp=T0, source_timestamp=T0 - timedelta(seconds=2))
        config = make_config(max_clock_skew_seconds=5.0)
        self.assertIsNone(validate_bar(bar, config))

    def test_historical_backfill_bar_is_never_rejected_for_clock_skew_against_now(self):
        """The regression this fix targets: a bar whose own timestamps
        are hours old (a legitimate backfill bar) must never be
        rejected just because wall-clock `now` differs from it."""
        old_time = T0 - timedelta(days=3)
        bar = make_bar(broker_timestamp=old_time, source_timestamp=old_time)
        config = make_config(max_clock_skew_seconds=5.0)
        self.assertIsNone(validate_bar(bar, config))


class TestOrdering(unittest.TestCase):
    def test_first_bar_ever_is_never_rejected(self):
        state = SequenceState()
        reason, gap = check_ordering(state, make_bar(), make_config())
        self.assertIsNone(reason)
        self.assertFalse(gap)

    def test_exact_duplicate_rejected(self):
        state = SequenceState()
        first = make_bar(sequence_number=1, bar_open_time=T0)
        advance(state, first)
        reason, _ = check_ordering(state, first, make_config())
        self.assertEqual(reason, RejectionReason.DUPLICATE)

    def test_sequence_regression_rejected(self):
        state = SequenceState()
        advance(state, make_bar(sequence_number=5, bar_open_time=T0))
        later_time = T0 + timedelta(minutes=15)
        reason, _ = check_ordering(state, make_bar(sequence_number=3, bar_open_time=later_time), make_config())
        self.assertEqual(reason, RejectionReason.OUT_OF_SEQUENCE)

    def test_timestamp_regression_rejected(self):
        state = SequenceState()
        advance(state, make_bar(sequence_number=1, bar_open_time=T0))
        earlier_time = T0 - timedelta(minutes=15)
        reason, _ = check_ordering(state, make_bar(sequence_number=2, bar_open_time=earlier_time), make_config())
        self.assertEqual(reason, RejectionReason.OUT_OF_ORDER)

    def test_normal_advance_detects_no_gap(self):
        state = SequenceState()
        advance(state, make_bar(sequence_number=1, bar_open_time=T0))
        next_bar = make_bar(sequence_number=2, bar_open_time=T0 + timedelta(minutes=15))
        reason, gap = check_ordering(state, next_bar, make_config())
        self.assertIsNone(reason)
        self.assertFalse(gap)

    def test_missing_bar_detected_as_gap(self):
        state = SequenceState()
        advance(state, make_bar(sequence_number=1, bar_open_time=T0))
        # Two M15 bars missing -- 45 minutes elapsed instead of 15.
        next_bar = make_bar(sequence_number=2, bar_open_time=T0 + timedelta(minutes=45))
        reason, gap = check_ordering(state, next_bar, make_config())
        self.assertIsNone(reason)
        self.assertTrue(gap)


class TestFreshness(unittest.TestCase):
    def test_never_seen_is_stale(self):
        self.assertTrue(is_stale(None, T0, Timeframe.M15, make_config()))

    def test_recent_bar_is_fresh(self):
        self.assertFalse(is_stale(T0, T0 + timedelta(minutes=1), Timeframe.M15, make_config()))

    def test_old_bar_is_stale(self):
        self.assertTrue(is_stale(T0, T0 + timedelta(hours=2), Timeframe.M15, make_config()))

    def test_future_last_bar_is_never_trusted(self):
        self.assertTrue(is_stale(T0 + timedelta(minutes=5), T0, Timeframe.M15, make_config()))


class TestWarmup(unittest.TestCase):
    def test_not_ready_below_threshold(self):
        tracker = WarmupTracker(make_config())
        tracker.record_closed_bar("EURUSD", Timeframe.M15)
        status = tracker.status("EURUSD", Timeframe.M15)
        self.assertFalse(status.ready)
        self.assertEqual(status.bars_received, 1)

    def test_ready_once_threshold_met(self):
        config = make_config(min_warmup_bars_by_timeframe={Timeframe.M15: 3})
        tracker = WarmupTracker(config)
        for _ in range(3):
            tracker.record_closed_bar("EURUSD", Timeframe.M15)
        self.assertTrue(tracker.status("EURUSD", Timeframe.M15).ready)

    def test_never_fabricates_a_bar(self):
        """The only way `bars_received` increases is a real call to
        `record_closed_bar` -- there is no method that synthesizes one."""
        tracker = WarmupTracker(make_config())
        self.assertEqual(tracker.status("EURUSD", Timeframe.M15).bars_received, 0)


class TestNormalization(unittest.TestCase):
    def test_normalize_produces_the_real_evidence_engine_bar_type(self):
        raw = make_bar()
        bar = normalize(raw)
        self.assertIsInstance(bar, Bar)
        self.assertEqual(bar.symbol, raw.symbol)
        self.assertEqual(bar.timestamp, raw.bar_open_time)
        self.assertEqual(bar.open, raw.open)
        self.assertEqual(bar.close, raw.close)


if __name__ == "__main__":
    unittest.main()
