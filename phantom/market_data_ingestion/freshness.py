"""Stale-feed detection (ADR-033 SS3.3). A feed with no accepted bar
yet is always stale -- fail closed, never "no data yet, assume fine"."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from .config import MarketDataIngestionConfig
from .models import TIMEFRAME_SECONDS, Timeframe


def is_stale(last_bar_open_time: Optional[datetime], now: datetime, timeframe: Timeframe, config: MarketDataIngestionConfig) -> bool:
    if last_bar_open_time is None:
        return True
    if now < last_bar_open_time:
        return True  # a future last-seen bar is never trusted either
    threshold_seconds = TIMEFRAME_SECONDS[timeframe] * config.staleness_multiplier_by_timeframe[timeframe]
    age_seconds = (now - last_bar_open_time).total_seconds()
    return age_seconds > threshold_seconds


__all__ = ["is_stale"]
