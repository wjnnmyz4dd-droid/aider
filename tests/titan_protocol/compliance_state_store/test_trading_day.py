"""Tests for `trading_day_id_for` -- the pure trading-day-boundary
calculation (Final Release Hardening, persisted compliance state)."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from titan_protocol.compliance_state_store.trading_day import trading_day_id_for


class TestUtcMidnightBoundary(unittest.TestCase):
    def test_before_and_after_midnight_are_different_days(self):
        before = datetime(2026, 7, 14, 23, 59, 59, tzinfo=timezone.utc)
        after = datetime(2026, 7, 15, 0, 0, 1, tzinfo=timezone.utc)
        self.assertNotEqual(trading_day_id_for(before, 0), trading_day_id_for(after, 0))

    def test_naive_datetime_is_treated_as_utc(self):
        naive = datetime(2026, 7, 14, 12, 0, 0)
        aware = datetime(2026, 7, 14, 12, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(trading_day_id_for(naive, 0), trading_day_id_for(aware, 0))


class TestConfiguredResetHour(unittest.TestCase):
    """A 17:00 UTC broker-day boundary (a common real-world convention)."""

    def test_just_before_the_reset_hour_is_the_previous_trading_day(self):
        just_before = datetime(2026, 7, 14, 16, 59, 59, tzinfo=timezone.utc)
        self.assertEqual(trading_day_id_for(just_before, 17), "2026-07-13")

    def test_at_the_reset_hour_is_the_new_trading_day(self):
        at_reset = datetime(2026, 7, 14, 17, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(trading_day_id_for(at_reset, 17), "2026-07-14")

    def test_a_full_24_hours_later_is_the_next_trading_day(self):
        day_one = datetime(2026, 7, 14, 17, 0, 0, tzinfo=timezone.utc)
        day_two = datetime(2026, 7, 15, 17, 0, 0, tzinfo=timezone.utc)
        self.assertNotEqual(trading_day_id_for(day_one, 17), trading_day_id_for(day_two, 17))


class TestBrokerTimeIsNotDstAware(unittest.TestCase):
    """Documented limitation: this store is stdlib-only and treats
    `daily_reset_hour_utc` as a fixed UTC hour year-round -- it does not
    shift with a broker's own DST-observing local time. This test
    documents the current, honest behavior rather than asserting a
    DST-awareness this module does not implement."""

    def test_reset_hour_is_a_fixed_utc_offset_across_a_dst_transition(self):
        before_dst_change = datetime(2026, 3, 1, 17, 0, 0, tzinfo=timezone.utc)
        after_dst_change = datetime(2026, 4, 1, 17, 0, 0, tzinfo=timezone.utc)
        # Both still roll over at exactly 17:00 UTC -- no DST shift applied.
        self.assertEqual(trading_day_id_for(before_dst_change, 17), "2026-03-01")
        self.assertEqual(trading_day_id_for(after_dst_change, 17), "2026-04-01")


if __name__ == "__main__":
    unittest.main()
