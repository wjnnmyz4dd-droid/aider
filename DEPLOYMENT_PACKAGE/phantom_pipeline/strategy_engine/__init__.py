"""Strategy Engine package (ADR-003) — Phase 1.

Consumes only `ScannerObservation` (ADR-002); never connects to the Data
Pipeline or MT5 directly; never scores, sizes, approves, rejects,
executes, or manages positions; never resolves conflicts between
`CandidateTrade`s. Produces only `CandidateTrade` (ADR-003 §2, §3, §6, §9).
"""

from __future__ import annotations

from .config import DEFAULT_CONFIG, STRATEGY_ENGINE_VERSION, StrategyEngineConfig
from .engine import StrategyEngine
from .metrics import StrategyEngineMetrics
from .models import (
    SCHEMA_VERSION,
    CandidateTrade,
    Evidence,
    SupportingObservation,
    make_candidate_id,
)
from .playbook import HealthStatus, Playbook, PlaybookMetadata
from .registry import DuplicateStrategyIdError, StrategyRegistry, discover_playbook_classes

__all__ = [
    "DEFAULT_CONFIG",
    "STRATEGY_ENGINE_VERSION",
    "StrategyEngineConfig",
    "StrategyEngine",
    "StrategyEngineMetrics",
    "SCHEMA_VERSION",
    "CandidateTrade",
    "Evidence",
    "SupportingObservation",
    "make_candidate_id",
    "HealthStatus",
    "Playbook",
    "PlaybookMetadata",
    "DuplicateStrategyIdError",
    "StrategyRegistry",
    "discover_playbook_classes",
]
