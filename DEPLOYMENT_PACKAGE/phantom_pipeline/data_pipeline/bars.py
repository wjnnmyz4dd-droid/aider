"""Bar construction and multi-timeframe aggregation (ADR-013 §2, §6).

`BarBuilder` constructs base-timeframe bars directly from normalized
ticks. `aggregate_bars` builds higher timeframes from already-finalized
base bars — never a second, independent tick-level computation for each
timeframe, the same "compute once, share the result" discipline
ADR-002 §13 already established for structural computations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Sequence

from .config import PipelineConfig
from .models import DataQuality, NormalizedBar, NormalizedTick, SCHEMA_VERSION, tick_price
from .trace import make_trace_id


def _bucket_start(timestamp: datetime, interval_seconds: int) -> datetime:
    epoch_seconds = timestamp.timestamp()
    bucket_epoch = epoch_seconds - (epoch_seconds % interval_seconds)
    return datetime.fromtimestamp(bucket_epoch, tz=timestamp.tzinfo)


@dataclass
class _InProgressBar:
    bucket_start: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    source: str


class BarBuilder:
    """Builds base-timeframe OHLCV bars from a stream of normalized ticks."""

    def __init__(self, config: PipelineConfig, timeframe: str):
        self._config = config
        self.timeframe = timeframe
        self._interval = config.interval_seconds_for(timeframe)
        self._in_progress: Dict[str, _InProgressBar] = {}

    def add_tick(self, tick: NormalizedTick) -> Optional[NormalizedBar]:
        """Feed one tick in; returns a finalized bar if this tick started a
        new bucket, else None."""
        price = tick_price(tick)
        if price is None:
            return None

        bucket_start = _bucket_start(tick.timestamp, self._interval)
        volume = tick.volume or 0.0

        current = self._in_progress.get(tick.symbol)
        finalized: Optional[NormalizedBar] = None

        if current is None:
            self._in_progress[tick.symbol] = _InProgressBar(
                bucket_start=bucket_start,
                open=price,
                high=price,
                low=price,
                close=price,
                volume=volume,
                source=tick.source,
            )
            return None

        if bucket_start > current.bucket_start:
            finalized = self._finalize(tick.symbol, current)
            self._in_progress[tick.symbol] = _InProgressBar(
                bucket_start=bucket_start,
                open=price,
                high=price,
                low=price,
                close=price,
                volume=volume,
                source=tick.source,
            )
        elif bucket_start == current.bucket_start:
            current.high = max(current.high, price)
            current.low = min(current.low, price)
            current.close = price
            current.volume += volume
        # bucket_start < current.bucket_start: a residual out-of-order tick
        # that survived TickIngestor's tolerance window; ignored for bar
        # construction rather than reopening an already-finalized bucket.

        return finalized

    def flush(self, symbol: str) -> Optional[NormalizedBar]:
        """Finalize and return the in-progress bar for `symbol`, if any."""
        current = self._in_progress.pop(symbol, None)
        if current is None:
            return None
        return self._finalize(symbol, current)

    def _finalize(self, symbol: str, bar: _InProgressBar) -> NormalizedBar:
        trace_id = make_trace_id(
            "bar", symbol, self.timeframe, bar.bucket_start.isoformat()
        )
        return NormalizedBar(
            schema_version=SCHEMA_VERSION,
            trace_id=trace_id,
            symbol=symbol,
            timeframe=self.timeframe,
            timestamp=bar.bucket_start,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
            quality=DataQuality.NOMINAL,
            is_repaired=False,
            source=bar.source,
        )


def aggregate_bars(
    bars: Sequence[NormalizedBar], target_timeframe: str, config: PipelineConfig
) -> List[NormalizedBar]:
    """Aggregate consecutive base-timeframe bars into `target_timeframe` bars.

    Reuses the already-produced base bars; never re-derives from ticks.
    `bars` must be sorted ascending by timestamp and share one symbol and
    source timeframe.
    """
    if not bars:
        return []

    target_interval = config.interval_seconds_for(target_timeframe)
    source_interval = config.interval_seconds_for(bars[0].timeframe)
    if target_interval % source_interval != 0:
        raise ValueError(
            f"{target_timeframe} is not an integer multiple of {bars[0].timeframe}"
        )
    factor = target_interval // source_interval

    result: List[NormalizedBar] = []
    bucket: List[NormalizedBar] = []
    current_bucket_start: Optional[datetime] = None

    for bar in bars:
        bucket_start = _bucket_start(bar.timestamp, target_interval)
        if current_bucket_start is None:
            current_bucket_start = bucket_start

        if bucket_start != current_bucket_start:
            result.append(_merge(bucket, target_timeframe, current_bucket_start))
            bucket = []
            current_bucket_start = bucket_start

        bucket.append(bar)
        if len(bucket) == factor:
            result.append(_merge(bucket, target_timeframe, current_bucket_start))
            bucket = []
            current_bucket_start = None

    if bucket:
        result.append(_merge(bucket, target_timeframe, current_bucket_start))

    return result


def _merge(
    constituents: Sequence[NormalizedBar], target_timeframe: str, bucket_start: datetime
) -> NormalizedBar:
    symbol = constituents[0].symbol
    trace_id = make_trace_id("bar", symbol, target_timeframe, bucket_start.isoformat())
    worst_quality = DataQuality.NOMINAL
    for c in constituents:
        if c.quality != DataQuality.NOMINAL:
            worst_quality = c.quality
    return NormalizedBar(
        schema_version=SCHEMA_VERSION,
        trace_id=trace_id,
        symbol=symbol,
        timeframe=target_timeframe,
        timestamp=bucket_start,
        open=constituents[0].open,
        high=max(c.high for c in constituents),
        low=min(c.low for c in constituents),
        close=constituents[-1].close,
        volume=sum(c.volume for c in constituents),
        quality=worst_quality,
        is_repaired=any(c.is_repaired for c in constituents),
        source=constituents[0].source,
    )
