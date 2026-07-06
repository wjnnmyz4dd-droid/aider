"""Deterministic, read-only ranking over already-computed scores
(ADR-004 §7, §9, §13).

`rank_scores()` is a pure function: it never calls `ScoringEngine.score()`
or any scoring rule, never mutates its input, and never alters any
`ScoreResult`'s own fields (structurally impossible — `ScoreResult` is
frozen). Ranking is a post-hoc view over scores that already exist, not
a step in computing them (§7).
"""

from __future__ import annotations

from typing import Sequence, Tuple

from .models import ScoreResult


def rank_scores(results: Sequence[ScoreResult]) -> Tuple[ScoreResult, ...]:
    """Return a new tuple of `results` ordered by `overall_score`
    descending, tie-broken by `candidate_id` ascending (a stable,
    content-derived tiebreak — never insertion order) for full
    determinism regardless of the input sequence's own order."""

    return tuple(
        sorted(results, key=lambda r: (-r.overall_score, r.candidate_id))
    )
