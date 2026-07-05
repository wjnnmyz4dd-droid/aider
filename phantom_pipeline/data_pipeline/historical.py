"""Historical cache (ADR-013 §11).

Bounded per symbol/timeframe, both by count (`historical_cache_max_bars_
per_series`) and by age (`historical_cache_ttl_seconds`) — never
unbounded growth, the same bounded/TTL-pruned discipline every other
stateful exception in this architecture already follows.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta
from typing import Deque, Dict, Tuple

from .config import PipelineConfig
from .models import HistoricalSeries, NormalizedBar, SCHEMA_VERSION
from .trace import make_trace_id


class HistoricalCache:
    """Bounded, TTL-pruned cache of finalized bars per (symbol, timeframe)."""

    def __init__(self, config: PipelineConfig):
        self._config = config
        self._series: Dict[Tuple[str, str], Deque[NormalizedBar]] = {}

    def add_bar(self, bar: NormalizedBar) -> None:
        key = (bar.symbol, bar.timeframe)
        series = self._series.get(key)
        if series is None:
            series = deque(maxlen=self._config.historical_cache_max_bars_per_series)
            self._series[key] = series
        series.append(bar)

    def evict_expired(self, now: datetime) -> None:
        ttl = timedelta(seconds=self._config.historical_cache_ttl_seconds)
        cutoff = now - ttl
        for series in self._series.values():
            while series and series[0].timestamp < cutoff:
                series.popleft()

    def get_series(self, symbol: str, timeframe: str) -> HistoricalSeries:
        bars = tuple(self._series.get((symbol, timeframe), ()))
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
