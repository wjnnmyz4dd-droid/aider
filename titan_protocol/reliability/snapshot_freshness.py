"""Snapshot freshness (ADR-032 SS2 item 4): a small pure function
generalizing `ADR-031`'s snapshot-timeout signal into a directly
callable check any observer can use outside a `RuntimeAuditRecord`'s
own stage timings."""

from __future__ import annotations

from datetime import datetime

from .config import ReliabilityConfig


def is_snapshot_fresh(generated_at: datetime, now: datetime, config: ReliabilityConfig) -> bool:
    age_seconds = (now - generated_at).total_seconds()
    if age_seconds < 0:
        return False  # a snapshot from the future is never trusted
    return age_seconds <= config.snapshot_freshness_threshold_seconds


__all__ = ["is_snapshot_fresh"]
