"""Structured logging (ADR-002 §11).

Mirrors `phantom_pipeline.data_pipeline.logging_sink`'s pattern: one
structured record per `ScannerObservation`, every field read directly off
the object, logging failure never propagates into or alters the returned
observation (logging is observability, not a gate).

Every record carries `trace_id` so it can be joined with whatever
downstream Strategy Engine / Scoring Engine records are produced from the
same observation (§11, closing the "no shared trace_id across a scan's
log lines" defect on record in `TEAM.md` §8). The task instruction for
this implementation also requires a `scanner_version` field on every
record, beyond what ADR-002 §11's own text lists — included here as an
explicit addition, not silently folded into the ADR's wording.
"""

from __future__ import annotations

import logging

from .config import SCANNER_VERSION
from .models import ScannerObservation

logger = logging.getLogger("phantom_pipeline.scanner")


def log_observation(observation: ScannerObservation, level: int = logging.INFO) -> None:
    try:
        logger.log(
            level,
            "scanner.observation",
            extra={
                "trace_id": observation.trace_id,
                "schema_version": observation.schema_version,
                "scanner_version": SCANNER_VERSION,
                "symbol": observation.symbol,
                "timestamp": observation.timestamp.isoformat(),
                "trend_summary": {
                    tf: reading.direction.value for tf, reading in observation.trend.items()
                },
                "structure_summary": [s.kind.value for s in observation.structure],
                "volatility_summary": observation.volatility.label.value,
                "session_summary": observation.session.active_sessions,
                "data_quality_flag": observation.data_quality_flag.value,
            },
        )
    except Exception:
        # Logging is observability, not a gate (ADR-002 §11) — a logging
        # failure must never propagate into or alter the returned
        # observation.
        pass
