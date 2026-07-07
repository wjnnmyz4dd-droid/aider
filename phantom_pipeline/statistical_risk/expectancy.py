"""Rolling expectancy/win-rate/profit-factor/Sharpe/Sortino (`ADR-022`
§1, capabilities 2-6).

`analytics.performance.compute_performance_statistics` already computes
the **whole-sample** versions of every one of these five statistics
(`ADR-022` §1, Hard Rule 8 — "no duplicate computation") — this module
never re-derives those. It computes only the **rolling** (trailing-
window) variant: the same formulas applied to the most recent
`StatisticalRiskConfig.rolling_window_trades` closed trades, a genuinely
different (and, unlike the whole-sample figures, time-varying) number.

`closed_trade_pnls()` is the shared "which trades count" filter every
other module in this package reuses (`probability.py`, `drawdown.py`,
`monte_carlo.py`) — one definition, never a second independent filter
that could silently drift from this one.
"""

from __future__ import annotations

from typing import List, Optional, Sequence

from ..analytics.models import OutcomeKind, TradeProvenanceRecord
from .config import DEFAULT_CONFIG, StatisticalRiskConfig


def closed_trade_pnls(records: Sequence[TradeProvenanceRecord]) -> List[float]:
    """Realized P/L for every record with a `CLOSED` final outcome, in
    the same order `records` was supplied — the caller is responsible
    for supplying `records` in chronological order; this function never
    reorders them (a rolling window depends on that order)."""
    return [
        r.final_outcome.realized_pnl
        for r in records
        if r.final_outcome is not None
        and r.final_outcome.outcome_kind == OutcomeKind.CLOSED
        and r.final_outcome.realized_pnl is not None
    ]


def rolling_window_pnls(
    records: Sequence[TradeProvenanceRecord],
    config: StatisticalRiskConfig = DEFAULT_CONFIG,
) -> List[float]:
    pnls = closed_trade_pnls(records)
    if config.rolling_window_trades <= 0:
        return pnls
    return pnls[-config.rolling_window_trades :]


def rolling_win_rate(pnls: Sequence[float]) -> Optional[float]:
    if not pnls:
        return None
    wins = sum(1 for p in pnls if p > 0)
    return wins / len(pnls)


def rolling_profit_factor(pnls: Sequence[float]) -> Optional[float]:
    if not pnls:
        return None
    gross_profit = sum(p for p in pnls if p > 0)
    gross_loss = abs(sum(p for p in pnls if p < 0))
    if gross_loss > 0:
        return gross_profit / gross_loss
    if gross_profit > 0:
        return float("inf")
    return None


def rolling_expectancy(pnls: Sequence[float]) -> Optional[float]:
    if not pnls:
        return None
    return sum(pnls) / len(pnls)


def rolling_sharpe_ratio(pnls: Sequence[float]) -> Optional[float]:
    expectancy = rolling_expectancy(pnls)
    if expectancy is None or len(pnls) < 2:
        return None
    variance = sum((p - expectancy) ** 2 for p in pnls) / len(pnls)
    stdev = variance**0.5
    return (expectancy / stdev) if stdev > 0 else None


def rolling_sortino_ratio(pnls: Sequence[float]) -> Optional[float]:
    expectancy = rolling_expectancy(pnls)
    if expectancy is None or len(pnls) < 2:
        return None
    losses = [p for p in pnls if p < 0]
    if not losses:
        return None
    downside_variance = sum(p**2 for p in losses) / len(pnls)
    downside_stdev = downside_variance**0.5
    return (expectancy / downside_stdev) if downside_stdev > 0 else None


def confidence_interval_bounds(
    pnls: Sequence[float], confidence_level: float
) -> "tuple[Optional[float], Optional[float]]":
    """A normal-approximation confidence interval on the mean P/L
    (`ADR-022` §1, capability 20) — `None`/`None` when fewer than two
    samples exist (Hard Rule 7: no honest standard error from one point).
    Uses a fixed z-table for the three confidence levels this package's
    config exposes, never a fabricated critical value."""
    if len(pnls) < 2:
        return None, None
    mean = sum(pnls) / len(pnls)
    variance = sum((p - mean) ** 2 for p in pnls) / (len(pnls) - 1)
    stderr = (variance / len(pnls)) ** 0.5
    z = _z_score(confidence_level)
    margin = z * stderr
    return mean - margin, mean + margin


_Z_TABLE = {0.90: 1.645, 0.95: 1.96, 0.99: 2.576}


def _z_score(confidence_level: float) -> float:
    return _Z_TABLE.get(round(confidence_level, 2), 1.96)


__all__ = [
    "closed_trade_pnls",
    "rolling_window_pnls",
    "rolling_win_rate",
    "rolling_profit_factor",
    "rolling_expectancy",
    "rolling_sharpe_ratio",
    "rolling_sortino_ratio",
    "confidence_interval_bounds",
]
