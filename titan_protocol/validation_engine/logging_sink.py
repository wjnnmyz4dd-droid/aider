"""Structured logging for the Validation Engine.

A logging failure never propagates into or alters this package's
return value -- same discipline as every other engine's logging_sink
this session.
"""

from __future__ import annotations

import logging

from .models import ValidationSnapshot

logger = logging.getLogger("titan_protocol.validation_engine")


def _safe_log(level: int, message: str, extra: dict) -> None:
    try:
        logger.log(level, message, extra=extra)
    except Exception:
        pass


def log_validation_snapshot(snapshot: ValidationSnapshot) -> None:
    _safe_log(
        logging.INFO,
        "validation_snapshot",
        {
            "generated_at": snapshot.generated_at.isoformat(),
            "passed": snapshot.passed,
            "scenario_count": len(snapshot.replay_verifications),
            "warning_count": len(snapshot.warnings),
            "recommendation_count": len(snapshot.recommendations),
        },
    )


__all__ = ["log_validation_snapshot"]
