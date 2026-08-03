"""Market structure: swings, Break of Structure, Change of Character,
support/resistance (ADR-024 §1 "Market Structure").

Every function here is a pure transform of a `Tuple[Bar, ...]` -- no
mutable module state, no randomness, no I/O. Two calls with the same
bars always produce identical output.
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from .config import EvidenceEngineConfig
from .models import (
    Bar,
    FairValueGap,
    MarketStructureResult,
    PriceLevel,
    StructureDirection,
    StructureEvent,
    StructureEventType,
    SwingPoint,
    SwingType,
    TrendClassification,
)


def find_swing_points(bars: Sequence[Bar], lookback: int) -> Tuple[SwingPoint, ...]:
    """A bar is a confirmed swing high (low) if its high (low) is
    strictly more extreme than every other bar within `lookback` bars on
    both sides. Ties never confirm a swing -- ambiguous extremes are
    left unclassified rather than guessed at."""
    swings: List[SwingPoint] = []
    n = len(bars)
    for i in range(lookback, n - lookback):
        window = bars[i - lookback : i + lookback + 1]
        candidate = bars[i]
        others_high = [b.high for j, b in enumerate(window) if j != lookback]
        others_low = [b.low for j, b in enumerate(window) if j != lookback]
        if others_high and candidate.high > max(others_high):
            swings.append(SwingPoint(SwingType.HIGH, i, candidate.timestamp, candidate.high))
        if others_low and candidate.low < min(others_low):
            swings.append(SwingPoint(SwingType.LOW, i, candidate.timestamp, candidate.low))
    swings.sort(key=lambda s: s.index)
    return tuple(swings)


def detect_structure_events(
    bars: Sequence[Bar], swings: Sequence[SwingPoint], bos_type: StructureEventType
) -> Tuple[StructureEvent, ...]:
    """Same walk as the internal helper's docstring describes, but
    classifies continuation breaks as `bos_type` (INTERNAL or EXTERNAL,
    chosen by the caller based on which swing set was passed in) and
    reversal breaks as CHOCH, regardless of scale."""
    events: List[StructureEvent] = []
    last_high: Optional[SwingPoint] = None
    last_low: Optional[SwingPoint] = None
    broken_indices = set()
    trend: Optional[StructureDirection] = None
    swings_by_index = sorted(swings, key=lambda s: s.index)
    swing_cursor = 0

    for i, bar in enumerate(bars):
        while swing_cursor < len(swings_by_index) and swings_by_index[swing_cursor].index <= i:
            swing = swings_by_index[swing_cursor]
            if swing.swing_type == SwingType.HIGH:
                last_high = swing
            else:
                last_low = swing
            swing_cursor += 1

        if last_high is not None and last_high.index not in broken_indices and bar.close > last_high.price:
            direction = StructureDirection.BULLISH
            kind = bos_type if trend in (None, direction) else StructureEventType.CHOCH
            events.append(
                StructureEvent(
                    event_type=kind,
                    direction=direction,
                    broken_swing=last_high,
                    confirmed_index=i,
                    confirmed_price=bar.close,
                )
            )
            broken_indices.add(last_high.index)
            trend = direction

        if last_low is not None and last_low.index not in broken_indices and bar.close < last_low.price:
            direction = StructureDirection.BEARISH
            kind = bos_type if trend in (None, direction) else StructureEventType.CHOCH
            events.append(
                StructureEvent(
                    event_type=kind,
                    direction=direction,
                    broken_swing=last_low,
                    confirmed_index=i,
                    confirmed_price=bar.close,
                )
            )
            broken_indices.add(last_low.index)
            trend = direction

    return tuple(events)


def _cluster_levels(
    points: Sequence[SwingPoint], tolerance_pct: float, min_touches: int
) -> Tuple[PriceLevel, ...]:
    """Greedy price clustering: sort by price, then group consecutive
    points within `tolerance_pct` of the running cluster's first price.
    Deterministic regardless of input order since the sort key is price
    then index."""
    if not points:
        return ()
    ordered = sorted(points, key=lambda p: (p.price, p.index))
    levels: List[PriceLevel] = []
    cluster: List[SwingPoint] = [ordered[0]]
    for point in ordered[1:]:
        anchor = cluster[0].price
        if anchor != 0 and abs(point.price - anchor) / abs(anchor) <= tolerance_pct / 100.0:
            cluster.append(point)
        else:
            if len(cluster) >= min_touches:
                levels.append(_cluster_to_level(cluster))
            cluster = [point]
    if len(cluster) >= min_touches:
        levels.append(_cluster_to_level(cluster))
    levels.sort(key=lambda lv: lv.price)
    return tuple(levels)


def _cluster_to_level(cluster: Sequence[SwingPoint]) -> PriceLevel:
    price = sum(p.price for p in cluster) / len(cluster)
    indices = tuple(sorted(p.index for p in cluster))
    return PriceLevel(price=price, touches=len(cluster), first_index=indices[0], last_index=indices[-1])


def support_resistance(
    swings: Sequence[SwingPoint], config: EvidenceEngineConfig
) -> Tuple[Tuple[PriceLevel, ...], Tuple[PriceLevel, ...]]:
    lows = [s for s in swings if s.swing_type == SwingType.LOW]
    highs = [s for s in swings if s.swing_type == SwingType.HIGH]
    support = _cluster_levels(lows, config.support_resistance_tolerance_pct, config.support_resistance_min_touches)
    resistance = _cluster_levels(highs, config.support_resistance_tolerance_pct, config.support_resistance_min_touches)
    return support, resistance


def _structural_trend(swings: Sequence[SwingPoint]) -> TrendClassification:
    """The simple, swing-sequence-only trend read used to classify BOS
    vs CHOCH direction: the last two highs and last two lows both
    ascending => uptrend; both descending => downtrend; anything else
    (including too few swings to judge) => range. The richer 6-state
    classification (compression/expansion/reversal) is `trend.py`'s
    responsibility, built on top of this and volatility."""
    highs = [s.price for s in swings if s.swing_type == SwingType.HIGH]
    lows = [s.price for s in swings if s.swing_type == SwingType.LOW]
    if len(highs) >= 2 and len(lows) >= 2:
        if highs[-1] > highs[-2] and lows[-1] > lows[-2]:
            return TrendClassification.TRENDING_UP
        if highs[-1] < highs[-2] and lows[-1] < lows[-2]:
            return TrendClassification.TRENDING_DOWN
    return TrendClassification.RANGE


def detect_fair_value_gaps(bars: Sequence[Bar]) -> Tuple[FairValueGap, ...]:
    """(Amendment 2) A bullish FVG forms when candle 1's high sits below
    candle 3's low (price gapped up through candle 2 without trading);
    a bearish FVG is the mirror. `filled` becomes true the first time
    any later bar's range overlaps the gap zone at all."""
    gaps: List[FairValueGap] = []
    for i in range(2, len(bars)):
        first, third = bars[i - 2], bars[i]
        if first.high < third.low:
            direction = StructureDirection.BULLISH
            gap_low, gap_high = first.high, third.low
        elif first.low > third.high:
            direction = StructureDirection.BEARISH
            gap_low, gap_high = third.high, first.low
        else:
            continue

        filled = False
        fill_index: Optional[int] = None
        for j in range(i + 1, len(bars)):
            later = bars[j]
            if later.low <= gap_high and later.high >= gap_low:
                filled = True
                fill_index = j
                break

        gaps.append(
            FairValueGap(
                direction=direction, start_index=i - 2, end_index=i,
                gap_high=gap_high, gap_low=gap_low, filled=filled, fill_index=fill_index,
            )
        )
    return tuple(gaps)


def analyze_market_structure(bars: Sequence[Bar], config: EvidenceEngineConfig) -> MarketStructureResult:
    internal_swings = find_swing_points(bars, config.swing_lookback)
    external_lookback = max(config.swing_lookback + 1, config.internal_structure_lookback)
    external_swings = find_swing_points(bars, external_lookback)

    internal_events = detect_structure_events(bars, internal_swings, StructureEventType.BOS_INTERNAL)
    external_events = detect_structure_events(bars, external_swings, StructureEventType.BOS_EXTERNAL)
    all_events = tuple(sorted(internal_events + external_events, key=lambda e: e.confirmed_index))

    support, resistance = support_resistance(internal_swings, config)
    trend = _structural_trend(external_swings if external_swings else internal_swings)

    return MarketStructureResult(
        swings=internal_swings,
        events=all_events,
        trend=trend,
        support_levels=support,
        resistance_levels=resistance,
    )


__all__ = [
    "find_swing_points",
    "detect_structure_events",
    "support_resistance",
    "detect_fair_value_gaps",
    "analyze_market_structure",
]
