"""Data models for the Validation Engine (Phase 2G, ADR-030).

Every scenario-level input here bundles the six engines' *already-
produced* frozen snapshot types (`EvidenceSnapshot`, `MarketIntelligenceSnapshot`,
`StrategySnapshot`, `RiskSnapshot`, `ComplianceSnapshot`) plus
`research_engine`'s `ClosedTrade`/`ClosedTradeHistory`/`ResearchSnapshot` --
never a raw bar or a recomputation of any of them (ADR-030 Hard Rule 4,
§3). Nothing here can hold a trade instruction, a parameter mutation, or
a config change: there is no `BUY`/`SELL` enum, no lot size, no applied
config anywhere in this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, Tuple

from titan_protocol.compliance_engine.models import ComplianceSnapshot
from titan_protocol.evidence_engine.models import EvidenceSnapshot
from titan_protocol.market_intelligence.models import MarketIntelligenceSnapshot
from titan_protocol.research_engine.models import ClosedTradeHistory, StatisticalMetrics
from titan_protocol.risk_engine.models import RiskSnapshot
from titan_protocol.strategy_engine.models import StrategySnapshot

SCHEMA_VERSION = 1


# -- Stress tagging -----------------------------------------------------------


class StressScenarioTag(Enum):
    HIGH_SPREAD = "HIGH_SPREAD"
    LOW_LIQUIDITY = "LOW_LIQUIDITY"
    GAP_OPEN = "GAP_OPEN"
    FLASH_CRASH = "FLASH_CRASH"
    COVID = "COVID"
    BREXIT = "BREXIT"
    CENTRAL_BANK_INTERVENTION = "CENTRAL_BANK_INTERVENTION"
    NFP = "NFP"
    FOMC = "FOMC"
    HOLIDAY_TRADING = "HOLIDAY_TRADING"
    WEEKEND_GAP = "WEEKEND_GAP"


class ConfigurationProfile(Enum):
    CONSERVATIVE = "CONSERVATIVE"
    BALANCED = "BALANCED"
    AGGRESSIVE = "AGGRESSIVE"
    LONDON_FOCUS = "LONDON_FOCUS"
    NEW_YORK_FOCUS = "NEW_YORK_FOCUS"
    TREND_FOCUS = "TREND_FOCUS"
    RANGE_FOCUS = "RANGE_FOCUS"
    CUSTOM = "CUSTOM"


class StageName(Enum):
    EVIDENCE = "EVIDENCE"
    MARKET_INTELLIGENCE = "MARKET_INTELLIGENCE"
    STRATEGY = "STRATEGY"
    RISK = "RISK"
    COMPLIANCE = "COMPLIANCE"
    BRIDGE = "BRIDGE"
    RESEARCH = "RESEARCH"


# -- Execution (recorded, never invoked -- ADR-030 Hard Rule 1) --------------


@dataclass(frozen=True)
class BridgeExecutionRecord:
    """Already-happened fill/rejection facts for one scenario's order.
    Recorded, read-only -- this package never talks to MT5 and never
    holds broker credentials."""

    pair: str
    was_executed: bool
    approved_size_r: float  # what Compliance Engine approved (0.0 if rejected)
    executed_size_r: float = 0.0
    requested_entry_price: Optional[float] = None
    actual_fill_price: Optional[float] = None
    slippage_pips: float = 0.0
    rejected_by_bridge: bool = False
    rejection_reason: Optional[str] = None
    notes: str = ""


# -- Scenario / run (the caller-supplied input, ADR-030 §4) ------------------


@dataclass(frozen=True)
class HistoricalScenario:
    """One pair/timestamp instance's recorded, already-produced snapshot
    from each of the five engines -- never derived from raw bars by this
    package (ADR-030 §3)."""

    scenario_id: str
    pair: str
    now: datetime
    evidence: EvidenceSnapshot
    market_intelligence: MarketIntelligenceSnapshot
    strategy: StrategySnapshot
    risk: RiskSnapshot
    compliance: ComplianceSnapshot
    execution: Optional[BridgeExecutionRecord] = None
    stress_tag: Optional[StressScenarioTag] = None


@dataclass(frozen=True)
class HistoricalRun:
    """An ordered set of recorded scenarios, plus an optional
    already-produced `ResearchSnapshot` (for the Research leg of
    Explainability Validation, ADR-030 §5.3)."""

    name: str
    scenarios: Tuple[HistoricalScenario, ...]
    research_snapshot: Optional[object] = None  # research_engine.models.ResearchSnapshot


@dataclass(frozen=True)
class ConfigurationRun:
    """One candidate configuration's already-recorded trade history, for
    the Configuration Tournament / Shadow Trading (ADR-030 §5.5-5.6)."""

    profile: ConfigurationProfile
    trades: ClosedTradeHistory


# -- Replay / verification (ADR-030 §5.1) ------------------------------------


@dataclass(frozen=True)
class OutputVerification:
    stage: StageName
    passed: bool
    checks: Tuple[str, ...]
    failures: Tuple[str, ...]


@dataclass(frozen=True)
class ScenarioVerification:
    scenario_id: str
    pair: str
    stage_verifications: Tuple[OutputVerification, ...]
    passed: bool


# -- Determinism (ADR-030 §5.2) ----------------------------------------------


@dataclass(frozen=True)
class DeterminismCheck:
    scenario_id: str
    runs: int
    all_identical: bool
    mismatches: Tuple[str, ...]


@dataclass(frozen=True)
class DeterminismReport:
    checks: Tuple[DeterminismCheck, ...]
    all_deterministic: bool


# -- Explainability (ADR-030 §5.3) -------------------------------------------


@dataclass(frozen=True)
class ExplainabilityCheck:
    stage: StageName
    has_explanation: bool
    detail: str


@dataclass(frozen=True)
class ExplainabilityReport:
    checks: Tuple[ExplainabilityCheck, ...]
    all_explained: bool


# -- Tournaments (ADR-030 §5.4-5.5) ------------------------------------------


@dataclass(frozen=True)
class TournamentEntry:
    """Shared shape for strategy/pair/session/configuration tournament
    rows -- one type, several thin builders (CLAUDE.md §6)."""

    subject: str
    rank: int  # 1 = best
    sample_size: int
    statistics: StatisticalMetrics
    recovery_factor: Optional[float]


@dataclass(frozen=True)
class ConfigurationTournamentResult:
    entries: Tuple[TournamentEntry, ...]
    recommendations: Tuple[str, ...]


@dataclass(frozen=True)
class ShadowComparisonResult:
    production: TournamentEntry
    candidate: TournamentEntry
    expectancy_delta: Optional[float]
    notable: bool
    recommendation: str


# -- Stress testing (ADR-030 §5.7) -------------------------------------------


@dataclass(frozen=True)
class StressTestResult:
    scenario_id: str
    tag: StressScenarioTag
    survived: bool
    error: Optional[str]
    correctly_restricted: bool
    detail: str


# -- Walk-forward (ADR-030 §5.8) ---------------------------------------------


@dataclass(frozen=True)
class WalkForwardResult:
    train_statistics: StatisticalMetrics
    validation_statistics: StatisticalMetrics
    out_of_sample_statistics: StatisticalMetrics
    train_sample_size: int
    validation_sample_size: int
    out_of_sample_sample_size: int
    degradation_detected: bool
    degradation_detail: str


# -- Monte Carlo validation (ADR-030 §5.9) -----------------------------------


@dataclass(frozen=True)
class MonteCarloValidationResult:
    sample_size: int
    simulations_run: int
    expected_drawdown: Optional[float]
    worst_case_drawdown: Optional[float]
    risk_of_ruin: Optional[float]
    confidence_note: str


# -- Drift detection (ADR-030 §5.10) -----------------------------------------


@dataclass(frozen=True)
class DriftFinding:
    dimension: str
    subject: str
    baseline_sample_size: int
    current_sample_size: int
    baseline_expectancy: Optional[float]
    current_expectancy: Optional[float]
    delta: Optional[float]
    degraded: bool


@dataclass(frozen=True)
class DriftAnalysis:
    findings: Tuple[DriftFinding, ...]
    execution_quality_delta: Optional[float]
    any_degradation_detected: bool


# -- Confidence calibration (ADR-030 §5.11) ----------------------------------


@dataclass(frozen=True)
class ConfidenceTierStatistics:
    tier: str
    sample_size: int
    statistics: StatisticalMetrics


@dataclass(frozen=True)
class ConfidenceCalibrationResult:
    tier_statistics: Tuple[ConfidenceTierStatistics, ...]
    well_calibrated: bool
    notes: Tuple[str, ...]


# -- Execution validation (ADR-030 §5.12) ------------------------------------


@dataclass(frozen=True)
class ExecutionValidationResult:
    records_checked: int
    violations: Tuple[str, ...]
    passed: bool


# -- Output (ADR-030 §6) ------------------------------------------------------


@dataclass(frozen=True)
class ValidationSnapshot:
    """No trade instruction, no parameter mutation, no config change --
    ever (ADR-030 Hard Rules 1-2)."""

    generated_at: datetime
    passed: bool
    warnings: Tuple[str, ...]
    recommendations: Tuple[str, ...]

    replay_verifications: Tuple[ScenarioVerification, ...]
    determinism_report: DeterminismReport
    explainability_report: ExplainabilityReport

    strategy_tournament: Tuple[TournamentEntry, ...]
    pair_tournament: Tuple[TournamentEntry, ...]
    session_tournament: Tuple[TournamentEntry, ...]
    configuration_tournament: ConfigurationTournamentResult
    shadow_comparison: Optional[ShadowComparisonResult]

    stress_test_results: Tuple[StressTestResult, ...]
    walk_forward_result: Optional[WalkForwardResult]
    monte_carlo_validation: Optional[MonteCarloValidationResult]
    drift_analysis: DriftAnalysis
    confidence_calibration: ConfidenceCalibrationResult
    execution_validation: ExecutionValidationResult


__all__ = [
    "SCHEMA_VERSION",
    "StressScenarioTag",
    "ConfigurationProfile",
    "StageName",
    "BridgeExecutionRecord",
    "HistoricalScenario",
    "HistoricalRun",
    "ConfigurationRun",
    "OutputVerification",
    "ScenarioVerification",
    "DeterminismCheck",
    "DeterminismReport",
    "ExplainabilityCheck",
    "ExplainabilityReport",
    "TournamentEntry",
    "ConfigurationTournamentResult",
    "ShadowComparisonResult",
    "StressTestResult",
    "WalkForwardResult",
    "MonteCarloValidationResult",
    "DriftFinding",
    "DriftAnalysis",
    "ConfidenceTierStatistics",
    "ConfidenceCalibrationResult",
    "ExecutionValidationResult",
    "ValidationSnapshot",
]
