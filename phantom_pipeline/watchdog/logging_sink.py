"""Structured logging (ADR-011 §12). Structured logging only — no
`print()`.

Every health event must include `trace_id` (the Watchdog's own
health-event chain, never a trading `trace_id`), `component`, `severity`,
`timestamp`, `reason`, and `recovery_action` if any was attempted (§12) —
attributable without re-running anything, the same explainability
discipline established at every prior stage. A logging failure never
propagates into or alters engine behavior.
"""

from __future__ import annotations

import logging

from .models import Alert, ComponentHealth, RecoveryStatus

logger = logging.getLogger("phantom_pipeline.watchdog")


def _safe_log(level: int, msg: str, extra: dict) -> None:
    try:
        logger.log(level, msg, extra=extra)
    except Exception:
        pass


def log_component_health(trace_id: str, health: ComponentHealth, level: int = logging.INFO) -> None:
    _safe_log(
        level,
        "watchdog.component_health",
        {
            "trace_id": trace_id,
            "component": health.component,
            "severity": health.state.value,
            "timestamp": health.timestamp.isoformat(),
            "reason": health.reason,
            "recovery_action": None,
        },
    )


def log_recovery_attempt(trace_id: str, status: RecoveryStatus, reason: str, level: int = logging.WARNING) -> None:
    _safe_log(
        level,
        "watchdog.recovery_attempt",
        {
            "trace_id": trace_id,
            "component": status.component,
            "severity": None,
            "timestamp": status.timestamp.isoformat(),
            "reason": reason,
            "recovery_action": status.last_action.value if status.last_action else None,
        },
    )


def log_alert(alert: Alert, level: int = logging.WARNING) -> None:
    _safe_log(
        level,
        "watchdog.alert",
        {
            "trace_id": alert.trace_id,
            "component": alert.component,
            "severity": alert.severity.value,
            "timestamp": alert.timestamp.isoformat(),
            "reason": alert.detail,
            "recovery_action": None,
            "alert_class": alert.alert_class.value,
            "repeat_count": alert.repeat_count,
        },
    )
