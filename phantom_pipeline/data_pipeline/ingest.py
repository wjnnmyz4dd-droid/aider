"""Tick ingestion: duplicate and out-of-order detection (ADR-013 §6).

`TickIngestor` holds bounded, per-symbol state only (a fixed-size recent-
tick history and the last-accepted timestamp) — never unbounded growth,
the same TTL/size-bounded discipline every stateful exception in this
architecture already follows (ADR-002 §2's session clock, ADR-007/008's
idempotency records).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Deque, Dict, Optional, Tuple

from .config import PipelineConfig
from .models import NormalizedTick, SCHEMA_VERSION
from .normalize import normalize_price, normalize_symbol, normalize_timestamp, normalize_volume
from .trace import make_trace_id


@dataclass
class _SymbolIngestState:
    last_timestamp: Optional[datetime] = None
    recent_keys: Deque[Tuple] = field(default_factory=lambda: deque(maxlen=1))


class IngestResult:
    """Outcome of ingesting one raw tick: exactly one of these is set."""

    __slots__ = ("tick", "duplicate", "out_of_order_dropped", "malformed_reason")

    def __init__(
        self,
        tick: Optional[NormalizedTick] = None,
        duplicate: bool = False,
        out_of_order_dropped: bool = False,
        malformed_reason: Optional[str] = None,
    ):
        self.tick = tick
        self.duplicate = duplicate
        self.out_of_order_dropped = out_of_order_dropped
        self.malformed_reason = malformed_reason


class TickIngestor:
    """Normalizes raw ticks and detects duplicates / out-of-order arrivals."""

    def __init__(self, config: PipelineConfig):
        self._config = config
        self._state: Dict[str, _SymbolIngestState] = {}
        self.duplicate_count = 0
        self.out_of_order_dropped_count = 0
        self.malformed_count = 0

    def _state_for(self, symbol: str) -> _SymbolIngestState:
        state = self._state.get(symbol)
        if state is None:
            state = _SymbolIngestState(
                recent_keys=deque(maxlen=self._config.duplicate_tick_history)
            )
            self._state[symbol] = state
        return state

    def ingest(
        self,
        raw_symbol: str,
        raw_timestamp: datetime,
        bid: Optional[float],
        ask: Optional[float],
        last: Optional[float],
        volume: Optional[float],
        source: str,
    ) -> IngestResult:
        symbol = normalize_symbol(raw_symbol, self._config)

        try:
            timestamp = normalize_timestamp(raw_timestamp)
            norm_bid = normalize_price(bid, symbol, self._config) if bid is not None else None
            norm_ask = normalize_price(ask, symbol, self._config) if ask is not None else None
            norm_last = normalize_price(last, symbol, self._config) if last is not None else None
            norm_volume = normalize_volume(volume, self._config) if volume is not None else None
        except ValueError as exc:
            self.malformed_count += 1
            return IngestResult(malformed_reason=str(exc))

        state = self._state_for(symbol)

        key = (timestamp, norm_bid, norm_ask, norm_last, norm_volume)
        if key in state.recent_keys:
            self.duplicate_count += 1
            return IngestResult(duplicate=True)

        if state.last_timestamp is not None and timestamp < state.last_timestamp:
            tolerance = timedelta(seconds=self._config.out_of_order_tolerance_seconds)
            if state.last_timestamp - timestamp > tolerance:
                self.out_of_order_dropped_count += 1
                return IngestResult(out_of_order_dropped=True)
            # Within tolerance: accepted, but does not advance last_timestamp.
        else:
            state.last_timestamp = timestamp

        state.recent_keys.append(key)

        trace_id = make_trace_id("tick", symbol, timestamp.isoformat(), source)
        tick = NormalizedTick(
            schema_version=SCHEMA_VERSION,
            trace_id=trace_id,
            symbol=symbol,
            timestamp=timestamp,
            bid=norm_bid,
            ask=norm_ask,
            last=norm_last,
            volume=norm_volume,
            source=source,
        )
        return IngestResult(tick=tick)
