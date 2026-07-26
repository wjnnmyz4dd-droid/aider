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
from .models import Bar, OpeningRangeBarObservation, OpeningRangeState, SessionName


def _has_temporal_gap(bars_in_window: Sequence[Bar], expected_interval_seconds: int) -> bool:
    """True if any two consecutive bars in `bars_in_window` are spaced
    further apart than `expected_interval_seconds`, checked against
    `Bar.timestamp` alone."""
    for earlier, later in zip(bars_in_window, bars_in_window[1:]):
        if (later.timestamp - earlier.timestamp).total_seconds() > expected_interval_seconds:
            return True
    return False


def _compute_post_range_bars(
    bars: Sequence[Bar],
    range_end: datetime,
    range_end_index: int,
    expected_interval_seconds: int,
    window: int,
    now: datetime,
) -> Tuple[OpeningRangeBarObservation, ...]:
    """(ADR-024 Amendment 4) The bounded, chronological, contiguous
    prefix of completed bars immediately following `range_end_index`.
    The first candidate must open exactly at `range_end` -- no
    tolerance, no forward search. Every following candidate must open
    exactly one `expected_interval_seconds` after the previous accepted
    one. A continuity failure or an incomplete candidate stops
    extraction immediately; never skip-and-resume."""
    interval = timedelta(seconds=expected_interval_seconds)
    observations: List[OpeningRangeBarObservation] = []
    expected_timestamp = range_end
    index = range_end_index
    while len(observations) < window and index < len(bars):
        candidate = bars[index]
        if candidate.timestamp != expected_timestamp:
            break
        if candidate.timestamp + interval > now:
            break
        observations.append(
            OpeningRangeBarObservation(
                index=index,
                timestamp=candidate.timestamp,
                open=candidate.open,
                high=candidate.high,
                low=candidate.low,
                close=candidate.close,
            )
        )
        expected_timestamp = candidate.timestamp + interval
        index += 1
    return tuple(observations)


def _compute_single_range(
    bars: Sequence[Bar],
    now: datetime,
    session: SessionName,
    range_start: datetime,
    duration_minutes: int,
    min_bars: int,
    expected_interval_seconds: int,
    post_range_bar_window: int,
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

    post_range_bars = _compute_post_range_bars(
        bars, range_end, range_end_index, expected_interval_seconds, post_range_bar_window, now,
    )

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
        post_range_bars=post_range_bars,
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
                config.opening_range_post_range_bar_window,
            )
        )
    return tuple(states)


__all__ = ["compute_opening_ranges"]
