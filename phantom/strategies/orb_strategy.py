"""Strategy 1 — Opening Range Breakout.

Thin adapter over the existing :class:`~phantom.orb.ORBEngine` so ORB becomes a
first-class strategy while keeping its stateful range tracking and the
``/orb/status`` endpoint working unchanged.
"""

from __future__ import annotations

from typing import Optional

from ..config import Config, DEFAULT_CONFIG
from ..orb import ORBContext, ORBDecision, ORBEngine
from ..types import Direction, MarketSnapshot
from .base import Strategy, StrategyContext, StrategySignal


class ORBStrategy(Strategy):
    name = "ORB"

    def __init__(self, config: Config = DEFAULT_CONFIG, engine: Optional[ORBEngine] = None):
        self.config = config
        self.engine = engine or ORBEngine(config)
        self.last_decision: Optional[ORBDecision] = None

    def evaluate(self, snap: MarketSnapshot, ctx: StrategyContext) -> StrategySignal:
        orb_ctx = ORBContext(
            regime=ctx.regime,
            h4d1_aligned={
                Direction.LONG: ctx.h4_dir == Direction.LONG and ctx.d1_dir == Direction.LONG,
                Direction.SHORT: ctx.h4_dir == Direction.SHORT and ctx.d1_dir == Direction.SHORT,
            },
            bos={
                Direction.LONG: ctx.bos.found and ctx.bos.direction == Direction.LONG,
                Direction.SHORT: ctx.bos.found and ctx.bos.direction == Direction.SHORT,
            },
            news_safe=ctx.news_safe,
            spread_safe=ctx.spread_safe,
            exposure_safe=ctx.exposure_safe,
            correlation_safe=ctx.correlation_safe,
            atr=ctx.atr,
        )
        d = self.engine.evaluate(snap, orb_ctx)
        self.last_decision = d

        if d.confirmed:
            return StrategySignal(self.name, d.breakout_direction, score=d.score_impact,
                                  confirmed=True, reason=d.reason)
        if d.false_breakout:
            return StrategySignal(self.name, Direction.NONE, penalty=d.score_impact,
                                  blocked=True, reason=d.reason)
        return StrategySignal(self.name, Direction.NONE, blocked=d.blocked, reason=d.reason)
