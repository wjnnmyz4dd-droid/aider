"""Configuration for the persisted compliance state store (Final
Release Hardening, requirement 2)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

COMPLIANCE_STATE_STORE_VERSION = "1.0.0"


@dataclass(frozen=True)
class ComplianceStateStoreConfig:
    state_file: Path

    #: The broker/prop-firm's authoritative trading-day boundary,
    #: expressed as an hour-of-day in UTC (e.g. 17 for a 5pm UTC broker
    #: "server day" rollover). Deliberately a fixed UTC hour, not a
    #: timezone name -- this store is stdlib-only and does not attempt
    #: DST-aware timezone conversion; operators running against a
    #: broker whose own server-time offset changes with DST must update
    #: this value when that offset changes. See KNOWN_GAPS.md.
    daily_reset_hour_utc: int = 0

    #: Day-one bootstrap verification (KNOWN_GAPS.md #9). When `None`
    #: (default), `daily_starting_balance` is only ever bootstrapped
    #: once the reported account is verified flat (no open positions,
    #: `balance` == `equity` within `flat_account_equity_tolerance`) --
    #: never from the first report unconditionally. Setting this to an
    #: operator-confirmed value bypasses that verification entirely and
    #: uses it verbatim on the next bootstrap -- the deterministic
    #: escape hatch for the one contamination case wire data can never
    #: reveal (a trade opened and closed earlier the same day, before
    #: Titan ever received a report).
    day_start_balance_override: Optional[float] = None

    #: Tolerance (in account-currency units) for treating `balance` and
    #: `equity` as equal when verifying the account is flat. Must be
    #: >= 0 -- a broker's own rounding to the smallest currency unit
    #: (e.g. cents) is the reason this isn't exact equality.
    flat_account_equity_tolerance: float = 0.01

    def __post_init__(self) -> None:
        if self.day_start_balance_override is not None and self.day_start_balance_override <= 0:
            raise ValueError(
                f"day_start_balance_override must be > 0 if set, got {self.day_start_balance_override}"
            )
        if self.flat_account_equity_tolerance < 0:
            raise ValueError(
                f"flat_account_equity_tolerance must be >= 0, got {self.flat_account_equity_tolerance}"
            )


__all__ = ["COMPLIANCE_STATE_STORE_VERSION", "ComplianceStateStoreConfig"]
