"""Strategy / Pair / Session Tournament (ADR-030 §5.4): thin wrappers
over `research_engine`'s already-accepted ranking builders -- the
ranking logic itself is never reimplemented here (ADR-030 §0, Hard Rule
5). The only new code is widening `Ranking` into a `TournamentEntry`
that additionally surfaces `recovery_factor`."""

from __future__ import annotations

from typing import Sequence, Tuple

from titan_protocol.research_engine.models import ClosedTrade, Ranking
from titan_protocol.research_engine.pair_intelligence import rank_pairs
from titan_protocol.research_engine.session_intelligence import rank_sessions
from titan_protocol.research_engine.strategy_intelligence import rank_strategies

from .config import ValidationEngineConfig
from .models import TournamentEntry


def _to_tournament_entry(ranking: Ranking) -> TournamentEntry:
    return TournamentEntry(
        subject=ranking.key, rank=ranking.rank, sample_size=ranking.sample_size,
        statistics=ranking.statistics, recovery_factor=ranking.statistics.recovery_factor,
    )


def run_strategy_tournament(trades: Sequence[ClosedTrade], config: ValidationEngineConfig) -> Tuple[TournamentEntry, ...]:
    return tuple(_to_tournament_entry(r) for r in rank_strategies(trades, config.research_config))


def run_pair_tournament(trades: Sequence[ClosedTrade], config: ValidationEngineConfig) -> Tuple[TournamentEntry, ...]:
    return tuple(_to_tournament_entry(r) for r in rank_pairs(trades, config.research_config))


def run_session_tournament(trades: Sequence[ClosedTrade], config: ValidationEngineConfig) -> Tuple[TournamentEntry, ...]:
    return tuple(_to_tournament_entry(r) for r in rank_sessions(trades, config.research_config))


__all__ = ["run_strategy_tournament", "run_pair_tournament", "run_session_tournament"]
