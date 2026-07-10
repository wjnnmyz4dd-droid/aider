"""Explicit strategy registration -- no auto-discovery, no dynamic
import scanning. Duplicate registration by `StrategyId` is rejected."""

from __future__ import annotations

from typing import Dict, Tuple

from ..models import StrategyId
from .base import Strategy


class DuplicateStrategyError(ValueError):
    pass


class StrategyRegistry:
    def __init__(self) -> None:
        self._strategies: Dict[StrategyId, Strategy] = {}

    def register(self, strategy: Strategy) -> None:
        strategy_id = strategy.definition.strategy_id
        if strategy_id in self._strategies:
            raise DuplicateStrategyError(f"Strategy '{strategy_id.value}' is already registered")
        self._strategies[strategy_id] = strategy

    def get(self, strategy_id: StrategyId) -> Strategy:
        return self._strategies[strategy_id]

    def all(self) -> Tuple[Strategy, ...]:
        return tuple(self._strategies[sid] for sid in sorted(self._strategies, key=lambda s: s.value))

    def __contains__(self, strategy_id: StrategyId) -> bool:
        return strategy_id in self._strategies

    def __len__(self) -> int:
        return len(self._strategies)


__all__ = ["DuplicateStrategyError", "StrategyRegistry"]
