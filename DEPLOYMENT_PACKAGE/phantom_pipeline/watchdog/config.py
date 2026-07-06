"""Versioned configuration for the Watchdog (ADR-011 §7, §8, §9, §11).

Every interval/threshold/window here is a tunable implementation default,
never architecture (`CLAUDE.md` §7, §3) — the same discipline every prior
stage's config module already established.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

WATCHDOG_VERSION = "1.0.0-phase1"


@dataclass(frozen=True)
class WatchdogConfig:
    """`heartbeat_interval_overrides` lets MT5 Bridge use its own
    `ADR-008` §6-defined interval while every other stage falls back to
    `default_heartbeat_interval_seconds` as a liveness-proxy interval
    (§2's boundary note — no dedicated heartbeat concept exists yet for
    those stages).

    `recovery_backoff_seconds` is the minimum gap enforced between
    successive recovery attempts for the same component, scaled by the
    number of attempts already made in the current window — the same
    backoff-based shape `ADR-008` §6 already established for its own
    reconnect policy (§7)."""

    heartbeat_interval_overrides: Mapping[str, float] = field(default_factory=dict)
    default_heartbeat_interval_seconds: float = 30.0
    warning_missed_threshold: int = 2
    critical_missed_threshold: int = 5
    heartbeat_max_age_multiplier: float = 10.0
    heartbeat_history_ttl_seconds: float = 3600.0
    heartbeat_history_max_len: int = 500

    recovery_max_attempts: int = 3
    recovery_window_seconds: float = 300.0
    recovery_backoff_seconds: float = 30.0

    alert_escalation_duration_seconds: float = 600.0
    alert_dedup_window_seconds: float = 300.0

    log_level: int = 20  # logging.INFO, without importing logging here

    def heartbeat_interval_for(self, component: str) -> float:
        return self.heartbeat_interval_overrides.get(component, self.default_heartbeat_interval_seconds)


DEFAULT_CONFIG = WatchdogConfig()
