"""Phase 4C-R — frozen Position Management specification validation.

Design-only: validates precedence (F1), break-even/profit-lock/trailing MATH
(F2), reason-code registry (F3), audit schema (F4), manual policy (F5), and the
reconciliation matrix (F6). No execution tests.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from forex_swing_orb.position import (
    PMReason, DEFAULT_PM_CONFIG, STOP_UPDATE_PRECEDENCE, PRECEDENCE_INVARIANT,
    precedence_rank, precedence_dominates, AUDIT_RECORD_FIELDS,
    build_audit_record, validate_audit_record, classify_manual_change,
    ManualAction, RECONCILIATION_MATRIX, RECONCILIATION_CASES, reconciliation_rule,
    spec,
)

CFG = DEFAULT_PM_CONFIG
PIP = CFG.pip_size


# -- F1: precedence ----------------------------------------------------------
def test_precedence_exact_order():
    assert STOP_UPDATE_PRECEDENCE == (
        "broker_reconciliation", "manual_intervention", "emergency_kill_switch",
        "position_closed", "weekend_policy", "max_duration",
        "protective_stop_integrity", "break_even", "profit_lock",
        "structure_trail", "no_action")


def test_precedence_protective_dominates_management():
    # every protective/reconciliation rule outranks break-even/lock/trail
    for hi in ("broker_reconciliation", "manual_intervention", "emergency_kill_switch",
               "position_closed", "weekend_policy", "max_duration",
               "protective_stop_integrity"):
        for lo in ("break_even", "profit_lock", "structure_trail", "no_action"):
            assert precedence_dominates(hi, lo)
            assert not precedence_dominates(lo, hi)


def test_precedence_invariant_frozen():
    assert "weaken" in PRECEDENCE_INVARIANT and "higher-priority" in PRECEDENCE_INVARIANT
    assert precedence_rank("no_action") == len(STOP_UPDATE_PRECEDENCE) - 1
    assert precedence_rank("unknown") is None


# -- F2: break-even math -----------------------------------------------------
def test_initial_risk_long_short_and_fail_closed():
    assert spec.initial_risk("LONG", 1.1000, 1.0980) == 0.0020 or \
        abs(spec.initial_risk("LONG", 1.1000, 1.0980) - 0.0020) < 1e-12
    assert abs(spec.initial_risk("SHORT", 1.1000, 1.1020) - 0.0020) < 1e-12
    assert spec.initial_risk("LONG", 1.1000, 1.1000) is None      # zero -> fail closed
    assert spec.initial_risk("LONG", 1.1000, 1.1020) is None      # negative -> fail closed
    assert spec.initial_risk("SHORT", 1.1000, 1.0980) is None     # negative -> fail closed
    assert spec.initial_risk("LONG", float("nan"), 1.0) is None   # non-finite -> fail closed
    assert spec.initial_risk("FLAT", 1.1, 1.09) is None           # bad direction


def test_breakeven_trigger_operator_is_ge_long():
    R = spec.initial_risk("LONG", 1.1000, 1.0980)                 # 0.0020
    trig = spec.breakeven_trigger_price("LONG", 1.1000, R, CFG)   # 1.1000 + 1.0*0.0020
    assert abs(trig - 1.1020) < 1e-12
    assert spec.breakeven_triggered("LONG", 1.1020, trig) is True     # equality triggers
    assert spec.breakeven_triggered("LONG", 1.10199, trig) is False   # just below
    assert spec.breakeven_triggered("LONG", 1.1030, trig) is True


def test_breakeven_trigger_operator_is_ge_short():
    R = spec.initial_risk("SHORT", 1.1000, 1.1020)
    trig = spec.breakeven_trigger_price("SHORT", 1.1000, R, CFG)  # 1.1000 - 0.0020
    assert abs(trig - 1.0980) < 1e-12
    assert spec.breakeven_triggered("SHORT", 1.0980, trig) is True    # equality triggers
    assert spec.breakeven_triggered("SHORT", 1.09801, trig) is False


def test_breakeven_stop_includes_buffer_and_commission():
    off = (CFG.breakeven_buffer_pips + CFG.commission_pips) * PIP
    assert abs(spec.breakeven_stop("LONG", 1.1000, CFG) - (1.1000 + off)) < 1e-12
    assert abs(spec.breakeven_stop("SHORT", 1.1000, CFG) - (1.1000 - off)) < 1e-12


def test_breakeven_never_widens_vs_initial():
    from forex_swing_orb.position import stop_move_is_legal
    be = spec.breakeven_stop("LONG", 1.1000, CFG)
    assert stop_move_is_legal("LONG", 1.0980, be)                 # BE is toward profit
    be_s = spec.breakeven_stop("SHORT", 1.1000, CFG)
    assert stop_move_is_legal("SHORT", 1.1020, be_s)


def test_breakeven_fail_closed_on_bad_risk():
    assert spec.breakeven_trigger_price("LONG", 1.1000, None, CFG) is None
    assert spec.breakeven_stop("LONG", float("inf"), CFG) is None


# -- F2: profit lock ---------------------------------------------------------
def test_profit_lock_math_and_symmetry():
    R = spec.initial_risk("LONG", 1.1000, 1.0980)                 # 0.0020
    trig = spec.profit_lock_trigger_price("LONG", 1.1000, R, CFG) # +1.5R = 1.1030
    assert abs(trig - 1.1030) < 1e-9
    assert spec.profit_lock_triggered("LONG", trig, trig) is True     # equality triggers
    assert spec.profit_lock_triggered("LONG", trig - 1e-6, trig) is False  # just below
    lock = spec.profit_lock_stop("LONG", 1.1000, R, CFG)         # +0.5R = 1.1010
    assert abs(lock - 1.1010) < 1e-9
    # short symmetry
    Rs = spec.initial_risk("SHORT", 1.1000, 1.1020)
    trigs = spec.profit_lock_trigger_price("SHORT", 1.1000, Rs, CFG)
    assert abs(trigs - 1.0970) < 1e-9
    assert spec.profit_lock_triggered("SHORT", trigs, trigs) is True  # equality triggers
    locks = spec.profit_lock_stop("SHORT", 1.1000, Rs, CFG)
    assert abs(locks - 1.0990) < 1e-9


def test_profit_lock_anti_oscillation_via_improvement():
    # LOCKED stop must strictly improve on the current stop to move (no flip-flop)
    R = 0.0020
    lock = spec.profit_lock_stop("LONG", 1.1000, R, CFG)          # 1.1010
    assert spec.is_stop_improvement("LONG", 1.1000, lock, CFG) is True    # 1.1010 > 1.1000+thresh
    assert spec.is_stop_improvement("LONG", 1.1010, lock, CFG) is False   # equal -> no move


# -- F2: structure trailing --------------------------------------------------
def test_trailing_candidate_from_confirmed_swing():
    cand = spec.trailing_stop_candidate("LONG", 1.0990, CFG)      # swing - offset
    assert abs(cand - (1.0990 - CFG.trail_offset_pips * PIP)) < 1e-12
    cand_s = spec.trailing_stop_candidate("SHORT", 1.1010, CFG)
    assert abs(cand_s - (1.1010 + CFG.trail_offset_pips * PIP)) < 1e-12


def test_trailing_no_structure_returns_none():
    assert spec.trailing_stop_candidate("LONG", None, CFG) is None


def test_trailing_min_improvement_and_equal_hold():
    cur = 1.1000
    better = 1.1000 + 2 * CFG.min_trail_improvement_pips * PIP
    assert spec.is_stop_improvement("LONG", cur, better, CFG) is True
    assert spec.is_stop_improvement("LONG", cur, cur, CFG) is False       # equal = hold
    assert spec.is_stop_improvement("LONG", cur, 1.0995, CFG) is False    # worse = hold


def test_trailing_stale_structure():
    assert spec.structure_is_stale(CFG.stale_structure_max_bars + 1, CFG) is True
    assert spec.structure_is_stale(1, CFG) is False
    assert spec.structure_is_stale("x", CFG) is True             # malformed -> stale


def test_trailing_broker_min_stop_distance():
    cfg = DEFAULT_PM_CONFIG.__class__(broker_min_stop_pips=10.0)
    # candidate too close to price -> rejected
    assert spec.respects_broker_min_stop("LONG", 1.1000, 1.0999, cfg) is False
    assert spec.respects_broker_min_stop("LONG", 1.1000, 1.0980, cfg) is True
    assert spec.respects_broker_min_stop("LONG", 1.1, 1.09, DEFAULT_PM_CONFIG) is True  # disabled


# -- F3: reason-code registry -------------------------------------------------
def test_reason_code_registry_complete():
    required = {
        "PM_INITIAL", "PM_BREAKEVEN_PENDING", "PM_BREAKEVEN_TRIGGERED",
        "PM_BREAKEVEN_SET", "PM_PROFIT_LOCK_TRIGGERED", "PM_PROFIT_LOCK_SET",
        "PM_TRAIL_PENDING", "PM_TRAIL_ADVANCED", "PM_TRAIL_NO_IMPROVEMENT",
        "PM_STOP_WIDEN_REJECTED", "PM_STOP_LOOSEN_REJECTED", "PM_BROKER_CONSTRAINT",
        "PM_RECONCILIATION_REQUIRED", "PM_MANUAL_CHANGE_ADOPTED",
        "PM_MANUAL_CHANGE_REJECTED", "PM_POSITION_CLOSED", "PM_DATA_STALE",
        "PM_DATA_INSUFFICIENT", "PM_WEEKEND_EXIT", "PM_MAX_DURATION_EXIT"}
    present = {v for k, v in vars(PMReason).items()
              if isinstance(v, str) and v.startswith("PM_")}
    assert required.issubset(present), required - present
    assert set(PMReason.REQUIRED) == required


# -- F4: audit schema --------------------------------------------------------
def test_audit_schema_fields_complete():
    for f in ("signal_id", "ticket", "symbol", "direction", "phase", "entry_price",
              "initial_stop", "immutable_initial_R", "previous_stop", "proposed_stop",
              "applied_stop", "trigger_price", "market_reference", "structure_reference",
              "reason_code", "broker_result", "evaluation_timestamp",
              "reconciliation_status", "manual_status", "restart_source"):
        assert f in AUDIT_RECORD_FIELDS


def test_audit_record_build_and_validate():
    rec = build_audit_record(PMReason.BREAKEVEN_SET, "2024-01-25T12:00:00Z",
                             signal_id="s", ticket=1, previous_stop=1.098,
                             proposed_stop=1.1002, applied_stop=1.1002)
    ok, why = validate_audit_record(rec)
    assert ok, why
    assert rec["reason_code"] == PMReason.BREAKEVEN_SET
    assert rec["applied_stop"] == 1.1002
    # unspecified fields default to None (deterministic)
    assert rec["market_reference"] is None
    # missing reason_code fails validation
    bad = dict(rec); bad["reason_code"] = None
    assert validate_audit_record(bad)[0] is False


# -- F5: manual intervention -------------------------------------------------
def test_manual_tightening_adopted():
    action, reason = classify_manual_change("LONG", 1.0980, 1.0995)   # raised stop
    assert action == ManualAction.ADOPT and reason == PMReason.MANUAL_CHANGE_ADOPTED


def test_manual_loosening_rejected():
    action, reason = classify_manual_change("LONG", 1.0980, 1.0970)   # lowered stop
    assert action == ManualAction.REJECT and reason == PMReason.MANUAL_CHANGE_REJECTED


def test_manual_sl_removal_escalates():
    action, reason = classify_manual_change("LONG", 1.0980, None)
    assert action == ManualAction.ESCALATE and reason == PMReason.STOP_LOOSEN_REJECTED


def test_manual_close_detected():
    action, reason = classify_manual_change("LONG", 1.0980, 1.0980, position_present=False)
    assert action == ManualAction.CLOSE and reason == PMReason.POSITION_CLOSED


def test_manual_no_change():
    action, reason = classify_manual_change("SHORT", 1.1020, 1.1020)
    assert action == ManualAction.NONE


def test_manual_short_symmetry():
    assert classify_manual_change("SHORT", 1.1020, 1.1010)[0] == ManualAction.ADOPT   # tighter
    assert classify_manual_change("SHORT", 1.1020, 1.1030)[0] == ManualAction.REJECT  # looser


# -- F6: reconciliation matrix -----------------------------------------------
def test_reconciliation_matrix_covers_required_cases():
    required = {"broker_stop_differs", "bridge_missing", "audit_missing",
                "conflicting_audit", "no_broker_position", "terminal_disconnected",
                "duplicate_ticket", "crash_during_stop_modification",
                "unknown_broker_outcome", "stale_local_state"}
    assert required.issubset(set(RECONCILIATION_CASES))


def test_reconciliation_never_blind_retry():
    for row in RECONCILIATION_MATRIX:
        assert row["retry_allowed"] is False        # never blindly resend a stop mod
        assert row["audit"] is True
        assert row["reason_code"].startswith("PM_")
        assert row["source_of_truth"]


def test_reconciliation_uncertain_outcome_verifies_broker():
    for case in ("crash_during_stop_modification", "unknown_broker_outcome"):
        row = reconciliation_rule(case)
        assert "never_blind_resend" in row["result"]
        assert row["reason_code"] == PMReason.RECONCILIATION_REQUIRED


def test_reconciliation_no_position_marks_closed():
    row = reconciliation_rule("no_broker_position")
    assert row["reason_code"] == PMReason.POSITION_CLOSED
    assert row["source_of_truth"] == "mt5_terminal"


def test_reconciliation_unknown_case_returns_none():
    assert reconciliation_rule("not_a_case") is None
