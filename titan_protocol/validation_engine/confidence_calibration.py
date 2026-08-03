"""Confidence Calibration (ADR-030 §5.11): verifies that Risk Engine's
existing confidence-tier assignments actually correlate with realized
outcomes -- higher tiers should not show materially worse expectancy
than lower tiers. Tier ordering reuses `risk_engine.config.
DEFAULT_CONFIDENCE_SCHEDULE`'s own `min_score` ordering -- never a
second, invented ranking (ADR-030 Hard Rule 5). Statistics reuse
`research_engine.attribution.compute_bucket_statistics`."""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Sequence

from titan_protocol.research_engine.attribution import compute_bucket_statistics
from titan_protocol.research_engine.models import ClosedTrade, executed_trades
from titan_protocol.risk_engine.config import DEFAULT_CONFIDENCE_SCHEDULE

from .config import ValidationEngineConfig
from .models import ConfidenceCalibrationResult, ConfidenceTierStatistics

_TIER_ORDER: Dict[str, float] = {tier.label: tier.min_score for tier in DEFAULT_CONFIDENCE_SCHEDULE}


def _tier_sort_key(label: str) -> float:
    return _TIER_ORDER.get(label, float("-inf"))


def run_confidence_calibration(trades: Sequence[ClosedTrade], config: ValidationEngineConfig) -> ConfidenceCalibrationResult:
    groups: Dict[str, List[ClosedTrade]] = defaultdict(list)
    for trade in executed_trades(trades):
        if trade.risk_confidence_tier is not None:
            groups[trade.risk_confidence_tier].append(trade)

    tiers_ascending = sorted(groups, key=_tier_sort_key)
    tier_statistics = tuple(
        ConfidenceTierStatistics(tier=tier, sample_size=len(groups[tier]), statistics=compute_bucket_statistics(groups[tier], config.research_config))
        for tier in tiers_ascending
    )

    notes: List[str] = []
    well_calibrated = True
    for lower, higher in zip(tier_statistics, tier_statistics[1:]):
        if (
            lower.sample_size < config.min_sample_size_for_calibration_tier
            or higher.sample_size < config.min_sample_size_for_calibration_tier
            or lower.statistics.rolling_expectancy is None
            or higher.statistics.rolling_expectancy is None
        ):
            continue
        delta = higher.statistics.rolling_expectancy - lower.statistics.rolling_expectancy
        if delta <= -config.degradation_expectancy_delta_threshold:
            well_calibrated = False
            notes.append(
                f"tier {higher.tier!r} (expectancy {higher.statistics.rolling_expectancy:.2f}R) underperforms "
                f"lower tier {lower.tier!r} (expectancy {lower.statistics.rolling_expectancy:.2f}R) by {abs(delta):.2f}R"
            )

    if not notes:
        notes.append("no miscalibration detected among tiers with sufficient sample size")

    return ConfidenceCalibrationResult(tier_statistics=tier_statistics, well_calibrated=well_calibrated, notes=tuple(notes))


__all__ = ["run_confidence_calibration"]
