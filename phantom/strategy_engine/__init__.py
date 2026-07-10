"""Strategy Engine (Phase 2C).

The only authority responsible for determining which trading strategy,
if any, best fits current market conditions. It never decides position
size, risk, FTMO compliance, trade execution, or news approval -- it
selects a winning strategy (or rejects the setup) and explains why. See
`docs/adr/ADR-026-strategy-engine.md`.
"""

from __future__ import annotations

from .config import STRATEGY_ENGINE_VERSION, DEFAULT_APPROVED_PAIRS_BY_STRATEGY, StrategyEngineConfig
from .eligibility import check_eligibility
from .engine import StrategyEngine
from .explainability import build_strategy_snapshot
from .logging_sink import log_strategy_snapshot
from .metrics import StrategyEngineMetrics
from .models import (
    SCHEMA_VERSION,
    MarketRegime,
    QualificationResult,
    QualificationStatus,
    StrategyDefinition,
    StrategyId,
    StrategySnapshot,
    WinningStrategy,
)
from .selection import select_winning_strategy
from .strategies import (
    BosFvgStrategy,
    DuplicateStrategyError,
    LiquiditySweepMssStrategy,
    RangeReversalStrategy,
    SessionBreakoutStrategy,
    Strategy,
    StrategyRegistry,
    TrendContinuationStrategy,
    build_default_registry,
)

__all__ = [
    "STRATEGY_ENGINE_VERSION",
    "SCHEMA_VERSION",
    "DEFAULT_APPROVED_PAIRS_BY_STRATEGY",
    "StrategyEngineConfig",
    "StrategyEngine",
    "StrategyEngineMetrics",
    "StrategyId",
    "MarketRegime",
    "QualificationStatus",
    "QualificationResult",
    "StrategyDefinition",
    "WinningStrategy",
    "StrategySnapshot",
    "check_eligibility",
    "select_winning_strategy",
    "build_strategy_snapshot",
    "log_strategy_snapshot",
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
