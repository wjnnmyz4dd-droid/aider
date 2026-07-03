"""Strategy 4 (Playbook 7) — Support & Resistance Bounce.

Confirmation-only. Identifies significant horizontal support/resistance zones
from recent swing pivots (repeated price reactions), and confirms a bounce only
when the latest candle *rejects* the zone with clear price action, in the
direction of the higher-timeframe trend. Weak or frequently-broken levels are
ignored (a zone needs repeated touches and must still be respected). It never
opens a trade — it returns a score influence the StrategyEngine consolidates.

LONG : price tags a SUPPORT zone (>= min_touches), rejects it with a lower wick
       and closes back above, and the H4 trend is up.
SHORT: mirror image at a RESISTANCE zone with the H4 trend down.

Scoring: Bounce +8, +HTF trend +5 (required), +Strong zone +5 (well-tested).
The whole strategy layer stays hard-capped by StrategyEngine.layer_cap, so this
playbook can never inflate a score beyond the existing model.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from ..config import Config, DEFAULT_CONFIG
from ..indicators import swing_points
from ..types import Candle, Direction, MarketSnapshot
from .base import Strategy, StrategyContext, StrategySignal


def _zones(levels: List[float], tol: float) -> List[Tuple[float, int]]:
    """Cluster price levels within ``tol`` of each other into (center, touches).

    ``touches`` is how many swing pivots formed the zone — the count of repeated
    reactions, used to weed out weak (single-touch) levels.
    """
    if tol <= 0 or not levels:
        return []
    ordered = sorted(levels)
    zones: List[Tuple[float, int]] = []
    bucket = [ordered[0]]
    for lvl in ordered[1:]:
        if lvl - bucket[0] <= tol:
            bucket.append(lvl)
        else:
            zones.append((sum(bucket) / len(bucket), len(bucket)))
            bucket = [lvl]
    zones.append((sum(bucket) / len(bucket), len(bucket)))
    return zones


class SupportResistanceBounce(Strategy):
    name = "S&R Bounce"

    def __init__(self, config: Config = DEFAULT_CONFIG):
        self.config = config

    def evaluate(self, snap: MarketSnapshot, ctx: StrategyContext) -> StrategySignal:
        sp = self.config.strategies
        atr = ctx.atr
        if not atr or atr <= 0:
            return StrategySignal(self.name, reason="no ATR")

        candles = snap.tf(self.config.orb.execution_tf)
        if len(candles) < 2 * sp.sr_lookback + 3:
            return StrategySignal(self.name, reason="insufficient bars")

        # HTF trend gates direction — we only take bounces WITH the trend
        # (never catch a falling knife against it). NEUTRAL H4 -> no signal,
        # which also keeps us out of directionless chop.
        direction = ctx.h4_dir
        if direction == Direction.NONE:
            return StrategySignal(self.name, reason="no HTF trend")

        highs, lows = swing_points(candles, sp.sr_lookback)
        tol = atr * sp.sr_zone_atr_mult
        last = candles[-1]
        prev = candles[-2]
        rng = last.high - last.low
        if rng <= 0:
            return StrategySignal(self.name, reason="flat candle")

        if direction == Direction.LONG:
            zones = _zones([p for _, p in lows], tol)
            # nearest support at/below where price is testing from above
            cands = [(c, t) for c, t in zones if c <= last.high]
            if not cands:
                return StrategySignal(self.name, direction, blocked=True,
                                      reason="no support zone in range")
            center, touches = max(cands, key=lambda z: z[0])  # closest below
            # the candle LOW is the contact point: it must dip into the zone
            # band (not far below = a break, not far above = never touched).
            near = center - atr * sp.sr_proximity_atr_mult <= last.low <= center + tol
            respected = prev.close >= center - tol  # level was acting as support (price above it)
            lower_wick = min(last.open, last.close) - last.low
            rejected = last.close > center and lower_wick >= sp.sr_rejection_wick_ratio * rng
        else:  # SHORT
            zones = _zones([p for _, p in highs], tol)
            cands = [(c, t) for c, t in zones if c >= last.low]
            if not cands:
                return StrategySignal(self.name, direction, blocked=True,
                                      reason="no resistance zone in range")
            center, touches = min(cands, key=lambda z: z[0])  # closest above
            near = center - tol <= last.high <= center + atr * sp.sr_proximity_atr_mult
            respected = prev.close <= center + tol
            upper_wick = last.high - max(last.open, last.close)
            rejected = last.close < center and upper_wick >= sp.sr_rejection_wick_ratio * rng

        if touches < sp.sr_min_touches:
            return StrategySignal(self.name, direction, blocked=True,
                                  reason="weak level (too few touches)")
        if not (near and respected and rejected):
            missing = [n for n, ok in (("near", near), ("respected", respected),
                                       ("rejection", rejected)) if not ok]
            return StrategySignal(self.name, direction, blocked=True,
                                  reason="no bounce: " + ",".join(missing))

        score = sp.sr_bounce + sp.sr_trend
        strong = touches >= sp.sr_strong_touches
        if strong:
            score += sp.sr_strong_zone
        return StrategySignal(
            self.name, direction, score=score, confirmed=True,
            reason=(f"{direction.value} bounce at {center:.5f} "
                    f"({touches} touches{'/strong' if strong else ''}); "
                    f"+{sp.sr_bounce:g} trend +{sp.sr_trend:g}"
                    f"{f' strong +{sp.sr_strong_zone:g}' if strong else ''}"),
        )
