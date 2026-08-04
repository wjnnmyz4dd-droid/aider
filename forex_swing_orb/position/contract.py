"""Deterministic Position Management contract (Phase 4C-R — FROZEN DESIGN).

Data, registries, and pure invariant predicates only. Nothing here executes,
moves a stop, or touches MT5/the bridge; the deterministic *mathematics* live in
``spec.py`` (pure functions, no side effects). This module freezes:

  * the stop lifecycle + forward-only transition invariant
  * the canonical stop-update PRECEDENCE order + its safety invariant (F1)
  * the complete PM reason-code registry (F3)
  * the canonical PM audit-record schema (F4)
  * the manual-intervention classification policy (F5)
  * the reconciliation decision matrix (F6)
  * the never-widen / never-loosen stop invariants

No implementation decision is left to developer interpretation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


class StopPhase:
    """Forward-only stop lifecycle."""
    INITIAL = "INITIAL"
    BREAKEVEN = "BREAKEVEN"
    LOCKED = "LOCKED"
    TRAILING = "TRAILING"
    CLOSED = "CLOSED"

    ORDER = (INITIAL, BREAKEVEN, LOCKED, TRAILING, CLOSED)


class TrailMethod:
    STRUCTURE = "STRUCTURE"    # baseline: trail behind confirmed strategy structure
    ATR = "ATR"                # future option
    NONE = "NONE"


class WeekendPolicy:
    FLATTEN = "FLATTEN"
    HOLD = "HOLD"


class ManualPolicy:
    ADOPT_AND_AUDIT = "ADOPT_AND_AUDIT"          # adopt manual TIGHTENING, audit
    REJECT_OR_ESCALATE = "REJECT_OR_ESCALATE"    # reject/escalate manual LOOSENING


class ManualAction:
    NONE = "NONE"
    ADOPT = "ADOPT"
    REJECT = "REJECT"
    ESCALATE = "ESCALATE"
    CLOSE = "CLOSE"
    RECONCILE = "RECONCILE"


class PMReason:
    """Complete Position Management reason-code registry (F3, normalized)."""
    INITIAL = "PM_INITIAL"
    BREAKEVEN_PENDING = "PM_BREAKEVEN_PENDING"
    BREAKEVEN_TRIGGERED = "PM_BREAKEVEN_TRIGGERED"
    BREAKEVEN_SET = "PM_BREAKEVEN_SET"
    PROFIT_LOCK_TRIGGERED = "PM_PROFIT_LOCK_TRIGGERED"
    PROFIT_LOCK_SET = "PM_PROFIT_LOCK_SET"
    TRAIL_PENDING = "PM_TRAIL_PENDING"
    TRAIL_ADVANCED = "PM_TRAIL_ADVANCED"
    TRAIL_NO_IMPROVEMENT = "PM_TRAIL_NO_IMPROVEMENT"
    STOP_WIDEN_REJECTED = "PM_STOP_WIDEN_REJECTED"
    STOP_LOOSEN_REJECTED = "PM_STOP_LOOSEN_REJECTED"
    BROKER_CONSTRAINT = "PM_BROKER_CONSTRAINT"
    RECONCILIATION_REQUIRED = "PM_RECONCILIATION_REQUIRED"
    MANUAL_CHANGE_ADOPTED = "PM_MANUAL_CHANGE_ADOPTED"
    MANUAL_CHANGE_REJECTED = "PM_MANUAL_CHANGE_REJECTED"
    POSITION_CLOSED = "PM_POSITION_CLOSED"
    DATA_STALE = "PM_DATA_STALE"
    DATA_INSUFFICIENT = "PM_DATA_INSUFFICIENT"
    WEEKEND_EXIT = "PM_WEEKEND_EXIT"
    MAX_DURATION_EXIT = "PM_MAX_DURATION_EXIT"
    # supporting codes (superset; not required by the registry list but used)
    KILL_SWITCH = "PM_KILL_SWITCH"
    PARTIAL_CLOSED = "PM_PARTIAL_CLOSED"
    RECOVERED_FROM_BROKER = "PM_RECOVERED_FROM_BROKER"
    MANUAL_DETECTED = "PM_MANUAL_DETECTED"
    NO_ACTION = "PM_NO_ACTION"

    #: the exact 20 codes the acceptance review requires to exist
    REQUIRED = (
        INITIAL, BREAKEVEN_PENDING, BREAKEVEN_TRIGGERED, BREAKEVEN_SET,
        PROFIT_LOCK_TRIGGERED, PROFIT_LOCK_SET, TRAIL_PENDING, TRAIL_ADVANCED,
        TRAIL_NO_IMPROVEMENT, STOP_WIDEN_REJECTED, STOP_LOOSEN_REJECTED,
        BROKER_CONSTRAINT, RECONCILIATION_REQUIRED, MANUAL_CHANGE_ADOPTED,
        MANUAL_CHANGE_REJECTED, POSITION_CLOSED, DATA_STALE, DATA_INSUFFICIENT,
        WEEKEND_EXIT, MAX_DURATION_EXIT,
    )


@dataclass(frozen=True)
class PositionConfig:
    """All deterministic PM parameters (data only; no behavior)."""
    initial_stop_source: str = "strategy"      # SL always from the strategy
    # break-even
    breakeven_trigger_r: float = 1.0           # trigger at +1R (operator: >=)
    breakeven_buffer_pips: float = 2.0         # BE stop = entry +/- buffer
    commission_pips: float = 0.0               # added into the BE buffer to net-cover costs
    # profit lock
    profit_lock_r: float = 1.5                 # trigger at +1.5R (operator: >=)
    profit_lock_retain_r: float = 0.5          # lock +0.5R of profit
    # structure trailing
    trail_method: str = TrailMethod.STRUCTURE
    trail_offset_pips: float = 1.0             # stop sits this far beyond the swing
    min_trail_improvement_pips: float = 1.0    # minimum improvement to move the stop
    reuse_strategy_swings: bool = True         # consume strategy swings; never recompute
    swing_confirmation: str = "strategy_pivot_k"   # confirmation inherited from strategy
    stale_structure_max_bars: int = 3          # structure older than this is stale
    broker_min_stop_pips: float = 0.0          # respect broker minimum stop distance
    evaluation_cadence: str = "ON_CLOSED_BAR"  # evaluate once per closed bar
    # ATR trailing (future option)
    atr_period: int = 14
    atr_multiple: float = 1.5
    # partial profit (optional)
    partial_enabled: bool = False
    partial_fraction: float = 0.5
    partial_at_r: float = 1.0
    # duration / weekend / manual
    max_duration_bars: int = 0                 # 0 = disabled
    weekend_policy: str = WeekendPolicy.FLATTEN
    weekend_cutoff_dow: int = 4                # Friday (Mon=0), UTC
    weekend_cutoff_hour_utc: int = 20          # 20:00 UTC (DST-immune: fixed UTC)
    manual_policy: str = ManualPolicy.ADOPT_AND_AUDIT
    pip_size: float = 0.0001


DEFAULT_PM_CONFIG = PositionConfig()

# -- F1: canonical stop-update precedence (highest priority first) ------------
STOP_UPDATE_PRECEDENCE = (
    "broker_reconciliation",     # 1
    "manual_intervention",       # 2
    "emergency_kill_switch",     # 3
    "position_closed",           # 4
    "weekend_policy",            # 5
    "max_duration",              # 6
    "protective_stop_integrity", # 7
    "break_even",                # 8
    "profit_lock",               # 9
    "structure_trail",           # 10
    "no_action",                 # 11
)

PRECEDENCE_INVARIANT = (
    "No lower-priority rule may weaken a higher-priority protective action; "
    "on any evaluation the highest-priority applicable rule decides, and a "
    "stop may only move in a protective (never-widen, never-loosen) direction."
)


def precedence_rank(rule):
    """0-based rank (lower = higher priority). None if unknown."""
    return STOP_UPDATE_PRECEDENCE.index(rule) if rule in STOP_UPDATE_PRECEDENCE else None


def precedence_dominates(rule_a, rule_b):
    """True iff rule_a has priority over (or equals) rule_b."""
    ra, rb = precedence_rank(rule_a), precedence_rank(rule_b)
    return ra is not None and rb is not None and ra <= rb


# Restart recovery: ordered sources of truth (never in-memory only).
RECOVERY_SOURCES_OF_TRUTH = ("mt5_terminal", "filesystem_bridge", "pm_audit_log")

REQUIRED_STATE_FIELDS = (
    "signal_id", "ticket", "symbol", "direction", "entry", "initial_stop",
    "current_stop", "take_profit", "phase", "opened_timestamp",
    "last_update_timestamp", "bars_open", "partials_done", "manual_flag",
    "broker_synced",
)


def build_state(signal_id, ticket, symbol, direction, entry, initial_stop,
                take_profit, opened_timestamp, phase=StopPhase.INITIAL):
    return {
        "signal_id": signal_id, "ticket": ticket, "symbol": symbol,
        "direction": direction, "entry": entry, "initial_stop": initial_stop,
        "current_stop": initial_stop, "take_profit": take_profit, "phase": phase,
        "opened_timestamp": opened_timestamp, "last_update_timestamp": opened_timestamp,
        "bars_open": 0, "partials_done": 0, "manual_flag": False, "broker_synced": True,
    }


def validate_state(state):
    if not isinstance(state, dict):
        return False, "not-a-dict"
    for f in REQUIRED_STATE_FIELDS:
        if f not in state:
            return False, f"missing:{f}"
    if state["phase"] not in StopPhase.ORDER:
        return False, "bad-phase"
    return True, "OK"


# -- F4: canonical audit-record schema ---------------------------------------
AUDIT_RECORD_FIELDS = (
    "signal_id", "ticket", "symbol", "direction", "phase", "entry_price",
    "initial_stop", "immutable_initial_R", "previous_stop", "proposed_stop",
    "applied_stop", "trigger_price", "market_reference", "structure_reference",
    "reason_code", "broker_result", "evaluation_timestamp",
    "reconciliation_status", "manual_status", "restart_source",
)


def build_audit_record(reason_code, evaluation_timestamp, **fields):
    """Construct the ONE canonical PM audit record for a stop evaluation/movement.
    Deterministic: pure function of its inputs. Every stop movement produces
    exactly one such record. Unspecified fields default to None."""
    rec = {f: None for f in AUDIT_RECORD_FIELDS}
    rec["reason_code"] = reason_code
    rec["evaluation_timestamp"] = evaluation_timestamp
    for k, v in fields.items():
        if k in rec:
            rec[k] = v
    return rec


def validate_audit_record(rec):
    if not isinstance(rec, dict):
        return False, "not-a-dict"
    for f in AUDIT_RECORD_FIELDS:
        if f not in rec:
            return False, f"missing:{f}"
    if not rec.get("reason_code"):
        return False, "missing:reason_code"
    return True, "OK"


# -- safety invariants (pure) ------------------------------------------------
def _is_long(direction):
    return str(direction).upper() in ("LONG", "BULLISH")


def _is_short(direction):
    return str(direction).upper() in ("SHORT", "BEARISH")


def _finite(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def stop_move_is_legal(direction, old_stop, new_stop):
    """Never loosen: LONG stops may only rise, SHORT stops may only fall;
    equal (hold) is allowed."""
    if not (_finite(old_stop) and _finite(new_stop)):
        return False
    if _is_long(direction):
        return new_stop >= old_stop
    if _is_short(direction):
        return new_stop <= old_stop
    return False


def _loss_distance(direction, entry, stop):
    """Distance from entry on the LOSS side, clamped at 0 (a stop in profit has
    zero loss-distance)."""
    if _is_long(direction):
        return max(0.0, entry - stop)
    if _is_short(direction):
        return max(0.0, stop - entry)
    return math.inf


def risk_not_increased(direction, entry, old_stop, new_stop):
    """Never widen risk: the new stop's loss-distance-from-entry must not exceed
    the old stop's. (Meaningful loss-side measure; not vacuous.)"""
    if not (_finite(entry) and _finite(old_stop) and _finite(new_stop)):
        return False
    if not (_is_long(direction) or _is_short(direction)):
        return False
    return _loss_distance(direction, entry, new_stop) <= _loss_distance(direction, entry, old_stop)


