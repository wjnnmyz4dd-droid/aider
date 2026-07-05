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
