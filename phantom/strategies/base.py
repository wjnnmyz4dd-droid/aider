"""Shared strategy types."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List

from ..structure import StructureSignal
from ..types import Candle, Direction, MarketSnapshot, Regime


@dataclass
class StrategyContext:
    """Facts computed once by the scorer and shared with every strategy, so no
    strategy recomputes indicators or re-reads guards."""

    regime: Regime
    h4_dir: Direction
    d1_dir: Direction
    bias: Direction
    bos: StructureSignal
    choch: StructureSignal
    sweep: StructureSignal
    fvg: StructureSignal
    ob: StructureSignal
    news_safe: bool
    spread_safe: bool
    correlation_safe: bool
    exposure_safe: Dict[Direction, bool]
    atr: float
    exec_candles: List[Candle]


@dataclass
class StrategySignal:
    """One strategy's contribution. ``score`` is a non-negative directional
    contribution; ``penalty`` is a non-positive value applied regardless of
    direction (e.g. a false breakout)."""

    name: str
    direction: Direction = Direction.NONE
    score: float = 0.0
    penalty: float = 0.0
    confirmed: bool = False
    blocked: bool = False
    reason: str = ""

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "direction": self.direction.value,
            "score": round(self.score, 2),
            "penalty": round(self.penalty, 2),
            "confirmed": self.confirmed,
            "blocked": self.blocked,
            "reason": self.reason,
        }


class Strategy(ABC):
    """A signal contributor. Must never place or imply an order."""

    name: str = "strategy"

    @abstractmethod
    def evaluate(self, snap: MarketSnapshot, ctx: StrategyContext) -> StrategySignal:
        ...
