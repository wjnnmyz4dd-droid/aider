"""`MarketDataIngestionEngine` -- the Market Data Ingestion layer's
orchestrator (Phase 3C, ADR-033).

A genuinely stateful component (per-(symbol,timeframe) sequence/warmup/
retention state, per-symbol tick state) -- the same discipline
`ADR-032`'s Reliability Engine and `ADR-011`'s Watchdog already
established for stateful cross-cutting components. One internal lock
guards all mutable state; every public method is safe to call
concurrently.
"""

from __future__ import annotations

import threading
from collections import deque
from datetime import datetime
from typing import Deque, Dict, List, Optional, Tuple

from titan_protocol.evidence_engine.models import Bar

from .config import MarketDataIngestionConfig
from .freshness import is_stale
from .models import (
    FeedFreshness,
    IngestionResult,
    MarketFeedHealthSnapshot,
    RawBar,
    RejectionReason,
    TickEvent,
    Timeframe,
    WarmupStatus,
)
from .logging_sink import log_ingestion_result
from .normalization import normalize
from .ordering import SequenceState, advance, check_ordering
from .validation import validate_bar
from .warmup import WarmupTracker
from .metrics import MarketDataIngestionMetrics

_Key = Tuple[str, Timeframe]


class MarketDataIngestionEngine:
    def __init__(self, config: MarketDataIngestionConfig, metrics: Optional[MarketDataIngestionMetrics] = None) -> None:
        self.config = config
        self.metrics = metrics
        self._lock = threading.Lock()
        self._sequence_state: Dict[_Key, SequenceState] = {}
        self._bars: Dict[_Key, Deque[Bar]] = {}
        self._warmup = WarmupTracker(config)
        self._latest_tick: Dict[str, TickEvent] = {}
        self._spread_window: Dict[str, Deque[float]] = {}
        self._gap_reasons: List[str] = []

    def _sequence_state_for(self, key: _Key) -> SequenceState:
        return self._sequence_state.setdefault(key, SequenceState())

    def _bars_for(self, key: _Key) -> Deque[Bar]:
        return self._bars.setdefault(key, deque(maxlen=self.config.max_bars_retained))

    def ingest_bar(self, raw: RawBar, now: datetime) -> IngestionResult:
        result = self._ingest_bar_locked(raw, now)
        log_ingestion_result(raw, result)
        if self.metrics is not None:
            if result.accepted:
                self.metrics.record_bar_accepted()
                if result.gap_detected:
                    self.metrics.record_gap_detected()
            else:
                self.metrics.record_bar_rejected()
        return result

    def _ingest_bar_locked(self, raw: RawBar, now: datetime) -> IngestionResult:
        with self._lock:
            rejection = validate_bar(raw, self.config)
            if rejection is not None:
                return IngestionResult(accepted=False, rejection_reason=rejection, reason_detail=f"validation failed: {rejection.value}")

            key = (raw.symbol, raw.timeframe)
            state = self._sequence_state_for(key)
            ordering_rejection, gap_detected = check_ordering(state, raw, self.config)
            if ordering_rejection is not None:
                return IngestionResult(accepted=False, rejection_reason=ordering_rejection, reason_detail=f"ordering failed: {ordering_rejection.value}")

            advance(state, raw)
            if gap_detected:
                self._gap_reasons.append(f"gap detected for {raw.symbol}/{raw.timeframe.value} before bar_open_time={raw.bar_open_time.isoformat()}")

            if raw.is_closed:
                self._bars_for(key).append(normalize(raw))
                self._warmup.record_closed_bar(raw.symbol, raw.timeframe)
            if raw.bid is not None and raw.ask is not None:
                self._record_spread(raw.symbol, raw.bid, raw.ask)

            return IngestionResult(accepted=True, gap_detected=gap_detected)

    def ingest_tick(self, tick: TickEvent, now: datetime) -> IngestionResult:
        if tick.symbol not in self.config.enabled_pairs:
            return IngestionResult(accepted=False, rejection_reason=RejectionReason.UNKNOWN_SYMBOL, reason_detail="tick for unknown symbol")
        if tick.ask < tick.bid:
            return IngestionResult(accepted=False, rejection_reason=RejectionReason.MALFORMED, reason_detail="ask < bid")
        with self._lock:
            self._latest_tick[tick.symbol] = tick
            self._record_spread(tick.symbol, tick.bid, tick.ask)
        if self.metrics is not None:
            self.metrics.record_tick_ingested()
        return IngestionResult(accepted=True)

    def _record_spread(self, symbol: str, bid: float, ask: float) -> None:
        window = self._spread_window.setdefault(symbol, deque(maxlen=self.config.spread_rolling_window))
        window.append(ask - bid)

    def backfill(self, symbol: str, timeframe: Timeframe, bars: List[RawBar], now: datetime) -> WarmupStatus:
        """Startup historical warmup -- validates continuity via the
        same ordering/validation path every live bar goes through,
        never a shortcut. Never fabricates a missing bar to fill a
        gap in the supplied history."""
        for raw in sorted(bars, key=lambda b: b.sequence_number):
            self.ingest_bar(raw, now)
        with self._lock:
            return self._warmup.status(symbol, timeframe)

    def is_ready(self, symbol: str, timeframe: Timeframe, now: datetime) -> bool:
        with self._lock:
            warmup_ready = self._warmup.status(symbol, timeframe).ready
            state = self._sequence_state.get((symbol, timeframe))
            last_bar_open_time = state.last_bar_open_time if state else None
        if not warmup_ready:
            return False
        return not is_stale(last_bar_open_time, now, timeframe, self.config)

    def get_bars(self, symbol: str, timeframe: Timeframe) -> Tuple[Bar, ...]:
        with self._lock:
            return tuple(self._bars_for((symbol, timeframe)))

    def latest_spread(self, symbol: str) -> Optional[Tuple[float, float]]:
        with self._lock:
            tick = self._latest_tick.get(symbol)
            window = self._spread_window.get(symbol)
            if tick is None or not window:
                return None
            current_spread = tick.ask - tick.bid
            average_spread = sum(window) / len(window)
            return current_spread, average_spread

    def warmup_status(self, symbol: str, timeframe: Timeframe) -> WarmupStatus:
        with self._lock:
            return self._warmup.status(symbol, timeframe)

    def health_snapshot(self, now: datetime) -> MarketFeedHealthSnapshot:
        with self._lock:
            warmup_statuses = self._warmup.all_statuses()
            freshness = tuple(
                FeedFreshness(
                    symbol=symbol, timeframe=timeframe,
                    last_bar_open_time=(self._sequence_state.get((symbol, timeframe)) or SequenceState()).last_bar_open_time,
                    is_stale=is_stale(
                        (self._sequence_state.get((symbol, timeframe)) or SequenceState()).last_bar_open_time,
                        now, timeframe, self.config,
                    ),
                )
                for symbol in self.config.enabled_pairs
                for timeframe in self.config.required_timeframes
            )
            reasons = tuple(self._gap_reasons[-50:])  # bounded -- most recent gaps only
        return MarketFeedHealthSnapshot(generated_at=now, warmup_statuses=warmup_statuses, freshness=freshness, reasons=reasons)


__all__ = ["MarketDataIngestionEngine"]
