"""The 5 concrete strategies (ADR-026 §1) plus the shared `Strategy`
interface and explicit registry."""

from __future__ import annotations

from .base import Strategy
from .bos_fvg import BosFvgStrategy
from .liquidity_sweep_mss import LiquiditySweepMssStrategy
from .range_reversal import RangeReversalStrategy
from .registry import DuplicateStrategyError, StrategyRegistry
from .session_breakout import SessionBreakoutStrategy
from .trend_continuation import TrendContinuationStrategy


def build_default_registry() -> StrategyRegistry:
    """The canonical registry: all 5 strategies, registered once."""
    registry = StrategyRegistry()
    registry.register(LiquiditySweepMssStrategy())
    registry.register(BosFvgStrategy())
    registry.register(TrendContinuationStrategy())
    registry.register(SessionBreakoutStrategy())
    registry.register(RangeReversalStrategy())
    return registry


__all__ = [
    "Strategy",
    "StrategyRegistry",
    "DuplicateStrategyError",
    "LiquiditySweepMssStrategy",
    "BosFvgStrategy",
    "TrendContinuationStrategy",
    "SessionBreakoutStrategy",
    "RangeReversalStrategy",
    "build_default_registry",
]
