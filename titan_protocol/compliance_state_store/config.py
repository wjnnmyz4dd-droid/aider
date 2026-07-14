"""Configuration for the persisted compliance state store (Final
Release Hardening, requirement 2)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

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


__all__ = ["COMPLIANCE_STATE_STORE_VERSION", "ComplianceStateStoreConfig"]