def phase_transition_is_legal(from_phase, to_phase):
    """Forward-only lifecycle; any phase may go to CLOSED; same phase allowed;
    CLOSED is terminal."""
    order = StopPhase.ORDER
    if from_phase not in order or to_phase not in order:
        return False
    if from_phase == StopPhase.CLOSED:
        return to_phase == StopPhase.CLOSED
    if to_phase == StopPhase.CLOSED:
        return True
    return order.index(to_phase) >= order.index(from_phase)


# -- F5: manual-intervention classification (pure) ---------------------------
def classify_manual_change(direction, expected_stop, observed_stop,
                           position_present=True):
    """Deterministically classify a detected manual broker change.

    Returns (ManualAction, PMReason). Never violates never-widen/never-loosen:
      * no position at broker            -> CLOSE (PM_POSITION_CLOSED)
      * stop removed (observed is None)  -> ESCALATE loosening (PM_STOP_LOOSEN_REJECTED)
      * no change                        -> NONE
      * tighter (toward profit)          -> ADOPT (PM_MANUAL_CHANGE_ADOPTED)
      * looser (widened risk)            -> REJECT (PM_MANUAL_CHANGE_REJECTED)
    """
    if not position_present:
        return ManualAction.CLOSE, PMReason.POSITION_CLOSED
    if observed_stop is None:                          # SL removal = loosening
        return ManualAction.ESCALATE, PMReason.STOP_LOOSEN_REJECTED
    if not _finite(observed_stop) or not _finite(expected_stop):
        return ManualAction.RECONCILE, PMReason.RECONCILIATION_REQUIRED
    if observed_stop == expected_stop:
        return ManualAction.NONE, PMReason.NO_ACTION
    if stop_move_is_legal(direction, expected_stop, observed_stop):   # tighter
        return ManualAction.ADOPT, PMReason.MANUAL_CHANGE_ADOPTED
    return ManualAction.REJECT, PMReason.MANUAL_CHANGE_REJECTED       # looser


