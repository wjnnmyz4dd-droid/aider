"""The command relay queue -- the single transport chokepoint.

`CommandQueue` is the only place a `TradeCommand` is stored between
`BridgeEngine.submit_command()` enqueuing it and the EA picking it up
via a poll. Every command is keyed by `correlation_id`, supplied by
whoever submits the command -- this module invents no parallel ID
scheme.

Fail-closed: `enqueue()` refuses when the caller reports the bridge is
not ready (no recent EA heartbeat) or when the emergency stop is
active. Idempotent: a duplicate `correlation_id` is never enqueued
twice, a stale (past-TTL) command is dropped rather than delivered, and
a duplicate execution report for an already-terminal `correlation_id`
is a no-op, never a second fill.
"""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

from .config import BridgeConfig
from .models import EmergencyStopState, ErrorCode, ExecutionReport, TradeCommand

# Rough, documented approximation only -- not a precise measurement.
# Used solely for the "memory estimate" observability gauge (Phase 1.6);
# never for any correctness decision.
_APPROX_BYTES_PER_COMMAND_RECORD = 512
_APPROX_BYTES_PER_CACHED_REPORT = 256


class CommandQueue:
    """Both `enqueue()` and `poll()` go through this single chokepoint --
    emergency-stop state lives here, not duplicated across any other
    file, so there is exactly one place that can ever gate command
    flow.

    Thread safety: `phantom/bridge/server.py` serves every route through
    `http.server.ThreadingHTTPServer`, one thread per request, so this
    queue's state can be reached concurrently from separate `enqueue`/
    `poll`/`record_result`/read calls. A single non-reentrant lock guards
    every method's body -- no method here calls another public method of
    this class internally, so a plain `Lock` cannot self-deadlock.

    Retention (Phase 1.6): nothing here grows forever. A deterministic,
    age-ordered cleanup pass runs at most once per
    `config.cleanup_interval_seconds`, triggered opportunistically from
    `enqueue()`, `poll()`, and `record_result()` -- no new clock
    parameter was added to any of them; each already carries (or is
    passed) a timestamp usable as "now" for this purpose. See
    `_run_cleanup_locked()` for the exact rule, and
    `PHANTOM_BRIDGE_PHASE1_6_HARDENING_REPORT.md` for the full retention
    model and rationale. No public method's signature or return type
    changed; every new method below is additive (observability reads
    only)."""

    def __init__(self, config: BridgeConfig) -> None:
        self.config = config
        self._lock = threading.Lock()
        self._commands: Dict[str, TradeCommand] = {}
        self._pending_order: List[str] = []
        self._delivered_ids: Set[str] = set()
        self._executed_ids: Set[str] = set()
        self._results: Dict[str, ExecutionReport] = {}
        self._emergency_stop = EmergencyStopState(active=False, reason=None, activated_at=None)
        self._last_cleanup_at: Optional[datetime] = None
        self._cleanup_run_count = 0
        self._expired_removed_count = 0
        self._largest_pending_seen = 0

    def set_emergency_stop(self, active: bool, reason: Optional[str], at: Optional[datetime]) -> EmergencyStopState:
        with self._lock:
            self._emergency_stop = EmergencyStopState(active=active, reason=reason if active else None, activated_at=at if active else None)
            return self._emergency_stop

    @property
    def emergency_stop_state(self) -> EmergencyStopState:
        with self._lock:
            return self._emergency_stop

    def enqueue(self, command: TradeCommand, is_ready: bool) -> Optional[ErrorCode]:
        """Returns a rejection reason, or `None` if enqueued."""
        with self._lock:
            self._run_cleanup_locked(command.issued_at)
            if self._emergency_stop.active:
                return ErrorCode.EMERGENCY_STOP_ACTIVE
            if not is_ready:
                return ErrorCode.BRIDGE_NOT_READY
            if command.correlation_id in self._commands:
                return ErrorCode.DUPLICATE_CORRELATION_ID
            self._commands[command.correlation_id] = command
            self._pending_order.append(command.correlation_id)
            if len(self._pending_order) > self._largest_pending_seen:
                self._largest_pending_seen = len(self._pending_order)
            return None

    def poll(self, now: datetime) -> Tuple[TradeCommand, ...]:
        """Every still-pending command is either delivered now (if not
        stale) or dropped (if stale) -- never left pending across two
        `poll()` calls, since a command is meant for immediate relay,
        not a durable backlog. Returns nothing while the emergency stop
        is active, regardless of what was already pending."""
        with self._lock:
            # Cleanup runs even during an emergency stop -- a halted
            # bridge is exactly when a long outage could otherwise let
            # retention grow unchecked, so this check is deliberately
            # ahead of the early-return below, not after it.
            self._run_cleanup_locked(now)
            if self._emergency_stop.active:
                self._pending_order = []
                return ()
            ready = []
            for correlation_id in self._pending_order:
                command = self._commands[correlation_id]
                age = (now - command.issued_at).total_seconds()
                if age > self.config.command_ttl_seconds:
                    continue
                ready.append(command)
                self._delivered_ids.add(correlation_id)
            self._pending_order = []
            return tuple(ready)

    def record_result(self, correlation_id: str, report: ExecutionReport) -> bool:
        """Returns `True` if newly recorded, `False` if this
        `correlation_id` already has a terminal result (a duplicate
        execution report) or was never a command this queue issued
        (only Phantom-issued commands may ever have a result
        recorded)."""
        with self._lock:
            self._run_cleanup_locked(report.reported_at)
            if correlation_id not in self._commands:
                return False
            if correlation_id in self._executed_ids:
                return False
            self._executed_ids.add(correlation_id)
            self._results[correlation_id] = report
            return True

    def command_for(self, correlation_id: str) -> Optional[TradeCommand]:
        with self._lock:
            return self._commands.get(correlation_id)

    def result_for(self, correlation_id: str) -> Optional[ExecutionReport]:
        with self._lock:
            return self._results.get(correlation_id)

    def is_delivered(self, correlation_id: str) -> bool:
        with self._lock:
            return correlation_id in self._delivered_ids

    def is_executed(self, correlation_id: str) -> bool:
        with self._lock:
            return correlation_id in self._executed_ids

    def all_results(self) -> Tuple[ExecutionReport, ...]:
        with self._lock:
            return tuple(self._results.values())

    # -- Retention (Phase 1.6) -------------------------------------------

    def _run_cleanup_locked(self, now: datetime) -> None:
        """Assumes `self._lock` is already held. Deterministic,
        age-ordered purge only -- no randomness, no LRU-by-access.

        Per correlation_id, evaluated at each cleanup pass:

        - No result recorded yet: purge once
          `now - command.issued_at > correlation_ttl_seconds` (the
          outer bound for an abandoned/never-executed command).
        - A result IS recorded: purge once
          `now - report.reported_at > max(execution_report_ttl_seconds,
          duplicate_detection_ttl_seconds)` -- kept at least long enough
          to satisfy both "keep the execution report until its own TTL"
          and "keep duplicate-detection state long enough to guarantee
          idempotency."

        On top of the TTL rule, a deterministic count-based cap also
        applies: if more completed (executed) correlation_ids remain
        than `min(max_completed_commands, max_cached_reports)`, the
        oldest completed ones (by `reported_at`) are purged first until
        back under the cap -- "automatically purge completed commands"
        and "bound caches by size" both resolve to this one rule, since
        a completed command and its cached report are the same
        correlation_id's record here, not two independent stores.

        Runs at most once per `cleanup_interval_seconds`; a no-op
        otherwise (cheap: one datetime comparison)."""
        if (
            self._last_cleanup_at is not None
            and (now - self._last_cleanup_at).total_seconds() < self.config.cleanup_interval_seconds
        ):
            return
        self._last_cleanup_at = now
        self._cleanup_run_count += 1

        to_purge: List[str] = []
        for correlation_id, command in self._commands.items():
            if correlation_id in self._executed_ids:
                report = self._results.get(correlation_id)
                reported_at = report.reported_at if report is not None else command.issued_at
                retain_seconds = max(
                    self.config.execution_report_ttl_seconds,
                    self.config.duplicate_detection_ttl_seconds,
                )
                if (now - reported_at).total_seconds() > retain_seconds:
                    to_purge.append(correlation_id)
            else:
                if (now - command.issued_at).total_seconds() > self.config.correlation_ttl_seconds:
                    to_purge.append(correlation_id)

        purge_set = set(to_purge)
        completed_survivors = [
            correlation_id for correlation_id in self._commands
            if correlation_id in self._executed_ids and correlation_id not in purge_set
        ]
        effective_cap = min(self.config.max_completed_commands, self.config.max_cached_reports)
        if len(completed_survivors) > effective_cap:
            completed_survivors.sort(
                key=lambda cid: self._results[cid].reported_at if cid in self._results else self._commands[cid].issued_at
            )
            overflow = len(completed_survivors) - effective_cap
            to_purge.extend(completed_survivors[:overflow])

        final_purge_set = set(to_purge)
        if final_purge_set:
            self._pending_order = [
                correlation_id for correlation_id in self._pending_order
                if correlation_id not in final_purge_set
            ]
        for correlation_id in to_purge:
            self._commands.pop(correlation_id, None)
            self._delivered_ids.discard(correlation_id)
            self._executed_ids.discard(correlation_id)
            self._results.pop(correlation_id, None)
        self._expired_removed_count += len(to_purge)

    # -- Observability (Phase 1.6, additive only) -------------------------

    def pending_count(self) -> int:
        """Current undelivered backlog depth ("current queue size")."""
        with self._lock:
            return len(self._pending_order)

    def completed_count(self) -> int:
        """Correlation IDs with a recorded execution result, currently
        retained (pre-cleanup, this equals `duplicate_cache_size()` --
        both read the same underlying set; see the class docstring)."""
        with self._lock:
            return len(self._executed_ids)

    def duplicate_cache_size(self) -> int:
        with self._lock:
            return len(self._executed_ids)

    def cached_report_count(self) -> int:
        with self._lock:
            return len(self._results)

    def total_tracked_correlation_ids(self) -> int:
        """Every correlation_id this queue currently remembers at all
        (completed or not), before the next cleanup pass."""
        with self._lock:
            return len(self._commands)

    def largest_pending_queue_observed(self) -> int:
        with self._lock:
            return self._largest_pending_seen

    def cleanup_run_count(self) -> int:
        with self._lock:
            return self._cleanup_run_count

    def expired_entries_removed_count(self) -> int:
        with self._lock:
            return self._expired_removed_count

    def estimated_memory_bytes(self) -> int:
        """A documented approximation (fixed per-entry byte costs times
        entry count), not a precise measurement -- adequate for
        observability/alerting trend-watching, never for a correctness
        decision."""
        with self._lock:
            return (
                len(self._commands) * _APPROX_BYTES_PER_COMMAND_RECORD
                + len(self._results) * _APPROX_BYTES_PER_CACHED_REPORT
            )


__all__ = ["CommandQueue"]
