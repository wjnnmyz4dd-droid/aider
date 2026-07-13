"""Thread-safe counters for Market Data Ingestion (mirrors every other
engine's `metrics.py` this session -- observability only, never a
decision input)."""

from __future__ import annotations

import threading


class MarketDataIngestionMetrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._accepted = 0
        self._rejected = 0
        self._gaps_detected = 0
        self._ticks_ingested = 0

    def record_bar_accepted(self) -> None:
        with self._lock:
            self._accepted += 1

    def record_bar_rejected(self) -> None:
        with self._lock:
            self._rejected += 1

    def record_gap_detected(self) -> None:
        with self._lock:
            self._gaps_detected += 1

    def record_tick_ingested(self) -> None:
        with self._lock:
            self._ticks_ingested += 1

    @property
    def accepted_count(self) -> int:
        with self._lock:
            return self._accepted

    @property
    def rejected_count(self) -> int:
        with self._lock:
            return self._rejected

    @property
    def gaps_detected_count(self) -> int:
        with self._lock:
            return self._gaps_detected

    @property
    def ticks_ingested_count(self) -> int:
        with self._lock:
            return self._ticks_ingested


__all__ = ["MarketDataIngestionMetrics"]
