"""Versioned configuration for the TitanProtocolEA transport (Phase 1).

Every threshold here is a tunable implementation default, never
architecture. `api_key` has no default -- a hardcoded default secret is
never acceptable, even a documented placeholder one. This is a local,
component-scoped configuration for the bridge only; a shared, single
configuration source across every future component is its own later
phase, not built here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Tuple

from .symbol_mapping import SymbolMapping

BRIDGE_VERSION = "1.0.0-phase1"

#: ADR-034 -- the only two transports this Bridge can serve over. `"http"`
#: is the `WebRequest()`-based transport and the shipped default
#: (Amendment 4); `"socket"` is the native-MQL5-socket transport,
#: fully supported as an explicit opt-in. Exactly one is active per
#: deployment (Amendment 1).
VALID_TRANSPORTS: Tuple[str, ...] = ("http", "socket")


@dataclass(frozen=True)
class BridgeConfig:
    api_key: str
    allowed_symbols: Tuple[str, ...]
    #: Broker-native symbol <-> canonical pair-name normalization
    #: (Final Release Hardening, symbol-universe consistency). Defaults
    #: to a no-op mapping (identity) -- fully backward compatible with
    #: every existing call site that never set this.
    symbol_mapping: SymbolMapping = field(default_factory=SymbolMapping)
    #: Canonical default -- must equal `titan_protocol.runtime.config.RuntimeConfig.magic_number`
    #: (the same EA instance reads both; `deployment_windows/config_loader.py`
    #: enforces this at startup and refuses to start on any mismatch).
    magic_number: int = 20260710
    max_lot_size: float = 5.0
    max_slippage_points: int = 20
    heartbeat_timeout_seconds: float = 30.0
    command_ttl_seconds: float = 15.0
    log_level: int = 20  # logging.INFO, without importing logging here

    # -- Phase 1.6 long-run retention (all additive, all optional with
    # defaults -- no existing constructor call site is affected). See
    # PHANTOM_BRIDGE_PHASE1_6_HARDENING_REPORT.md for the retention
    # model these govern.
    execution_report_ttl_seconds: float = 3600.0
    duplicate_detection_ttl_seconds: float = 900.0
    correlation_ttl_seconds: float = 7200.0
    cleanup_interval_seconds: float = 60.0
    max_completed_commands: int = 10000
    max_cached_reports: int = 10000
    # Reserved: ConnectionHealth retains only the single most recent
    # heartbeat (already the minimum required for fail-closed logic) --
    # there is no growing heartbeat history in this codebase for this
    # value to bound. Present because it is part of this phase's
    # mandated minimum configuration surface, not because anything
    # currently consumes it.
    max_heartbeat_history: int = 1
    # Bounds BridgeEngine's two audit-only append logs (errors,
    # independent trade-transaction mirror) -- not named in the
    # mandated minimum list, added because both are exactly the kind of
    # "retained result collection" this phase's scope explicitly
    # covers and both grew unbounded before this change.
    max_error_history: int = 1000
    max_trade_transaction_history: int = 1000

    # -- ADR-034: native MQL5 socket transport. `transport="http"` is the
    # shipped default (Amendment 4 -- reverted from Amendment 2's
    # `"socket"` default following a live-deployment forensic
    # investigation that could not rule out a socket-primary
    # misconfiguration/fallback-bind gap as the cause of a WebRequest()
    # transport-layer failure; HTTP is the better-understood, more
    # broadly compatible substrate to ship by default). `"socket"`
    # remains fully supported as an explicit opt-in -- set it and
    # restart to switch, never a second concurrently-running transport
    # (ADR-034 Amendment 1).
    transport: str = "http"
    socket_port: int = 8788
    #: Rejected (frame refused, connection closed) before the payload is
    #: ever read -- bounds worst-case per-message memory, independent of
    #: `max_lot_size`/queue retention, which bound trading state, not
    #: wire frames.
    socket_max_message_bytes: int = 65536
    #: A connection that sends nothing for this long is treated as a
    #: stale/dead session and closed -- distinct from
    #: `heartbeat_timeout_seconds` (an application-level EA-liveness
    #: fact `ConnectionHealth` tracks); this is a transport-level socket
    #: fact, enforced by the OS via `socket.settimeout()`.
    socket_idle_timeout_seconds: float = 60.0
    #: Bounds concurrently-open socket connections -- mirrors
    #: `_BridgeHTTPServer.request_queue_size`'s existing precedent of a
    #: documented, cheap, defensive resource bound.
    socket_max_connections: int = 8

    def __post_init__(self) -> None:
        object.__setattr__(self, "allowed_symbols", tuple(self.allowed_symbols))
        if self.transport not in VALID_TRANSPORTS:
            raise ValueError(
                f"BridgeConfig.transport must be one of {VALID_TRANSPORTS}, got {self.transport!r}"
            )


__all__ = ["BRIDGE_VERSION", "BridgeConfig"]
