"""Learning / Recommendation Engine (ADR-029 §5): deterministic
threshold-based recommendation generation ONLY -- no ML, no LLM, no
automatic optimization, no parameter mutation (Hard Rule 1). Every
`Recommendation` is a plain sentence built from a real, measured delta
between two attribution buckets, never a generated narrative.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Callable, Dict, List, Optional, Sequence

from .config import ResearchEngineConfig
from .effectiveness import compare_buckets
from .models import ClosedTrade, EffectivenessComparison, PerformanceAttribution, Recommendation, executed_trades


def _confidence_tag(sample_size: int, config: ResearchEngineConfig) -> str:
    if sample_size >= config.high_confidence_sample_size:
        return "HIGH"
    if sample_size >= config.medium_confidence_sample_size:
        return "MEDIUM"
    return "LOW"


def _notable_delta(comparison: EffectivenessComparison, config: ResearchEngineConfig) -> bool:
    if comparison.delta is None:
        return False
    if comparison.comparison_sample_size < config.min_sample_size_for_recommendation:
        return False
    return abs(comparison.delta) >= config.recommendation_expectancy_delta_threshold


def recommendations_from_attribution(
    attributions: Sequence[PerformanceAttribution], overall: EffectivenessComparison, config: ResearchEngineConfig,
) -> List[Recommendation]:
    """One recommendation per attribution bucket whose expectancy
    deviates notably from the overall baseline."""

    recommendations: List[Recommendation] = []
    overall_expectancy = overall.comparison_expectancy
    if overall_expectancy is None:
        return recommendations

    for attribution in attributions:
        for bucket in attribution.buckets:
            if not bucket.statistics.sufficient_data or bucket.statistics.rolling_expectancy is None:
                continue
            if bucket.sample_size < config.min_sample_size_for_recommendation:
                continue
            delta = bucket.statistics.rolling_expectancy - overall_expectancy
            if abs(delta) < config.recommendation_expectancy_delta_threshold:
                continue
            direction = "outperforms" if delta > 0 else "underperforms"
            text = (
                f"{attribution.dimension.value} = {bucket.key!r} {direction} the overall average "
                f"(expectancy {bucket.statistics.rolling_expectancy:+.2f}R vs {overall_expectancy:+.2f}R baseline, n={bucket.sample_size})."
            )
            recommendations.append(Recommendation(
                text=text, supporting_dimension=attribution.dimension.value,
                supporting_data=f"bucket={bucket.key}, n={bucket.sample_size}, delta={delta:+.2f}R",
                confidence=_confidence_tag(bucket.sample_size, config),
            ))
    return recommendations


def _pair_strategy_key(t: ClosedTrade) -> Optional[str]:
    if t.strategy_id is None:
        return None
    return f"{t.pair} {t.strategy_id.value}"


def cross_dimension_recommendations(
    trades: Sequence[ClosedTrade], secondary_key_func: Callable[[ClosedTrade], Optional[str]],
    secondary_label: str, config: ResearchEngineConfig,
) -> List[Recommendation]:
    """Matches the task's own worked examples directly -- e.g. "EURUSD
    Trend Continuation performs better in London than NY" is exactly a
    (pair, strategy) x session cross-tabulation: each secondary-
    dimension slice is compared against the *same* pair+strategy's
    other trades, isolating that dimension's specific effect."""

    groups: Dict[str, List[ClosedTrade]] = defaultdict(list)
    for trade in executed_trades(trades):
        key = _pair_strategy_key(trade)
        if key is not None:
            groups[key].append(trade)

    recommendations: List[Recommendation] = []
    for primary_key, group in sorted(groups.items()):
        sub: Dict[str, List[ClosedTrade]] = defaultdict(list)
        for trade in group:
            secondary_key = secondary_key_func(trade)
            if secondary_key is not None:
                sub[secondary_key].append(trade)

        for secondary_key, sub_group in sorted(sub.items()):
            baseline = [t for t in group if secondary_key_func(t) != secondary_key]
            comparison = compare_buckets(f"{primary_key}|{secondary_label}={secondary_key}", baseline, sub_group, config)
            if not _notable_delta(comparison, config):
                continue
            direction = "better" if comparison.delta > 0 else "worse"
            text = (
                f"{primary_key} performs {direction} when {secondary_label} = {secondary_key} "
                f"than otherwise (delta {comparison.delta:+.2f}R, n={comparison.comparison_sample_size})."
            )
            recommendations.append(Recommendation(
                text=text, supporting_dimension=f"{primary_key}|{secondary_label}",
                supporting_data=f"n={comparison.comparison_sample_size}, delta={comparison.delta:+.2f}R",
                confidence=_confidence_tag(comparison.comparison_sample_size, config),
            ))
    return recommendations


__all__ = ["recommendations_from_attribution", "cross_dimension_recommendations", "_pair_strategy_key"]
