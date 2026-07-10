"""Session Intelligence (ADR-029 §5): London, London/NY Overlap, Early
NY, Late NY, Asia -- ranked by the same shared builder."""

from __future__ import annotations

from typing import Sequence, Tuple

from .attribution import DIMENSION_KEY_FUNCS
from .config import ResearchEngineConfig
from .models import AttributionDimension, ClosedTrade, Ranking
from .ranking import build_rankings


def rank_sessions(trades: Sequence[ClosedTrade], config: ResearchEngineConfig) -> Tuple[Ranking, ...]:
    return build_rankings(trades, DIMENSION_KEY_FUNCS[AttributionDimension.SESSION], config)


__all__ = ["rank_sessions"]
