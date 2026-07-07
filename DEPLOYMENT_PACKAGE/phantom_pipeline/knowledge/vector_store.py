"""Vector store for the Knowledge & RAG subsystem (`ADR-020` §8).

`InMemoryVectorStore` is this ADR's real Phase 1 store — the same
"real in-memory store now, a persistence backend later" posture every
other package's `InMemory*Store` already takes (e.g.
`analytics.store.InMemoryTradeProvenanceStore`,
`watchdog.state_store.InMemoryWatchdogStateStore`). A persistent (on-disk
or external) vector database is explicitly out of scope for this ADR.

Thread-safe: `add`/`delete`/`search` each take a lock only around the
mutation or the snapshot read, never while scoring — concurrent
ingestion and search never corrupt state or raise.
"""

from __future__ import annotations

import math
import threading
from typing import Dict, Mapping, Optional, Protocol, Tuple


def _cosine_similarity(a: Tuple[float, ...], b: Tuple[float, ...]) -> float:
    if len(a) != len(b):
        raise ValueError(f"vector dimension mismatch: {len(a)} != {len(b)}")
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


class VectorStore(Protocol):
    def add(self, document_id: str, vector: Tuple[float, ...], metadata: Mapping[str, str]) -> None: ...

    def delete(self, document_id: str) -> None: ...

    def search(
        self, query_vector: Tuple[float, ...], top_k: int, filters: Optional[Mapping[str, str]]
    ) -> Tuple[Tuple[str, float], ...]: ...

    def __contains__(self, document_id: str) -> bool: ...

    @property
    def count(self) -> int: ...


class InMemoryVectorStore:
    def __init__(self) -> None:
        self._vectors: Dict[str, Tuple[float, ...]] = {}
        self._metadata: Dict[str, Dict[str, str]] = {}
        self._lock = threading.Lock()

    def add(self, document_id: str, vector: Tuple[float, ...], metadata: Optional[Mapping[str, str]] = None) -> None:
        with self._lock:
            self._vectors[document_id] = tuple(vector)
            self._metadata[document_id] = dict(metadata or {})

    def delete(self, document_id: str) -> None:
        with self._lock:
            self._vectors.pop(document_id, None)
            self._metadata.pop(document_id, None)

    def __contains__(self, document_id: str) -> bool:
        with self._lock:
            return document_id in self._vectors

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._vectors)

    def search(
        self,
        query_vector: Tuple[float, ...],
        top_k: int = 10,
        filters: Optional[Mapping[str, str]] = None,
    ) -> Tuple[Tuple[str, float], ...]:
        filters = dict(filters or {})
        with self._lock:
            items = list(self._vectors.items())
            metadata_snapshot = {doc_id: dict(meta) for doc_id, meta in self._metadata.items()}

        candidates = []
        for document_id, vector in items:
            meta = metadata_snapshot.get(document_id, {})
            if not all(meta.get(key) == value for key, value in filters.items()):
                continue
            candidates.append((document_id, _cosine_similarity(query_vector, vector)))

        candidates.sort(key=lambda pair: pair[1], reverse=True)
        return tuple(candidates[:top_k])


__all__ = ["VectorStore", "InMemoryVectorStore"]
