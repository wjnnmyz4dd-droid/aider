"""Research & Learning Engine (Phase 2F).

The only authority responsible for measuring, analyzing, and
recommending improvements based on historical system performance. It
never places trades, rejects trades, sizes positions, changes
strategies, changes parameters, modifies live behavior, or
communicates with MT5 -- it is completely advisory. See
`docs/adr/ADR-029-research-learning-engine.md`.
"""

from __future__ import annotations

from .attribution import DIMENSION_KEY_FUNCS, attribute_all_dimensions, attribute_by, compute_bucket_statistics
from .config import RESEARCH_ENGINE_VERSION, ResearchEngineConfig
from .effectiveness import bucket_by_score_tertiles, compare_buckets
from .engine import ResearchEngine
from .execution_quality import compute_execution_quality_record, summarize_execution_quality
from .explainability import build_research_snapshot
from .logging_sink import log_research_snapshot
from .metrics import ResearchEngineMetrics
from .models import (
    SCHEMA_VERSION,
    AttributionBucket,
    AttributionDimension,
    ClosedTrade,
    ClosedTradeHistory,
    ComplianceEffectiveness,
    EffectivenessComparison,
    ExecutionQualityRecord,
    ExecutionQualitySummary,
    MarketIntelligenceReview,
    PerformanceAttribution,
    Ranking,
    Recommendation,
    ReportPeriod,
    ResearchSnapshot,
    RiskReview,
    SRInteraction,
    TrendVsRange,
    VolatilityBucket,
    executed_trades,
)
from .pair_intelligence import rank_pairs
from .recommendations import cross_dimension_recommendations, recommendations_from_attribution
from .reporting import filter_trades_by_period, period_bounds
from .reviews import review_compliance, review_market_intelligence, review_risk
from .session_intelligence import rank_sessions
from .strategy_intelligence import rank_strategies

__all__ = [
    "RESEARCH_ENGINE_VERSION",
    "SCHEMA_VERSION",
    "ResearchEngineConfig",
    "ResearchEngine",
    "ResearchEngineMetrics",
    "SRInteraction",
    "VolatilityBucket",
    "TrendVsRange",
    "ClosedTrade",
    "ClosedTradeHistory",
    "executed_trades",
    "AttributionDimension",
    "AttributionBucket",
    "PerformanceAttribution",
    "Ranking",
    "ExecutionQualityRecord",
    "ExecutionQualitySummary",
    "EffectivenessComparison",
    "MarketIntelligenceReview",
    "RiskReview",
    "ComplianceEffectiveness",
    "Recommendation",
    "ReportPeriod",
    "ResearchSnapshot",
    "attribute_by",
    "attribute_all_dimensions",
    "compute_bucket_statistics",
    "DIMENSION_KEY_FUNCS",
    "rank_pairs",
    "rank_strategies",
    "rank_sessions",
    "compute_execution_quality_record",
    "summarize_execution_quality",
    "compare_buckets",
    "bucket_by_score_tertiles",
    "review_market_intelligence",
    "review_risk",
    "review_compliance",
    "recommendations_from_attribution",
    "cross_dimension_recommendations",
    "period_bounds",
    "filter_trades_by_period",
    "build_research_snapshot",
    "log_research_snapshot",
]
