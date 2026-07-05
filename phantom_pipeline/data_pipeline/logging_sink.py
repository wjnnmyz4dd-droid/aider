"""Structured logging (ADR-013 §14).

Every ingestion event — a `NormalizedTick` or a finalized `NormalizedBar`
— is logged as one structured record carrying `trace_id`,
`schema_version`, `symbol`, `timeframe` (absent for a tick-level event,
which has no timeframe), `timestamp`, `source`, and `quality` state.

Zero business logic, zero Scanner knowledge, zero Strategy knowledge,
zero vendor-specific behavior: this module only formats and emits
already-decided facts read directly off the object it is given. It
never inspects, filters, or alters pipeline behavior based on what it
logs — logging is observability, not a gate, the same discipline
`ADR-002` §11 already established, extended one stage earlier. A
logging failure must never propagate into or alter pipeline behavior.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Union

from .models import NormalizedBar, NormalizedTick

logger = logging.getLogger("phantom_pipeline.data_pipeline")


def log_ingestion_event(
    event: Union[NormalizedTick, NormalizedBar], level: int = logging.INFO
) -> None:
    """Emit one structured, deterministic log record for a produced
    ingestion event. `level` is the configured log level
    (`PipelineConfig.log_level`) — never hard-coded, always caller-
    supplied, so verbosity is configurable without touching this
    function.

    Deterministic: every field is read directly from `event`; nothing
    here depends on wall-clock time or randomness beyond what the
    standard library's own `logging` module attaches for display
    purposes (e.g. the handler's own timestamp formatting), which is
    never part of `event` itself and never fed back into the pipeline.
    """
    timeframe = getattr(event, "timeframe", None)
    quality = getattr(event, "quality", None)
    quality_state = quality.value if quality is not None else None

    try:
        logger.log(
            level,
            "data_pipeline.ingestion_event",
            extra={
                "trace_id": event.trace_id,
                "schema_version": event.schema_version,
                "symbol": event.symbol,
                "timeframe": timeframe,
                "timestamp": event.timestamp.isoformat(),
                "source": getattr(event, "source", None),
                "quality": quality_state,
            },
        )
    except Exception:
        # Logging is observability, not a gate (ADR-002 §11) — a logging
        # failure must never propagate into or alter pipeline behavior.
        pass


def log_gap_repair(bar: NormalizedBar, level: int = logging.INFO) -> None:
    """One structured record per repaired bar (ADR-013 §7, §14) — makes
    every repair attributable without re-running anything. `bar` is
    always the already-repaired `NormalizedBar` (`is_repaired=True`),
    never the gap itself, so this carries the same fields every other
    ingestion event does."""
    try:
        logger.log(
            level,
            "data_pipeline.gap_repair",
            extra={
                "trace_id": bar.trace_id,
                "schema_version": bar.schema_version,
                "symbol": bar.symbol,
                "timeframe": bar.timeframe,
                "timestamp": bar.timestamp.isoformat(),
                "source": bar.source,
                "quality": bar.quality.value,
            },
        )
    except Exception:
        pass


def log_cache_invalidation(
    symbol: str, timeframe: str, reason: str, bars_cleared: int, timestamp: datetime, level: int = logging.WARNING
) -> None:
    """One structured record per explicit cache-invalidation event
    (ADR-013 §11) — never a silent clear. Carries `symbol`, `timeframe`,
    `reason`, `bars_cleared`, and `timestamp` so the event is fully
    attributable after the fact, the same completeness discipline
    `ADR-013` §14 already requires for ingestion events."""
    try:
        logger.log(
            level,
            "data_pipeline.cache_invalidation",
            extra={
                "symbol": symbol,
                "timeframe": timeframe,
                "reason": reason,
                "bars_cleared": bars_cleared,
                "timestamp": timestamp.isoformat(),
            },
        )
    except Exception:
        pass
