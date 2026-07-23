"""Tests for start.py's positions-staleness observability signal (Titan
Protocol Independent Verification -- positions-staleness finding,
currently Partially Verified, not confirmed).

Covers both pure decision functions directly (no live-cycle loop or
background thread needed):

* `_positions_are_stale()` -- the raw condition.
* `_positions_staleness_event()` -- edge-triggered + periodic-repeat
  classification, added after an independent red-team review of this
  instrumentation itself found the original per-cycle-unconditional
  logging would flood logs for the duration of any real outage
  (`_live_cycle_loop()` runs every `_LIVE_CYCLE_INTERVAL_SECONDS`, 15s
  by default -- an hour-long outage would otherwise produce ~240
  identical WARNING lines).

Observability only throughout: no test here asserts anything about
trade acceptance/rejection, because there is nothing of the sort to
assert -- these functions have no such effect."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from ._fixtures import DEPLOYMENT_DIR  # noqa: F401 -- ensures deployment_windows/ is on sys.path

import start

_NOW = datetime(2026, 7, 23, tzinfo=timezone.utc)
_THRESHOLD = 30.0


class TestPositionsAreStale(unittest.TestCase):
    def test_true_when_heartbeat_healthy_and_positions_older_than_threshold(self):
        self.assertTrue(start._positions_are_stale(True, _THRESHOLD + 0.001, _THRESHOLD))

    def test_false_when_heartbeat_unhealthy_even_if_positions_are_old(self):
        """positions_are_live=False means the heartbeat itself is
        unhealthy -- a different, already-observable condition
        (position_source_state == "absent" in the existing
        portfolio_state_source log). Must not double up on it."""
        self.assertFalse(start._positions_are_stale(False, _THRESHOLD + 100.0, _THRESHOLD))

    def test_false_when_positions_never_reported_at_all(self):
        """position_report_age_seconds is None when positions have never
        been received -- nothing to measure an age against, a distinct
        condition from staleness."""
        self.assertFalse(start._positions_are_stale(True, None, _THRESHOLD))

    def test_false_when_positions_are_fresh(self):
        self.assertFalse(start._positions_are_stale(True, 1.0, _THRESHOLD))

    def test_false_exactly_at_threshold_boundary(self):
        """Mirrors this codebase's established boundary convention
        elsewhere (e.g. CommandQueue.is_abandoned(): `waited_seconds >
        timeout`, not `>=`) -- exactly at the threshold is not yet
        stale."""
        self.assertFalse(start._positions_are_stale(True, _THRESHOLD, _THRESHOLD))


class TestPositionsStalenessEvent(unittest.TestCase):
    """Proves the log-flooding fix: entry, sustained staleness (no
    per-cycle repeat until the interval elapses), recovery, and
    recurrence (a fresh "entered" after a "recovered")."""

    def test_stale_entry_produces_entered_event(self):
        event = start._positions_staleness_event(
            is_stale_now=True, was_stale_last_cycle=False, last_logged_at=None,
            now=_NOW, repeat_log_interval_seconds=_THRESHOLD,
        )
        self.assertEqual(event, "entered")

    def test_sustained_staleness_does_not_repeat_before_interval_elapses(self):
        """The core anti-flooding assertion: many consecutive stale
        cycles within the repeat interval must NOT each produce a log
        event -- the pre-fix behavior this test would have caught."""
        last_logged_at = _NOW
        for offset_seconds in (1, 5, 10, 15, 20, 29.999):
            event = start._positions_staleness_event(
                is_stale_now=True, was_stale_last_cycle=True, last_logged_at=last_logged_at,
                now=_NOW + timedelta(seconds=offset_seconds), repeat_log_interval_seconds=_THRESHOLD,
            )
            self.assertIsNone(event, f"must not log again at +{offset_seconds}s, well within the repeat interval")

    def test_sustained_staleness_repeats_once_interval_elapses(self):
        last_logged_at = _NOW
        event = start._positions_staleness_event(
            is_stale_now=True, was_stale_last_cycle=True, last_logged_at=last_logged_at,
            now=_NOW + timedelta(seconds=_THRESHOLD), repeat_log_interval_seconds=_THRESHOLD,
        )
        self.assertEqual(event, "repeat")

    def test_recovery_produces_recovered_event(self):
        event = start._positions_staleness_event(
            is_stale_now=False, was_stale_last_cycle=True, last_logged_at=_NOW,
            now=_NOW + timedelta(seconds=1), repeat_log_interval_seconds=_THRESHOLD,
        )
        self.assertEqual(event, "recovered")

    def test_recurrence_after_recovery_produces_a_fresh_entered_event(self):
        """A brand-new staleness episode after a prior recovery must be
        classified as "entered" again, never suppressed as a
        continuation of the old (already-recovered) episode."""
        event = start._positions_staleness_event(
            is_stale_now=True, was_stale_last_cycle=False, last_logged_at=_NOW,
            now=_NOW + timedelta(hours=1), repeat_log_interval_seconds=_THRESHOLD,
        )
        self.assertEqual(event, "entered")

    def test_never_stale_produces_no_event(self):
        event = start._positions_staleness_event(
            is_stale_now=False, was_stale_last_cycle=False, last_logged_at=None,
            now=_NOW, repeat_log_interval_seconds=_THRESHOLD,
        )
        self.assertIsNone(event)

    def test_stale_with_no_prior_log_timestamp_logs_immediately(self):
        """Defensive case: is_stale_now and was_stale_last_cycle both
        True but last_logged_at is None (should not occur via the real
        entered->repeat/recovered state machine, but must not silently
        suppress logging if it ever does -- fail toward more
        observability, not less)."""
        event = start._positions_staleness_event(
            is_stale_now=True, was_stale_last_cycle=True, last_logged_at=None,
            now=_NOW, repeat_log_interval_seconds=_THRESHOLD,
        )
        self.assertEqual(event, "repeat")


if __name__ == "__main__":
    unittest.main()
