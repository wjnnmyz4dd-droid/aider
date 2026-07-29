"""The cross-pair selection contract (ADR-037 §6): a pure, side-effect-
free function of a candidate-set input, deliberately without a ranking
formula or weights beyond the closed product-policy decision (score
alone, `<=` inclusive tolerance-band tie, reject-on-tie).

Reimplements the tiny tolerance-band comparison locally rather than
importing `strategy_engine.selection._narrow_by` -- that function is
module-private (`strategy_engine/selection.py`'s own `__all__ =
["select_winning_strategy"]`), so importing it from another package
would be an ordinary encapsulation violation. Reusing the established
*algorithm* while not importing private cross-package code is the
correct minimal-change choice: three duplicated lines, never a
forbidden dependency.
"""

from __future__ import annotations

from typing import Tuple

from .models import OpportunityCandidate, SelectionOutcome


def select_winner(candidates: Tuple[OpportunityCandidate, ...], tie_tolerance: float) -> SelectionOutcome:
    if not candidates:
        return SelectionOutcome(winner=None, reason="no candidates")

    best = max(c.score for c in candidates)
    tied = [c for c in candidates if best - c.score <= tie_tolerance]

    if len(tied) == 1:
        return SelectionOutcome(winner=tied[0].pair, reason="single candidate")

    # Still tied after the tolerance-band comparison: reject, never
    # randomize or fall back to a secondary criterion -- reject-on-tie
    # is the closed product-policy decision (ADR-037 ranking/tie/
    # session-policy decision).
    return SelectionOutcome(winner=None, reason="tie within tolerance")


__all__ = ["select_winner"]
