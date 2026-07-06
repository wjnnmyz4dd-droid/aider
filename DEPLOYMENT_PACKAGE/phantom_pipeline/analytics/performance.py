"""Performance statistics (ADR-010 §9) — computed from real recorded
outcomes only, never fabricated (the direct idea behind `phantom/
analytics.py`'s `StrategyPerformanceTracker`, studied per ADR-010 §15,
not reused verbatim: its hand-maintained strategy list is explicitly
rejected — see `attribution.py`).

Only `TradeProvenanceRecord`s with a `CLOSED` `final_outcome` and a
non-`None` `realized_pnl` contribute to these statistics — an open or
rejected trade has no realized result to measure.
"""

from __future__ import annotations

from datetime import datetime
from typing import Sequence

from .config import ANALYTICS_VERSION
from .models import OutcomeKind, PerformanceStatistics, TradeProvenanceRecord


def _closed_pnls(records: Sequence[TradeProvenanceRecord]):
    return [
        r.final_outcome.realized_pnl
        for r in records
        if r.final_outcome is not None
        and r.final_outcome.outcome_kind == OutcomeKind.CLOSED
        and r.final_outcome.realized_pnl is not None
    ]


def compute_performance_statistics(records: Sequence[TradeProvenanceRecord], now: datetime) -> PerformanceStatistics:
    pnls = _closed_pnls(records)
    trade_count = len(pnls)
    if trade_count == 0:
        return PerformanceStatistics(
            trade_count=0, win_rate=None, profit_factor=None, sharpe=None, sortino=None,
            expectancy=None, average_mae=None, average_mfe=None, max_drawdown=None,
            generated_at=now, analytics_version=ANALYTICS_VERSION,
        )

    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    win_rate = len(wins) / trade_count
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss
    elif gross_profit > 0:
        profit_factor = float("inf")
    else:
        profit_factor = None

    expectancy = sum(pnls) / trade_count
    variance = sum((p - expectancy) ** 2 for p in pnls) / trade_count
    stdev = variance ** 0.5
    sharpe = (expectancy / stdev) if stdev > 0 else None

    downside_variance = (sum(p**2 for p in losses) / trade_count) if losses else 0.0
    downside_stdev = downside_variance ** 0.5
    sortino = (expectancy / downside_stdev) if downside_stdev > 0 else None

    closed_records = [
        r for r in records
        if r.final_outcome is not None and r.final_outcome.outcome_kind == OutcomeKind.CLOSED
    ]
    maes = [r.final_outcome.mae for r in closed_records if r.final_outcome.mae is not None]
    mfes = [r.final_outcome.mfe for r in closed_records if r.final_outcome.mfe is not None]
    average_mae = sum(maes) / len(maes) if maes else None
    average_mfe = sum(mfes) / len(mfes) if mfes else None

    cumulative = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for pnl in pnls:
        cumulative += pnl
        peak = max(peak, cumulative)
        max_drawdown = max(max_drawdown, peak - cumulative)

    return PerformanceStatistics(
        trade_count=trade_count,
        win_rate=win_rate,
        profit_factor=profit_factor,
        sharpe=sharpe,
        sortino=sortino,
        expectancy=expectancy,
        average_mae=average_mae,
        average_mfe=average_mfe,
        max_drawdown=max_drawdown,
        generated_at=now,
        analytics_version=ANALYTICS_VERSION,
    )
