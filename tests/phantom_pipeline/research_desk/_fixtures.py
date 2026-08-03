"""Shared test-only fixtures for the Phantom AI Research Desk tests.
Reuses `tests.phantom_pipeline.knowledge._fixtures` for
`TradeProvenanceRecord`/`ScannerObservation` construction rather than
duplicating it, and adds `PeriodReport`/`NewsCalendarState` builders this
package's own tests need.
"""

from __future__ import annotations

from datetime import datetime, timezone

from phantom_pipeline.compliance_engine.models import NewsBlackoutWindow, NewsCalendarState
from phantom_pipeline.paper_trading.forward_test_engine import ForwardTestReport
from phantom_pipeline.paper_trading.report_generator import PeriodReport
from tests.phantom_pipeline.knowledge._fixtures import (  # noqa: F401
    SYMBOL,
    T0,
    make_candidate,
    make_compliance_decision,
    make_execution_decision,
    make_position_management_decision,
    make_risk_decision,
    make_scanner_observation,
    make_score_result,
    make_trade_provenance_record,
)

NOW = T0


def make_news_calendar_state(stale: bool = False, currencies=("USD",)) -> NewsCalendarState:
    windows = tuple(NewsBlackoutWindow(currency=c, start=NOW, end=NOW) for c in currencies)
    return NewsCalendarState(feed_stale=stale, blackout_windows=windows if not stale else ())


def make_forward_test_report() -> ForwardTestReport:
    return ForwardTestReport(
        schema_version=1, generated_at=NOW, window_start=NOW, window_end=NOW, trade_count=10,
        win_rate=0.6, profit_factor=1.5, expectancy=10.0, average_rr=1.8, max_drawdown=5.0,
        daily_drawdown_pct=1.0, total_drawdown_pct=2.0, average_validation_latency_seconds=0.01,
        average_broker_latency_seconds=0.02, average_fill_latency_seconds=0.03, average_slippage=0.0001,
        slippage_sample_size=10, missed_trade_count=1, blocked_trade_count=2, duplicate_prevention_count=0,
        recovery_attempt_count=0, recovery_success_rate=1.0, average_recovery_time_seconds=0.0,
        analytics_version="1.0.0-phase1",
    )


def make_period_report(
    worst_pair="GBPUSD", worst_session="TOKYO", worst_regime="MARKDOWN",
    compliance_blocks=None, execution_blocks=None, forward_test_report=None,
) -> PeriodReport:
    return PeriodReport(
        schema_version=1, period_kind="WEEKLY", window_start=NOW, window_end=NOW, generated_at=NOW,
        forward_test_report=forward_test_report or make_forward_test_report(), prop_firm_status=None,
        best_pair="EURUSD", worst_pair=worst_pair, best_session="LONDON", worst_session=worst_session,
        best_regime="MARKUP", worst_regime=worst_regime,
        biggest_winner_trace_id="t1", biggest_winner_pnl=100.0, biggest_loser_trace_id="t2", biggest_loser_pnl=-50.0,
        compliance_blocks_by_check=compliance_blocks if compliance_blocks is not None else {"NEWS_BLACKOUT": 5, "SPREAD_LIMIT": 1},
        execution_blocks_by_check=execution_blocks if execution_blocks is not None else {},
        compliance_decisions_by_verdict={"APPROVE": 8, "BLOCK": 2},
        kill_switch_active=False, daily_lockout_active=False,
    )
