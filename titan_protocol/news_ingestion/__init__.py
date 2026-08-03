"""News Provider Failover (Phase 3E, ADR-033 Part 2) -- owns Trading
Economics/Forex Factory API communication, authentication, response
parsing, schema conversion, provider health tracking, and the
failover/recovery state machine for the frozen, unmodified Market
Intelligence Engine. Owns no event interpretation, blackout window,
currency filtering, impact classification, session awareness, or trade
gating -- Market Intelligence Engine remains the sole authority for
all of that and never knows which provider is active."""

from __future__ import annotations

from .adapter import to_market_intelligence_event
from .config import NEWS_INGESTION_VERSION, NewsIngestionConfig
from .engine import NewsIngestionEngine
from .failover import NewsFailoverEngine
from .metrics import NewsIngestionMetrics
from .models import (
    SCHEMA_VERSION,
    FailoverState,
    NewsEventStatus,
    NewsFeedHealthSnapshot,
    NewsProviderError,
    NormalizedNewsEvent,
    ProviderAuthenticationFailed,
    ProviderHealth,
    ProviderName,
    ProviderRateLimited,
    ProviderSchemaError,
    ProviderTimeout,
    ProviderUnavailable,
    TrustState,
)
from .providers.base import NewsProvider
from .providers.forex_factory import ForexFactoryProvider
from .providers.trading_economics import TradingEconomicsProvider

__all__ = [
    "SCHEMA_VERSION",
    "NEWS_INGESTION_VERSION",
    "ProviderName",
    "TrustState",
    "NewsEventStatus",
    "NewsProviderError",
    "ProviderUnavailable",
    "ProviderTimeout",
    "ProviderRateLimited",
    "ProviderAuthenticationFailed",
    "ProviderSchemaError",
    "NormalizedNewsEvent",
    "ProviderHealth",
    "FailoverState",
    "NewsFeedHealthSnapshot",
    "NewsIngestionConfig",
    "NewsFailoverEngine",
    "NewsIngestionEngine",
    "NewsIngestionMetrics",
    "NewsProvider",
    "TradingEconomicsProvider",
    "ForexFactoryProvider",
    "to_market_intelligence_event",
]
