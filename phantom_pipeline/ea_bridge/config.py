"""Versioned configuration for the EA Bridge (`ADR-023` §4).

Every threshold here is a tunable implementation default, never
architecture (`CLAUDE.md` §7, §3) — the same discipline every prior
stage's config module already establishes. `api_key` has no default
(a required constructor argument) — a hardcoded default secret is never
acceptable, even a documented placeholder one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

EA_BRIDGE_VERSION = "1.0.0-phase1"


@dataclass(frozen=True)
class EABridgeConfig:
    """`command_ttl_seconds` bounds how long an `ExecutionCommand` may sit
    on the queue before it is dropped as stale (`ADR-023` §3) — the same
    "never resubmit/re-deliver an order whose window has passed" posture
    `mt5_bridge`'s own idempotency store already established, applied
    here to the EA-facing side of the same `execution_id`.
    """

    api_key: str
    allowed_symbols: Tuple[str, ...]
    magic_number: int = 20260708
    max_lot_size: float = 5.0
    max_slippage_points: int = 20
    heartbeat_interval_seconds: float = 5.0
    heartbeat_timeout_seconds: float = 30.0
    command_ttl_seconds: float = 15.0
    bar_sync_interval_seconds: float = 60.0
    execution_report_ttl_seconds: float = 3600.0
    log_level: int = 20  # logging.INFO, without importing logging here

    def __post_init__(self) -> None:
        object.__setattr__(self, "allowed_symbols", tuple(self.allowed_symbols))


__all__ = ["EA_BRIDGE_VERSION", "EABridgeConfig"]
