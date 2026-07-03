"""Strategy 5 (Playbook 8) — Momentum Continuation.

Confirmation-only. Detects strong, *sustained* directional expansion in the
trend direction and returns a score influence the StrategyEngine consolidates.
It never opens a trade.

To qualify:
  * Direction is set by the higher-timeframe trend (H4); NEUTRAL -> no signal.
  * The regime must agree with the direction (TRENDING_UP for long,
    TRENDING_DOWN for short) — this keeps the playbook out of ranging markets.
  * Market structure must agree — a BOS in the trend direction (continuation).
  * Momentum must be *increasing*, not a one-candle spike: the last ``mom_bars``
    closes are strictly directional AND short-window ATR is expanding versus the
    baseline ATR AND the cumulative move over those bars clears a minimum ATR
    multiple. A single spike after flat bars fails the monotonic-closes test.

Scoring: Continuation +8, +Structure(BOS) +5 (required), +Strong expansion +5.
Bounded by StrategyEngine.layer_cap — it can never inflate a score beyond the
existing model.
"""

from __future__ import annotations

from ..config import Config, DEFAULT_CONFIG
from ..indicators import atr as atr_of
from ..types import Direction, MarketSnapshot, Regime
from .base import Strategy, StrategyContext, StrategySignal


class MomentumContinuation(Strategy):
    name = "Momentum Continuation"

    def __init__(self, config: Config = DEFAULT_CONFIG):
        self.config = config

    def evaluate(self, snap: MarketSnapshot, ctx: StrategyContext) -> StrategySignal:
        sp = self.config.strategies
        baseline = ctx.atr
        if not baseline or baseline <= 0:
            return StrategySignal(self.name, reason="no ATR baseline")

        direction = ctx.h4_dir
        if direction == Direction.NONE:
            return StrategySignal(self.name, reason="no HTF trend")

        # Avoid ranging markets: the regime must agree with the trend direction.
        regime_ok = (
            direction == Direction.LONG and ctx.regime == Regime.TRENDING_UP
        ) or (
            direction == Direction.SHORT and ctx.regime == Regime.TRENDING_DOWN
        )
        if not regime_ok:
            return StrategySignal(self.name, direction, blocked=True,
                                  reason="regime not trending with direction")

        # Structure alignment — a break of structure in the trend direction.
        bos_ok = ctx.bos.found and ctx.bos.direction == direction
        if not bos_ok:
            return StrategySignal(self.name, direction, blocked=True,
                                  reason="no BOS in trend direction")

        candles = snap.tf(self.config.orb.execution_tf)
        need = sp.mom_atr_short + sp.mom_bars + 1
        if len(candles) < need:
            return StrategySignal(self.name, direction, blocked=True,
                                  reason="insufficient bars")

        closes = [c.close for c in candles]
        window = closes[-(sp.mom_bars + 1):]  # mom_bars steps
        if direction == Direction.LONG:
            sustained = all(window[i] > window[i - 1] for i in range(1, len(window)))
        else:
            sustained = all(window[i] < window[i - 1] for i in range(1, len(window)))
        if not sustained:
            return StrategySignal(self.name, direction, blocked=True,
                                  reason="one-candle spike / not sustained")

        atr_short = atr_of(candles, sp.mom_atr_short)
        if atr_short is None:
            return StrategySignal(self.name, direction, blocked=True,
                                  reason="no short ATR")
        expansion = atr_short / baseline
        move = abs(window[-1] - window[0])
        if expansion < sp.mom_expansion_ratio:
            return StrategySignal(self.name, direction, blocked=True,
                                  reason=f"no expansion ({expansion:.2f}x)")
        if move < sp.mom_min_move_atr * baseline:
            return StrategySignal(self.name, direction, blocked=True,
                                  reason="move too small vs ATR")

        score = sp.mom_continuation + sp.mom_structure
        strong = expansion >= sp.mom_strong_expansion_ratio
        if strong:
            score += sp.mom_strong
        return StrategySignal(
            self.name, direction, score=score, confirmed=True,
            reason=(f"{direction.value} continuation exp={expansion:.2f}x "
                    f"move={move / baseline:.2f}ATR{'/strong' if strong else ''}; "
                    f"+{sp.mom_continuation:g} BOS +{sp.mom_structure:g}"
                    f"{f' strong +{sp.mom_strong:g}' if strong else ''}"),
        )
