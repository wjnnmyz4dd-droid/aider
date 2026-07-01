"""Institutional-style signal strategies.

Every strategy is a *signal contributor only* — it returns a score influence,
never an order. The :class:`~phantom.strategies.engine.StrategyEngine`
consolidates them with conflict resolution and a hard anti-inflation cap before
the scorer folds the result in.
"""

from .base import Strategy, StrategyContext, StrategySignal
from .engine import StrategyEngine, StrategyOutcome

__all__ = [
    "Strategy",
    "StrategyContext",
    "StrategySignal",
    "StrategyEngine",
    "StrategyOutcome",
]
