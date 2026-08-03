"""Per-check unit tests (ADR-006 §6-§14, §18)."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from phantom_pipeline.compliance_engine import checks as c
from phantom_pipeline.compliance_engine.config import ComplianceEngineConfig
from phantom_pipeline.compliance_engine.models import CheckStatus, NewsBlackoutWindow, NewsCalendarState
from phantom_pipeline.scanner.models import Direction
from tests.phantom_pipeline.compliance_engine._fixtures import SYMBOL, T0, make_account_state


class TestKillSwitchGate(unittest.TestCase):
    def test_not_triggered_passes(self):
        result = c.kill_switch_gate(False, None)
        self.assertEqual(result.status, CheckStatus.PASSED)

    def test_triggered_fails(self):
        result = c.kill_switch_gate(True, "total_drawdown_breach")
        self.assertEqual(result.status, CheckStatus.FAILED)


class TestDailyDrawdown(unittest.TestCase):
    def test_missing_account_state_is_unevaluable(self):
        result = c.daily_drawdown(None, ComplianceEngineConfig(), locked_out=False)
        self.assertEqual(result.status, CheckStatus.UNEVALUABLE)

    def test_below_threshold_passes(self):
        config = ComplianceEngineConfig(max_daily_drawdown_percent=3.0)
        account = make_account_state(daily_drawdown_pct=1.0)
        result = c.daily_drawdown(account, config, locked_out=False)
        self.assertEqual(result.status, CheckStatus.PASSED)

    def test_at_or_above_threshold_fails(self):
        config = ComplianceEngineConfig(max_daily_drawdown_percent=3.0)
        account = make_account_state(daily_drawdown_pct=3.0)
        result = c.daily_drawdown(account, config, locked_out=False)
        self.assertEqual(result.status, CheckStatus.FAILED)

    def test_already_locked_out_fails_regardless_of_current_drawdown(self):
        config = ComplianceEngineConfig(max_daily_drawdown_percent=3.0)
        account = make_account_state(daily_drawdown_pct=0.0)
        result = c.daily_drawdown(account, config, locked_out=True)
        self.assertEqual(result.status, CheckStatus.FAILED)


class TestTotalDrawdown(unittest.TestCase):
    def test_missing_account_state_is_unevaluable(self):
        result = c.total_drawdown(None, ComplianceEngineConfig())
        self.assertEqual(result.status, CheckStatus.UNEVALUABLE)

    def test_below_threshold_passes(self):
        config = ComplianceEngineConfig(max_total_drawdown_percent=8.0)
        account = make_account_state(total_drawdown_pct=1.0)
        result = c.total_drawdown(account, config)
        self.assertEqual(result.status, CheckStatus.PASSED)

    def test_at_or_above_threshold_fails(self):
        config = ComplianceEngineConfig(max_total_drawdown_percent=8.0)
        account = make_account_state(total_drawdown_pct=8.0)
        result = c.total_drawdown(account, config)
        self.assertEqual(result.status, CheckStatus.FAILED)


class TestNewsRestriction(unittest.TestCase):
    def test_missing_news_state_is_unevaluable(self):
        result = c.news_restriction(None, SYMBOL, T0)
        self.assertEqual(result.status, CheckStatus.UNEVALUABLE)

    def test_stale_feed_is_unevaluable(self):
        state = NewsCalendarState(feed_stale=True, blackout_windows=())
        result = c.news_restriction(state, SYMBOL, T0)
        self.assertEqual(result.status, CheckStatus.UNEVALUABLE)

    def test_naive_timestamp_is_unevaluable(self):
        state = NewsCalendarState(feed_stale=False, blackout_windows=())
        result = c.news_restriction(state, SYMBOL, datetime(2026, 7, 6, 10, 0, 0))
        self.assertEqual(result.status, CheckStatus.UNEVALUABLE)

    def test_unparseable_symbol_is_unevaluable(self):
        state = NewsCalendarState(feed_stale=False, blackout_windows=())
        result = c.news_restriction(state, "NOT_A_PAIR", T0)
        self.assertEqual(result.status, CheckStatus.UNEVALUABLE)

    def test_no_relevant_blackout_passes(self):
        state = NewsCalendarState(feed_stale=False, blackout_windows=())
        result = c.news_restriction(state, SYMBOL, T0)
        self.assertEqual(result.status, CheckStatus.PASSED)

    def test_active_blackout_for_relevant_currency_fails(self):
        window = NewsBlackoutWindow("USD", T0 - timedelta(minutes=15), T0 + timedelta(minutes=15))
        state = NewsCalendarState(feed_stale=False, blackout_windows=(window,))
        result = c.news_restriction(state, SYMBOL, T0)
        self.assertEqual(result.status, CheckStatus.FAILED)

    def test_blackout_for_irrelevant_currency_passes(self):
        window = NewsBlackoutWindow("JPY", T0 - timedelta(minutes=15), T0 + timedelta(minutes=15))
        state = NewsCalendarState(feed_stale=False, blackout_windows=(window,))
        result = c.news_restriction(state, SYMBOL, T0)
        self.assertEqual(result.status, CheckStatus.PASSED)


class TestSessionRestriction(unittest.TestCase):
    def test_naive_timestamp_is_unevaluable(self):
        result = c.session_restriction(ComplianceEngineConfig(), datetime(2026, 7, 6, 10, 0, 0))
        self.assertEqual(result.status, CheckStatus.UNEVALUABLE)

    def test_no_session_windows_configured_is_unevaluable(self):
        result = c.session_restriction(ComplianceEngineConfig(session_windows=()), T0)
        self.assertEqual(result.status, CheckStatus.UNEVALUABLE)

    def test_inside_configured_window_passes(self):
        # T0 = 10:00 UTC, inside the default LONDON window (07:00-16:00).
        result = c.session_restriction(ComplianceEngineConfig(), T0)
        self.assertEqual(result.status, CheckStatus.PASSED)

    def test_outside_all_configured_windows_fails(self):
        from phantom_pipeline.compliance_engine.config import SessionWindow

        config = ComplianceEngineConfig(session_windows=(SessionWindow("ONLY", 1, 0, 2, 0),))
        result = c.session_restriction(config, T0)
        self.assertEqual(result.status, CheckStatus.FAILED)


class TestWeekendRestriction(unittest.TestCase):
    def test_missing_market_status_is_unevaluable(self):
        result = c.weekend_restriction(None)
        self.assertEqual(result.status, CheckStatus.UNEVALUABLE)

    def test_open_market_passes(self):
        result = c.weekend_restriction("OPEN")
        self.assertEqual(result.status, CheckStatus.PASSED)

    def test_closed_market_fails(self):
        result = c.weekend_restriction("CLOSED_WEEKEND")
        self.assertEqual(result.status, CheckStatus.FAILED)


class TestSpreadValidation(unittest.TestCase):
    def test_missing_spread_is_unevaluable(self):
        result = c.spread_validation(None, SYMBOL, ComplianceEngineConfig())
        self.assertEqual(result.status, CheckStatus.UNEVALUABLE)

    def test_unconfigured_symbol_is_unevaluable(self):
        result = c.spread_validation(0.0001, SYMBOL, ComplianceEngineConfig())
        self.assertEqual(result.status, CheckStatus.UNEVALUABLE)

    def test_spread_within_threshold_passes(self):
        config = ComplianceEngineConfig(spread_thresholds={SYMBOL: 0.0005})
        result = c.spread_validation(0.0001, SYMBOL, config)
        self.assertEqual(result.status, CheckStatus.PASSED)

    def test_spread_above_threshold_fails(self):
        config = ComplianceEngineConfig(spread_thresholds={SYMBOL: 0.0005})
        result = c.spread_validation(0.001, SYMBOL, config)
        self.assertEqual(result.status, CheckStatus.FAILED)


class TestSlippageValidation(unittest.TestCase):
    def test_missing_expected_slippage_is_unevaluable(self):
        result = c.slippage_validation(None, SYMBOL, ComplianceEngineConfig())
        self.assertEqual(result.status, CheckStatus.UNEVALUABLE)

    def test_unconfigured_symbol_is_unevaluable(self):
        result = c.slippage_validation(0.0001, SYMBOL, ComplianceEngineConfig())
        self.assertEqual(result.status, CheckStatus.UNEVALUABLE)

    def test_slippage_within_threshold_passes(self):
        config = ComplianceEngineConfig(slippage_thresholds={SYMBOL: 0.0005})
        result = c.slippage_validation(0.0001, SYMBOL, config)
        self.assertEqual(result.status, CheckStatus.PASSED)

    def test_slippage_above_threshold_fails(self):
        config = ComplianceEngineConfig(slippage_thresholds={SYMBOL: 0.0005})
        result = c.slippage_validation(0.001, SYMBOL, config)
        self.assertEqual(result.status, CheckStatus.FAILED)


class TestMaxPositions(unittest.TestCase):
    def test_missing_account_state_is_unevaluable(self):
        result = c.max_positions(None, SYMBOL, Direction.UP, ComplianceEngineConfig())
        self.assertEqual(result.status, CheckStatus.UNEVALUABLE)

    def test_below_limits_passes(self):
        config = ComplianceEngineConfig(max_positions_per_symbol=3, max_positions_account_wide=6)
        account = make_account_state()
        result = c.max_positions(account, SYMBOL, Direction.UP, config)
        self.assertEqual(result.status, CheckStatus.PASSED)

    def test_at_per_symbol_limit_fails(self):
        from phantom_pipeline.compliance_engine.models import OpenPosition

        config = ComplianceEngineConfig(max_positions_per_symbol=2, max_positions_account_wide=10)
        account = make_account_state(
            open_positions=(
                OpenPosition(SYMBOL, Direction.UP),
                OpenPosition(SYMBOL, Direction.UP),
            )
        )
        result = c.max_positions(account, SYMBOL, Direction.UP, config)
        self.assertEqual(result.status, CheckStatus.FAILED)

    def test_at_account_wide_limit_fails(self):
        from phantom_pipeline.compliance_engine.models import OpenPosition

        config = ComplianceEngineConfig(max_positions_per_symbol=10, max_positions_account_wide=1)
        account = make_account_state(open_positions=(OpenPosition("GBPUSD", Direction.DOWN),))
        result = c.max_positions(account, SYMBOL, Direction.UP, config)
        self.assertEqual(result.status, CheckStatus.FAILED)

    def test_opposite_direction_same_symbol_does_not_count_toward_stacking_limit(self):
        from phantom_pipeline.compliance_engine.models import OpenPosition

        config = ComplianceEngineConfig(max_positions_per_symbol=1, max_positions_account_wide=10)
        account = make_account_state(open_positions=(OpenPosition(SYMBOL, Direction.DOWN),))
        result = c.max_positions(account, SYMBOL, Direction.UP, config)
        self.assertEqual(result.status, CheckStatus.PASSED)


if __name__ == "__main__":
    unittest.main()
