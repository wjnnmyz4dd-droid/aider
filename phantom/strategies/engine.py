"""StrategyEngine — consolidates strategy signals into one score contribution.

Consolidation rules (anti-inflation by construction):
  * Agreeing strategies do NOT sum their scores (that would double-count the
    shared BOS/trend inputs). The directional contribution is
    ``max(scores) + a small capped confluence bonus``.
  * Opposing directions CANCEL to their difference and are then dampened, and
    the conflict is flagged. Conflicting strategies can never raise the score.
  * The net positive contribution is hard-capped at ``layer_cap`` (== the prior
    ORB maximum), so this layer can never inflate the score above the previous
    model. Penalties (e.g. false breakout) are always applied.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from ..config import Config, DEFAULT_CONFIG
from ..orb import ORBDecision, ORBEngine
from ..types import Direction, MarketSnapshot
from .base import StrategyContext, StrategySignal
from .liquidity_reversal import LiquiditySweepReversal
from .momentum_continuation import MomentumContinuation
from .orb_strategy import ORBStrategy
from .session_breakout import SessionBreakoutContinuation
from .support_resistance import SupportResistanceBounce


@dataclass
class StrategyOutcome:
    net_score: float
    direction: Direction
    conflict: bool
    signals: List[StrategySignal]
    orb_decision: Optional[ORBDecision] = None
    detail: str = ""

    def as_dict(self) -> dict:
        return {
            "net_score": round(self.net_score, 2),
            "direction": self.direction.value,
            "conflict": self.conflict,
            "detail": self.detail,
            "signals": [s.as_dict() for s in self.signals],
        }


class StrategyEngine:
    def __init__(self, config: Config = DEFAULT_CONFIG, orb_engine: Optional[ORBEngine] = None):
        self.config = config
        self.orb_strategy = ORBStrategy(config, engine=orb_engine)
        self.strategies = [
            self.orb_strategy,
            LiquiditySweepReversal(config),
            SessionBreakoutContinuation(config),
            SupportResistanceBounce(config),
            MomentumContinuation(config),
        ]

    @property
    def orb_engine(self) -> ORBEngine:
        return self.orb_strategy.engine

    def _side_score(self, signals: List[StrategySignal]) -> float:
        if not signals:
            return 0.0
        sp = self.config.strategies
        base = max(s.score for s in signals)
        bonus = min((len(signals) - 1) * sp.confluence_bonus_per, sp.confluence_cap)
        return base + bonus

    def resolve(self, signals: List[StrategySignal]) -> StrategyOutcome:
        sp = self.config.strategies
        longs = [s for s in signals if s.confirmed and s.direction == Direction.LONG and s.score > 0]
        shorts = [s for s in signals if s.confirmed and s.direction == Direction.SHORT and s.score > 0]
        penalties = sum(s.penalty for s in signals)  # <= 0

        l_score = self._side_score(longs)
        s_score = self._side_score(shorts)
        conflict = l_score > 0 and s_score > 0

        if conflict:
            direction = Direction.LONG if l_score >= s_score else Direction.SHORT
            # Opposing sides cancel; the remainder is dampened -> stronger
            # confirmation required, never inflation.
            net = abs(l_score - s_score) * sp.conflict_dampen
            detail = (f"CONFLICT long={l_score:.1f} vs short={s_score:.1f} "
                      f"-> {direction.value} {net:.1f} (dampened)")
        elif l_score > 0 or s_score > 0:
            direction = Direction.LONG if l_score > 0 else Direction.SHORT
            net = max(l_score, s_score)
            agree = longs if l_score > 0 else shorts
            detail = f"{direction.value} {net:.1f} from " + ",".join(s.name for s in agree)
        else:
            direction = Direction.NONE
            net = 0.0
            detail = "no confirmed strategy"

        net = min(net, sp.layer_cap)  # hard anti-inflation cap
        net += penalties
        if penalties < 0:
            detail += f"; penalties {penalties:.1f}"

        return StrategyOutcome(net, direction, conflict, signals, detail=detail)

    def _gate(self, sig: StrategySignal, ctx: StrategyContext) -> StrategySignal:
        """Enforce shared protections so NO strategy can bypass them. A blocked
        signal keeps any penalty but forfeits its positive contribution."""
        if not sig.confirmed:
            return sig
        if not ctx.news_safe:
            return StrategySignal(sig.name, blocked=True, penalty=sig.penalty,
                                  reason="gated: news")
        if not ctx.correlation_safe:
            return StrategySignal(sig.name, blocked=True, penalty=sig.penalty,
                                  reason="gated: correlation")
        if sig.direction != Direction.NONE and not ctx.exposure_safe.get(sig.direction, True):
            return StrategySignal(sig.name, blocked=True, penalty=sig.penalty,
                                  reason="gated: exposure")
        return sig

    def evaluate(self, snap: MarketSnapshot, ctx: StrategyContext) -> StrategyOutcome:
        signals = [self._gate(s.evaluate(snap, ctx), ctx) for s in self.strategies]
        outcome = self.resolve(signals)
        outcome.orb_decision = self.orb_strategy.last_decision
        return outcome
