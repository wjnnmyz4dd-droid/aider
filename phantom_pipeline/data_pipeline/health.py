"""This stage's own operational health signal (ADR-013 §5).

The input Watchdog (ADR-011) observes for this stage — this module only
reports the signal; it never performs Watchdog's own aggregation,
alerting, or recovery logic (ADR-011 §2's boundary note).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from .models import PipelineHealth, SCHEMA_VERSION
from .trace import make_trace_id


def compute_pipeline_health(
    now: datetime,
    ticks_processed: int,
    bars_produced: int,
    gap_count: int,
) -> PipelineHealth:
    reason: Optional[str]
    if gap_count > 0:
        status = "DEGRADED"
        reason = f"{gap_count} missing bar(s) detected, not yet repaired"
    else:
        status = "HEALTHY"
        reason = None

    trace_id = make_trace_id("health", now.isoformat())
    return PipelineHealth(
        schema_version=SCHEMA_VERSION,
        trace_id=trace_id,
        timestamp=now,
        status=status,
        reason=reason,
        ticks_processed=ticks_processed,
        bars_produced=bars_produced,
        gap_count=gap_count,
    )
