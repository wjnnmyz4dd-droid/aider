"""Session Edge — multi-agent intelligence layer (Phase 4A: design + foundation).

ADVISORY ONLY. No agent or service in this package can place a trade, alter an
order, write a bridge instruction, reach the network, or override a deterministic
gate. The deterministic Session Edge strategy, the filesystem bridge, and the MT5
adapter remain outside this package and authoritative.

Single sources of truth (no duplication):
  * serialization / hashing  -> forex_swing_orb.bridge.serialize
  * audit contract           -> forex_swing_orb.bridge.audit.AuditLog
  * memory                   -> agents.memory.MemoryStore (one store)
  * model provider           -> agents.llm.LLMProvider (one abstraction)
  * explainability           -> agents.explain.ExplainabilityService (one)
  * decision policy          -> agents.coordinator.DecisionCoordinator (one)
"""

from __future__ import annotations

from .contract import (SCHEMA_VERSION, Assessment, Advisory, StrategyCandidate,
                       ReasonCode, LiquidityRating, NewsRating,
                       build_request, build_result, validate_request,
                       validate_result, confidence_band)
from .base import Agent
from .llm import LLMProvider, MockLLMProvider
from .memory import MemoryStore
from .explain import ExplainabilityService
from .coordinator import DecisionCoordinator
from .orchestrator import Orchestrator, ORCHESTRATION_ORDER
from .shadow import ShadowRunner, ShadowAnalytics, shadow_metrics

__all__ = [
    "SCHEMA_VERSION", "Assessment", "Advisory", "StrategyCandidate", "ReasonCode",
    "LiquidityRating", "NewsRating", "build_request", "build_result",
    "validate_request", "validate_result", "confidence_band", "Agent",
    "LLMProvider", "MockLLMProvider", "MemoryStore", "ExplainabilityService",
    "DecisionCoordinator", "Orchestrator", "ORCHESTRATION_ORDER",
    "ShadowRunner", "ShadowAnalytics", "shadow_metrics",
]
