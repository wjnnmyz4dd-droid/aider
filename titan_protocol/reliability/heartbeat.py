"""Heartbeat monitoring (ADR-032 SS2 item 2): a thread-safe store of
last-seen timestamps per component, and a pure function deriving
`HealthState` from staleness -- mirrors `ADR-011`'s own heartbeat
staleness derivation in shape, built fresh (never imported, ADR-032
SS0)."""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Dict, Optional

from .config import ReliabilityConfig
from .models import HealthState


class HeartbeatStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_seen: Dict[str, datetime] = {}

    def record(self, component: str, now: datetime) -> None:
        with self._lock:
            self._last_seen[component] = now

    def last_seen_at(self, component: str) -> Optional[datetime]:
        with self._lock:
            return self._last_seen.get(component)

    def known_components(self) -> tuple:
        with self._lock:
            return tuple(self._last_seen.keys())


def derive_heartbeat_state(last_seen_at: Optional[datetime], now: datetime, config: ReliabilityConfig) -> HealthState:
    """Fail closed: no heartbeat ever recorded is UNKNOWN, never
    HEALTHY (ADR-032 Hard Rule 5)."""

    if last_seen_at is None:
        return HealthState.UNKNOWN

    age_seconds = (now - last_seen_at).total_seconds()
    if age_seconds < 0:
        return HealthState.UNKNOWN  # a timestamp from the future is never trusted
    if age_seconds <= config.heartbeat_healthy_interval_seconds:
        return HealthState.HEALTHY
    if age_seconds <= config.heartbeat_degraded_interval_seconds:
        return HealthState.DEGRADED
    if age_seconds <= config.heartbeat_grace_period_seconds:
        return HealthState.UNHEALTHY
    return HealthState.UNKNOWN


__all__ = ["HeartbeatStore", "derive_heartbeat_state"]
