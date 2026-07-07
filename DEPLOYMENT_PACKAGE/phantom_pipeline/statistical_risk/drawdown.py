"""Drawdown statistics (`ADR-022` §1, capability 7; §1 `expected_drawdown`
field).

`analytics.performance.compute_performance_statistics` already computes
**whole-sample** maximum drawdown (`ADR-022` Hard Rule 8) — this module
computes the **rolling** (windowed) maximum drawdown instead, over the
same trailing window `expectancy.py` uses for its own rolling stats, and
the **expected** (forward-looking, Monte-Carlo-derived) drawdown, which
has no existing implementation anywhere in the repository.
"""

from __future__ import annotations

from typing import Optional, Sequence

from .models import MonteCarloResult


def rolling_max_drawdown(pnls: Sequence[float]) -> Optional[float]:
    """Peak-to-trough drawdown (in the same currency units as `pnls`)
    over the rolling window's cumulative P/L curve — `None` when the
    window is empty."""
    if not pnls:
        return None
    cumulative = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for pnl in pnls:
        cumulative += pnl
        peak = max(peak, cumulative)
        max_drawdown = max(max_drawdown, peak - cumulative)
    return max_drawdown


def expected_drawdown(monte_carlo_result: Optional[MonteCarloResult]) -> Optional[float]:
    """The mean peak-to-trough drawdown percentage observed across every
    simulated equity path (`ADR-022` §1 Hard Rule 7) — `None` when no
    simulation was run (e.g. insufficient historical sample)."""
    if monte_carlo_result is None:
        return None
    return monte_carlo_result.mean_max_drawdown_pct


__all__ = ["rolling_max_drawdown", "expected_drawdown"]
