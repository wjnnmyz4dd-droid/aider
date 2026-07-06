"""Analytics package (ADR-010) — Phase 1.

Phantom's permanent institutional memory: collects immutable, read-only
copies of every object every prior stage produces, keyed by `trace_id`,
and builds `TradeProvenanceRecord`s, performance statistics, replay
input sets, and missing-event reports. Read-only — never changes a live
trading decision, never holds order-placement or position-management
capability (ADR-010 §1, §3, §11).
"""

from __future__ import annotations

from .config import ANALYTICS_VERSION, DEFAULT_CONFIG, AnalyticsConfig
from .engine import AnalyticsEngine
from .metrics import AnalyticsMetrics
from .models import (
    SCHEMA_VERSION,
    BrokerEvent,
    FinalOutcome,
    MissingEventReport,
    OutcomeKind,
    PerformanceStatistics,
    ReplayInputSet,
    TradeProvenanceRecord,
)
from .store import InMemoryTradeProvenanceStore, TradeProvenanceStore

__all__ = [
    "ANALYTICS_VERSION",
    "DEFAULT_CONFIG",
    "AnalyticsConfig",
    "AnalyticsEngine",
    "AnalyticsMetrics",
    "SCHEMA_VERSION",
    "BrokerEvent",
    "FinalOutcome",
    "MissingEventReport",
    "OutcomeKind",
    "PerformanceStatistics",
    "ReplayInputSet",
    "TradeProvenanceRecord",
    "InMemoryTradeProvenanceStore",
    "TradeProvenanceStore",
]
