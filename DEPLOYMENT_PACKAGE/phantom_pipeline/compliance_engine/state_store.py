"""Durable kill-switch / daily-lockout state (ADR-006 §14, §15, `ADR-015`
§6's Database entry).

The kill switch is a **permanent**, latched state — once triggered it
must survive a process restart (ADR-006 §14). The daily lockout is keyed
by trading day, so it resets automatically once the day advances,
distinct from the kill switch's permanence (ADR-006 §6 vs §14).

Both stores are read-only from `checks.py`'s perspective — only
`ComplianceEngine` (via `trigger_kill_switch`/`trigger_daily_lockout`)
ever writes to them, and only after this call's own fresh evaluation
determines a breach occurred. This mirrors `ADR-015` §6's fail-closed
rule for Compliance-critical database state: if the store cannot be
read reliably, callers must treat that as `is_kill_switch_triggered() ->
True` / `is_daily_locked_out() -> True`, never silently as `False`.

`InMemoryComplianceStateStore` is explicitly non-durable (state is lost
on process restart) and exists for isolated unit tests and non-production
use only. `SqliteComplianceStateStore` is the durable implementation,
using only the Python standard library (`sqlite3`) per `ADR-015` §6's
SQLite-initial guidance, so a Compliance Engine deployment never depends
on a database driver beyond what ships with Python.
"""

from __future__ import annotations

import sqlite3
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional


class ComplianceStateStore(ABC):
    @abstractmethod
    def is_kill_switch_triggered(self) -> bool:
        ...

    @abstractmethod
    def kill_switch_reason(self) -> Optional[str]:
        ...

    @abstractmethod
    def trigger_kill_switch(self, reason: str, trace_id: str, timestamp: datetime) -> None:
        ...

    @abstractmethod
    def is_daily_locked_out(self, day: str) -> bool:
        ...

    @abstractmethod
    def trigger_daily_lockout(
        self, day: str, reason: str, trace_id: str, timestamp: datetime
    ) -> None:
        ...


class InMemoryComplianceStateStore(ComplianceStateStore):
    """Non-durable — state does not survive a process restart. For
    isolated unit tests only; never use for production kill-switch
    persistence (ADR-006 §14)."""

    def __init__(self) -> None:
        self._kill_switch_reason: Optional[str] = None
        self._locked_day: Optional[str] = None

    def is_kill_switch_triggered(self) -> bool:
        return self._kill_switch_reason is not None

    def kill_switch_reason(self) -> Optional[str]:
        return self._kill_switch_reason

    def trigger_kill_switch(self, reason: str, trace_id: str, timestamp: datetime) -> None:
        if self._kill_switch_reason is None:
            self._kill_switch_reason = reason

    def is_daily_locked_out(self, day: str) -> bool:
        return self._locked_day == day

    def trigger_daily_lockout(
        self, day: str, reason: str, trace_id: str, timestamp: datetime
    ) -> None:
        self._locked_day = day


class SqliteComplianceStateStore(ComplianceStateStore):
    """Durable kill-switch/daily-lockout persistence (ADR-006 §14,
    `ADR-015` §6). Opens a short-lived connection per call rather than
    holding one open for the store's lifetime, so state genuinely reads
    back from disk across a simulated process restart (a fresh store
    instance pointed at the same `db_path`)."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS compliance_state ("
                "key TEXT PRIMARY KEY, reason TEXT, trace_id TEXT, timestamp TEXT)"
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def is_kill_switch_triggered(self) -> bool:
        return self.kill_switch_reason() is not None

    def kill_switch_reason(self) -> Optional[str]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT reason FROM compliance_state WHERE key = 'kill_switch'"
            ).fetchone()
        return row[0] if row is not None else None

    def trigger_kill_switch(self, reason: str, trace_id: str, timestamp: datetime) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO compliance_state (key, reason, trace_id, timestamp) "
                "VALUES ('kill_switch', ?, ?, ?)",
                (reason, trace_id, timestamp.isoformat()),
            )

    def is_daily_locked_out(self, day: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT reason FROM compliance_state WHERE key = 'daily_lockout'"
            ).fetchone()
        return row is not None and row[0] == day

    def trigger_daily_lockout(
        self, day: str, reason: str, trace_id: str, timestamp: datetime
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO compliance_state (key, reason, trace_id, timestamp) "
                "VALUES ('daily_lockout', ?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET reason = excluded.reason, "
                "trace_id = excluded.trace_id, timestamp = excluded.timestamp",
                (day, trace_id, timestamp.isoformat()),
            )
