"""Pure alert-classification logic (ADR-011 §11).

Alert *sending* (Telegram delivery, per `ADR-015` §9 — strictly outbound,
notify-only) is out of this Phase's scope; this module only classifies
what alert, if any, a state transition should produce, and whether a
repeated identical alert should collapse into a dedup count instead of
being reported again. Dedup/escalation bookkeeping (the "have we already
alerted on this" state) lives in `WatchdogStateStore`, read fresh by
`engine.py` and passed in here as plain values, mirroring
`checks.py`'s own discipline.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Tuple

from .config import WatchdogConfig
from .models import AlertClass, ComponentHealth, HealthState

_CRITICAL_STATES = (HealthState.CRITICAL, HealthState.OFFLINE, HealthState.UNKNOWN)
_WARNING_STATES = (HealthState.DEGRADED, HealthState.WARNING)


def classify_alert(component_health: ComponentHealth) -> Optional[AlertClass]:
    """The base alert class for a component's current state (ADR-011
    §11) — `SHUTDOWN` is the only state whose alert is suppressed
    (deliberate, operator-visible, never silent)."""
    if component_health.state == HealthState.SHUTDOWN:
        return None
    if component_health.state in _CRITICAL_STATES:
        return AlertClass.CRITICAL
    if component_health.state in _WARNING_STATES:
        return AlertClass.WARNING
    if component_health.state == HealthState.RECOVERING:
        return AlertClass.RECOVERY
    return None


def should_escalate(
    component: str, state: HealthState, state_since: Optional[Tuple[HealthState, datetime]], now: datetime, config: WatchdogConfig
) -> bool:
    """A component remaining at `CRITICAL` beyond a configured duration
    raises the alert's severity/urgency rather than repeating the same
    alert indefinitely at the same level (ADR-011 §11)."""
    if state != HealthState.CRITICAL or state_since is None:
        return False
    since_state, since_at = state_since
    if since_state != HealthState.CRITICAL:
        return False
    return (now - since_at).total_seconds() >= config.alert_escalation_duration_seconds


def resolve_repeat_count(
    detail: str,
    last_signature: Optional[Tuple[str, datetime, int]],
    now: datetime,
    config: WatchdogConfig,
) -> int:
    """Repeated identical alerts (same component, same `AlertClass`,
    same detail) within `alert_dedup_window_seconds` collapse into one
    alert with an incrementing `repeat_count`, rather than being resent
    individually (ADR-011 §11). `last_signature` is already scoped to one
    `(component, alert_class)` pair by the caller."""
    if last_signature is None:
        return 1
    prev_detail, prev_at, prev_repeat_count = last_signature
    if prev_detail != detail:
        return 1
    if (now - prev_at).total_seconds() > config.alert_dedup_window_seconds:
        return 1
    return prev_repeat_count + 1
