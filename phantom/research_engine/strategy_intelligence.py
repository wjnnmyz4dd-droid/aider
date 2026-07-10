"""Strategy Intelligence (ADR-029 §5): win rate, profit factor,
drawdown, average R, ranked. Regime/session/pair performance for a
given strategy are available via `attribution.py`'s own
`STRATEGY`/`REGIME`/`SESSION`/`PAIR` buckets -- never recomputed here a
second way."""

from __future__ import annotations

from typing import Sequence, Tuple

from .attribution import DIMENSION_KEY_FUNCS
from .config import ResearchEngineConfig
from .models import AttributionDimension, ClosedTrade, Ranking
from .ranking import build_rankings


def rank_strategies(trades: Sequence[ClosedTrade], config: ResearchEngineConfig) -> Tuple[Ranking, ...]:
    return build_rankings(trades, DIMENSION_KEY_FUNCS[AttributionDimension.STRATEGY], config)


__all__ = ["rank_strategies"]
