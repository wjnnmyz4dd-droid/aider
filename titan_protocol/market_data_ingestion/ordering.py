"""Sequence/duplicate/out-of-order detection, and missing-bar (gap)
detection, per (symbol, timeframe) (ADR-033 SS3.3).

`SequenceState` is deliberately a plain, caller-owned mutable record --
`MarketDataIngestionEngine` holds one per (symbol, timeframe) behind
its own lock; nothing in this module does its own locking, keeping it
a pure, independently testable function of (state, new bar)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Tuple

from .config import MarketDataIngestionConfig
from .models import TIMEFRAME_SECONDS, RawBar, RejectionReason


@dataclass
class SequenceState:
    last_sequence_number: Optional[int] = None
    last_bar_open_time: Optional[datetime] = None


def check_ordering(state: SequenceState, raw: RawBar, config: MarketDataIngestionConfig) -> Tuple[Optional[RejectionReason], bool]:
    """Returns `(rejection_reason, gap_detected)`. A gap is reported
    (never rejected on) when the new bar's `bar_open_time` advances by
    more than `gap_detection_multiplier` times the nominal interval --
    informational evidence of one or more missing bars, not itself
    invalid data."""

    if state.last_sequence_number is None or state.last_bar_open_time is None:
        return None, False  # first bar ever seen for this (symbol, timeframe)

    if raw.sequence_number == state.last_sequence_number and raw.bar_open_time == state.last_bar_open_time:
        return RejectionReason.DUPLICATE, False
    if raw.sequence_number <= state.last_sequence_number:
        return RejectionReason.OUT_OF_SEQUENCE, False
    if raw.bar_open_time <= state.last_bar_open_time:
        return RejectionReason.OUT_OF_ORDER, False

    nominal_interval = TIMEFRAME_SECONDS[raw.timeframe]
    elapsed = (raw.bar_open_time - state.last_bar_open_time).total_seconds()
    gap_detected = elapsed > nominal_interval * config.gap_detection_multiplier

    return None, gap_detected


def advance(state: SequenceState, raw: RawBar) -> None:
    state.last_sequence_number = raw.sequence_number
    state.last_bar_open_time = raw.bar_open_time


__all__ = ["SequenceState", "check_ordering", "advance"]
