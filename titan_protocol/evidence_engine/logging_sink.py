"""Structured logging for the Evidence Engine.

A logging failure never propagates into or alters this package's
return value -- same discipline as `titan_protocol/bridge/logging_sink.py`.
"""

from __future__ import annotations

import logging

from .models import EvidenceReport

logger = logging.getLogger("titan_protocol.evidence_engine")


def _safe_log(level: int, message: str, extra: dict) -> None:
    try:
        logger.log(level, message, extra=extra)
    except Exception:
        pass


def log_evidence_report(report: EvidenceReport) -> None:
    _safe_log(
        logging.INFO,
        "evidence_report",
        {
            "symbol": report.symbol,
            "generated_at": report.generated_at.isoformat(),
            "composite_score": report.score.composite,
            "component_count": len(report.score.components),
        },
    )


__all__ = ["log_evidence_report"]
