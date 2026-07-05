"""Bounded, TTL-pruned duplicate-request tracking (ADR-007 §7).

This is a deliberate, narrow exception to the statelessness every prior
stage requires (`ADR-002` §2, `ADR-003` §2, `ADR-004` §2) — the same
class of exception those ADRs already carve out for a session-window
clock. Unlike Compliance Engine's kill switch (`ADR-006` §14), ADR-007
does not require this state to survive a process restart — only that it
be explicitly bounded and pruned (mirroring `phantom/orb.py`'s
`state_ttl_days` idea), so no durable/SQLite persistence is invented
here (`CLAUDE.md` §7: "never guess," never invent state ownership the
ADR doesn't call for).

A repeated request is not "the same inputs" as its first occurrence:
idempotency state is itself part of what this stage observes, and it
differs between the first and second attempt — this is why a duplicate
correctly, deterministically produces REJECT without contradicting
determinism (ADR-007 §7, §9).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timedelta


class IdempotencyStore(ABC):
    @abstractmethod
    def has_seen(self, candidate_id: str, now: datetime) -> bool:
        ...

    @abstractmethod
    def record(self, candidate_id: str, now: datetime) -> None:
        ...


class InMemoryIdempotencyStore(IdempotencyStore):
    """Bounded by TTL pruning only — every call prunes entries older than
    `ttl_seconds` relative to `now`, so memory usage stays bounded by the
    request rate over one TTL window, never growing unbounded."""

    def __init__(self, ttl_seconds: float) -> None:
        self.ttl_seconds = ttl_seconds
        self._seen_at: dict[str, datetime] = {}

    def _prune(self, now: datetime) -> None:
        cutoff = now - timedelta(seconds=self.ttl_seconds)
        expired = [key for key, seen_at in self._seen_at.items() if seen_at < cutoff]
        for key in expired:
            del self._seen_at[key]

    def has_seen(self, candidate_id: str, now: datetime) -> bool:
        self._prune(now)
        return candidate_id in self._seen_at

    def record(self, candidate_id: str, now: datetime) -> None:
        self._seen_at[candidate_id] = now
