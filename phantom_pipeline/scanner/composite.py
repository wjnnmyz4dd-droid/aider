"""Amendment 1 composite fields (ADR-002 §5, §13).

Every function here derives its result from facts already computed
elsewhere in the same scan (`swing.py`'s swing hierarchy, `trend.py`'s
strength history, `volatility.py`'s ratio) — never a second independent
computation pass. This is the direct application of §13's swing_points()
lesson to Amendment 1's new fields.

`market_phase`'s classification below is a first-pass heuristic, not a
tuned model — like every other threshold in this package, it is an
implementation default subject to empirical revision (ADR-002 §13,
`config.py`'s own docstring), not architecture.
"""

from __future__ import annotations

from typing import Optional, Sequence, Tuple

from .config import ScannerConfig
from .models import (
    Direction,
    EqualLevel,
    MarketPhase,
    RangeStructure,
    StructureConfidence,
    StructureTrendState,
    SwingKind,
    SwingPoint,
    SwingSequenceType,
)


def classify_sequence(swings: Sequence[SwingPoint]) -> SwingSequenceType:
    highs = [s.price for s in swings if s.kind == SwingKind.HIGH]
    lows = [s.price for s in swings if s.kind == SwingKind.LOW]

    if len(highs) < 2 or len(lows) < 2:
        return SwingSequenceType.INSUFFICIENT_DATA

    highs_rising = all(a < b for a, b in zip(highs, highs[1:]))
    lows_rising = all(a < b for a, b in zip(lows, lows[1:]))
    highs_falling = all(a > b for a, b in zip(highs, highs[1:]))
    lows_falling = all(a > b for a, b in zip(lows, lows[1:]))

    if highs_rising and lows_rising:
        return SwingSequenceType.HIGHER_HIGHS_HIGHER_LOWS
    if highs_falling and lows_falling:
        return SwingSequenceType.LOWER_HIGHS_LOWER_LOWS
    return SwingSequenceType.MIXED


def _direction_for_sequence(sequence: SwingSequenceType) -> Direction:
    if sequence == SwingSequenceType.HIGHER_HIGHS_HIGHER_LOWS:
        return Direction.UP
    if sequence == SwingSequenceType.LOWER_HIGHS_LOWER_LOWS:
        return Direction.DOWN
    if sequence == SwingSequenceType.MIXED:
        return Direction.NEUTRAL
    return Direction.UNKNOWN


def external_internal_structure(
    swings: Sequence[SwingPoint],
) -> Tuple[StructureTrendState, StructureTrendState]:
    major = [s for s in swings if s.is_major]
    minor = [s for s in swings if not s.is_major]

    external_sequence = classify_sequence(major)
    internal_sequence = classify_sequence(minor)

    external = StructureTrendState(_direction_for_sequence(external_sequence), external_sequence)
    internal = StructureTrendState(_direction_for_sequence(internal_sequence), internal_sequence)
    return external, internal


def equal_levels(
    swings: Sequence[SwingPoint], kind: SwingKind, tolerance_pct: float
) -> Tuple[EqualLevel, ...]:
    prices = sorted(s.price for s in swings if s.kind == kind)
    if not prices:
        return ()

    groups: list = [[prices[0]]]
    for price in prices[1:]:
        group_avg = sum(groups[-1]) / len(groups[-1])
        if group_avg == 0:
            groups.append([price])
            continue
        if abs(price - group_avg) / abs(group_avg) <= tolerance_pct:
            groups[-1].append(price)
        else:
            groups.append([price])

    return tuple(
        EqualLevel(kind, sum(group) / len(group), len(group))
        for group in groups
        if len(group) >= 2
    )


def range_structure(ratio: Optional[float], config: ScannerConfig) -> RangeStructure:
    if ratio is None:
        return RangeStructure.UNKNOWN
    if ratio >= config.volatility_elevated_ratio:
        return RangeStructure.EXPANSION
    if ratio <= config.volatility_compressed_ratio:
        return RangeStructure.COMPRESSION
    return RangeStructure.NEUTRAL


def trend_momentum(
    strength_history: Sequence[float],
) -> Tuple[Optional[bool], Optional[bool]]:
    """Returns `(accelerating, exhausting)`. `None` for both when there is
    not enough of the already-computed strength series to compare against
    (fail closed, never guessed)."""

    if len(strength_history) < 2:
        return None, None

    latest = abs(strength_history[-1])
    previous = abs(strength_history[-2])

    if latest > previous:
        return True, False
    if latest < previous:
        return False, True
    return False, False


def market_phase(
    external: StructureTrendState,
    internal: StructureTrendState,
    range_state: RangeStructure,
) -> MarketPhase:
    if range_state == RangeStructure.UNKNOWN or external.direction == Direction.UNKNOWN:
        return MarketPhase.UNKNOWN

    if range_state == RangeStructure.EXPANSION:
        if external.direction == Direction.UP:
            return MarketPhase.MARKUP
        if external.direction == Direction.DOWN:
            return MarketPhase.MARKDOWN
        return MarketPhase.UNDEFINED

    if range_state in (RangeStructure.COMPRESSION, RangeStructure.NEUTRAL):
        if internal.direction == Direction.UP:
            return MarketPhase.ACCUMULATION
        if internal.direction == Direction.DOWN:
            return MarketPhase.DISTRIBUTION
        return MarketPhase.UNDEFINED

    return MarketPhase.UNDEFINED


def structure_confidence(
    swings: Sequence[SwingPoint],
    external: StructureTrendState,
    internal: StructureTrendState,
    config: ScannerConfig,
) -> StructureConfidence:
    if len(swings) < config.min_swings_for_phase:
        return StructureConfidence.INSUFFICIENT_DATA

    if external.sequence == SwingSequenceType.INSUFFICIENT_DATA or (
        internal.sequence == SwingSequenceType.INSUFFICIENT_DATA
    ):
        return StructureConfidence.INSUFFICIENT_DATA

    if external.sequence == SwingSequenceType.MIXED or internal.sequence == SwingSequenceType.MIXED:
        return StructureConfidence.AMBIGUOUS

    if (
        external.direction == internal.direction
        and external.direction not in (Direction.NEUTRAL, Direction.UNKNOWN)
    ):
        return StructureConfidence.CLEAR

    return StructureConfidence.AMBIGUOUS
