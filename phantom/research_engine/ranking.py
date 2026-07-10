"""Shared ranking builder (ADR-029 §5): one function, reused by
`pair_intelligence.py`, `strategy_intelligence.py`, and
`session_intelligence.py`, differing only in their grouping key
(CLAUDE.md §6). Ranked by expectancy, ties broken by sample size --
never randomized (the same discipline `ADR-026`'s selection cascade and
`ADR-027`'s sizing already established)."""

from __future__ import annotations

from collections import defaultdict
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .attribution import compute_bucket_statistics
from .config import ResearchEngineConfig
from .models import ClosedTrade, Ranking, executed_trades


def _average_hold_time_seconds(group: Sequence[ClosedTrade]) -> float:
    if not group:
        return 0.0
    return sum((t.closed_at - t.opened_at).total_seconds() for t in group) / len(group)


def build_rankings(
    trades: Sequence[ClosedTrade], key_func: Callable[[ClosedTrade], Optional[str]], config: ResearchEngineConfig,
) -> Tuple[Ranking, ...]:
    groups: Dict[str, List[ClosedTrade]] = defaultdict(list)
    for trade in executed_trades(trades):
        key = key_func(trade)
        if key is not None:
            groups[key].append(trade)

    entries = []
    for key, group in groups.items():
        if len(group) < config.min_sample_size_for_ranking:
            continue
        stats = compute_bucket_statistics(group, config)
        entries.append((key, len(group), stats, _average_hold_time_seconds(group)))

    def sort_key(entry):
        _, sample_size, stats, _ = entry
        expectancy = stats.rolling_expectancy if stats.rolling_expectancy is not None else float("-inf")
        return (-expectancy, -sample_size, entry[0])

    entries.sort(key=sort_key)
    return tuple(
        Ranking(key=key, rank=i + 1, sample_size=size, statistics=stats, average_hold_time_seconds=hold)
        for i, (key, size, stats, hold) in enumerate(entries)
    )


__all__ = ["build_rankings"]
