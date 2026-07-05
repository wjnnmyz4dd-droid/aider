"""Versioned configuration for the MT5 Bridge (ADR-008 §4, §6).

Every timeout/threshold/policy value here is a tunable implementation
default, never architecture (`CLAUDE.md` §7, §3) — the same discipline
every prior stage's config module already established.
"""

from __future__ import annotations

from dataclasses import dataclass

MT5_BRIDGE_VERSION = "1.0.0-phase1"


@dataclass(frozen=True)
class MT5BridgeConfig:
    """`heartbeat_timeout_seconds` is the maximum age of the last
    successful heartbeat before the connection is treated as
    desynchronized (ADR-008 §6, §9) — a connection reporting `READY`
    without one is never silently trusted.

    `reconnect_max_attempts`/`reconnect_backoff_seconds` bound the
    reconnect sequence (ADR-008 §6) — this governs *connection*
    reattempts only; it never implies resubmission of an in-flight order
    (§8's "never retry blindly" applies to orders, not connections).
    """

    heartbeat_interval_seconds: float = 5.0
    heartbeat_timeout_seconds: float = 15.0
    reconnect_max_attempts: int = 5
    reconnect_backoff_seconds: float = 2.0
    submission_timeout_seconds: float = 10.0
    acknowledgement_timeout_seconds: float = 5.0
    idempotency_ttl_seconds: float = 3600.0
    log_level: int = 20  # logging.INFO, without importing logging here


DEFAULT_CONFIG = MT5BridgeConfig()
