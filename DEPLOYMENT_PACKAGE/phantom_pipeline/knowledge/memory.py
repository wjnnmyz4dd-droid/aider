"""Trade memory repository (`ADR-020` §2, §3) — real Phase 1 in-memory
store for `TradeMemoryRecord`s, thread-safe, deduplicated by `trace_id`
(re-recording the same trade is a no-op, never a duplicate entry).
"""

from __future__ import annotations

import threading
from typing import Callable, Dict, Optional, Tuple

from .models import TradeMemoryRecord


class TradeMemoryStore:
    def __init__(self) -> None:
        self._records: Dict[str, TradeMemoryRecord] = {}
        self._lock = threading.Lock()

    def add(self, record: TradeMemoryRecord) -> bool:
        with self._lock:
            if record.trace_id in self._records:
                return False
            self._records[record.trace_id] = record
            return True

    def get(self, trace_id: str) -> Optional[TradeMemoryRecord]:
        with self._lock:
            return self._records.get(trace_id)

    def all(self) -> Tuple[TradeMemoryRecord, ...]:
        with self._lock:
            return tuple(self._records.values())

    def find_by(
        self,
        symbol: Optional[str] = None,
        session: Optional[str] = None,
        market_regime: Optional[str] = None,
        strategy_id: Optional[str] = None,
        predicate: Optional[Callable[[TradeMemoryRecord], bool]] = None,
    ) -> Tuple[TradeMemoryRecord, ...]:
        with self._lock:
            records = tuple(self._records.values())

        results = []
        for record in records:
            if symbol is not None and record.symbol != symbol:
                continue
            if session is not None and session not in record.sessions:
                continue
            if market_regime is not None and record.market_regime != market_regime:
                continue
            if strategy_id is not None and record.strategy_id != strategy_id:
                continue
            if predicate is not None and not predicate(record):
                continue
            results.append(record)
        return tuple(results)

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._records)


__all__ = ["TradeMemoryStore"]
