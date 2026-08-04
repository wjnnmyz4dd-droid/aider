"""Phase 4C — deterministic Position Management ARCHITECTURE validation.

Validates the frozen design + safety invariants. No execution exists yet: these
tests assert the contract/invariants, never a live trailing/break-even algorithm.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]   # .../aider
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from forex_swing_orb.position import (StopPhase, TrailMethod, WeekendPolicy,
                                      ManualPolicy, PMReason, PositionConfig,
                                      DEFAULT_PM_CONFIG, REQUIRED_STATE_FIELDS,
                                      build_state, validate_state,
                                      stop_move_is_legal, risk_not_increased,
                                      phase_transition_is_legal,
                                      RECOVERY_SOURCES_OF_TRUTH)


# -- config / schema architecture -------------------------------------------
def test_config_is_frozen_and_deterministic():
    import dataclasses
    assert dataclasses.is_dataclass(PositionConfig)
    c = DEFAULT_PM_CONFIG
    # break-even + trailing + duration + weekend + manual all present as data
    for f in ("breakeven_trigger_r", "breakeven_buffer_pips", "profit_lock_r",
              "trail_method", "atr_period", "atr_multiple", "partial_enabled",
              "max_duration_bars", "weekend_policy", "manual_policy", "pip_size"):
        assert hasattr(c, f)
    import pytest
    with pytest.raises(dataclasses.FrozenInstanceError):
        c.breakeven_trigger_r = 2.0            # frozen: cannot be mutated at runtime


def test_initial_stop_source_is_strategy():
    assert DEFAULT_PM_CONFIG.initial_stop_source == "strategy"


def test_state_schema_complete():
    st = build_state("s", 111, "EURUSD.FX", "LONG", 1.1000, 1.0980, 1.1040, "2024-01-25T12:00:00Z")
    ok, why = validate_state(st)
    assert ok, why
    for f in REQUIRED_STATE_FIELDS:
        assert f in st
    assert st["phase"] == StopPhase.INITIAL
    assert st["current_stop"] == st["initial_stop"]


def test_state_validation_rejects_bad_phase():
    st = build_state("s", 1, "EURUSD.FX", "LONG", 1.1, 1.098, 1.104, "t")
    st["phase"] = "WHATEVER"
    ok, why = validate_state(st)
    assert not ok and why == "bad-phase"


# -- break-even architecture -------------------------------------------------
def test_breakeven_phase_and_reasons_defined():
    assert StopPhase.BREAKEVEN in StopPhase.ORDER
    assert PMReason.BREAKEVEN_TRIGGERED and PMReason.BREAKEVEN_SET
    assert DEFAULT_PM_CONFIG.breakeven_trigger_r > 0
    assert DEFAULT_PM_CONFIG.breakeven_buffer_pips >= 0


# -- trailing-stop invariants (the safety contract) --------------------------
def test_trail_only_toward_profit_long():
    assert stop_move_is_legal("LONG", 1.0980, 1.1000) is True     # raise = legal
    assert stop_move_is_legal("LONG", 1.1000, 1.0980) is False    # lower = illegal
    assert stop_move_is_legal("LONG", 1.1000, 1.1000) is True     # hold = legal


def test_trail_only_toward_profit_short():
    assert stop_move_is_legal("SHORT", 1.1020, 1.1000) is True    # lower = legal
    assert stop_move_is_legal("SHORT", 1.1000, 1.1020) is False   # raise = illegal


def test_never_widen_risk():
    assert risk_not_increased("LONG", 1.1000, 1.0980, 1.0990) is True    # tighter
    assert risk_not_increased("LONG", 1.1000, 1.0980, 1.0970) is False   # wider
    assert risk_not_increased("SHORT", 1.1000, 1.1020, 1.1010) is True
    assert risk_not_increased("SHORT", 1.1000, 1.1020, 1.1030) is False


def test_unknown_direction_is_illegal():
    assert stop_move_is_legal("SIDEWAYS", 1.1, 1.1) is False


def test_trail_methods_and_reasons_defined():
    assert TrailMethod.STRUCTURE and TrailMethod.ATR and TrailMethod.NONE
    for r in (PMReason.TRAIL_ADVANCED, PMReason.TRAIL_HELD,
              PMReason.STOP_REJECTED_WIDEN, PMReason.PROFIT_LOCKED):
        assert isinstance(r, str) and r.startswith("PM_")


# -- phase lifecycle (forward-only) ------------------------------------------
def test_phase_transitions_forward_only():
    assert phase_transition_is_legal(StopPhase.INITIAL, StopPhase.BREAKEVEN)
    assert phase_transition_is_legal(StopPhase.BREAKEVEN, StopPhase.TRAILING)
    assert phase_transition_is_legal(StopPhase.INITIAL, StopPhase.INITIAL)     # hold
    assert phase_transition_is_legal(StopPhase.TRAILING, StopPhase.CLOSED)     # any->closed
    assert not phase_transition_is_legal(StopPhase.TRAILING, StopPhase.INITIAL)  # backward
    assert not phase_transition_is_legal(StopPhase.CLOSED, StopPhase.TRAILING)   # terminal


# -- weekend / manual / duration architecture --------------------------------
def test_weekend_and_manual_policies_defined():
    assert WeekendPolicy.FLATTEN and WeekendPolicy.HOLD
    assert ManualPolicy.ADOPT_AND_AUDIT and ManualPolicy.RECONCILE_REQUIRED
    assert DEFAULT_PM_CONFIG.weekend_policy in (WeekendPolicy.FLATTEN, WeekendPolicy.HOLD)
    assert isinstance(DEFAULT_PM_CONFIG.max_duration_bars, int)


# -- restart recovery design -------------------------------------------------
def test_recovery_sources_of_truth_order():
    # never in-memory only: MT5 terminal + filesystem bridge + audit
    assert RECOVERY_SOURCES_OF_TRUTH[0] == "mt5_terminal"
    assert "filesystem_bridge" in RECOVERY_SOURCES_OF_TRUTH
    assert "pm_audit_log" in RECOVERY_SOURCES_OF_TRUTH
    for r in (PMReason.RECOVERED_FROM_BROKER, PMReason.RECONCILIATION_REQUIRED,
              PMReason.BROKER_DESYNC, PMReason.MANUAL_DETECTED):
        assert r.startswith("PM_")


# -- design-only: no execution / networking / broker calls -------------------
def test_position_package_has_no_execution_or_networking():
    pkg = Path(__file__).resolve().parents[1]
    for src in pkg.glob("*.py"):
        text = src.read_text()
        for tok in ("ea_mt5", "order_send", "OrderSend", "producer",
                    "write_instruction", "import socket", "urllib",
                    "requests.get", "WebRequest("):
            assert tok not in text, f"{src.name}:{tok}"


def test_no_stop_computation_function_present():
    # design freeze: the trailing/BE ALGORITHM is documented, not implemented
    calc = (Path(__file__).resolve().parents[1] / "contract.py").read_text()
    for banned in ("def compute_next_stop", "def next_stop", "def trail_stop",
                   "def move_to_breakeven"):
        assert banned not in calc
