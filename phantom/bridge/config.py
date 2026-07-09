"""Versioned configuration for the PhantomBridgeEA transport (Phase 1).

Every threshold here is a tunable implementation default, never
architecture. `api_key` has no default -- a hardcoded default secret is
never acceptable, even a documented placeholder one. This is a local,
component-scoped configuration for the bridge only; a shared, single
configuration source across every future component is its own later
phase, not built here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

BRIDGE_VERSION = "1.0.0-phase1"


@dataclass(frozen=True)
class BridgeConfig:
    api_key: str
    allowed_symbols: Tuple[str, ...]
    magic_number: int = 20260709
    max_lot_size: float = 5.0
    max_slippage_points: int = 20
    heartbeat_timeout_seconds: float = 30.0
    command_ttl_seconds: float = 15.0
    log_level: int = 20  # logging.INFO, without importing logging here

    def __post_init__(self) -> None:
        object.__setattr__(self, "allowed_symbols", tuple(self.allowed_symbols))


__all__ = ["BRIDGE_VERSION", "BridgeConfig"]
