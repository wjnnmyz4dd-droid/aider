"""Pure helper functions for compliance-lock/emergency-stop state
transitions (ADR-028 §5.10). `ComplianceEngine` itself never mutates
`AccountState` -- these are convenience functions for whatever
orchestrates the pipeline to construct the *next* `AccountState` it
supplies, exactly as `evaluate()`'s own `lock_recommendation` output is
meant to be applied (ADR-028 §3)."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Optional

from .models import AccountState, ComplianceLockState


def is_locked(account: AccountState) -> bool:
    return account.compliance_lock.active or account.emergency_stop_active


def apply_daily_reset(account: AccountState, now: datetime) -> AccountState:
    """Resets daily-scoped counters and lifts a compliance lock whose
    configured `resets_at` has passed -- never lifts an emergency stop,
    which requires an explicit operator unlock."""

    new_lock = account.compliance_lock
    if account.compliance_lock.active and account.compliance_lock.resets_at is not None and now >= account.compliance_lock.resets_at:
        new_lock = ComplianceLockState()
    return replace(account, daily_starting_balance=account.account_balance, trades_today_count=0, compliance_lock=new_lock)


def apply_operator_unlock(account: AccountState) -> AccountState:
    """An explicit operator action -- clears both the compliance lock
    and the emergency stop, regardless of `resets_at`."""

    return replace(account, compliance_lock=ComplianceLockState(), emergency_stop_active=False)


def trigger_lock(account: AccountState, reason: str, locked_at: datetime, resets_at: Optional[datetime] = None) -> AccountState:
    return replace(account, compliance_lock=ComplianceLockState(active=True, reason=reason, locked_at=locked_at, resets_at=resets_at))


__all__ = ["is_locked", "apply_daily_reset", "apply_operator_unlock", "trigger_lock"]
