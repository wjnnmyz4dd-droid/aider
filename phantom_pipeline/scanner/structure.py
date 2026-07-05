"""Market structure facts (ADR-002 §5, §6, §13).

Every function here consumes the single `Tuple[SwingPoint, ...]`
`swing.py` already computed — none of them re-run swing detection, which
is the exact `swing_points()`-recomputation pattern ADR-002 §13 forbids
(`phantom/structure.py`'s `bos()`, `choch()`, and `liquidity_sweep()` each
independently called `ind.swing_points()`; this module calls it zero
times).

BOS/CHoCH and liquidity sweeps are detected in a single pass over the
bars (`_walk_major_breaks`) since both need the same "last confirmed
major swing extreme" pointer walk — a second pass would itself be a
duplicated computation of the kind §13 forbids.

Kinds mirror the shape of `phantom/structure.py`'s `StructureSignal`
(found/direction/detail) as an idea, not as an authoritative type
(ADR-002 §17) — and are strictly playbook-agnostic (no ORB, no
Liquidity Reversal naming; ADR-002 §6).
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from ..data_pipeline.models import NormalizedBar
from .config import ScannerConfig
from .models import (
    Direction,
    LiquidityEvent,
    StructuralSignal,
    StructureKind,
    SwingKind,
    SwingPoint,
)


def major_swings(swings: Sequence[SwingPoint]) -> Tuple[SwingPoint, ...]:
    return tuple(s for s in swings if s.is_major)


def _walk_major_breaks(
    bars: Sequence[NormalizedBar], swings: Sequence[SwingPoint]
) -> Tuple[List[StructuralSignal], List[LiquidityEvent]]:
    majors = major_swings(swings)
    signals: List[StructuralSignal] = []
    events: List[LiquidityEvent] = []

    last_major_high: Optional[float] = None
    last_major_low: Optional[float] = None
    trend: Optional[Direction] = None
    major_idx = 0

    for i, bar in enumerate(bars):
        while major_idx < len(majors) and majors[major_idx].index <= i:
            m = majors[major_idx]
            if m.kind == SwingKind.HIGH:
                last_major_high = m.price
            else:
                last_major_low = m.price
            major_idx += 1

        if last_major_high is not None and bar.high > last_major_high:
            if bar.close > last_major_high:
                kind = StructureKind.BOS if trend in (None, Direction.UP) else StructureKind.CHOCH
                signals.append(
                    StructuralSignal(
                        kind,
                        Direction.UP,
                        f"close {bar.close} broke above major high {last_major_high}",
                    )
                )
                trend = Direction.UP
                last_major_high = bar.close
            else:
                events.append(LiquidityEvent("SWEEP_HIGH", Direction.DOWN, bar.high))

        if last_major_low is not None and bar.low < last_major_low:
            if bar.close < last_major_low:
                kind = StructureKind.BOS if trend in (None, Direction.DOWN) else StructureKind.CHOCH
                signals.append(
                    StructuralSignal(
                        kind,
                        Direction.DOWN,
                        f"close {bar.close} broke below major low {last_major_low}",
                    )
                )
                trend = Direction.DOWN
                last_major_low = bar.close
            else:
                events.append(LiquidityEvent("SWEEP_LOW", Direction.UP, bar.low))

    return signals, events


def _fair_value_gaps(bars: Sequence[NormalizedBar]) -> List[StructuralSignal]:
    signals: List[StructuralSignal] = []
    for i in range(2, len(bars)):
        left, _, right = bars[i - 2], bars[i - 1], bars[i]
        if left.high < right.low:
            signals.append(
                StructuralSignal(
                    StructureKind.FVG,
                    Direction.UP,
                    f"gap between {left.high} and {right.low}",
                )
            )
        elif left.low > right.high:
            signals.append(
                StructuralSignal(
                    StructureKind.FVG,
                    Direction.DOWN,
                    f"gap between {right.high} and {left.low}",
                )
            )
    return signals


def _order_blocks(
    bars: Sequence[NormalizedBar], atr_value: Optional[float], config: ScannerConfig
) -> List[StructuralSignal]:
    if atr_value is None or atr_value <= 0:
        return []

    # Reuses `major_swing_atr_multiple` (already named/configured for swing
    # magnitude classification) as the same "significant relative to ATR"
    # threshold here, rather than introducing a second unconfigured
    # magic-number constant for the same underlying concept.
    threshold = config.major_swing_atr_multiple * atr_value

    signals: List[StructuralSignal] = []
    for i in range(1, len(bars)):
        bar = bars[i]
        prior = bars[i - 1]
        true_range = bar.high - bar.low
        if true_range < threshold:
            continue
        if bar.close > bar.open and prior.close < prior.open:
            signals.append(
                StructuralSignal(
                    StructureKind.ORDER_BLOCK,
                    Direction.UP,
                    f"bearish candle at {prior.timestamp} preceding impulsive move",
                )
            )
        elif bar.close < bar.open and prior.close > prior.open:
            signals.append(
                StructuralSignal(
                    StructureKind.ORDER_BLOCK,
                    Direction.DOWN,
                    f"bullish candle at {prior.timestamp} preceding impulsive move",
                )
            )
    return signals


def _support_resistance(swings: Sequence[SwingPoint]) -> List[StructuralSignal]:
    signals: List[StructuralSignal] = []
    for swing in major_swings(swings):
        if swing.kind == SwingKind.LOW:
            signals.append(
                StructuralSignal(StructureKind.SUPPORT, Direction.NEUTRAL, f"level {swing.price}")
            )
        else:
            signals.append(
                StructuralSignal(
                    StructureKind.RESISTANCE, Direction.NEUTRAL, f"level {swing.price}"
                )
            )
    return signals


def compute_structure(
    bars: Sequence[NormalizedBar],
    swings: Sequence[SwingPoint],
    atr_value: Optional[float],
    config: ScannerConfig,
) -> Tuple[Tuple[StructuralSignal, ...], Tuple[LiquidityEvent, ...]]:
    breaks, sweeps = _walk_major_breaks(bars, swings)
    signals = (
        breaks
        + _fair_value_gaps(bars)
        + _order_blocks(bars, atr_value, config)
        + _support_resistance(swings)
    )
    return tuple(signals), tuple(sweeps)
