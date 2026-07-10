"""The pair-eligibility hard gate (ADR-026 Hard Rules 4-5).

Checked before any strategy's own qualification logic runs. A pair
outside a strategy's approved universe is `NOT_ELIGIBLE`,
unconditionally -- never partially eligible, never blended into the
qualification score.
"""

from __future__ import annotations

from typing import Optional

from .config import StrategyEngineConfig
from .models import QualificationResult, QualificationStatus, StrategyId


def check_eligibility(strategy_id: StrategyId, pair: str, config: StrategyEngineConfig) -> Optional[QualificationResult]:
    """Returns a `NOT_ELIGIBLE` `QualificationResult` if `pair` is
    outside `strategy_id`'s approved universe; `None` if the caller
    should proceed to that strategy's own `qualify()` logic."""
    approved = config.approved_pairs_for(strategy_id)
    if pair in approved:
        return None
    return QualificationResult(
        strategy_id=strategy_id,
        pair=pair,
        status=QualificationStatus.NOT_ELIGIBLE,
        score=0.0,
        confidence=0.0,
        reason="Pair not supported by strategy",
        strengths=(),
        weaknesses=(f"{pair} is not in {strategy_id.value}'s approved pair universe",),
    )


__all__ = ["check_eligibility"]
