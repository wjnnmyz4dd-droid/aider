"""The 5 concrete strategies (ADR-026 §1) plus the shared `Strategy`
interface and explicit registry."""

from __future__ import annotations

from typing import Optional

from titan_protocol.strategy_state_store import OrbQualificationStore

from .base import Strategy
from .bos_fvg import BosFvgStrategy
from .liquidity_sweep_mss import LiquiditySweepMssStrategy
from .orb_breakout import OrbBreakoutStrategy
from .range_reversal import RangeReversalStrategy
from .registry import DuplicateStrategyError, StrategyRegistry
from .session_breakout import SessionBreakoutStrategy
from .trend_continuation import TrendContinuationStrategy


def build_default_registry(orb_qualification_store: Optional[OrbQualificationStore] = None) -> StrategyRegistry:
    """The canonical registry: the 5 legacy strategies, always; plus
    Opening Range Breakout when a qualification-lockout store is
    supplied (ADR-035 Phase 6) -- omitted by default so every existing
    zero-argument caller is unaffected."""
    registry = StrategyRegistry()
    registry.register(LiquiditySweepMssStrategy())
    registry.register(BosFvgStrategy())
    registry.register(TrendContinuationStrategy())
    registry.register(SessionBreakoutStrategy())
    registry.register(RangeReversalStrategy())
    if orb_qualification_store is not None:
        registry.register(OrbBreakoutStrategy(orb_qualification_store))
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
    "OrbBreakoutStrategy",
    "build_default_registry",
]
