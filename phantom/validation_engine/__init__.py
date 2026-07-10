"""Validation Engine (Phase 2G).

Phantom's independent verification authority for the six engines built
this session (Evidence, Market Intelligence, Strategy, Risk,
Compliance, Research & Learning). It never trades, sizes positions,
changes parameters, optimizes live systems, changes configurations, or
executes orders -- it only validates. See
`docs/adr/ADR-030-validation-engine.md`.
"""

from __future__ import annotations

from .audit import build_independent_audit_report
from .config import VALIDATION_ENGINE_VERSION, ValidationEngineConfig
from .confidence_calibration import run_confidence_calibration
from .configuration_tournament import run_configuration_tournament
from .determinism import check_determinism, check_determinism_for_run
from .drift_detection import detect_drift
from .engine import ValidationEngine
from .execution_validation import validate_execution
from .explainability import build_explainability_report
from .logging_sink import log_validation_snapshot
from .metrics import ValidationEngineMetrics
from .models import (
    SCHEMA_VERSION,
    BridgeExecutionRecord,
    ConfidenceCalibrationResult,
    ConfidenceTierStatistics,
    ConfigurationProfile,
    ConfigurationRun,
    ConfigurationTournamentResult,
    DeterminismCheck,
    DeterminismReport,
    DriftAnalysis,
    DriftFinding,
    ExecutionValidationResult,
    ExplainabilityCheck,
    ExplainabilityReport,
    HistoricalRun,
    HistoricalScenario,
    MonteCarloValidationResult,
    OutputVerification,
    ScenarioVerification,
    ShadowComparisonResult,
    StageName,
    StressScenarioTag,
    StressTestResult,
    TournamentEntry,
    ValidationSnapshot,
    WalkForwardResult,
)
from .monte_carlo_validation import run_monte_carlo_validation
from .replay import verify_run, verify_scenario
from .shadow_trading import run_shadow_comparison
from .stress_testing import run_stress_test, run_stress_tests
from .tournament import run_pair_tournament, run_session_tournament, run_strategy_tournament
from .walk_forward import run_walk_forward

__all__ = [
    "VALIDATION_ENGINE_VERSION",
    "SCHEMA_VERSION",
    "ValidationEngineConfig",
    "ValidationEngine",
    "ValidationEngineMetrics",
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
    "verify_scenario",
    "verify_run",
    "check_determinism",
    "check_determinism_for_run",
    "build_explainability_report",
    "run_strategy_tournament",
    "run_pair_tournament",
    "run_session_tournament",
    "run_configuration_tournament",
    "run_shadow_comparison",
    "run_stress_test",
    "run_stress_tests",
    "run_walk_forward",
    "run_monte_carlo_validation",
    "detect_drift",
    "run_confidence_calibration",
    "validate_execution",
    "build_independent_audit_report",
    "log_validation_snapshot",
]
