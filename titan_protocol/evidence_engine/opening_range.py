"""Opening range computation (ADR-035 §3, Phase 0 -- ADR-024 Amendment 2).

Computes `OpeningRangeState` -- a fixed-width price range anchored to a
configured session-open time -- independently per configured anchor in
`EvidenceEngineConfig.opening_range_anchors`. A pure transform of
`bars`/`now`, exactly like `detect_fair_value_gaps(bars)` needs only
`bars` -- no dependency on any other `_analyze()` step's output, and no
import of `market_data_ingestion`: that package's own gap flag never
reaches this package's `Bar` objects, so the gap check below is Evidence
Engine's own, independent computation against `Bar.timestamp` alone.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Sequence, Tuple

from .config import EvidenceEngineConfig
from .models import Bar, OpeningRangeState, SessionName


def _has_temporal_gap(bars_in_window: Sequence[Bar], expected_interval_seconds: int) -> bool:
    """True if any two consecutive bars in `bars_in_window` are spaced
    further apart than `expected_interval_seconds`, checked against
    `Bar.timestamp` alone."""
    for earlier, later in zip(bars_in_window, bars_in_window[1:]):
        if (later.timestamp - earlier.timestamp).total_seconds() > expected_interval_seconds:
            return True
    return False


def _compute_single_range(
    bars: Sequence[Bar],
    now: datetime,
    session: SessionName,
    range_start: datetime,
    duration_minutes: int,
    min_bars: int,
    expected_interval_seconds: int,
) -> OpeningRangeState:
    range_end = range_start + timedelta(minutes=duration_minutes)
    is_formed = now >= range_end

    included_indices = [i for i, bar in enumerate(bars) if range_start <= bar.timestamp < range_end]
    if not included_indices:
        return OpeningRangeState(
            session=session,
            range_start=range_start,
            range_end=range_end,
            range_start_index=0,
            range_end_index=0,
            range_high=0.0,
            range_low=0.0,
            range_midpoint=0.0,
            is_formed=is_formed,
            is_valid=False,
        )

    range_start_index = included_indices[0]
    range_end_index = included_indices[-1] + 1
    included_bars = bars[range_start_index:range_end_index]

    range_high = max(bar.high for bar in included_bars)
    range_low = min(bar.low for bar in included_bars)
    range_midpoint = (range_high + range_low) / 2.0
    is_valid = len(included_bars) >= min_bars and not _has_temporal_gap(included_bars, expected_interval_seconds)

    return OpeningRangeState(
        session=session,
        range_start=range_start,
        range_end=range_end,
        range_start_index=range_start_index,
        range_end_index=range_end_index,
        range_high=range_high,
        range_low=range_low,
        range_midpoint=range_midpoint,
        is_formed=is_formed,
        is_valid=is_valid,
    )


def compute_opening_ranges(
    bars: Sequence[Bar], now: datetime, config: EvidenceEngineConfig
) -> Tuple[OpeningRangeState, ...]:
    """One `OpeningRangeState` per configured anchor whose window's start
    has been reached by the supplied `bars` -- an anchor whose start is
    still in the future for this cycle produces no entry at all, never a
    placeholder (ADR-035 §3)."""
    states: List[OpeningRangeState] = []
    for session, start_hour_utc, start_minute_utc in config.opening_range_anchors:
        range_start = now.replace(hour=start_hour_utc, minute=start_minute_utc, second=0, microsecond=0)
        if not bars or bars[-1].timestamp < range_start:
            continue
        states.append(
            _compute_single_range(
                bars,
                now,
                session,
                range_start,
                config.opening_range_duration_minutes,
                config.opening_range_min_bars,
                config.expected_bar_interval_seconds,
            )
        )
    return tuple(states)


__all__ = ["compute_opening_ranges"]
