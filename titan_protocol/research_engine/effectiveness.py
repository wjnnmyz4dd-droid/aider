"""Shared bucket-comparison helper (ADR-029 §5): one function, reused
by every named review in `reviews.py`, rather than three divergent
comparison implementations (CLAUDE.md §6)."""

from __future__ import annotations

from typing import Sequence

from .attribution import compute_bucket_statistics
from .config import ResearchEngineConfig
from .models import ClosedTrade, EffectivenessComparison


def compare_buckets(
    label: str, baseline: Sequence[ClosedTrade], comparison: Sequence[ClosedTrade], config: ResearchEngineConfig,
) -> EffectivenessComparison:
    baseline_stats = compute_bucket_statistics(baseline, config) if baseline else None
    comparison_stats = compute_bucket_statistics(comparison, config) if comparison else None

    baseline_expectancy = baseline_stats.rolling_expectancy if baseline_stats and baseline_stats.sufficient_data else None
    comparison_expectancy = comparison_stats.rolling_expectancy if comparison_stats and comparison_stats.sufficient_data else None

    delta = None
    if baseline_expectancy is not None and comparison_expectancy is not None:
        delta = comparison_expectancy - baseline_expectancy

    notable = (
        len(baseline) >= config.effectiveness_min_sample_size
        and len(comparison) >= config.effectiveness_min_sample_size
        and delta is not None
        and abs(delta) >= config.effectiveness_notable_delta_threshold
    )

    return EffectivenessComparison(
        label=label, baseline_sample_size=len(baseline), baseline_expectancy=baseline_expectancy,
        comparison_sample_size=len(comparison), comparison_expectancy=comparison_expectancy,
        delta=delta, notable=notable,
    )


def bucket_by_score_tertiles(trades: Sequence[ClosedTrade], score_func, label: str, config: ResearchEngineConfig) -> EffectivenessComparison:
    """Splits `trades` into the lowest and highest thirds by
    `score_func`'s value and compares them -- answers "does a higher
    score actually correlate with a better outcome" for whatever
    upstream score is being reviewed."""

    scored = sorted(trades, key=score_func)
    n = len(scored)
    third = n // 3
    if third < config.effectiveness_min_sample_size:
        return compare_buckets(label, (), (), config)
    low = scored[:third]
    high = scored[2 * third:]
    return compare_buckets(label, low, high, config)


__all__ = ["compare_buckets", "bucket_by_score_tertiles"]
