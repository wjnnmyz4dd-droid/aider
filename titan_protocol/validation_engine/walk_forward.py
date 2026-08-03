"""Walk-Forward Testing (ADR-030 §5.8): train -> validation -> out-of-
sample, in that sequential order. Statistics for each bucket come from
`research_engine.attribution.compute_bucket_statistics` -- never a
second implementation (ADR-030 Hard Rule 5)."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Sequence

from titan_protocol.research_engine.attribution import compute_bucket_statistics
from titan_protocol.research_engine.models import ClosedTrade, executed_trades

from .config import ValidationEngineConfig
from .models import WalkForwardResult


def run_walk_forward(
    trades: Sequence[ClosedTrade], config: ValidationEngineConfig,
    train_end: Optional[datetime] = None, validation_end: Optional[datetime] = None,
) -> WalkForwardResult:
    executed = sorted(executed_trades(trades), key=lambda t: t.evaluated_at)

    if train_end is None or validation_end is None:
        n = len(executed)
        third = n // 3
        train: List[ClosedTrade] = list(executed[:third])
        validation: List[ClosedTrade] = list(executed[third:2 * third])
        out_of_sample: List[ClosedTrade] = list(executed[2 * third:])
    else:
        train = [t for t in executed if t.evaluated_at < train_end]
        validation = [t for t in executed if train_end <= t.evaluated_at < validation_end]
        out_of_sample = [t for t in executed if t.evaluated_at >= validation_end]

    train_stats = compute_bucket_statistics(train, config.research_config)
    validation_stats = compute_bucket_statistics(validation, config.research_config)
    out_of_sample_stats = compute_bucket_statistics(out_of_sample, config.research_config)

    degradation_detected = False
    detail = "insufficient data to assess degradation"
    if (
        len(train) >= config.min_sample_size_for_walk_forward_bucket
        and len(out_of_sample) >= config.min_sample_size_for_walk_forward_bucket
        and train_stats.rolling_expectancy is not None
        and out_of_sample_stats.rolling_expectancy is not None
    ):
        delta = out_of_sample_stats.rolling_expectancy - train_stats.rolling_expectancy
        degradation_detected = delta <= -config.degradation_expectancy_delta_threshold
        detail = (
            f"out-of-sample expectancy ({out_of_sample_stats.rolling_expectancy:.2f}R) vs. "
            f"train expectancy ({train_stats.rolling_expectancy:.2f}R), delta {delta:+.2f}R"
        )

    return WalkForwardResult(
        train_statistics=train_stats, validation_statistics=validation_stats, out_of_sample_statistics=out_of_sample_stats,
        train_sample_size=len(train), validation_sample_size=len(validation), out_of_sample_sample_size=len(out_of_sample),
        degradation_detected=degradation_detected, degradation_detail=detail,
    )


__all__ = ["run_walk_forward"]
