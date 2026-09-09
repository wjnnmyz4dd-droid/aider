"""Session Edge — deterministic Position Management (Phase 4C-R: FROZEN DESIGN).

Freezes the complete deterministic specification (state, config, reason codes,
stop-update precedence, audit schema, manual-intervention policy, reconciliation
matrix, and the break-even / profit-lock / structure-trailing MATHEMATICS) plus
the safety invariants a future executor must satisfy. It contains NO execution:
it never moves a stop, never talks to MT5 or the bridge, and no AI agent can act
on stops. ``spec`` holds pure math; ``contract`` holds data + invariants.
"""

from __future__ import annotations

from .contract import (
    StopPhase, TrailMethod, WeekendPolicy, ManualPolicy, ManualAction, PMReason,
    PositionConfig, DEFAULT_PM_CONFIG, REQUIRED_STATE_FIELDS, build_state,
    validate_state, stop_move_is_legal, risk_not_increased,
    phase_transition_is_legal, RECOVERY_SOURCES_OF_TRUTH,
    STOP_UPDATE_PRECEDENCE, PRECEDENCE_INVARIANT, precedence_rank,
    precedence_dominates, AUDIT_RECORD_FIELDS, build_audit_record,
    validate_audit_record, classify_manual_change, RECONCILIATION_MATRIX,
    RECONCILIATION_CASES, reconciliation_rule,
)
from . import spec

__all__ = [
    "StopPhase", "TrailMethod", "WeekendPolicy", "ManualPolicy", "ManualAction",
    "PMReason", "PositionConfig", "DEFAULT_PM_CONFIG", "REQUIRED_STATE_FIELDS",
    "build_state", "validate_state", "stop_move_is_legal", "risk_not_increased",
    "phase_transition_is_legal", "RECOVERY_SOURCES_OF_TRUTH",
    "STOP_UPDATE_PRECEDENCE", "PRECEDENCE_INVARIANT", "precedence_rank",
    "precedence_dominates", "AUDIT_RECORD_FIELDS", "build_audit_record",
    "validate_audit_record", "classify_manual_change", "RECONCILIATION_MATRIX",
    "RECONCILIATION_CASES", "reconciliation_rule", "spec",
]
