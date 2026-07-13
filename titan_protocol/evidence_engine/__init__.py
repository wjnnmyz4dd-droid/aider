"""Evidence Engine (Phase 2A).

The only authority responsible for determining market quality. It never
decides buy/sell, position size, risk, news approval, or compliance
approval -- it measures evidence and produces a deterministic,
explainable score per pair. See
`docs/adr/ADR-024-evidence-engine.md`.
"""

from __future__ import annotations

from .candlesticks import recognize_patterns
from .config import EVIDENCE_ENGINE_VERSION, EvidenceEngineConfig
from .engine import EvidenceEngine
from .explainability import build_evidence_report
from .indicators import (
    RESERVED_FUTURE_INDICATOR_NAMES,
    DuplicateIndicatorError,
    Indicator,
    IndicatorCache,
    IndicatorRegistry,
)
from .liquidity import analyze_liquidity, build_liquidity_pools, detect_displacement, detect_liquidity_sweeps, find_equal_levels
from .logging_sink import log_evidence_report
from .metrics import EvidenceEngineMetrics
from .models import (
    SCHEMA_VERSION,
    Bar,
    CandlestickMatch,
    CandlestickPattern,
    ComponentScore,
    ConfluenceZone,
    EqualLevel,
    EvidenceReport,
    EvidenceScore,
    EvidenceSnapshot,
    FairValueGap,
    IndicatorResult,
    LiquidityPool,
    LiquidityResult,
    LiquiditySweep,
    MarketStructureResult,
    PairRanking,
    PatternContext,
    PriceLevel,
    PsychologicalLevel,
    SessionName,
    SessionState,
    StructureDirection,
    StructureEvent,
    StructureEventType,
    SupportResistanceContext,
    SwingPoint,
    SwingType,
    TrendClassification,
    VolatilityState,
)
from .ranking import rank_pairs
from .scoring import compute_component_scores, compute_evidence_score
from .session import analyze_session, session_for_hour
from .structure import (
    analyze_market_structure,
    detect_fair_value_gaps,
    detect_structure_events,
    find_swing_points,
    support_resistance,
)
from .support_resistance import build_support_resistance_context
from .trend import classify_trend
from .volatility import analyze_volatility, atr, atr_series, true_ranges

__all__ = [
    "EVIDENCE_ENGINE_VERSION",
    "SCHEMA_VERSION",
    "EvidenceEngineConfig",
    "EvidenceEngine",
    "EvidenceEngineMetrics",
    "Bar",
    "SwingType",
    "SwingPoint",
    "StructureEventType",
    "StructureDirection",
    "StructureEvent",
    "TrendClassification",
    "PriceLevel",
    "MarketStructureResult",
    "EqualLevel",
    "LiquidityPool",
    "LiquiditySweep",
    "LiquidityResult",
    "CandlestickPattern",
    "PatternContext",
    "CandlestickMatch",
    "VolatilityState",
    "SessionName",
    "SessionState",
    "IndicatorResult",
    "ComponentScore",
    "EvidenceScore",
    "EvidenceReport",
    "PairRanking",
    "PsychologicalLevel",
    "ConfluenceZone",
    "SupportResistanceContext",
    "FairValueGap",
    "EvidenceSnapshot",
    "build_support_resistance_context",
    "detect_fair_value_gaps",
    "RESERVED_FUTURE_INDICATOR_NAMES",
    "Indicator",
    "DuplicateIndicatorError",
    "IndicatorRegistry",
    "IndicatorCache",
    "find_swing_points",
    "detect_structure_events",
    "support_resistance",
    "analyze_market_structure",
    "find_equal_levels",
    "build_liquidity_pools",
    "detect_displacement",
    "detect_liquidity_sweeps",
    "analyze_liquidity",
    "recognize_patterns",
    "classify_trend",
    "true_ranges",
    "atr_series",
    "atr",
    "analyze_volatility",
    "session_for_hour",
    "analyze_session",
    "compute_component_scores",
    "compute_evidence_score",
    "rank_pairs",
    "build_evidence_report",
    "log_evidence_report",
]
