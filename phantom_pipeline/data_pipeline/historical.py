"""Historical cache (ADR-013 §11).

Bounded per symbol/timeframe, both by count (`historical_cache_max_bars_
per_series`) and by age (`historical_cache_ttl_seconds`) — never
unbounded growth, the same bounded/TTL-pruned discipline every other
stateful exception in this architecture already follows.

`load_bulk` is the warm-cache/bulk-historical-load entry point (§4, §11)
— it populates a symbol/timeframe series directly from an
already-constructed bar sequence (e.g. a bulk historical load at
startup), never re-deriving from ticks. It is deliberately separate from
`add_bar` (the live-ingestion path): loading bulk history is not a live
event and must never be captured into `ReplayRecorder` (`replay.py`),
preserving replay determinism for genuinely live-produced data.

`invalidate` is the explicit, logged cache-invalidation operation (§11)
— never a silent clear; the caller (`DataPipeline.invalidate_cache`) is
responsible for logging the event, this method only performs the
bounded, deterministic clear itself.

`hit_count`/`miss_count` are plain, unbounded-but-trivially-small running
counters (two integers) feeding the "cache hit ratio" metric (§15) — the
same "state lives on the component that knows it, read fresh by the
caller" discipline `TickIngestor`'s own counters already established in
this package.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta
from typing import Deque, Dict, Sequence, Tuple

from .config import PipelineConfig
from .models import HistoricalSeries, NormalizedBar, SCHEMA_VERSION
from .trace import make_trace_id


def _validate_bar_sequence(bars: Sequence[NormalizedBar]) -> None:
    """Defense-in-depth validation for a bulk-loaded bar sequence (ADR-013
    §7, §8) — the same three checks §7 requires at live-tick ingestion
    (non-monotonic timestamps, non-positive prices, impossible OHLC
    ordering), applied independently at this second ingestion path. This
    is not a duplicated responsibility (§8): a bug in whatever assembled
    this bulk sequence must not silently corrupt the cache.
    """
    previous_timestamp = None
    for bar in bars:
        if previous_timestamp is not None and bar.timestamp <= previous_timestamp:
            raise ValueError(
                f"bulk-loaded bars must be strictly ascending by timestamp: "
                f"{bar.timestamp!r} does not follow {previous_timestamp!r}"
            )
        previous_timestamp = bar.timestamp

        if bar.low > bar.high:
            raise ValueError(f"impossible OHLC ordering (low > high) at {bar.timestamp!r}")
        if bar.open <= 0 or bar.high <= 0 or bar.low <= 0 or bar.close <= 0:
            raise ValueError(f"non-positive price in bar at {bar.timestamp!r}")
        if not (bar.low <= bar.open <= bar.high) or not (bar.low <= bar.close <= bar.high):
            raise ValueError(f"open/close outside [low, high] at {bar.timestamp!r}")


class HistoricalCache:
    """Bounded, TTL-pruned cache of finalized bars per (symbol, timeframe)."""

    def __init__(self, config: PipelineConfig):
        self._config = config
        self._series: Dict[Tuple[str, str], Deque[NormalizedBar]] = {}
        self.hit_count = 0
        self.miss_count = 0

    def add_bar(self, bar: NormalizedBar) -> None:
        key = (bar.symbol, bar.timeframe)
        series = self._series.get(key)
        if series is None:
            series = deque(maxlen=self._config.historical_cache_max_bars_per_series)
            self._series[key] = series
        series.append(bar)

    def load_bulk(self, symbol: str, timeframe: str, bars: Sequence[NormalizedBar]) -> None:
        """Bulk-load a symbol/timeframe's historical series directly
        (ADR-013 §4, §11's warm-cache bootstrap) — deterministic:
        loading the same `bars` twice produces the same resulting series
        both times. Subject to the same bounded/TTL discipline as
        live-ingested bars (the most recent `historical_cache_max_bars_
        per_series` entries are retained)."""
        _validate_bar_sequence(bars)
        key = (symbol, timeframe)
        series: Deque[NormalizedBar] = deque(
            bars, maxlen=self._config.historical_cache_max_bars_per_series
        )
        self._series[key] = series

    def invalidate(self, symbol: str, timeframe: str) -> int:
        """Explicitly clear a symbol/timeframe's cached series (ADR-013
        §11) — never a silent clear; returns the number of bars removed
        so the caller can log a complete audit record. A no-op (returns
        0) for a key that was never populated."""
        key = (symbol, timeframe)
        series = self._series.pop(key, None)
        return len(series) if series is not None else 0

    def evict_expired(self, now: datetime) -> None:
        ttl = timedelta(seconds=self._config.historical_cache_ttl_seconds)
        cutoff = now - ttl
        for series in self._series.values():
            while series and series[0].timestamp < cutoff:
                series.popleft()

    def get_series(self, symbol: str, timeframe: str) -> HistoricalSeries:
        bars = tuple(self._series.get((symbol, timeframe), ()))
        if bars:
            self.hit_count += 1
        else:
            self.miss_count += 1
        trace_id = make_trace_id(
            "historical",
            symbol,
            timeframe,
            bars[0].timestamp.isoformat() if bars else "empty",
            bars[-1].timestamp.isoformat() if bars else "empty",
        )
        return HistoricalSeries(
            schema_version=SCHEMA_VERSION,
            trace_id=trace_id,
            symbol=symbol,
            timeframe=timeframe,
            bars=bars,
        )
