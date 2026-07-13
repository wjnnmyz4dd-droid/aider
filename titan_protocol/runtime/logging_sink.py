"""Structured logging for the Runtime Orchestrator.

A logging failure never propagates into or alters this package's
return value -- same discipline as every other engine's logging_sink
this session. No silent failures (ADR-031 SS7): every cycle is logged,
including a FAILED outcome.
"""

from __future__ import annotations

import logging

from .models import RuntimeAuditRecord

logger = logging.getLogger("titan_protocol.runtime")


def _safe_log(level: int, message: str, extra: dict) -> None:
    try:
        logger.log(level, message, extra=extra)
    except Exception:
        pass


def log_runtime_audit_record(record: RuntimeAuditRecord) -> None:
    level = logging.ERROR if record.outcome.name == "FAILED" else logging.INFO
    _safe_log(
        level,
        "runtime_audit_record",
        {
            "cycle_id": record.cycle_id,
            "pair": record.pair,
            "profile_id": record.profile_id,
            "outcome": record.outcome.value,
            "stage_reached": record.stage_reached.value if record.stage_reached else None,
            "duration_ms": record.duration_ms,
        },
    )


__all__ = ["log_runtime_audit_record"]
