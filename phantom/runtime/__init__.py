"""Runtime Orchestrator (Phase 3A).

The ONLY live coordinator. It owns ZERO trading logic -- it executes
the already-approved pipeline (Evidence -> Market Intelligence ->
Strategy -> Risk -> Compliance -> Bridge) in the correct order. See
`docs/adr/ADR-031-runtime-orchestrator.md`.
"""

from __future__ import annotations

from .bridge_handoff import build_trade_command
from .config import RUNTIME_VERSION, RuntimeConfig
from .engine import BridgeSubmit, RuntimeOrchestrator
from .logging_sink import log_runtime_audit_record
from .metrics import RuntimeMetrics
from .models import (
    SCHEMA_VERSION,
    ConfigValidationIssue,
    ConfigValidationResult,
    CycleOutcome,
    CycleReport,
    CycleStage,
    RuntimeAuditRecord,
    RuntimeContext,
    StageTiming,
    TradingProfile,
    TradingWindow,
    WatchdogSignal,
    WatchdogTimeoutKind,
)
from .profiles import (
    MAJOR_FOREX_UNIVERSE,
    make_custom_profile,
    make_london_aggressive_profile,
    make_london_and_new_york_profile,
    make_london_conservative_profile,
    make_new_york_aggressive_profile,
    make_new_york_conservative_profile,
)
from .validation import validate_profile, validate_profiles
from .watchdog_integration import (
    APPROVED_RESTART_COMPONENTS,
    detect_snapshot_timeout,
    detect_timeouts,
    is_approved_for_restart,
)

__all__ = [
    "RUNTIME_VERSION",
    "SCHEMA_VERSION",
    "RuntimeConfig",
    "RuntimeOrchestrator",
    "BridgeSubmit",
    "RuntimeMetrics",
    "TradingWindow",
    "TradingProfile",
    "RuntimeContext",
    "CycleStage",
    "CycleOutcome",
    "StageTiming",
    "RuntimeAuditRecord",
    "CycleReport",
    "ConfigValidationIssue",
    "ConfigValidationResult",
    "WatchdogTimeoutKind",
    "WatchdogSignal",
    "MAJOR_FOREX_UNIVERSE",
    "make_london_conservative_profile",
    "make_london_aggressive_profile",
    "make_new_york_conservative_profile",
    "make_new_york_aggressive_profile",
    "make_london_and_new_york_profile",
    "make_custom_profile",
    "validate_profile",
    "validate_profiles",
    "APPROVED_RESTART_COMPONENTS",
    "detect_timeouts",
    "detect_snapshot_timeout",
    "is_approved_for_restart",
    "build_trade_command",
    "log_runtime_audit_record",
]
