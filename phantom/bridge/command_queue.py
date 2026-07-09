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

from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

from .config import BridgeConfig
from .models import EmergencyStopState, ErrorCode, ExecutionReport, TradeCommand


class CommandQueue:
    """Both `enqueue()` and `poll()` go through this single chokepoint --
    emergency-stop state lives here, not duplicated across any other
    file, so there is exactly one place that can ever gate command
    flow."""

    def __init__(self, config: BridgeConfig) -> None:
        self.config = config
        self._commands: Dict[str, TradeCommand] = {}
        self._pending_order: List[str] = []
        self._delivered_ids: Set[str] = set()
        self._executed_ids: Set[str] = set()
        self._results: Dict[str, ExecutionReport] = {}
        self._emergency_stop = EmergencyStopState(active=False, reason=None, activated_at=None)

    def set_emergency_stop(self, active: bool, reason: Optional[str], at: Optional[datetime]) -> EmergencyStopState:
        self._emergency_stop = EmergencyStopState(active=active, reason=reason if active else None, activated_at=at if active else None)
        return self._emergency_stop

    @property
    def emergency_stop_state(self) -> EmergencyStopState:
        return self._emergency_stop

    def enqueue(self, command: TradeCommand, is_ready: bool) -> Optional[ErrorCode]:
        """Returns a rejection reason, or `None` if enqueued."""
        if self._emergency_stop.active:
            return ErrorCode.EMERGENCY_STOP_ACTIVE
        if not is_ready:
            return ErrorCode.BRIDGE_NOT_READY
        if command.correlation_id in self._commands:
            return ErrorCode.DUPLICATE_CORRELATION_ID
        self._commands[command.correlation_id] = command
        self._pending_order.append(command.correlation_id)
        return None

    def poll(self, now: datetime) -> Tuple[TradeCommand, ...]:
        """Every still-pending command is either delivered now (if not
        stale) or dropped (if stale) -- never left pending across two
        `poll()` calls, since a command is meant for immediate relay,
        not a durable backlog. Returns nothing while the emergency stop
        is active, regardless of what was already pending."""
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
        if correlation_id not in self._commands:
            return False
        if correlation_id in self._executed_ids:
            return False
        self._executed_ids.add(correlation_id)
        self._results[correlation_id] = report
        return True

    def command_for(self, correlation_id: str) -> Optional[TradeCommand]:
        return self._commands.get(correlation_id)

    def result_for(self, correlation_id: str) -> Optional[ExecutionReport]:
        return self._results.get(correlation_id)

    def is_delivered(self, correlation_id: str) -> bool:
        return correlation_id in self._delivered_ids

    def is_executed(self, correlation_id: str) -> bool:
        return correlation_id in self._executed_ids

    def all_results(self) -> Tuple[ExecutionReport, ...]:
        return tuple(self._results.values())


__all__ = ["CommandQueue"]
