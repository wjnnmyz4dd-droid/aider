"""Deterministic Position Management contract (Phase 4C — DESIGN + INVARIANTS).

Data + pure invariant predicates only. No stop is ever computed here and nothing
is executed; the trailing/break-even *algorithms* are documented in
docs/SESSION_EDGE_PHASE_4C_SHADOW_AND_POSITION_MGMT.md and deferred to the
implementation phase. The predicates below are the safety contract that any
future executor must satisfy and that tests validate now.
"""

from __future__ import annotations

from dataclasses import dataclass


class StopPhase:
    """Forward-only stop lifecycle."""
    INITIAL = "INITIAL"        # initial (strategy-provided) stop in place
    BREAKEVEN = "BREAKEVEN"    # stop moved to entry (+/- buffer)
    LOCKED = "LOCKED"          # profit locked beyond break-even
    TRAILING = "TRAILING"      # deterministically trailing behind structure/ATR
    CLOSED = "CLOSED"          # position closed

    ORDER = (INITIAL, BREAKEVEN, LOCKED, TRAILING, CLOSED)


class TrailMethod:
    STRUCTURE = "STRUCTURE"    # trail behind confirmed structure (strategy swings)
    ATR = "ATR"                # future option: ATR-based trailing
    NONE = "NONE"


class WeekendPolicy:
    FLATTEN = "FLATTEN"        # close before weekend
    HOLD = "HOLD"             # hold across weekend (documented risk)


class ManualPolicy:
    ADOPT_AND_AUDIT = "ADOPT_AND_AUDIT"   # detect manual change, adopt broker truth, audit
    RECONCILE_REQUIRED = "RECONCILE_REQUIRED"


class PMReason:
    """Deterministic position-management reason codes (design registry)."""
    INITIAL_SL_SET = "PM_INITIAL_SL_SET"
    BREAKEVEN_TRIGGERED = "PM_BREAKEVEN_TRIGGERED"
    BREAKEVEN_SET = "PM_BREAKEVEN_SET"
    PROFIT_LOCKED = "PM_PROFIT_LOCKED"
    TRAIL_ADVANCED = "PM_TRAIL_ADVANCED"
    TRAIL_HELD = "PM_TRAIL_HELD"
    STOP_REJECTED_WIDEN = "PM_STOP_REJECTED_WIDEN"      # illegal move refused
    MAX_DURATION_EXIT = "PM_MAX_DURATION_EXIT"
    WEEKEND_FLAT = "PM_WEEKEND_FLAT"
    WEEKEND_HOLD = "PM_WEEKEND_HOLD"
    PARTIAL_TAKEN = "PM_PARTIAL_TAKEN"
    MANUAL_DETECTED = "PM_MANUAL_DETECTED"
    BROKER_DESYNC = "PM_BROKER_DESYNC"
    RECOVERED_FROM_BROKER = "PM_RECOVERED_FROM_BROKER"
    RECONCILIATION_REQUIRED = "PM_RECONCILIATION_REQUIRED"


@dataclass(frozen=True)
class PositionConfig:
    """All deterministic PM parameters (data only). No behavior."""
    initial_stop_source: str = "strategy"          # SL always comes from the strategy
    breakeven_trigger_r: float = 1.0               # move to BE at +1R
    breakeven_buffer_pips: float = 2.0             # BE stop = entry +/- buffer
    profit_lock_r: float = 1.5                     # lock beyond BE at +1.5R
    trail_method: str = TrailMethod.STRUCTURE
    atr_period: int = 14                           # future ATR option
    atr_multiple: float = 1.5
    partial_enabled: bool = False                  # optional partial profit
    partial_fraction: float = 0.5
    partial_at_r: float = 1.0
    max_duration_bars: int = 0                     # 0 = disabled
    weekend_policy: str = WeekendPolicy.FLATTEN
    manual_policy: str = ManualPolicy.ADOPT_AND_AUDIT
    pip_size: float = 0.0001


DEFAULT_PM_CONFIG = PositionConfig()

# Restart recovery: the ORDER of sources of truth a future executor must use to
# rebuild stop/position state (never in-memory only).
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


# -- safety invariants (pure; the executor MUST satisfy these) ---------------
def _is_long(direction):
    return str(direction).upper() in ("LONG", "BULLISH")


def _is_short(direction):
    return str(direction).upper() in ("SHORT", "BEARISH")


def stop_move_is_legal(direction, old_stop, new_stop):
    """Trail only toward profit; never loosen a stop. LONG stops may only rise;
    SHORT stops may only fall. Equal is allowed (hold)."""
    if _is_long(direction):
        return new_stop >= old_stop
    if _is_short(direction):
        return new_stop <= old_stop
    return False


def risk_not_increased(direction, entry, old_stop, new_stop):
    """A stop move must never increase distance-to-entry on the loss side
    (never widen risk). Equivalent to stop_move_is_legal for a with-trade stop."""
    if _is_long(direction):
        return new_stop >= old_stop and new_stop <= entry + abs(entry)  # sane upper bound
    if _is_short(direction):
        return new_stop <= old_stop
    return False


def phase_transition_is_legal(from_phase, to_phase):
    """Forward-only lifecycle; any phase may go to CLOSED; same phase allowed."""
    order = StopPhase.ORDER
    if from_phase not in order or to_phase not in order:
        return False
    if to_phase == StopPhase.CLOSED:
        return True
    return order.index(to_phase) >= order.index(from_phase)
