"""Drift Detection (ADR-030 §5.10): current performance vs. historical
baseline performance, per strategy/pair/session/regime and per
execution quality. Grouping and statistics reuse
`research_engine.attribution`'s already-accepted dimension key
functions and `compute_bucket_statistics` -- never a second
implementation (ADR-030 Hard Rule 5)."""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Sequence

from titan_protocol.research_engine.attribution import DIMENSION_KEY_FUNCS, compute_bucket_statistics
from titan_protocol.research_engine.execution_quality import summarize_execution_quality
from titan_protocol.research_engine.models import AttributionDimension, ClosedTrade, executed_trades

from .config import ValidationEngineConfig
from .models import DriftAnalysis, DriftFinding

_DRIFT_DIMENSIONS = (
    AttributionDimension.STRATEGY, AttributionDimension.PAIR,
    AttributionDimension.SESSION, AttributionDimension.REGIME,
)


def _group(trades: Sequence[ClosedTrade], dimension: AttributionDimension) -> Dict[str, List[ClosedTrade]]:
    key_func = DIMENSION_KEY_FUNCS[dimension]
    groups: Dict[str, List[ClosedTrade]] = defaultdict(list)
    for trade in executed_trades(trades):
        key = key_func(trade)
        if key is not None:
            groups[key].append(trade)
    return groups


def _findings_for_dimension(
    dimension: AttributionDimension, baseline: Sequence[ClosedTrade], current: Sequence[ClosedTrade], config: ValidationEngineConfig,
) -> List[DriftFinding]:
    baseline_groups = _group(baseline, dimension)
    current_groups = _group(current, dimension)
    findings = []

    for subject in sorted(set(baseline_groups) | set(current_groups)):
        baseline_group = baseline_groups.get(subject, [])
        current_group = current_groups.get(subject, [])

        baseline_stats = compute_bucket_statistics(baseline_group, config.research_config) if baseline_group else None
        current_stats = compute_bucket_statistics(current_group, config.research_config) if current_group else None

        baseline_expectancy = baseline_stats.rolling_expectancy if baseline_stats and baseline_stats.sufficient_data else None
        current_expectancy = current_stats.rolling_expectancy if current_stats and current_stats.sufficient_data else None

        delta = None
        degraded = False
        if (
            baseline_expectancy is not None and current_expectancy is not None
            and len(baseline_group) >= config.min_sample_size_for_drift_bucket
            and len(current_group) >= config.min_sample_size_for_drift_bucket
        ):
            delta = current_expectancy - baseline_expectancy
            degraded = delta <= -config.degradation_expectancy_delta_threshold

        findings.append(DriftFinding(
            dimension=dimension.value, subject=subject,
            baseline_sample_size=len(baseline_group), current_sample_size=len(current_group),
            baseline_expectancy=baseline_expectancy, current_expectancy=current_expectancy,
            delta=delta, degraded=degraded,
        ))

    return findings


def detect_drift(baseline: Sequence[ClosedTrade], current: Sequence[ClosedTrade], config: ValidationEngineConfig) -> DriftAnalysis:
    findings: List[DriftFinding] = []
    for dimension in _DRIFT_DIMENSIONS:
        findings.extend(_findings_for_dimension(dimension, baseline, current, config))

    baseline_quality = summarize_execution_quality(baseline, config.research_config)
    current_quality = summarize_execution_quality(current, config.research_config)
    execution_quality_delta = None
    if executed_trades(baseline) and executed_trades(current):
        execution_quality_delta = current_quality.overall_score - baseline_quality.overall_score

    execution_degraded = (
        execution_quality_delta is not None
        and execution_quality_delta <= -config.execution_quality_degradation_threshold
    )

    return DriftAnalysis(
        findings=tuple(findings), execution_quality_delta=execution_quality_delta,
        any_degradation_detected=execution_degraded or any(f.degraded for f in findings),
    )


__all__ = ["detect_drift"]
