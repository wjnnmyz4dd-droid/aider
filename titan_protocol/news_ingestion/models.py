"""Data models for the News Provider Failover layer (Phase 3E, ADR-033
Part 2). Every type here describes a raw provider fact, a normalized
event, or a health/failover result derived from one -- nothing here is
a trade, blackout, or scoring decision. See `adapter.py` for the
one-way conversion to `titan_protocol.market_intelligence.models.NewsEvent`,
the exact, unmodified type Market Intelligence Engine already accepts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, Tuple

SCHEMA_VERSION = 1


class ProviderName(Enum):
    TRADING_ECONOMICS = "TRADING_ECONOMICS"
    FOREX_FACTORY = "FOREX_FACTORY"


class TrustState(Enum):
    TRUSTED = "TRUSTED"
    UNTRUSTED = "UNTRUSTED"


class NewsEventStatus(Enum):
    SCHEDULED = "SCHEDULED"
    RELEASED = "RELEASED"
    REVISED = "REVISED"


class NewsProviderError(Exception):
    """Base for every classified provider failure. The failover engine's
    routing decision depends on knowing *why* a provider failed, so a
    provider must never raise a bare, unclassified exception -- always
    one of the five subclasses below."""


class ProviderUnavailable(NewsProviderError):
    pass


class ProviderTimeout(NewsProviderError):
    pass


class ProviderRateLimited(NewsProviderError):
    pass


class ProviderAuthenticationFailed(NewsProviderError):
    pass


class ProviderSchemaError(NewsProviderError):
    pass


@dataclass(frozen=True)
class NormalizedNewsEvent:
    """Every provider must output exactly this structure -- the mission's
    own named field list, verbatim. `provider`/`provider_timestamp`
    identify which adapter produced this event and when it fetched it;
    `source` is the provider's own free-text attribution string (e.g.
    a calendar/desk name), independent of which of our two adapters
    fetched it."""

    event_id: str
    currency: str
    country: str
    event_name: str
    category: str
    impact: str
    scheduled_time: datetime
    actual: Optional[float]
    forecast: Optional[float]
    previous: Optional[float]
    revision: Optional[float]
    source: str
    provider: ProviderName
    provider_timestamp: datetime
    ingestion_timestamp: datetime
    freshness: float  # seconds between provider_timestamp and ingestion_timestamp
    confidence: float  # 0.0-1.0, schema-conversion confidence
    status: NewsEventStatus


@dataclass(frozen=True)
class ProviderHealth:
    provider: ProviderName
    trust_state: TrustState
    last_success_at: Optional[datetime]
    latency_ms: Optional[float]
    timeout_count: int
    parse_failure_count: int
    consecutive_successes: int
    stale_age_seconds: Optional[float]
    last_error: Optional[str]


@dataclass(frozen=True)
class FailoverState:
    active_provider: ProviderName
    failover_count: int
    recovery_count: int
    last_failover_at: Optional[datetime]
    last_recovery_at: Optional[datetime]


@dataclass(frozen=True)
class NewsFeedHealthSnapshot:
    generated_at: datetime
    active_provider: ProviderName
    trusted: bool
    provider_health: Tuple[ProviderHealth, ...]
    failover_state: FailoverState


__all__ = [
    "SCHEMA_VERSION",
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
]
