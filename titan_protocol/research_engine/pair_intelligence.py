"""Pair Intelligence (ADR-029 §5): win rate, profit factor, Sharpe,
Sortino, expectancy, average R, drawdown, and average hold time per
pair, ranked."""

from __future__ import annotations

from typing import Sequence, Tuple

from .attribution import DIMENSION_KEY_FUNCS
from .config import ResearchEngineConfig
from .models import AttributionDimension, ClosedTrade, Ranking
from .ranking import build_rankings


def rank_pairs(trades: Sequence[ClosedTrade], config: ResearchEngineConfig) -> Tuple[Ranking, ...]:
    return build_rankings(trades, DIMENSION_KEY_FUNCS[AttributionDimension.PAIR], config)


__all__ = ["rank_pairs"]
