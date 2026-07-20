"""Pair-level in-flight command registry (Runtime-owned).

`RuntimeOrchestrator` generates a fresh `TradeCommand`/`correlation_id`
every cycle (`bridge_handoff.build_trade_command()`) whenever
`compliance.ready_for_bridge` is true, with no memory of a command it
already submitted for the same pair last cycle. This registry closes
that gap: it tracks at most one outstanding (submitted, not yet
resolved) command per pair, so `RuntimeOrchestrator` can refuse to
generate a second one until the first reaches a terminal state (an
`ExecutionReport` was recorded against it, checked via
`BridgeEngine.command_resolved()`) or expires (`ttl_seconds`, a bound
against a command whose `ExecutionReport` never arrives).

Deliberately Runtime-owned, not Bridge-owned: `titan_protocol/bridge/`
is the execution relay only, never a decision authority (ADR-023) --
"should a second command be allowed while the first is unresolved" is a
decision-time gate, and belongs alongside Runtime's other gates
(risk/compliance), not inside the relay itself. This module has no
dependency on `titan_protocol.bridge` at all; it is handed a plain
`is_resolved(correlation_id) -> bool` callable by its caller (see
`reconcile()`), matching the same narrow-callable pattern
`RuntimeOrchestrator.bridge_submit` already uses.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Dict, Optional


@dataclass(frozen=True)
class _InFlightEntry:
    correlation_id: str
    submitted_at: datetime


class InFlightCommandRegistry:
    """Thread safety: reached from the live-cycle loop only in this
    codebase's current wiring (one thread), but guarded by a lock
    regardless -- cheap, and removes any future assumption that this
    can only ever be called single-threaded."""

    def __init__(self, ttl_seconds: float) -> None:
        self._ttl_seconds = ttl_seconds
        self._lock = threading.Lock()
        self._by_pair: Dict[str, _InFlightEntry] = {}

    def has_unresolved(self, pair: str, now: datetime) -> bool:
        """True if `pair` has a command outstanding that has neither
        resolved nor expired. Never mutates state -- expiry is only
        ever applied by `reconcile()`, so a caller that checks this
        without ever calling `reconcile()` still gets a correct answer
        (the TTL check is evaluated fresh here too), but the entry
        itself is only cleaned up by `reconcile()`."""
        with self._lock:
            entry = self._by_pair.get(pair)
            if entry is None:
                return False
            return (now - entry.submitted_at).total_seconds() <= self._ttl_seconds

    def record_submission(self, pair: str, correlation_id: str, now: datetime) -> None:
        with self._lock:
            self._by_pair[pair] = _InFlightEntry(correlation_id=correlation_id, submitted_at=now)

    def reconcile(self, now: datetime, is_resolved: Callable[[str], bool]) -> int:
        """Drops every tracked entry that has either resolved (per
        `is_resolved(correlation_id)`, a caller-supplied query -- this
        module never assumes how resolution is determined) or expired
        past `ttl_seconds`. Returns the number of entries dropped this
        call, for logging. Call once per live cycle, before checking
        `has_unresolved()` for that cycle's pairs."""
        with self._lock:
            to_drop = []
            for pair, entry in self._by_pair.items():
                if (now - entry.submitted_at).total_seconds() > self._ttl_seconds:
                    to_drop.append(pair)
                    continue
                if is_resolved(entry.correlation_id):
                    to_drop.append(pair)
            for pair in to_drop:
                del self._by_pair[pair]
            return len(to_drop)

    def correlation_id_for(self, pair: str) -> Optional[str]:
        with self._lock:
            entry = self._by_pair.get(pair)
            return entry.correlation_id if entry is not None else None

    def in_flight_count(self) -> int:
        with self._lock:
            return len(self._by_pair)


__all__ = ["InFlightCommandRegistry"]
