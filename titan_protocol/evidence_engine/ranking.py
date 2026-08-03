"""Pair ranking (ADR-024 §1 "Pair Ranking").

Ranks already-scored pairs highest-first. Never selects a trade -- it
only orders reports that already exist.
"""

from __future__ import annotations

from typing import Sequence, Tuple

from .models import EvidenceReport, PairRanking


def rank_pairs(reports: Sequence[EvidenceReport]) -> Tuple[PairRanking, ...]:
    """Sorted by composite score descending; ties broken by symbol name
    ascending so the ordering is fully deterministic regardless of
    input order."""
    ordered = sorted(reports, key=lambda r: (-r.score.composite, r.symbol))
    return tuple(
        PairRanking(symbol=report.symbol, rank=i + 1, score=report.score.composite)
        for i, report in enumerate(ordered)
    )


__all__ = ["rank_pairs"]
