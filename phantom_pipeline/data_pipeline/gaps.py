"""Gap detection (ADR-013 §7).

Phase 1 scope is detection only. A detected gap is reported via
`GapEvent`/`DataQualityReport` — never filled with a fabricated bar.
Gap *repair* (ADR-013 §7's bounded, single-bar, `is_repaired`-flagged
forward-fill policy) is explicitly out of scope for Phase 1.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Sequence

from .config import PipelineConfig
from .models import NormalizedBar


@dataclass(frozen=True)
class GapEvent:
    """A detected discontinuity between two consecutive bars."""

    symbol: str
    timeframe: str
    after: datetime
    before: datetime
    missing_bar_count: int


def detect_gaps(
    bars: Sequence[NormalizedBar], config: PipelineConfig
) -> List[GapEvent]:
    """Detect missing bars in an otherwise-continuous, ascending-timestamp
    bar sequence for one symbol/timeframe.

    Never fabricates a replacement bar — a gap is reported, not filled.

    Raises ValueError if `bars` is not sorted ascending by timestamp —
    every gap computed from unsorted input would be meaningless, so this
    fails closed rather than silently returning wrong results.
    """
    if len(bars) < 2:
        return []

    timeframe = bars[0].timeframe
    interval = timedelta(seconds=config.interval_seconds_for(timeframe))

    gaps: List[GapEvent] = []
    for previous, current in zip(bars, bars[1:]):
        if current.timestamp < previous.timestamp:
            raise ValueError(
                "detect_gaps requires bars sorted ascending by timestamp: "
                f"{current.timestamp!r} follows {previous.timestamp!r}"
            )
        delta = current.timestamp - previous.timestamp
        if delta > interval:
            missing = int(delta / interval) - 1
            if missing > 0:
                gaps.append(
                    GapEvent(
                        symbol=previous.symbol,
                        timeframe=timeframe,
                        after=previous.timestamp,
                        before=current.timestamp,
                        missing_bar_count=missing,
                    )
                )
    return gaps
