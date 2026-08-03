"""Gap detection and repair (ADR-013 §7).

Detection (`detect_gaps`) reports missing bars via `GapEvent` — never
fills anything. Repair (`repair_gaps`) is strictly bounded: **only a
single missing bar within an otherwise-continuous sequence may be
repaired** (forward-filled from the prior bar's close); consecutive
missing bars are never repaired — they are left absent, reported as a
genuine gap for the consuming stage's own fail-closed behavior (`ADR-002`
§9's "missing-timeframe" failure mode), exactly as §7 requires.

Every repaired bar carries `is_repaired=True` and `quality=DataQuality.GAP`
— never indistinguishable from a directly-observed bar (Hard Rules:
"never fabricate a plausible-looking reading"). Repair never occurs
during warm-up: `detect_gaps` itself requires at least two bars to
compute a gap, so there is never a gap (and therefore never a repair)
until a genuine continuous sequence exists to repair from.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Sequence

from .config import PipelineConfig
from .models import DataQuality, NormalizedBar, SCHEMA_VERSION
from .trace import make_trace_id


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


def repair_gaps(bars: Sequence[NormalizedBar], config: PipelineConfig) -> List[NormalizedBar]:
    """Return a new bar sequence with every single-missing-bar gap
    forward-filled (ADR-013 §7). `bars` is never mutated — a fresh list is
    always returned. A gap of more than one consecutive missing bar is
    left absent, unchanged from `detect_gaps`'s own report; the caller's
    own `DataQualityReport` (via `quality.py`) is the mechanism for
    surfacing that genuine gap, not this function.

    Raises ValueError on unsorted input, via the same `detect_gaps` check
    this function reuses — never computes a repair from a meaningless gap.
    """
    gaps = detect_gaps(bars, config)
    if not gaps:
        return list(bars)

    single_bar_gap_after = {
        gap.after: gap for gap in gaps if gap.missing_bar_count == 1
    }
    if not single_bar_gap_after:
        return list(bars)

    timeframe = bars[0].timeframe
    interval = timedelta(seconds=config.interval_seconds_for(timeframe))

    repaired: List[NormalizedBar] = []
    for bar in bars:
        repaired.append(bar)
        gap = single_bar_gap_after.get(bar.timestamp)
        if gap is None:
            continue
        repaired.append(_forward_fill(bar, bar.timestamp + interval))
    return repaired


def _forward_fill(previous: NormalizedBar, timestamp: datetime) -> NormalizedBar:
    """One repaired bar: OHLC forward-filled from `previous`'s close,
    zero volume (no trading activity was actually observed), always
    flagged `is_repaired=True` and `quality=DataQuality.GAP` — never
    presented as if directly observed (Hard Rules)."""
    trace_id = make_trace_id(
        "bar_repaired", previous.symbol, previous.timeframe, timestamp.isoformat()
    )
    return NormalizedBar(
        schema_version=SCHEMA_VERSION,
        trace_id=trace_id,
        symbol=previous.symbol,
        timeframe=previous.timeframe,
        timestamp=timestamp,
        open=previous.close,
        high=previous.close,
        low=previous.close,
        close=previous.close,
        volume=0.0,
        quality=DataQuality.GAP,
        is_repaired=True,
        source=previous.source,
    )
