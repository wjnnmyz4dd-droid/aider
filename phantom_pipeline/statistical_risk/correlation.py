"""Correlation-adjusted portfolio exposure recommendations (`ADR-022` §1,
capability 15).

Reuses `risk_engine.models.OpenPosition.correlation_bucket` verbatim
(`ADR-022` §2) — this module never assigns its own, second bucket to a
symbol; a position whose bucket is `None` (unevaluable, exactly per
`risk_engine.config`'s own "absent from the mapping" convention) is
counted separately and never silently folded into a named bucket.
"""

from __future__ import annotations

from collections import Counter
from typing import Sequence

from ..risk_engine.models import OpenPosition
from .config import DEFAULT_CONFIG, StatisticalRiskConfig
from .models import CorrelationState, RiskRecommendation

UNEVALUATED_BUCKET = "UNEVALUATED"


def build_correlation_state(
    open_positions: Sequence[OpenPosition], config: StatisticalRiskConfig = DEFAULT_CONFIG
) -> CorrelationState:
    counts = Counter(
        position.correlation_bucket if position.correlation_bucket is not None else UNEVALUATED_BUCKET
        for position in open_positions
    )
    flagged = tuple(
        sorted(
            bucket
            for bucket, count in counts.items()
            if count >= config.position_concentration_warning_count
        )
    )
    most_concentrated = max(counts, key=lambda b: counts[b]) if counts else None
    max_count = counts[most_concentrated] if most_concentrated is not None else 0

    return CorrelationState(
        bucket_exposure_count=dict(counts),
        most_concentrated_bucket=most_concentrated,
        max_bucket_concentration_count=max_count,
        flagged_buckets=flagged,
    )


def recommendation_for_correlation(state: CorrelationState) -> RiskRecommendation:
    if UNEVALUATED_BUCKET in state.flagged_buckets:
        return RiskRecommendation.REDUCE_RISK_50
    if state.flagged_buckets:
        return RiskRecommendation.REDUCE_RISK_25
    return RiskRecommendation.NORMAL_RISK


__all__ = ["UNEVALUATED_BUCKET", "build_correlation_state", "recommendation_for_correlation"]
