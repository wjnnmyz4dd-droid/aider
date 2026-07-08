"""The command relay queue (`ADR-023` §2, §3, Hard Rules 4, 5, 7).

`CommandQueue` is the only place an `ExecutionCommand` is stored between
`EABrokerAdapter.send_request()` enqueuing it and the EA picking it up
via `/ea/commands/poll`. Every command is keyed by `execution_id` — the
same identifier `mt5_bridge` already generates (`make_execution_id`);
this module invents no parallel ID scheme.

Fail-closed (`ADR-023` Hard Rule 5): `enqueue()` refuses when the caller
reports the bridge is not ready (i.e. no recent EA heartbeat). Idempotent
(`ADR-023` Hard Rule 7): a duplicate `execution_id` is never enqueued
twice, a stale (past-TTL) command is dropped rather than delivered, and a
duplicate execution report for an already-terminal `execution_id` is a
no-op, never a second fill.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

from .config import EABridgeConfig
from .models import ExecutionCommand, ExecutionReport


class CommandQueue:
    """The single transport chokepoint both `enqueue()` (from
    `EABrokerAdapter.send_request()`) and `poll()` (from the EA's
    `/ea/commands/poll`) go through — emergency-stop state lives here,
    not duplicated across the adapter/engine, so there is exactly one
    place that can ever gate command flow (`ADR-023` Hard Rule 5)."""

    def __init__(self, config: EABridgeConfig) -> None:
        self.config = config
        self._commands: Dict[str, ExecutionCommand] = {}
        self._pending_order: List[str] = []
        self._delivered_ids: Set[str] = set()
        self._executed_ids: Set[str] = set()
        self._results: Dict[str, ExecutionReport] = {}
        self._emergency_stop_active = False

    def set_emergency_stop(self, active: bool) -> None:
        self._emergency_stop_active = active

    @property
    def emergency_stop_active(self) -> bool:
        return self._emergency_stop_active

    def enqueue(self, command: ExecutionCommand, is_ready: bool) -> Optional[str]:
        """Returns a rejection reason, or `None` if enqueued."""
        if self._emergency_stop_active:
            return "emergency_stop_active"
        if not is_ready:
            return "bridge_not_ready"
        if command.execution_id in self._commands:
            return "duplicate_command_id"
        self._commands[command.execution_id] = command
        self._pending_order.append(command.execution_id)
        return None

    def poll(self, now: datetime) -> Tuple[ExecutionCommand, ...]:
        """Every still-pending command is either delivered now (if not
        stale) or dropped (if stale) — never left pending across two
        `poll()` calls, since a command is meant for immediate relay, not
        a durable backlog. Returns nothing while emergency-stop is
        active, regardless of what was already pending."""
        if self._emergency_stop_active:
            self._pending_order = []
            return ()
        ready = []
        for execution_id in self._pending_order:
            command = self._commands[execution_id]
            age = (now - command.issued_at).total_seconds()
            if age > self.config.command_ttl_seconds:
                continue
            ready.append(command)
            self._delivered_ids.add(execution_id)
        self._pending_order = []
        return tuple(ready)

    def record_result(self, execution_id: str, report: ExecutionReport) -> bool:
        """Returns `True` if newly recorded, `False` if this
        `execution_id` already has a terminal result (a duplicate
        execution report, `ADR-023` Hard Rule 7) or was never a command
        this queue issued (`ADR-023` Hard Rule 4 — only Phantom-issued
        commands may ever have a result recorded)."""
        if execution_id not in self._commands:
            return False
        if execution_id in self._executed_ids:
            return False
        self._executed_ids.add(execution_id)
        self._results[execution_id] = report
        return True

    def command_for(self, execution_id: str) -> Optional[ExecutionCommand]:
        return self._commands.get(execution_id)

    def result_for(self, execution_id: str) -> Optional[ExecutionReport]:
        return self._results.get(execution_id)

    def is_delivered(self, execution_id: str) -> bool:
        return execution_id in self._delivered_ids

    def is_executed(self, execution_id: str) -> bool:
        return execution_id in self._executed_ids


__all__ = ["CommandQueue"]
