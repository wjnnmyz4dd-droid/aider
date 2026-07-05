"""Shared test-only fixtures for the Dashboard test suite."""

from __future__ import annotations

from datetime import datetime, timezone

from phantom_pipeline.analytics.models import PerformanceStatistics, TradeProvenanceRecord

T0 = datetime(2026, 7, 5, 12, 0, 0, tzinfo=timezone.utc)


def make_trade_record(trace_id: str = "trace-1", **overrides) -> TradeProvenanceRecord:
    kwargs = dict(
        schema_version=1,
        trace_id=trace_id,
        scanner_observation=None,
        candidate=None,
        score_result=None,
        risk_decision=None,
        compliance_decision=None,
        execution_decision=None,
        broker_events=(),
        fill_reports=(),
        position_management_decisions=(),
        position_updates=(),
        position_synchronization_results=(),
        account_snapshots=(),
        market_snapshots=(),
        final_outcome=None,
        analytics_version="1.0.0-phase1",
        collected_at=T0,
    )
    kwargs.update(overrides)
    return TradeProvenanceRecord(**kwargs)


def make_performance_statistics(**overrides) -> PerformanceStatistics:
    kwargs = dict(
        trade_count=1,
        win_rate=1.0,
        profit_factor=None,
        sharpe=None,
        sortino=None,
        expectancy=100.0,
        average_mae=None,
        average_mfe=None,
        max_drawdown=None,
        generated_at=T0,
        analytics_version="1.0.0-phase1",
    )
    kwargs.update(overrides)
    return PerformanceStatistics(**kwargs)
