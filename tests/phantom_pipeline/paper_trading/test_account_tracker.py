"""AccountTracker tests."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from phantom_pipeline.paper_trading.account_tracker import AccountTracker
from phantom_pipeline.paper_trading.session_manager import SessionManager, SessionManagerConfig

T0 = datetime(2026, 7, 6, 1, 0, 0, tzinfo=timezone.utc)


class TestAccountTrackerBasics(unittest.TestCase):
    def test_rejects_non_positive_initial_equity(self):
        with self.assertRaises(ValueError):
            AccountTracker(initial_equity=0.0)

    def test_first_observation_has_zero_drawdown(self):
        tracker = AccountTracker(initial_equity=10000.0)
        snapshot = tracker.observe(10000.0, T0)
        self.assertEqual(snapshot.daily_drawdown_pct, 0.0)
        self.assertEqual(snapshot.total_drawdown_pct, 0.0)

    def test_equity_drop_produces_positive_drawdown(self):
        tracker = AccountTracker(initial_equity=10000.0)
        tracker.observe(10000.0, T0)
        snapshot = tracker.observe(9800.0, T0 + timedelta(minutes=5))
        self.assertAlmostEqual(snapshot.daily_drawdown_pct, 2.0)
        self.assertAlmostEqual(snapshot.total_drawdown_pct, 2.0)

    def test_equity_gain_never_produces_negative_drawdown(self):
        tracker = AccountTracker(initial_equity=10000.0)
        tracker.observe(10000.0, T0)
        snapshot = tracker.observe(10500.0, T0 + timedelta(minutes=5))
        self.assertEqual(snapshot.daily_drawdown_pct, 0.0)
        self.assertEqual(snapshot.total_drawdown_pct, 0.0)


class TestDailyReset(unittest.TestCase):
    def test_daily_drawdown_resets_at_trading_day_boundary(self):
        tracker = AccountTracker(initial_equity=10000.0)
        tracker.observe(10000.0, T0)
        tracker.observe(9700.0, T0 + timedelta(hours=1))  # 3% daily DD
        next_day = T0 + timedelta(days=1)
        snapshot = tracker.observe(9700.0, next_day)
        self.assertEqual(snapshot.daily_drawdown_pct, 0.0)  # new day baseline == 9700
        self.assertAlmostEqual(snapshot.total_drawdown_pct, 3.0)  # total DD survives the reset

    def test_total_drawdown_survives_across_many_days(self):
        tracker = AccountTracker(initial_equity=10000.0)
        tracker.observe(10000.0, T0)
        for day in range(1, 5):
            tracker.observe(9500.0, T0 + timedelta(days=day))
        snapshot = tracker.observe(9000.0, T0 + timedelta(days=5))
        self.assertAlmostEqual(snapshot.total_drawdown_pct, 10.0)


class TestPeakBasedDrawdown(unittest.TestCase):
    def test_peak_tracks_highest_observed_equity(self):
        tracker = AccountTracker(initial_equity=10000.0)
        tracker.observe(10000.0, T0)
        tracker.observe(11000.0, T0 + timedelta(minutes=1))
        snapshot = tracker.observe(10500.0, T0 + timedelta(minutes=2))
        self.assertEqual(snapshot.peak_equity, 11000.0)
        self.assertAlmostEqual(snapshot.total_drawdown_pct_from_peak, (11000 - 10500) / 11000 * 100)
        self.assertEqual(snapshot.total_drawdown_pct, 0.0)  # still above initial equity


if __name__ == "__main__":
    unittest.main()
