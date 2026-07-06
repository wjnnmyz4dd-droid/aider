"""Scoring Engine package (ADR-004) — Phase 1.

Consumes only `CandidateTrade` (ADR-003); never connects to the Data
Pipeline, Scanner, or MT5 directly; never modifies or discards a
candidate; never approves, rejects, sizes, executes, or manages
positions; never performs compliance. Produces only `ScoreResult` (or a
deterministic `ScoringFailureRecord`) — one per `CandidateTrade`, always
(ADR-004 §2, §3, §6, §7).
"""

from __future__ import annotations

from .config import DEFAULT_CONFIG, SCORING_ENGINE_VERSION, ScoringEngineConfig
from .engine import SUPPORTED_CANDIDATE_SCHEMA_VERSIONS, ScoringEngine
from .metrics import ScoringEngineMetrics
from .models import (
    SCHEMA_VERSION,
    FactorBreakdown,
    RuleContribution,
    RuleOutcome,
    ScoreResult,
    ScoringEvidence,
    ScoringFailureRecord,
)
from .ranking import rank_scores
from .registry import DuplicateRuleIdError, ScoringRuleRegistry, discover_rule_classes
from .rule import ScoringRule, ScoringRuleMetadata

__all__ = [
    "DEFAULT_CONFIG",
    "SCORING_ENGINE_VERSION",
    "ScoringEngineConfig",
    "SUPPORTED_CANDIDATE_SCHEMA_VERSIONS",
    "ScoringEngine",
    "ScoringEngineMetrics",
    "SCHEMA_VERSION",
    "FactorBreakdown",
    "RuleContribution",
    "RuleOutcome",
    "ScoreResult",
    "ScoringEvidence",
    "ScoringFailureRecord",
    "rank_scores",
    "DuplicateRuleIdError",
    "ScoringRuleRegistry",
    "discover_rule_classes",
    "ScoringRule",
    "ScoringRuleMetadata",
]
