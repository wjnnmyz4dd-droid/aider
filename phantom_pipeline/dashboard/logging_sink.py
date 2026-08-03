"""Structured logging (ADR-012 §7). Structured logging only — no
`print()`.

Every displayed item links to `trace_id`, `timestamp`, `component`, and
`status` (§7); a view build logs one entry per contributing item, so any
rendered view is attributable back to its source records without
re-running anything. A logging failure never propagates into or alters
engine behavior.
"""

from __future__ import annotations

import logging

from .models import AlertView, ComponentStatus, View

logger = logging.getLogger("phantom_pipeline.dashboard")


def _safe_log(level: int, msg: str, extra: dict) -> None:
    try:
        logger.log(level, msg, extra=extra)
    except Exception:
        pass


def log_view_built(view: View, level: int = logging.INFO) -> None:
    _safe_log(
        level,
        "dashboard.view_built",
        {
            "view_name": view.view_name.value,
            "generated_at": view.generated_at.isoformat(),
            "component_count": len(view.component_statuses),
            "alert_count": len(view.alerts),
            "trade_record_count": len(view.trade_records),
        },
    )


def log_component_status_displayed(view_name: str, status: ComponentStatus, level: int = logging.DEBUG) -> None:
    _safe_log(
        level,
        "dashboard.component_status_displayed",
        {
            "view_name": view_name,
            "component": status.component,
            "status": status.health_state,
            "trace_id": status.trace_id,
            "timestamp": status.timestamp.isoformat(),
        },
    )


def log_alert_displayed(view_name: str, alert: AlertView, level: int = logging.DEBUG) -> None:
    _safe_log(
        level,
        "dashboard.alert_displayed",
        {
            "view_name": view_name,
            "component": alert.component,
            "status": alert.severity,
            "trace_id": alert.trace_id,
            "timestamp": alert.timestamp.isoformat(),
        },
    )
