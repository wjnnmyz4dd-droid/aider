"""SessionManager tests — pure, deterministic functions of an explicit
`now`, mirroring every prior stage's own "no wall-clock dependence"
discipline."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from phantom_pipeline.paper_trading.session_manager import (
    DEFAULT_CONFIG,
    SessionManager,
    SessionManagerConfig,
    SessionWindow,
)


def _dt(year=2026, month=7, day=6, hour=0, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


class TestSessionWindowContains(unittest.TestCase):
    def test_simple_window(self):
        window = SessionWindow("LONDON", 7, 0, 16, 0)
        self.assertTrue(window.contains(10, 0))
        self.assertFalse(window.contains(6, 59))
        self.assertFalse(window.contains(16, 0))

    def test_wraparound_window(self):
        window = SessionWindow("SYDNEY", 21, 0, 6, 0)
        self.assertTrue(window.contains(23, 0))
        self.assertTrue(window.contains(2, 0))
        self.assertFalse(window.contains(10, 0))


class TestActiveSessions(unittest.TestCase):
    def setUp(self):
        self.manager = SessionManager()

    def test_london_session_active(self):
        # 2026-07-06 is a Monday
        now = _dt(hour=10)
        self.assertIn("LONDON", self.manager.active_sessions(now))

    def test_multiple_sessions_can_overlap(self):
        now = _dt(hour=13)  # London + New York overlap window
        active = self.manager.active_sessions(now)
        self.assertIn("LONDON", active)
        self.assertIn("NEW_YORK", active)

    def test_asian_and_us_sessions_not_simultaneously_active(self):
        now = _dt(hour=9, minute=30)  # Tokyo just closed, before New York opens
        active = self.manager.active_sessions(now)
        self.assertNotIn("TOKYO", active)
        self.assertNotIn("NEW_YORK", active)


class TestWeekendHandling(unittest.TestCase):
    def setUp(self):
        self.manager = SessionManager()

    def test_friday_before_close_is_trading_day(self):
        friday = _dt(year=2026, month=7, day=10, hour=20, minute=0)  # Friday
        self.assertFalse(self.manager.is_weekend(friday))
        self.assertTrue(self.manager.is_trading_day(friday))

    def test_friday_after_close_is_weekend(self):
        friday = _dt(year=2026, month=7, day=10, hour=22, minute=0)
        self.assertTrue(self.manager.is_weekend(friday))
        self.assertFalse(self.manager.is_trading_day(friday))

    def test_saturday_is_weekend(self):
        saturday = _dt(year=2026, month=7, day=11, hour=12, minute=0)
        self.assertTrue(self.manager.is_weekend(saturday))

    def test_sunday_before_reopen_is_weekend(self):
        sunday = _dt(year=2026, month=7, day=12, hour=20, minute=0)
        self.assertTrue(self.manager.is_weekend(sunday))

    def test_sunday_after_reopen_is_trading(self):
        sunday = _dt(year=2026, month=7, day=12, hour=22, minute=0)
        self.assertFalse(self.manager.is_weekend(sunday))

    def test_monday_is_trading_day(self):
        monday = _dt(year=2026, month=7, day=6, hour=10)
        self.assertFalse(self.manager.is_weekend(monday))


class TestTradingDayBoundaries(unittest.TestCase):
    def setUp(self):
        self.manager = SessionManager()

    def test_trading_day_start_same_day_after_reset(self):
        now = _dt(hour=10)
        start = self.manager.trading_day_start(now)
        self.assertEqual(start, _dt(hour=0))

    def test_trading_day_start_before_reset_uses_previous_day(self):
        config = SessionManagerConfig(daily_reset_hour_utc=6)
        manager = SessionManager(config)
        now = _dt(hour=3)
        start = manager.trading_day_start(now)
        self.assertEqual(start, _dt(day=5, hour=6))

    def test_is_new_trading_day_true_across_boundary(self):
        previous = _dt(hour=23, minute=59)
        now = previous + timedelta(minutes=2)
        self.assertTrue(self.manager.is_new_trading_day(previous, now))

    def test_is_new_trading_day_false_within_same_day(self):
        previous = _dt(hour=10)
        now = _dt(hour=11)
        self.assertFalse(self.manager.is_new_trading_day(previous, now))


if __name__ == "__main__":
    unittest.main()
