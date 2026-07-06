"""Transport-layer duplicate-submission tracking (ADR-008 §7).

This is a second, independent layer of idempotency from `ADR-007` §7's
decision-layer duplicate-request handling, not a duplication of it —
`ADR-007` prevents a duplicate `ExecutionDecision` APPROVE from being
produced for the same trade; this prevents a duplicate *submission to
the broker* (a Bridge restart mid-flight, a transport-level retry, a
replayed message) from reaching MT5 twice for what was, at the decision
layer, a single approved trade. Bounded and TTL-pruned, mirroring
`execution_validator.idempotency_store`'s own discipline — no durable
persistence is invented here, since ADR-008 does not require this record
to survive a process restart (unlike Compliance Engine's kill switch,
`ADR-006` §14).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timedelta


class TransportIdempotencyStore(ABC):
    @abstractmethod
    def has_submitted(self, execution_id: str, now: datetime) -> bool:
        ...

    @abstractmethod
    def record_submitted(self, execution_id: str, now: datetime) -> None:
        ...

    @abstractmethod
    def has_acknowledged(self, execution_id: str) -> bool:
        ...

    @abstractmethod
    def record_acknowledged(self, execution_id: str) -> None:
        ...

    @abstractmethod
    def has_filled(self, execution_id: str) -> bool:
        ...

    @abstractmethod
    def record_filled(self, execution_id: str) -> None:
        ...

    @abstractmethod
    def has_closed(self, execution_id: str) -> bool:
        ...

    @abstractmethod
    def record_closed(self, execution_id: str) -> None:
        ...


class InMemoryTransportIdempotencyStore(TransportIdempotencyStore):
    """Bounded by TTL pruning on the submission record only — the
    acknowledged/filled/closed flags for a given `execution_id` are
    pruned alongside it, so memory usage stays bounded by the submission
    rate over one TTL window."""

    def __init__(self, ttl_seconds: float) -> None:
        self.ttl_seconds = ttl_seconds
        self._submitted_at: dict = {}
        self._acknowledged: set = set()
        self._filled: set = set()
        self._closed: set = set()

    def _prune(self, now: datetime) -> None:
        cutoff = now - timedelta(seconds=self.ttl_seconds)
        expired = [key for key, seen_at in self._submitted_at.items() if seen_at < cutoff]
        for key in expired:
            del self._submitted_at[key]
            self._acknowledged.discard(key)
            self._filled.discard(key)
            self._closed.discard(key)

    def has_submitted(self, execution_id: str, now: datetime) -> bool:
        self._prune(now)
        return execution_id in self._submitted_at

    def record_submitted(self, execution_id: str, now: datetime) -> None:
        self._submitted_at[execution_id] = now

    def has_acknowledged(self, execution_id: str) -> bool:
        return execution_id in self._acknowledged

    def record_acknowledged(self, execution_id: str) -> None:
        self._acknowledged.add(execution_id)

    def has_filled(self, execution_id: str) -> bool:
        return execution_id in self._filled

    def record_filled(self, execution_id: str) -> None:
        self._filled.add(execution_id)

    def has_closed(self, execution_id: str) -> bool:
        return execution_id in self._closed

    def record_closed(self, execution_id: str) -> None:
        self._closed.add(execution_id)
