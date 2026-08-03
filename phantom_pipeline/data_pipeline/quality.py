"""Data quality assessment (ADR-013 §7).

Produces a `DataQualityReport` over a bar window — completeness,
freshness, continuity, and a qualitative confidence label (never a
numeric score, the same discipline ADR-002 §5's `structure_confidence`
already established).
"""

from __future__ import annotations

from datetime import datetime
from typing import Sequence

from .config import PipelineConfig
from .gaps import detect_gaps
from .models import DataQualityReport, SCHEMA_VERSION
from .models import NormalizedBar
from .trace import make_trace_id


def compute_quality_report(
    symbol: str,
    timeframe: str,
    bars: Sequence[NormalizedBar],
    window_start: datetime,
    window_end: datetime,
    now: datetime,
    config: PipelineConfig,
    duplicate_count: int,
    out_of_order_count: int,
) -> DataQualityReport:
    """`duplicate_count`/`out_of_order_count` are the ingestor's
    cumulative, whole-lifetime counters (see `TickIngestor`), not counts
    scoped to `[window_start, window_end]` — there is currently no
    per-window duplicate/out-of-order tracking. Callers comparing reports
    across different windows should read these two fields as
    "cumulative as of `now`," not "observed in this window."
    """
    interval = config.interval_seconds_for(timeframe)
    expected_bars = max(
        1, int((window_end - window_start).total_seconds() // interval)
    )
    actual_bars = len(bars)
    completeness = min(1.0, actual_bars / expected_bars) if expected_bars else 1.0

    gaps = detect_gaps(bars, config) if bars else []
    gap_count = sum(g.missing_bar_count for g in gaps)
    continuity = gap_count == 0

    freshness_seconds = (
        (now - bars[-1].timestamp).total_seconds() if bars else float("inf")
    )

    if not bars:
        confidence = "INSUFFICIENT"
    elif freshness_seconds > config.freshness_stale_after_seconds or gap_count > 0:
        confidence = "DEGRADED"
    else:
        confidence = "NOMINAL"

    trace_id = make_trace_id(
        "quality", symbol, timeframe, window_start.isoformat(), window_end.isoformat()
    )
    return DataQualityReport(
        schema_version=SCHEMA_VERSION,
        trace_id=trace_id,
        symbol=symbol,
        timeframe=timeframe,
        window_start=window_start,
        window_end=window_end,
        completeness=completeness,
        freshness_seconds=freshness_seconds,
        # No live broker feed adapter exists yet in Phase 1 (ADR-015 §6),
        # so there is no genuine ingestion-receipt time to measure against
        # a bar's own timestamp. None is the honest value here, not a
        # fabricated figure — see DataQualityReport's own docstring.
        latency_seconds=None,
        continuity=continuity,
        confidence=confidence,
        gap_count=gap_count,
        duplicate_count=duplicate_count,
        out_of_order_count=out_of_order_count,
    )
