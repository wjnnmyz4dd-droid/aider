"""Scanner's own independent failure-mode detection (ADR-002 §9, §10).

This re-validates inputs even though the Data Pipeline (ADR-013) should
already have caught malformed candles — not a duplicated responsibility,
but a second independent check the Scanner Purity Principle (§2) requires:
the Scanner must not trust any input, including an upstream stage's own
validation, since it has no way to verify that validation actually ran.

Checks run in the exact order ADR-002 §9 lists its failure modes; the
first match wins (`NOMINAL` if none match). Amendment 1's 8th failure mode
(insufficient swing history for phase/confidence) is a distinct condition
from general warm-up and is signaled through `structure_confidence`
directly, not through this top-level flag (§9 explicitly distinguishes the
two: "a symbol can have enough bars for a trend reading but not enough
distinct swing points for phase classification").
"""

from __future__ import annotations

from datetime import datetime
from typing import Mapping, Optional, Sequence

from ..data_pipeline.models import MarketSnapshot, NormalizedBar
from .config import ScannerConfig
from .models import DataQualityFlag


def assess_quality(
    symbol: str,
    bars_by_timeframe: Mapping[str, Sequence[NormalizedBar]],
    market_snapshot: Optional[MarketSnapshot],
    session_time: datetime,
    primary_timeframe: str,
    config: ScannerConfig,
) -> DataQualityFlag:
    primary_bars = bars_by_timeframe.get(primary_timeframe)

    if primary_bars is None:
        return DataQualityFlag.MISSING_TIMEFRAME

    if len(primary_bars) < config.min_bars_for_structure:
        return DataQualityFlag.WARM_UP

    if _has_malformed_candles(primary_bars):
        return DataQualityFlag.MALFORMED_DATA

    if _spread_is_stale(market_snapshot, session_time, config):
        return DataQualityFlag.STALE_SPREAD

    if session_time.tzinfo is None:
        return DataQualityFlag.SESSION_AMBIGUOUS

    if not config.is_symbol_recognized(symbol):
        return DataQualityFlag.SYMBOL_NOT_RECOGNIZED

    if market_snapshot is not None and market_snapshot.market_status.upper() != "OPEN":
        return DataQualityFlag.MARKET_NOT_TRADEABLE

    return DataQualityFlag.NOMINAL


def _has_malformed_candles(bars: Sequence[NormalizedBar]) -> bool:
    prev_timestamp = None
    for bar in bars:
        if prev_timestamp is not None and bar.timestamp <= prev_timestamp:
            return True
        prev_timestamp = bar.timestamp

        if bar.open <= 0 or bar.high <= 0 or bar.low <= 0 or bar.close <= 0:
            return True
        if bar.low > bar.high:
            return True
        if bar.open > bar.high or bar.open < bar.low:
            return True
        if bar.close > bar.high or bar.close < bar.low:
            return True
    return False


def _spread_is_stale(
    market_snapshot: Optional[MarketSnapshot],
    session_time: datetime,
    config: ScannerConfig,
) -> bool:
    if market_snapshot is None:
        return True
    if market_snapshot.spread is None or market_snapshot.spread <= 0:
        return True
    if market_snapshot.spread > config.max_spread:
        return True

    try:
        age = (session_time - market_snapshot.timestamp).total_seconds()
    except TypeError:
        # Mismatched tz-awareness between session_time and the snapshot's
        # own timestamp — cannot honestly measure staleness; fail closed.
        return True
    if age > config.spread_stale_after_seconds:
        return True
    return False
