"""Bar validation (ADR-033 SS3.3) -- pure functions, no state. Rejects
malformed data before it ever reaches ordering/warmup tracking."""

from __future__ import annotations

from typing import Optional

from .config import MarketDataIngestionConfig
from .models import RawBar, RejectionReason


def validate_bar(raw: RawBar, config: MarketDataIngestionConfig) -> Optional[RejectionReason]:
    """Returns the rejection reason if the bar fails validation, else
    `None`. Checked in a fixed, documented order so the first
    applicable reason is always reported, never a random one.

    Clock skew is `broker_timestamp` vs. `source_timestamp` -- two
    clocks that should always agree at capture time, live or
    backfilled -- never compared against ingestion wall-clock `now`.
    Wall-clock `now` legitimately differs from a bar's own timestamps
    by hours or days during historical backfill; that is expected and
    must never be rejected as a clock problem."""

    if raw.symbol not in config.enabled_pairs:
        return RejectionReason.UNKNOWN_SYMBOL
    if raw.timeframe not in config.required_timeframes:
        return RejectionReason.UNKNOWN_TIMEFRAME

    if any(v is None for v in (raw.open, raw.high, raw.low, raw.close, raw.volume)):
        return RejectionReason.INCOMPLETE

    if raw.high < raw.low:
        return RejectionReason.MALFORMED
    if raw.high < raw.open or raw.high < raw.close:
        return RejectionReason.MALFORMED
    if raw.low > raw.open or raw.low > raw.close:
        return RejectionReason.MALFORMED
    if raw.volume < 0:
        return RejectionReason.MALFORMED
    if raw.bid is not None and raw.ask is not None and raw.ask < raw.bid:
        return RejectionReason.MALFORMED

    skew_seconds = abs((raw.broker_timestamp - raw.source_timestamp).total_seconds())
    if skew_seconds > config.max_clock_skew_seconds:
        return RejectionReason.CLOCK_SKEW

    return None


__all__ = ["validate_bar"]
