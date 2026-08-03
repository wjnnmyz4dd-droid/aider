"""Knowledge & RAG subsystem-only metrics surface (`ADR-020` §3).

Export-only, additive — recording a metric has zero effect on any
returned output, matching every prior stage's own metrics module
discipline (e.g. `watchdog.metrics.WatchdogMetrics`).
"""

from __future__ import annotations

from typing import List


class KnowledgeMetrics:
    def __init__(self) -> None:
        self._documents_indexed_count: int = 0
        self._duplicate_documents_skipped_count: int = 0
        self._trades_indexed_count: int = 0
        self._duplicate_trades_skipped_count: int = 0
        self._searches_performed_count: int = 0
        self._search_latencies_seconds: List[float] = []

    def record_document_ingested(self) -> None:
        self._documents_indexed_count += 1

    def record_duplicate_document_skipped(self) -> None:
        self._duplicate_documents_skipped_count += 1

    def record_trade_indexed(self) -> None:
        self._trades_indexed_count += 1

    def record_duplicate_trade_skipped(self) -> None:
        self._duplicate_trades_skipped_count += 1

    def record_search(self, latency_seconds: float) -> None:
        self._searches_performed_count += 1
        self._search_latencies_seconds.append(latency_seconds)

    @property
    def documents_indexed_count(self) -> int:
        return self._documents_indexed_count

    @property
    def duplicate_documents_skipped_count(self) -> int:
        return self._duplicate_documents_skipped_count

    @property
    def trades_indexed_count(self) -> int:
        return self._trades_indexed_count

    @property
    def duplicate_trades_skipped_count(self) -> int:
        return self._duplicate_trades_skipped_count

    @property
    def searches_performed_count(self) -> int:
        return self._searches_performed_count

    @property
    def average_search_latency_seconds(self) -> float:
        if not self._search_latencies_seconds:
            return 0.0
        return sum(self._search_latencies_seconds) / len(self._search_latencies_seconds)


__all__ = ["KnowledgeMetrics"]
