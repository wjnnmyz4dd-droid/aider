"""Persisted, restart-safe compliance state (Final Release Hardening,
requirement 2).

This is deliberately a thin, caller-owned persistence record -- not a
new compliance model. It stores exactly the fields ADR-028's own
`AccountState`/`ComplianceLockState` already declare as caller-owned
(`daily_starting_balance`, `peak_balance`, `compliance_lock`,
`trading_days_count`) plus the two facts no engine type carries because
they are calendar/storage concerns, not compliance concerns
(`trading_day_id`, `last_reset_at`). Current daily loss and daily
profit are NOT stored here: `ComplianceEngine`'s own
`daily_loss.py`/`profit_protection.py` already derive both, live, from
`account_balance` vs `daily_starting_balance` -- storing them again
would be a duplicate calculation (CLAUDE.md §1.4)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from titan_protocol.compliance_engine.models import ComplianceLockState

#: Bumped whenever the on-disk shape changes. `store.py` refuses to load
#: a file whose `schema_version` it does not explicitly know how to
#: read (fail closed on ambiguous persisted state) rather than guessing.
SCHEMA_VERSION = 1


class CorruptStateError(Exception):
    """Raised when persisted compliance state exists but cannot be
    trusted (missing keys, wrong types, unknown schema version, invalid
    JSON, and no usable backup either). Callers must fail closed on
    this -- never silently fall back to fresh/default state, since that
    would silently erase a real loss/lock history."""


@dataclass(frozen=True)
class PersistedComplianceState:
    """The full, restart-safe compliance state for one trading day."""

    schema_version: int
    trading_day_id: str
    daily_starting_balance: float
    peak_balance: float
    compliance_lock: ComplianceLockState
    trading_days_count: int
    last_reset_at: datetime


__all__ = ["SCHEMA_VERSION", "CorruptStateError", "PersistedComplianceState"]
