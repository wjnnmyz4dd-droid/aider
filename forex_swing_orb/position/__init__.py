"""Session Edge — deterministic Position Management (Phase 4C: DESIGN ONLY).

This package FREEZES the deterministic position-management design: state schema,
configuration, reason codes, phase model, and the safety INVARIANTS a future
implementation must satisfy (never widen risk, trail only toward profit,
forward-only phase transitions). It contains NO execution behavior: it never
computes a trailing/break-even stop, never talks to MT5 or the bridge, and never
moves a stop. AI agents may recommend; only a future deterministic executor will
act, and it must satisfy the invariants defined here.
"""

from __future__ import annotations

from .contract import (StopPhase, TrailMethod, WeekendPolicy, ManualPolicy,
                       PMReason, PositionConfig, DEFAULT_PM_CONFIG,
                       REQUIRED_STATE_FIELDS, build_state, validate_state,
                       stop_move_is_legal, risk_not_increased,
                       phase_transition_is_legal, RECOVERY_SOURCES_OF_TRUTH)

__all__ = [
    "StopPhase", "TrailMethod", "WeekendPolicy", "ManualPolicy", "PMReason",
    "PositionConfig", "DEFAULT_PM_CONFIG", "REQUIRED_STATE_FIELDS", "build_state",
    "validate_state", "stop_move_is_legal", "risk_not_increased",
    "phase_transition_is_legal", "RECOVERY_SOURCES_OF_TRUTH",
]
