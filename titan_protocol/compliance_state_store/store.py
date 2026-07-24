"""Durable, restart-safe storage for compliance day-state (Final
Release Hardening, requirement 2).

Design constraints this module exists to satisfy:

- Compliance stays the sole rules authority and stateless/deterministic
  (ADR-028 §3, Hard Rule 6) -- this module never evaluates a rule; it
  only stores/retrieves the `AccountState` fields ADR-028 already
  documents as caller-owned, and reuses ADR-028's own pure
  `lock.apply_daily_reset()` helper for the one state transition
  (daily rollover + lock auto-clear) rather than re-implementing it.
- Never reset loss/lock state merely because this process restarted --
  only `reconcile()` crossing a real trading-day boundary resets
  anything. A missing file on first-ever run bootstraps fresh state
  (there is nothing to lose); a file that exists but cannot be read
  correctly is a fail-closed error (`CorruptStateError`), never a
  silent reset.
- Atomic writes: a temp file is written and fsync'd, then swapped in
  with `os.replace` (atomic on both POSIX and Windows), so a crash
  mid-write can never leave a half-written state file. The previous
  good file is rotated to a `.bak` sibling before every overwrite, so a
  corrupted primary can still be recovered from its last-known-good
  backup instead of failing closed unnecessarily.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from titan_protocol.compliance_engine.lock import apply_daily_reset
from titan_protocol.compliance_engine.models import AccountState, ComplianceLockState, LockRecommendation

from .bootstrap import resolve_bootstrap_balance
from .config import ComplianceStateStoreConfig
from .models import SCHEMA_VERSION, CorruptStateError, PersistedComplianceState
from .trading_day import trading_day_id_for


def _dt_to_iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value is not None else None


def _dt_from_iso(value: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(value) if value is not None else None


def _lock_to_dict(lock: ComplianceLockState) -> dict:
    return {
        "active": lock.active,
        "reason": lock.reason,
        "locked_at": _dt_to_iso(lock.locked_at),
        "resets_at": _dt_to_iso(lock.resets_at),
    }


def _lock_from_dict(raw: dict) -> ComplianceLockState:
    return ComplianceLockState(
        active=bool(raw["active"]),
        reason=raw["reason"],
        locked_at=_dt_from_iso(raw["locked_at"]),
        resets_at=_dt_from_iso(raw["resets_at"]),
    )


def _state_to_dict(state: PersistedComplianceState) -> dict:
    return {
        "schema_version": state.schema_version,
        "trading_day_id": state.trading_day_id,
        "daily_starting_balance": state.daily_starting_balance,
        "peak_balance": state.peak_balance,
        "compliance_lock": _lock_to_dict(state.compliance_lock),
        "trading_days_count": state.trading_days_count,
        "last_reset_at": _dt_to_iso(state.last_reset_at),
    }


def _state_from_dict(raw: dict) -> PersistedComplianceState:
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise CorruptStateError(
            f"persisted compliance state has schema_version={raw.get('schema_version')!r}, "
            f"expected {SCHEMA_VERSION!r} -- no migration is defined for this version"
        )
    return PersistedComplianceState(
        schema_version=raw["schema_version"],
        trading_day_id=str(raw["trading_day_id"]),
        daily_starting_balance=float(raw["daily_starting_balance"]),
        peak_balance=float(raw["peak_balance"]),
        compliance_lock=_lock_from_dict(raw["compliance_lock"]),
        trading_days_count=int(raw["trading_days_count"]),
        last_reset_at=_dt_from_iso(raw["last_reset_at"]),
    )


class ComplianceStateStore:
    def __init__(self, config: ComplianceStateStoreConfig) -> None:
        self.config = config

    def load_or_bootstrap(
        self, now: datetime, current_balance: float,
        current_equity: Optional[float] = None,
        has_open_positions: bool = False,
    ) -> Optional[PersistedComplianceState]:
        """Loads existing persisted state, or -- only when the file has
        never existed -- bootstraps fresh day-one state from a verified
        day-start balance (KNOWN_GAPS.md #9).

        `current_equity`/`has_open_positions` default to "the account is
        flat" (equity == balance, no open positions), preserving the
        exact behavior every existing caller that doesn't pass them
        already relies on. The real production caller
        (`deployment_windows/start.py`) always supplies the real
        EA-reported values.

        Returns `None` when the file doesn't exist yet, no
        `day_start_balance_override` is configured, and the account is
        not yet verified flat -- the caller must skip this cycle, never
        substitute a guess (see `bootstrap.resolve_bootstrap_balance()`)."""

        current_equity = current_balance if current_equity is None else current_equity
        path = self.config.state_file
        if not path.exists():
            bootstrap_balance = resolve_bootstrap_balance(
                current_balance, current_equity, has_open_positions,
                self.config.flat_account_equity_tolerance, self.config.day_start_balance_override,
            )
            if bootstrap_balance is None:
                return None
            state = PersistedComplianceState(
                schema_version=SCHEMA_VERSION,
                trading_day_id=trading_day_id_for(now, self.config.daily_reset_hour_utc),
                daily_starting_balance=bootstrap_balance,
                peak_balance=bootstrap_balance,
                compliance_lock=ComplianceLockState(),
                trading_days_count=1,
                last_reset_at=now,
            )
            self._save(state)
            return state
        return self._load_existing(path)

    def _load_existing(self, path: Path) -> PersistedComplianceState:
        primary_error: Optional[Exception] = None
        try:
            return _state_from_dict(json.loads(path.read_text(encoding="utf-8")))
        except Exception as exc:  # noqa: BLE001 -- any of these means "cannot trust this file"
            primary_error = exc

        backup = path.with_suffix(path.suffix + ".bak")
        if backup.exists():
            try:
                return _state_from_dict(json.loads(backup.read_text(encoding="utf-8")))
            except Exception:  # noqa: BLE001 -- backup is also unusable
                pass

        raise CorruptStateError(
            f"persisted compliance state at {path} is missing/corrupted and no usable backup "
            f"was found -- refusing to silently bootstrap fresh state, since that would erase "
            f"real loss/lock history. Original error: {primary_error!r}"
        ) from primary_error

    def _save(self, state: PersistedComplianceState) -> None:
        path = self.config.state_file
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            backup = path.with_suffix(path.suffix + ".bak")
            backup.write_bytes(path.read_bytes())
        fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-compliance-state-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(_state_to_dict(state), handle, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, path)
        except BaseException:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)
            raise

    def reconcile(self, state: PersistedComplianceState, now: datetime, current_balance: float) -> PersistedComplianceState:
        """Call once per cycle with the latest reported balance. Rolls
        the trading day over (resetting `daily_starting_balance` and
        auto-clearing an expired lock, via ADR-028's own
        `apply_daily_reset`) only when `now` has actually crossed the
        configured trading-day boundary; otherwise only advances the
        monotonic all-time peak used as the total-drawdown reference."""

        new_day_id = trading_day_id_for(now, self.config.daily_reset_hour_utc)
        if new_day_id != state.trading_day_id:
            temp_account = AccountState(
                account_balance=current_balance,
                daily_starting_balance=state.daily_starting_balance,
                peak_balance=state.peak_balance,
                compliance_lock=state.compliance_lock,
            )
            reset_account = apply_daily_reset(temp_account, now)
            state = replace(
                state,
                trading_day_id=new_day_id,
                daily_starting_balance=reset_account.daily_starting_balance,
                compliance_lock=reset_account.compliance_lock,
                trading_days_count=state.trading_days_count + 1,
                last_reset_at=now,
            )
        if current_balance > state.peak_balance:
            state = replace(state, peak_balance=current_balance)
        self._save(state)
        return state

    def apply_lock_recommendation(
        self, state: PersistedComplianceState, recommendation: Optional[LockRecommendation], now: datetime,
        resets_at: Optional[datetime] = None,
    ) -> PersistedComplianceState:
        """Persists a new lock when `ComplianceSnapshot.lock_recommendation`
        says to (ADR-028 §7's own designed extension point) -- the
        caller decides `resets_at` (typically the next trading-day
        boundary); this store never invents one."""

        if recommendation is None or not recommendation.trigger:
            return state
        new_state = replace(
            state,
            compliance_lock=ComplianceLockState(active=True, reason=recommendation.reason, locked_at=now, resets_at=resets_at),
        )
        self._save(new_state)
        return new_state


def to_account_state(state: PersistedComplianceState, current_balance: float, **overrides) -> AccountState:
    """Builds this cycle's `AccountState` from persisted day-state plus
    the freshly-reported balance -- the caller-owned fields ADR-028
    documents (`consecutive_losses`, `trades_today_count`, etc.) are
    supplied by `overrides` from whatever already tracks them; this
    store only knows about the fields it persists."""

    return AccountState(
        account_balance=current_balance,
        daily_starting_balance=state.daily_starting_balance,
        peak_balance=state.peak_balance,
        compliance_lock=state.compliance_lock,
        trading_days_count=state.trading_days_count,
        **overrides,
    )


__all__ = ["ComplianceStateStore", "to_account_state"]
