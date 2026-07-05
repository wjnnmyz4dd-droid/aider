"""Single swing-pivot computation (ADR-002 §13).

This is the *one* place swing highs/lows are detected. Every downstream
consumer (`structure.py`, `composite.py`) takes the `Tuple[SwingPoint, ...]`
this module produces as an input — none of them re-detect swings at a
different lookback. This is the direct fix for `phantom/structure.py`'s
`swing_points()` being independently recomputed by `bos()`, `choch()`, and
`liquidity_sweep()` (ADR-002 §13, §17).

Major vs minor (external vs internal structure, Amendment 1) is a
classification of this same swing list by magnitude — never a second
swing-detection pass at a different lookback. Magnitude is measured in ATR
multiples using the ATR value `volatility.py` already computed for this
scan, passed in as `atr_value` rather than recomputed here.
"""

from __future__ import annotations

from typing import Optional, Sequence, Tuple

from ..data_pipeline.models import NormalizedBar
from .config import ScannerConfig
from .models import SwingKind, SwingPoint


def swing_points(
    bars: Sequence[NormalizedBar],
    config: ScannerConfig,
    atr_value: Optional[float],
) -> Tuple[SwingPoint, ...]:
    """Fractal pivot detection: bar `i` is a swing high if its `high` is the
    strict maximum within `[i - lookback, i + lookback]`; mirror for swing
    low. `is_major` is set when the swing's range against its immediately
    preceding opposite-kind swing exceeds `config.major_swing_atr_multiple`
    ATRs — `atr_value` is `None` when the caller has no ATR reading yet, in
    which case every swing is classified minor (fail closed: never guess
    "major" without a real ATR to measure against)."""

    lookback = config.swing_lookback
    points = []
    for i in range(len(bars)):
        lo = i - lookback
        hi = i + lookback
        if lo < 0 or hi >= len(bars):
            continue
        window = bars[lo : hi + 1]
        bar = bars[i]

        if bar.high == max(b.high for b in window) and _is_strict_max(bar.high, window, i, lo):
            points.append(SwingPoint(i, bar.timestamp, bar.high, SwingKind.HIGH, False))
        if bar.low == min(b.low for b in window) and _is_strict_min(bar.low, window, i, lo):
            points.append(SwingPoint(i, bar.timestamp, bar.low, SwingKind.LOW, False))

    points.sort(key=lambda p: p.index)
    return _classify_major_minor(points, atr_value, config.major_swing_atr_multiple)


def _is_strict_max(value: float, window: Sequence[NormalizedBar], i: int, lo: int) -> bool:
    center_local = i - lo
    others = [b.high for idx, b in enumerate(window) if idx != center_local]
    return all(value > o for o in others)


def _is_strict_min(value: float, window: Sequence[NormalizedBar], i: int, lo: int) -> bool:
    center_local = i - lo
    others = [b.low for idx, b in enumerate(window) if idx != center_local]
    return all(value < o for o in others)


def _classify_major_minor(
    points: Sequence[SwingPoint],
    atr_value: Optional[float],
    major_swing_atr_multiple: float,
) -> Tuple[SwingPoint, ...]:
    if atr_value is None or atr_value <= 0 or len(points) < 2:
        return tuple(points)

    classified = [points[0]]
    prev = points[0]
    for point in points[1:]:
        swing_range = abs(point.price - prev.price)
        is_major = swing_range >= (major_swing_atr_multiple * atr_value)
        classified.append(
            SwingPoint(point.index, point.timestamp, point.price, point.kind, is_major)
        )
        prev = point
    return tuple(classified)