# -- F6: reconciliation decision matrix (data) -------------------------------
# Each row: (case, source_of_truth, result, reason_code, audit, retry_allowed).
# retry_allowed is NEVER True for an uncertain stop-modification outcome — the
# executor must never blindly resend a stop modification.
RECONCILIATION_MATRIX = (
    {"case": "broker_stop_differs", "source_of_truth": "mt5_terminal",
     "result": "classify_manual_then_adopt_or_escalate",
     "reason_code": PMReason.RECONCILIATION_REQUIRED, "audit": True, "retry_allowed": False},
    {"case": "bridge_missing", "source_of_truth": "mt5_terminal",
     "result": "rebuild_from_broker", "reason_code": PMReason.RECOVERED_FROM_BROKER,
     "audit": True, "retry_allowed": False},
    {"case": "audit_missing", "source_of_truth": "mt5_terminal+filesystem_bridge",
     "result": "rebuild_and_flag", "reason_code": PMReason.RECONCILIATION_REQUIRED,
     "audit": True, "retry_allowed": False},
    {"case": "conflicting_audit", "source_of_truth": "mt5_terminal",
     "result": "fail_closed", "reason_code": PMReason.RECONCILIATION_REQUIRED,
     "audit": True, "retry_allowed": False},
    {"case": "no_broker_position", "source_of_truth": "mt5_terminal",
     "result": "mark_closed", "reason_code": PMReason.POSITION_CLOSED,
     "audit": True, "retry_allowed": False},
    {"case": "terminal_disconnected", "source_of_truth": "none_available",
     "result": "hold_fail_closed", "reason_code": PMReason.DATA_STALE,
     "audit": True, "retry_allowed": False},
    {"case": "duplicate_ticket", "source_of_truth": "mt5_terminal",
     "result": "fail_closed", "reason_code": PMReason.RECONCILIATION_REQUIRED,
     "audit": True, "retry_allowed": False},
    {"case": "crash_during_stop_modification", "source_of_truth": "mt5_terminal",
     "result": "verify_broker_never_blind_resend",
     "reason_code": PMReason.RECONCILIATION_REQUIRED, "audit": True, "retry_allowed": False},
    {"case": "unknown_broker_outcome", "source_of_truth": "mt5_terminal",
     "result": "verify_broker_never_blind_resend",
     "reason_code": PMReason.RECONCILIATION_REQUIRED, "audit": True, "retry_allowed": False},
    {"case": "stale_local_state", "source_of_truth": "mt5_terminal",
     "result": "rebuild_from_broker", "reason_code": PMReason.RECOVERED_FROM_BROKER,
     "audit": True, "retry_allowed": False},
)

RECONCILIATION_CASES = tuple(row["case"] for row in RECONCILIATION_MATRIX)


def reconciliation_rule(case):
    """Deterministic lookup of the frozen reconciliation row (or None)."""
    for row in RECONCILIATION_MATRIX:
        if row["case"] == case:
            return row
    return None
