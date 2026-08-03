"""Warmup tracking (ADR-033 SS3.4): per (symbol, timeframe), counts
real, validated, closed bars only -- never fabricates a bar to reach
the configured minimum faster. `NOT_READY` (via `WarmupStatus.ready`)
until the minimum is satisfied."""

from __future__ import annotations

from typing import Dict, Tuple

from .config import MarketDataIngestionConfig
from .models import Timeframe, WarmupStatus


class WarmupTracker:
    def __init__(self, config: MarketDataIngestionConfig) -> None:
        self._config = config
        self._counts: Dict[Tuple[str, Timeframe], int] = {}

    def record_closed_bar(self, symbol: str, timeframe: Timeframe) -> None:
        key = (symbol, timeframe)
        self._counts[key] = self._counts.get(key, 0) + 1

    def status(self, symbol: str, timeframe: Timeframe) -> WarmupStatus:
        received = self._counts.get((symbol, timeframe), 0)
        required = self._config.min_warmup_bars_by_timeframe[timeframe]
        return WarmupStatus(symbol=symbol, timeframe=timeframe, bars_received=received, bars_required=required, ready=received >= required)

    def all_statuses(self) -> Tuple[WarmupStatus, ...]:
        return tuple(
            self.status(symbol, timeframe)
            for symbol in self._config.enabled_pairs
            for timeframe in self._config.required_timeframes
        )


__all__ = ["WarmupTracker"]
