"""Liquidity analysis: equal highs/lows, liquidity pools, sweeps, stop
hunts, the liquidity-trap filter, and displacement detection
(ADR-024 §1 "Liquidity Analysis").

This module only classifies. It never places, sizes, or times a trade
-- see `docs/adr/ADR-024-evidence-engine.md` Hard Rule 1.

Sweep vocabulary used throughout, defined once here to keep every
`LiquiditySweep` field auditable rather than a hidden judgment call:

- `is_stop_hunt`: the sweep bar's wick pierces beyond the pool's price
  and that same bar's close comes back to the origin side of the pool
  -- the classic wick-rejection shape.
- `displacement_follow_through`: the bar immediately after the sweep has
  a true range at or above `displacement_atr_multiple * ATR` and
  continues opposite the wick direction -- real momentum confirming the
  reversal the wick shape suggested.
- `is_trap`: `is_stop_hunt` is true but `displacement_follow_through` is
  false -- the sweep *looked* like a stop hunt but had no real
  follow-through, so treating it as a reversal signal would be a trap.
"""

from __future__ import annotations

from typing import List, Sequence, Tuple

from .config import EvidenceEngineConfig
from .models import Bar, EqualLevel, LiquidityPool, LiquidityResult, LiquiditySweep, SwingPoint, SwingType
from .volatility import atr_series


def find_equal_levels(
    swings: Sequence[SwingPoint], tolerance_pct: float, min_points: int
) -> Tuple[EqualLevel, ...]:
    """Clusters swing highs (and, separately, swing lows) that sit
    within `tolerance_pct` of one another -- the "equal highs" / "equal
    lows" concept. Deterministic: sorted by price then index before
    clustering, so input order never affects the result."""
    levels: List[EqualLevel] = []
    for swing_type in (SwingType.HIGH, SwingType.LOW):
        points = sorted((s for s in swings if s.swing_type == swing_type), key=lambda s: (s.price, s.index))
        cluster: List[SwingPoint] = []
        for point in points:
            if cluster and abs(point.price - cluster[0].price) / abs(cluster[0].price or 1.0) > tolerance_pct / 100.0:
                if len(cluster) >= min_points:
                    levels.append(_cluster_to_equal_level(swing_type, cluster))
                cluster = [point]
            else:
                cluster.append(point)
        if len(cluster) >= min_points:
            levels.append(_cluster_to_equal_level(swing_type, cluster))
    levels.sort(key=lambda lv: lv.price)
    return tuple(levels)


def _cluster_to_equal_level(swing_type: SwingType, cluster: Sequence[SwingPoint]) -> EqualLevel:
    price = sum(p.price for p in cluster) / len(cluster)
    indices = tuple(sorted(p.index for p in cluster))
    return EqualLevel(swing_type=swing_type, price=price, indices=indices)


def build_liquidity_pools(equal_levels: Sequence[EqualLevel], bars: Sequence[Bar]) -> Tuple[LiquidityPool, ...]:
    """An equal-level cluster becomes a pool at its representative
    price. `swept` is true if any bar after the cluster's last touch
    has already wicked beyond the pool's price -- resting liquidity that
    is no longer resting."""
    pools: List[LiquidityPool] = []
    for level in equal_levels:
        last_index = level.indices[-1]
        swept = False
        for bar in bars[last_index + 1 :]:
            if level.swing_type == SwingType.HIGH and bar.high > level.price:
                swept = True
                break
            if level.swing_type == SwingType.LOW and bar.low < level.price:
                swept = True
                break
        pools.append(LiquidityPool(swing_type=level.swing_type, price=level.price, indices=level.indices, swept=swept))
    return tuple(pools)


def detect_displacement(bars: Sequence[Bar], config: EvidenceEngineConfig) -> Tuple[int, ...]:
    """Indices of bars whose true range is at or above
    `displacement_atr_multiple * ATR(at that bar)` -- a single,
    reusable definition of "displacement" shared by sweep confirmation
    below and available standalone for any future consumer, so the
    threshold is defined in exactly one place."""
    if not bars:
        return ()
    atrs = atr_series(bars, config.atr_period)
    indices: List[int] = []
    for i, bar in enumerate(bars):
        reference_atr = atrs[i]
        bar_range = bar.high - bar.low
        if reference_atr > 0 and bar_range >= config.displacement_atr_multiple * reference_atr:
            indices.append(i)
    return tuple(indices)


def detect_liquidity_sweeps(
    bars: Sequence[Bar], pools: Sequence[LiquidityPool], config: EvidenceEngineConfig
) -> Tuple[LiquiditySweep, ...]:
    sweeps: List[LiquiditySweep] = []
    displacement_indices = set(detect_displacement(bars, config))

    for pool in pools:
        if not pool.swept:
            continue
        last_index = pool.indices[-1]
        sweep_index = None
        for i in range(last_index + 1, len(bars)):
            bar = bars[i]
            if pool.swing_type == SwingType.HIGH and bar.high > pool.price:
                sweep_index = i
                break
            if pool.swing_type == SwingType.LOW and bar.low < pool.price:
                sweep_index = i
                break
        if sweep_index is None:
            continue

        sweep_bar = bars[sweep_index]
        if pool.swing_type == SwingType.HIGH:
            closed_back_inside = sweep_bar.close < pool.price
            sweep_price = sweep_bar.high
        else:
            closed_back_inside = sweep_bar.close > pool.price
            sweep_price = sweep_bar.low
        is_stop_hunt = closed_back_inside

        displacement_follow_through = False
        if sweep_index + 1 < len(bars):
            follow_bar = bars[sweep_index + 1]
            strong_range = (sweep_index + 1) in displacement_indices
            if pool.swing_type == SwingType.HIGH:
                continues_reversal = follow_bar.close < sweep_bar.close
            else:
                continues_reversal = follow_bar.close > sweep_bar.close
            displacement_follow_through = strong_range and continues_reversal

        is_trap = is_stop_hunt and not displacement_follow_through

        sweeps.append(
            LiquiditySweep(
                pool=pool,
                sweep_index=sweep_index,
                sweep_price=sweep_price,
                closed_back_inside=closed_back_inside,
                is_stop_hunt=is_stop_hunt,
                is_trap=is_trap,
                displacement_follow_through=displacement_follow_through,
            )
        )
    return tuple(sweeps)


def analyze_liquidity(
    bars: Sequence[Bar], swings: Sequence[SwingPoint], config: EvidenceEngineConfig
) -> LiquidityResult:
    equal_levels = find_equal_levels(swings, config.equal_level_tolerance_pct, config.equal_level_min_points)
    pools = build_liquidity_pools(equal_levels, bars)
    sweeps = detect_liquidity_sweeps(bars, pools, config)
    return LiquidityResult(pools=pools, sweeps=sweeps)


__all__ = [
    "find_equal_levels",
    "build_liquidity_pools",
    "detect_displacement",
    "detect_liquidity_sweeps",
    "analyze_liquidity",
]
