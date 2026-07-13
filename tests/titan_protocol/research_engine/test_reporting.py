"""Unit tests: Daily/Weekly/Monthly/Quarterly/Custom period filtering
(ADR-029 §5)."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from titan_protocol.research_engine.models import ReportPeriod
from titan_protocol.research_engine.reporting import filter_trades_by_period, period_bounds
from tests.titan_protocol.research_engine._fixtures import make_executed_trade


class TestPeriodBounds(unittest.TestCase):
    def test_daily_starts_at_midnight(self):
        now = datetime(2026, 7, 10, 15, 30, tzinfo=timezone.utc)
        start, end = period_bounds(ReportPeriod.DAILY, now)
        self.assertEqual(start, datetime(2026, 7, 10, 0, 0, tzinfo=timezone.utc))
        self.assertEqual(end, now)

    def test_weekly_starts_on_monday(self):
        now = datetime(2026, 7, 10, 15, 30, tzinfo=timezone.utc)  # Friday
        start, end = period_bounds(ReportPeriod.WEEKLY, now)
        self.assertEqual(start.weekday(), 0)
        self.assertEqual(start, datetime(2026, 7, 6, 0, 0, tzinfo=timezone.utc))

    def test_monthly_starts_on_first_of_month(self):
        now = datetime(2026, 7, 10, 15, 30, tzinfo=timezone.utc)
        start, end = period_bounds(ReportPeriod.MONTHLY, now)
        self.assertEqual(start, datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc))

    def test_quarterly_starts_at_quarter_boundary(self):
        now = datetime(2026, 8, 15, tzinfo=timezone.utc)  # Q3
        start, end = period_bounds(ReportPeriod.QUARTERLY, now)
        self.assertEqual(start, datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc))

    def test_custom_requires_explicit_bounds(self):
        now = datetime(2026, 7, 10, tzinfo=timezone.utc)
        with self.assertRaises(ValueError):
            period_bounds(ReportPeriod.CUSTOM, now)

    def test_custom_uses_supplied_bounds(self):
        now = datetime(2026, 7, 10, tzinfo=timezone.utc)
        custom_start = datetime(2026, 6, 1, tzinfo=timezone.utc)
        custom_end = datetime(2026, 6, 30, tzinfo=timezone.utc)
        start, end = period_bounds(ReportPeriod.CUSTOM, now, custom_start, custom_end)
        self.assertEqual((start, end), (custom_start, custom_end))


class TestFilterTradesByPeriod(unittest.TestCase):
    def test_only_trades_within_bounds_included(self):
        start = datetime(2026, 7, 1, tzinfo=timezone.utc)
        end = datetime(2026, 7, 10, tzinfo=timezone.utc)
        inside = make_executed_trade(index=0, opened_at=datetime(2026, 7, 5, tzinfo=timezone.utc))
        outside = make_executed_trade(index=1, opened_at=datetime(2026, 8, 1, tzinfo=timezone.utc))
        filtered = filter_trades_by_period([inside, outside], start, end)
        self.assertEqual(filtered, (inside,))


if __name__ == "__main__":
    unittest.main()
