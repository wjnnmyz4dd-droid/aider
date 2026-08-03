"""Market Intelligence Engine (Phase 2B).

The only authority responsible for evaluating external market
conditions. It never decides buy/sell, position size, risk, strategy
selection, trade execution, or FTMO approval -- it determines whether
market conditions are safe and suitable for evaluation. See
`docs/adr/ADR-025-market-intelligence-engine.md`.
"""

from __future__ import annotations

from .config import MARKET_INTELLIGENCE_ENGINE_VERSION, MarketIntelligenceConfig
from .engine import MarketIntelligenceEngine
from .explainability import build_explanation
from .liquidity_intelligence import evaluate_liquidity
from .logging_sink import log_market_intelligence_snapshot
from .market_safety import evaluate_market_safety
from .metrics import MarketIntelligenceMetrics
from .models import (
    SCHEMA_VERSION,
    CENTRAL_BANK_CATEGORIES,
    LiquidityIntelligence,
    MarketIntelligenceExplanation,
    MarketIntelligenceSnapshot,
    MarketSafetyInputs,
    MarketSafetyStatus,
    NewsCategory,
    NewsEvent,
    NewsImpact,
    PairNewsIntelligence,
    PairSafety,
    PegPolicyEventType,
    PegPolicyStatus,
    SessionIntelligence,
    TradeReadiness,
)
from .news import build_pair_news_intelligence, bucket_events, compute_blackout, compute_news_score, pair_currencies
from .peg_policy import PegPolicyRegistry
from .scoring import build_pair_safety, build_trade_readiness
from .session_intelligence import evaluate_session

__all__ = [
    "MARKET_INTELLIGENCE_ENGINE_VERSION",
    "SCHEMA_VERSION",
    "MarketIntelligenceConfig",
    "MarketIntelligenceEngine",
    "MarketIntelligenceMetrics",
    "CENTRAL_BANK_CATEGORIES",
    "NewsImpact",
    "NewsCategory",
    "NewsEvent",
    "PairNewsIntelligence",
    "PegPolicyEventType",
    "PegPolicyStatus",
    "PegPolicyRegistry",
    "SessionIntelligence",
    "LiquidityIntelligence",
    "MarketSafetyInputs",
    "MarketSafetyStatus",
    "PairSafety",
    "TradeReadiness",
    "MarketIntelligenceExplanation",
    "MarketIntelligenceSnapshot",
    "pair_currencies",
    "bucket_events",
    "compute_blackout",
    "compute_news_score",
    "build_pair_news_intelligence",
    "evaluate_session",
    "evaluate_liquidity",
    "evaluate_market_safety",
    "build_pair_safety",
    "build_trade_readiness",
    "build_explanation",
    "log_market_intelligence_snapshot",
]
