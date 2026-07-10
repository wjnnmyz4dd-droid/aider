"""Structured logging for the System Reliability Engine.

A logging failure never propagates into or alters this package's
return value -- same discipline as every other engine's logging_sink
this session.
"""

from __future__ import annotations

import logging

from .models import SystemHealthSnapshot

logger = logging.getLogger("phantom.reliability")


def _safe_log(level: int, message: str, extra: dict) -> None:
    try:
        logger.log(level, message, extra=extra)
    except Exception:
        pass


def log_health_snapshot(snapshot: SystemHealthSnapshot) -> None:
    from .models import DegradationLevel

    level = logging.WARNING if snapshot.degradation_level != DegradationLevel.NORMAL else logging.INFO
    _safe_log(
        level,
        "system_health_snapshot",
        {
            "degradation_level": snapshot.degradation_level.value,
            "component_count": len(snapshot.component_health),
            "reasons": snapshot.reasons,
        },
    )


__all__ = ["log_health_snapshot"]
