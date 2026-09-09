"""Phase 4D — deterministic Position Manager behavioural tests (mock MT5).

Covers break-even, profit-lock, structure trailing, never-widen/loosen, manual
intervention, reconciliation, restart recovery, precedence, audit, and boundary
guarantees. Deterministic; no networking; no live terminal.
"""

from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from forex_swing_orb.ea_mt5 import mock_mt5
from forex_swing_orb.ea_mt5.position_manager import PositionManager, PMAudit
from forex_swing_orb.position import spec, DEFAULT_PM_CONFIG, PositionConfig
from forex_swing_orb.position.contract import StopPhase, PMReason

NOW = datetime(2024, 1, 25, 12, 0, tzinfo=timezone.utc)     # Thursday, mid-session
BUY, SELL = mock_mt5.ORDER_TYPE_BUY, mock_mt5.ORDER_TYPE_SELL
CFG = DEFAULT_PM_CONFIG


def rig(direction="LONG", entry=1.1000, sl=None, cfg=CFG, audit_path=None):
    m = mock_mt5.MockMT5(); m.add_symbol("EURUSD"); m.add_symbol("GBPUSD")
    if direction == "LONG":
        sl = 1.0980 if sl is None else sl; typ, tp = BUY, 1.1100
    else:
        sl = 1.1020 if sl is None else sl; typ, tp = SELL, 1.0900
    res = m.order_send({"symbol": "EURUSD", "volume": 0.10, "type": typ,
                        "price": entry, "sl": sl, "tp": tp, "comment": "sig"})
    path = audit_path or (Path(tempfile.mkdtemp()) / "pm.jsonl")
    pm = PositionManager(m, path, cfg)
    pm.register("sig", res.order, "EURUSD", direction, entry, sl, tp, NOW)
    return pm, m, res.order, path


def be_trigger(direction, entry=1.1000, sl=None, cfg=CFG):
    isl = (1.0980 if direction == "LONG" else 1.1020) if sl is None else sl
    R = spec.initial_risk(direction, entry, isl)
    return spec.breakeven_trigger_price(direction, entry, R, cfg)


# ============================ BREAK-EVEN (1-15) ============================
def test_be_long_below_trigger():
    pm, m, tk, _ = rig("LONG")
    r = pm.evaluate("sig", market_price=be_trigger("LONG") - 0.0002, now=NOW)
    assert r["reason_code"] == PMReason.BREAKEVEN_PENDING and r["phase"] == StopPhase.INITIAL


def test_be_long_exact_trigger_sets():
    pm, m, tk, _ = rig("LONG")
    r = pm.evaluate("sig", market_price=be_trigger("LONG"), now=NOW)   # >= qualifies
    assert r["reason_code"] == PMReason.BREAKEVEN_SET and r["phase"] == StopPhase.BREAKEVEN
    assert m.position_by_ticket(tk).sl == r["applied_stop"]


def test_be_long_above_trigger_sets():
    pm, m, tk, _ = rig("LONG")
    r = pm.evaluate("sig", market_price=be_trigger("LONG") + 0.0010, now=NOW)
    assert r["reason_code"] == PMReason.BREAKEVEN_SET


def test_be_short_below_favorable():
    pm, m, tk, _ = rig("SHORT")
    r = pm.evaluate("sig", market_price=be_trigger("SHORT") + 0.0002, now=NOW)   # not yet
    assert r["reason_code"] == PMReason.BREAKEVEN_PENDING


def test_be_short_exact_trigger_sets():
    pm, m, tk, _ = rig("SHORT")
    r = pm.evaluate("sig", market_price=be_trigger("SHORT"), now=NOW)
    assert r["reason_code"] == PMReason.BREAKEVEN_SET and r["phase"] == StopPhase.BREAKEVEN


def test_be_short_beyond_trigger_sets():
    pm, m, tk, _ = rig("SHORT")
    r = pm.evaluate("sig", market_price=be_trigger("SHORT") - 0.0010, now=NOW)
    assert r["reason_code"] == PMReason.BREAKEVEN_SET


def test_be_buffer_arithmetic():
    pm, m, tk, _ = rig("LONG")
    r = pm.evaluate("sig", market_price=be_trigger("LONG"), now=NOW)
    assert abs(r["applied_stop"] - (1.1000 + CFG.breakeven_buffer_pips * CFG.pip_size)) < 1e-12


def test_be_commission_adjustment():
    cfg = PositionConfig(commission_pips=1.0)
    pm, m, tk, _ = rig("LONG", cfg=cfg)
    r = pm.evaluate("sig", market_price=be_trigger("LONG", cfg=cfg), now=NOW)
    assert abs(r["applied_stop"] - (1.1000 + (2.0 + 1.0) * cfg.pip_size)) < 1e-12


def test_be_zero_initial_risk_fails_closed():
    # R = 0 -> register refuses (fail closed); no state, no modification
    pm, m, tk, path = rig("LONG", sl=1.1000)
    assert "sig" not in pm.states
    assert pm.audit.records_for("sig")[-1]["reason_code"] == PMReason.DATA_INSUFFICIENT
    assert not m.modify_log


def test_be_wrong_sided_initial_stop_fails_closed():
    pm, m, tk, path = rig("LONG", sl=1.1020)              # stop above entry (wrong side)
    assert "sig" not in pm.states
    assert pm.audit.records_for("sig")[-1]["reason_code"] == PMReason.DATA_INSUFFICIENT
    assert not m.modify_log


def test_be_non_finite_fails_closed():
    pm, m, tk, _ = rig("LONG")
    pm.states["sig"]["entry"] = float("nan")
    r = pm.evaluate("sig", market_price=1.1020, now=NOW)
    assert r["reason_code"] == PMReason.DATA_INSUFFICIENT


def test_be_equality_with_current_stop_no_modification():
    # stop already at/above BE -> phase advances, no redundant broker modify
    pm, m, tk, _ = rig("LONG", sl=1.0980)
    m.position_by_ticket(tk).sl = 1.1002                  # manually already at BE
    pm.states["sig"]["current_stop"] = 1.1002
    r = pm.evaluate("sig", market_price=be_trigger("LONG"), now=NOW)
    assert r["reason_code"] == PMReason.BREAKEVEN_SET and r["applied_stop"] is None
    assert not m.modify_log


def test_be_broker_constraint_no_advance():
    pm, m, tk, _ = rig("LONG"); m.script_modify("invalid_stops")
    r = pm.evaluate("sig", market_price=be_trigger("LONG"), now=NOW)
    assert r["reason_code"] == PMReason.BROKER_CONSTRAINT and r["phase"] == StopPhase.INITIAL


def test_be_broker_success_advances():
    pm, m, tk, _ = rig("LONG")
    r = pm.evaluate("sig", market_price=be_trigger("LONG"), now=NOW)
    assert r["phase"] == StopPhase.BREAKEVEN and r["broker_result"] == "DONE"


def test_be_broker_uncertain_requires_reconciliation():
    pm, m, tk, _ = rig("LONG"); m.script_modify("applied_but_unacked")
    r = pm.evaluate("sig", market_price=be_trigger("LONG"), now=NOW)
    assert r["reason_code"] == PMReason.RECONCILIATION_REQUIRED
    assert r["phase"] == StopPhase.INITIAL                # never advance on uncertainty


# ============================ PROFIT LOCK (16-22) =========================
def _to_breakeven(pm, direction="LONG"):
    pm.evaluate("sig", market_price=be_trigger(direction), now=NOW)


def test_lock_long_exact_trigger():
    pm, m, tk, _ = rig("LONG"); _to_breakeven(pm)
    R = spec.initial_risk("LONG", 1.1000, 1.0980)
    trig = spec.profit_lock_trigger_price("LONG", 1.1000, R, CFG)
    r = pm.evaluate("sig", market_price=trig, now=NOW)
    assert r["reason_code"] == PMReason.PROFIT_LOCK_SET and r["phase"] == StopPhase.LOCKED
    assert abs(r["applied_stop"] - (1.1000 + 0.5 * R)) < 1e-12


def test_lock_short_exact_trigger():
    pm, m, tk, _ = rig("SHORT"); _to_breakeven(pm, "SHORT")
    R = spec.initial_risk("SHORT", 1.1000, 1.1020)
    trig = spec.profit_lock_trigger_price("SHORT", 1.1000, R, CFG)
    r = pm.evaluate("sig", market_price=trig, now=NOW)
    assert r["reason_code"] == PMReason.PROFIT_LOCK_SET and r["phase"] == StopPhase.LOCKED


def test_lock_uses_immutable_R_after_breakeven():
    pm, m, tk, _ = rig("LONG"); _to_breakeven(pm)
    # tamper current stop (as BE would) — R must still derive from initial fields
    R = spec.initial_risk("LONG", pm.states["sig"]["entry"], pm.states["sig"]["initial_stop"])
    assert abs(R - 0.0020) < 1e-12
    trig = spec.profit_lock_trigger_price("LONG", 1.1000, R, CFG)
    r = pm.evaluate("sig", market_price=trig, now=NOW)
    assert abs(r["immutable_initial_R"] - 0.0020) < 1e-12


def test_lock_requires_strict_improvement():
    pm, m, tk, _ = rig("LONG"); _to_breakeven(pm)
    # move broker/current stop already beyond the lock level -> advance, no modify
    pm.states["sig"]["current_stop"] = 1.1010; m.position_by_ticket(tk).sl = 1.1010
    R = spec.initial_risk("LONG", 1.1000, 1.0980)
    trig = spec.profit_lock_trigger_price("LONG", 1.1000, R, CFG)
    r = pm.evaluate("sig", market_price=trig, now=NOW)
    assert r["phase"] == StopPhase.LOCKED and r["applied_stop"] is None


def test_lock_no_phase_regression():
    pm, m, tk, _ = rig("LONG"); _to_breakeven(pm)
    R = spec.initial_risk("LONG", 1.1000, 1.0980)
    pm.evaluate("sig", market_price=spec.profit_lock_trigger_price("LONG", 1.1000, R, CFG), now=NOW)
    assert pm.states["sig"]["phase"] == StopPhase.LOCKED
    # a later below-BE price never regresses the phase
    r = pm.evaluate("sig", market_price=1.1005, confirmed_swing=None, now=NOW)
    assert pm.states["sig"]["phase"] in (StopPhase.LOCKED, StopPhase.TRAILING)


def test_lock_broker_rejection():
    pm, m, tk, _ = rig("LONG"); _to_breakeven(pm); m.script_modify("reject")
    R = spec.initial_risk("LONG", 1.1000, 1.0980)
    r = pm.evaluate("sig", market_price=spec.profit_lock_trigger_price("LONG", 1.1000, R, CFG), now=NOW)
    assert r["reason_code"] == PMReason.BROKER_CONSTRAINT and r["phase"] == StopPhase.BREAKEVEN


def test_lock_broker_success():
    pm, m, tk, _ = rig("LONG"); _to_breakeven(pm)
    R = spec.initial_risk("LONG", 1.1000, 1.0980)
    r = pm.evaluate("sig", market_price=spec.profit_lock_trigger_price("LONG", 1.1000, R, CFG), now=NOW)
    assert r["phase"] == StopPhase.LOCKED and r["broker_result"] == "DONE"


# ============================ TRAILING (23-35) ============================
def _to_locked(pm, m, tk, direction="LONG"):
    _to_breakeven(pm, direction)
    isl = 1.0980 if direction == "LONG" else 1.1020
    R = spec.initial_risk(direction, 1.1000, isl)
    pm.evaluate("sig", market_price=spec.profit_lock_trigger_price(direction, 1.1000, R, CFG), now=NOW)


def test_trail_long_valid_higher_low():
    pm, m, tk, _ = rig("LONG"); _to_locked(pm, m, tk)
    r = pm.evaluate("sig", market_price=1.1050, confirmed_swing=1.1020,
                    structure_reference="hl-1", bars_since_swing=1, now=NOW)
    assert r["reason_code"] == PMReason.TRAIL_ADVANCED and r["phase"] == StopPhase.TRAILING
    assert abs(r["applied_stop"] - (1.1020 - CFG.trail_offset_pips * CFG.pip_size)) < 1e-12


def test_trail_short_valid_lower_high():
    pm, m, tk, _ = rig("SHORT"); _to_locked(pm, m, tk, "SHORT")
    r = pm.evaluate("sig", market_price=1.0950, confirmed_swing=1.0980,
                    structure_reference="lh-1", bars_since_swing=1, now=NOW)
    assert r["reason_code"] == PMReason.TRAIL_ADVANCED and r["phase"] == StopPhase.TRAILING


def test_trail_missing_structure_pending():
    pm, m, tk, _ = rig("LONG"); _to_locked(pm, m, tk)
    r = pm.evaluate("sig", market_price=1.1050, confirmed_swing=None, now=NOW)
    assert r["reason_code"] == PMReason.TRAIL_PENDING


def test_trail_stale_structure_rejected():
    pm, m, tk, _ = rig("LONG"); _to_locked(pm, m, tk)
    r = pm.evaluate("sig", market_price=1.1050, confirmed_swing=1.1020,
                    structure_reference="hl-1", bars_since_swing=99, now=NOW)
    assert r["reason_code"] == PMReason.DATA_STALE and not m.modify_log[len(m.modify_log)-2:] == []  # noqa


def test_trail_minimum_improvement_not_met():
    pm, m, tk, _ = rig("LONG"); _to_locked(pm, m, tk)
    cur = pm.states["sig"]["current_stop"]                # 1.1010
    swing = cur + CFG.trail_offset_pips * CFG.pip_size    # candidate == cur -> no improvement
    r = pm.evaluate("sig", market_price=1.1050, confirmed_swing=swing,
                    structure_reference="hl-x", bars_since_swing=1, now=NOW)
    assert r["reason_code"] == PMReason.TRAIL_NO_IMPROVEMENT


def test_trail_equal_stop_no_modification():
    pm, m, tk, _ = rig("LONG"); _to_locked(pm, m, tk)
    cur = pm.states["sig"]["current_stop"]
    swing = cur + CFG.trail_offset_pips * CFG.pip_size    # candidate exactly equals current
    n_before = len(m.modify_log)
    pm.evaluate("sig", market_price=1.1050, confirmed_swing=swing,
                structure_reference="eq", bars_since_swing=1, now=NOW)
    assert len(m.modify_log) == n_before                  # no modification


def test_trail_worse_long_stop_rejected():
    pm, m, tk, _ = rig("LONG"); _to_locked(pm, m, tk)
    r = pm.evaluate("sig", market_price=1.1050, confirmed_swing=1.0990,   # below current -> worse
                    structure_reference="bad", bars_since_swing=1, now=NOW)
    assert r["reason_code"] in (PMReason.STOP_LOOSEN_REJECTED, PMReason.STOP_WIDEN_REJECTED)


def test_trail_worse_short_stop_rejected():
    pm, m, tk, _ = rig("SHORT"); _to_locked(pm, m, tk, "SHORT")
    r = pm.evaluate("sig", market_price=1.0950, confirmed_swing=1.1010,   # above current -> worse
                    structure_reference="bad", bars_since_swing=1, now=NOW)
    assert r["reason_code"] in (PMReason.STOP_LOOSEN_REJECTED, PMReason.STOP_WIDEN_REJECTED)


def test_trail_broker_min_stop_distance_failure():
    cfg = PositionConfig(broker_min_stop_pips=100.0)
    pm, m, tk, _ = rig("LONG", cfg=cfg); _to_locked(pm, m, tk)
    r = pm.evaluate("sig", market_price=1.1021, confirmed_swing=1.1020,   # candidate too close to price
                    structure_reference="hl-1", bars_since_swing=1, now=NOW)
    assert r["reason_code"] == PMReason.BROKER_CONSTRAINT


def test_trail_duplicate_structure_reference():
    pm, m, tk, _ = rig("LONG"); _to_locked(pm, m, tk)
    pm.evaluate("sig", market_price=1.1050, confirmed_swing=1.1020,
                structure_reference="hl-1", bars_since_swing=1, now=NOW)
    r = pm.evaluate("sig", market_price=1.1051, confirmed_swing=1.1020,
                    structure_reference="hl-1", bars_since_swing=1, now=NOW)   # same ref
    assert r["reason_code"] == PMReason.TRAIL_NO_IMPROVEMENT


def test_trail_closed_bar_cadence_config():
    assert DEFAULT_PM_CONFIG.evaluation_cadence == "ON_CLOSED_BAR"


def test_trail_no_pivot_recompute_in_position_pkg():
    # trailing consumes strategy swings; the position package computes no pivots
    calc = (Path(_REPO) / "forex_swing_orb" / "position" / "spec.py").read_text()
    for banned in ("def pivot", "def fractal", "def compute_swing"):
        assert banned not in calc


# ============================ MANUAL (36-43) ==============================
def test_manual_tighter_long_adopted():
    pm, m, tk, _ = rig("LONG")
    m.position_by_ticket(tk).sl = 1.0990                  # manual raise (tighter)
    r = pm.evaluate("sig", market_price=1.1005, now=NOW)
    assert r["reason_code"] == PMReason.MANUAL_CHANGE_ADOPTED
    assert pm.states["sig"]["current_stop"] == 1.0990


def test_manual_tighter_short_adopted():
    pm, m, tk, _ = rig("SHORT")
    m.position_by_ticket(tk).sl = 1.1010                  # manual lower (tighter for short)
    r = pm.evaluate("sig", market_price=1.0995, now=NOW)
    assert r["reason_code"] == PMReason.MANUAL_CHANGE_ADOPTED


def test_manual_looser_rejected_and_restored():
    pm, m, tk, _ = rig("LONG")
    m.position_by_ticket(tk).sl = 1.0970                  # manual lower (looser)
    r = pm.evaluate("sig", market_price=1.1005, now=NOW)
    assert r["reason_code"] == PMReason.MANUAL_CHANGE_REJECTED
    assert m.position_by_ticket(tk).sl == 1.0980          # protective stop restored


def test_manual_stop_removal_escalated():
    pm, m, tk, _ = rig("LONG")
    m.position_by_ticket(tk).sl = 0.0                     # SL removed
    r = pm.evaluate("sig", market_price=1.1005, now=NOW)
    assert r["reason_code"] == PMReason.STOP_LOOSEN_REJECTED
    assert m.position_by_ticket(tk).sl == 1.0980          # protection restored


def test_manual_close_marks_closed():
    pm, m, tk, _ = rig("LONG")
    m.positions[tk].closed = True
    r = pm.evaluate("sig", market_price=1.1005, now=NOW)
    assert r["reason_code"] == PMReason.POSITION_CLOSED and r["phase"] == StopPhase.CLOSED


def test_manual_partial_close_reconciled():
    pm, m, tk, _ = rig("LONG")
    m.positions[tk].volume = 0.05                         # halved
    r = pm.evaluate("sig", market_price=1.1005, now=NOW)
    assert r["reason_code"] == PMReason.PARTIAL_CLOSED
    assert pm.states["sig"]["current_stop"] == 1.0980     # stop protection preserved


def test_manual_ticket_mismatch_fails_closed():
    pm, m, tk, _ = rig("LONG")
    r = pm.register("sig2", tk, "EURUSD", "LONG", 1.1000, 1.0980, 1.11, NOW)  # dup ticket
    assert r is None
    recs = PMAudit(_last_audit(pm)).records_for("sig2")
    assert recs and recs[-1]["reason_code"] == PMReason.RECONCILIATION_REQUIRED


def test_manual_symbol_mismatch_fails_closed():
    pm, m, tk, _ = rig("LONG")
    m.positions[tk].symbol = "GBPUSD"                     # broker symbol changed
    r = pm.evaluate("sig", market_price=1.1005, now=NOW)
    assert r["reason_code"] == PMReason.RECONCILIATION_REQUIRED
    assert r["reconciliation_status"] == "symbol_mismatch"


def _last_audit(pm):
    return pm.audit.path


# ============================ RECONCILIATION / RESTART (44-55) =============
def _restart(pm, path, m, cfg=CFG):
    return PositionManager(m, path, cfg)


def test_restart_after_breakeven():
    pm, m, tk, path = rig("LONG")
    pm.evaluate("sig", market_price=be_trigger("LONG"), now=NOW)
    pm2 = _restart(pm, path, m)
    st = pm2.recover("sig", NOW)
    assert st["phase"] == StopPhase.BREAKEVEN
    assert abs(st["current_stop"] - m.position_by_ticket(tk).sl) < 1e-12
    assert abs(spec.initial_risk("LONG", st["entry"], st["initial_stop"]) - 0.0020) < 1e-12


def test_restart_after_profit_lock():
    pm, m, tk, path = rig("LONG"); _to_locked(pm, m, tk)
    pm2 = _restart(pm, path, m)
    st = pm2.recover("sig", NOW)
    assert st["phase"] == StopPhase.LOCKED


def test_restart_after_trailing():
    pm, m, tk, path = rig("LONG"); _to_locked(pm, m, tk)
    pm.evaluate("sig", market_price=1.1050, confirmed_swing=1.1020,
                structure_reference="hl-1", bars_since_swing=1, now=NOW)
    pm2 = _restart(pm, path, m)
    st = pm2.recover("sig", NOW)
    assert st["phase"] == StopPhase.TRAILING


def test_crash_before_broker_ack_no_double_and_recovers():
    pm, m, tk, path = rig("LONG"); m.script_modify("applied_but_unacked")
    r = pm.evaluate("sig", market_price=be_trigger("LONG"), now=NOW)
    assert r["reason_code"] == PMReason.RECONCILIATION_REQUIRED
    n_mods = len(m.modify_log)                             # exactly one attempt
    # restart + recover: adopt broker truth, never re-issue
    pm2 = _restart(pm, path, m)
    st = pm2.recover("sig", NOW)
    assert len(m.modify_log) == n_mods                    # no blind retry during recovery
    assert abs(st["current_stop"] - m.position_by_ticket(tk).sl) < 1e-12


def test_crash_after_modify_before_audit_recovers_from_broker():
    pm, m, tk, path = rig("LONG"); m.script_modify("applied_but_unacked")
    pm.evaluate("sig", market_price=be_trigger("LONG"), now=NOW)  # broker applied, no SET audit
    pm2 = _restart(pm, path, m)
    st = pm2.recover("sig", NOW)
    assert st["current_stop"] == m.position_by_ticket(tk).sl      # rebuilt from broker truth


def test_unknown_broker_outcome_reconciliation():
    pm, m, tk, _ = rig("LONG"); m.script_modify("requote")   # non-constraint... actually constraint
    # force a truly unknown retcode path via disconnect during verify
    m.script_modify("disconnect")
    r = pm.evaluate("sig", market_price=be_trigger("LONG"), now=NOW)
    assert r["reason_code"] in (PMReason.RECONCILIATION_REQUIRED, PMReason.BROKER_CONSTRAINT)


def test_disconnected_terminal_no_modification():
    pm, m, tk, _ = rig("LONG"); m.connected = False
    n = len(m.modify_log)
    r = pm.evaluate("sig", market_price=be_trigger("LONG"), now=NOW)
    assert r["reason_code"] == PMReason.DATA_STALE and len(m.modify_log) == n


def test_no_broker_position_marks_closed():
    pm, m, tk, _ = rig("LONG"); m.positions[tk].closed = True
    r = pm.evaluate("sig", market_price=1.1005, now=NOW)
    assert r["reason_code"] == PMReason.POSITION_CLOSED


def test_restart_no_audit_returns_none():
    m = mock_mt5.MockMT5(); m.add_symbol("EURUSD")
    pm = PositionManager(m, Path(tempfile.mkdtemp()) / "e.jsonl")
    assert pm.recover("nope", NOW) is None


def test_no_blind_retry_on_uncertain():
    pm, m, tk, _ = rig("LONG"); m.script_modify("applied_but_unacked")
    pm.evaluate("sig", market_price=be_trigger("LONG"), now=NOW)
    n = len(m.modify_log)
    # subsequent cycle reconciles broker truth (adopt), does NOT re-modify
    r = pm.evaluate("sig", market_price=be_trigger("LONG") + 0.0001, now=NOW)
    assert r["reason_code"] == PMReason.MANUAL_CHANGE_ADOPTED
    assert len(m.modify_log) == n


# ============================ GENERAL (56-68) =============================
def test_precedence_position_closed_over_management():
    pm, m, tk, _ = rig("LONG"); m.positions[tk].closed = True
    # even with a BE trigger price, closed-position reconciliation wins
    r = pm.evaluate("sig", market_price=be_trigger("LONG"), now=NOW)
    assert r["reason_code"] == PMReason.POSITION_CLOSED


def test_one_action_per_evaluation():
    pm, m, tk, _ = rig("LONG")
    n = len(m.modify_log)
    pm.evaluate("sig", market_price=be_trigger("LONG"), now=NOW)
    assert len(m.modify_log) - n == 1                     # at most one modification


def test_never_widen_invariant():
    pm, m, tk, _ = rig("LONG"); _to_locked(pm, m, tk)     # current stop ~1.1010
    r = pm.evaluate("sig", market_price=1.1050, confirmed_swing=1.0960,   # beyond initial risk
                    structure_reference="w", bars_since_swing=1, now=NOW)
    assert r["reason_code"] == PMReason.STOP_WIDEN_REJECTED


def test_never_loosen_invariant():
    pm, m, tk, _ = rig("LONG"); _to_locked(pm, m, tk)     # current stop ~1.1010
    r = pm.evaluate("sig", market_price=1.1050, confirmed_swing=1.1005,   # backward but within initial
                    structure_reference="l", bars_since_swing=1, now=NOW)
    assert r["reason_code"] == PMReason.STOP_LOOSEN_REJECTED


def test_long_short_symmetry_be():
    rl = rig("LONG")[0].evaluate("sig", market_price=be_trigger("LONG"), now=NOW)
    rs = rig("SHORT")[0].evaluate("sig", market_price=be_trigger("SHORT"), now=NOW)
    assert rl["reason_code"] == rs["reason_code"] == PMReason.BREAKEVEN_SET


def test_deterministic_audit_record_schema():
    from forex_swing_orb.position import AUDIT_RECORD_FIELDS, validate_audit_record
    pm, m, tk, _ = rig("LONG")
    r = pm.evaluate("sig", market_price=be_trigger("LONG"), now=NOW)
    ok, why = validate_audit_record(r)
    assert ok, why
    assert set(r.keys()) == set(AUDIT_RECORD_FIELDS)


def test_no_ai_stop_authority_and_no_networking():
    src = (Path(_REPO) / "forex_swing_orb" / "ea_mt5" / "position_manager.py").read_text()
    for tok in ("import socket", "urllib", "requests.get", "WebRequest(",
                "openai", "anthropic", "llm", "agent"):
        assert tok.lower() not in src.lower()


def test_no_new_trade_entry_in_position_manager():
    src = (Path(_REPO) / "forex_swing_orb" / "ea_mt5" / "position_manager.py").read_text()
    # PM modifies/closes existing positions only; it never opens/directs a trade
    assert "order_send(" not in src


def test_single_position_manager_class():
    import re
    root = Path(_REPO) / "forex_swing_orb"
    n = 0
    for p in root.rglob("*.py"):
        if "test" in p.name:
            continue
        n += len(re.findall(r"^class PositionManager\b", p.read_text(), re.MULTILINE))
    assert n == 1


def test_audit_append_only_and_deterministic():
    pm, m, tk, path = rig("LONG")
    pm.evaluate("sig", market_price=be_trigger("LONG"), now=NOW)
    lines1 = Path(path).read_text().count("\n")
    pm.evaluate("sig", market_price=1.1025, now=NOW)
    lines2 = Path(path).read_text().count("\n")
    assert lines2 > lines1                                # append-only grows


# ============================ Phase 4D-R (F1/F2/F3) =======================
def _betrig(direction="LONG"):
    return be_trigger(direction)


def _off_grid_mock():
    """A mock whose broker NORMALIZES stops to the 5-digit tick grid (simulating
    a real terminal): any modify_stop snaps sl to 5 digits."""
    m = mock_mt5.MockMT5(); m.add_symbol("EURUSD")
    real = m.modify_stop
    def snap(ticket, sl):
        res = real(ticket, round(sl, 5))          # broker stores tick-grid value
        return res
    m.modify_stop = snap
    return m


def test_f2_broker_normalization_no_false_reconcile():
    # candidate is quantized before sending; broker stores the same tick -> verify
    # ok and no phantom manual-change on the next cycle
    pm, m, tk, _ = rig("LONG")
    r = pm.evaluate("sig", market_price=_betrig(), now=NOW)
    assert r["reason_code"] == PMReason.BREAKEVEN_SET
    assert r["applied_stop"] == round(r["applied_stop"], 5)       # on the tick grid
    r2 = pm.evaluate("sig", market_price=_betrig() + 0.0001, now=NOW)
    assert r2["reason_code"] not in (PMReason.MANUAL_CHANGE_ADOPTED, PMReason.MANUAL_CHANGE_REJECTED)


def test_f2_broker_normalized_weaker_is_uncertain():
    pm, m, tk, _ = rig("LONG")
    real = m.modify_stop
    def weaker(ticket, sl):
        res = real(ticket, sl); p = m.positions.get(ticket)
        if p:
            p.sl = sl - 0.0005                     # broker normalized WEAKER
        return res
    m.modify_stop = weaker
    r = pm.evaluate("sig", market_price=_betrig(), now=NOW)
    assert r["reason_code"] == PMReason.RECONCILIATION_REQUIRED   # never treated as success
    assert pm.states["sig"]["phase"] == StopPhase.INITIAL


def test_f2_tolerant_equality_ticks():
    pm, m, tk, _ = rig("LONG")
    # values within the same tick compare equal; a full tick apart do not
    assert pm._eq_stop(1.10000, 1.100004, "EURUSD") is True
    assert pm._eq_stop(1.10000, 1.10001, "EURUSD") is False


def test_f3_exact_one_pip_improvement_advances():
    pm, m, tk, _ = rig("LONG")
    pm.evaluate("sig", market_price=_betrig(), now=NOW)
    R = spec.initial_risk("LONG", 1.1000, 1.0980)
    pm.evaluate("sig", market_price=spec.profit_lock_trigger_price("LONG", 1.1000, R, CFG), now=NOW)
    cur = pm.states["sig"]["current_stop"]
    swing = cur + CFG.trail_offset_pips * CFG.pip_size + CFG.min_trail_improvement_pips * CFG.pip_size
    r = pm.evaluate("sig", market_price=1.1060, confirmed_swing=swing,
                    structure_reference="p1", bars_since_swing=1, now=NOW)
    assert r["reason_code"] == PMReason.TRAIL_ADVANCED


def test_f2_normalizing_broker_full_lifecycle():
    m = _off_grid_mock()
    res = m.order_send({"symbol": "EURUSD", "volume": 0.1, "type": BUY, "price": 1.1000,
                        "sl": 1.0980, "tp": 1.11, "comment": "sig"})
    pm = PositionManager(m, Path(tempfile.mkdtemp()) / "pm.jsonl")
    pm.register("sig", res.order, "EURUSD", "LONG", 1.1000, 1.0980, 1.11, NOW)
    r = pm.evaluate("sig", market_price=_betrig(), now=NOW)
    assert r["reason_code"] == PMReason.BREAKEVEN_SET and r["broker_result"] == "DONE"


def test_f1_intent_audit_failure_fails_closed():
    pm, m, tk, _ = rig("LONG")
    orig = pm.audit.emit
    def boom(rec):
        raise OSError("disk full")
    pm.audit.emit = boom
    n = len(m.modify_log)
    r = pm.evaluate("sig", market_price=_betrig(), now=NOW)     # must NOT raise
    pm.audit.emit = orig
    assert r["reason_code"] == PMReason.RECONCILIATION_REQUIRED
    assert r["reconciliation_status"] == "audit_intent_failed"
    assert len(m.modify_log) == n                                # no modification attempted
    assert pm.states["sig"]["phase"] == StopPhase.INITIAL


def test_f1_completion_audit_failure_no_throw_and_recovers():
    pm, m, tk, path = rig("LONG")
    orig = pm.audit.emit
    seq = {"n": 0}
    def flaky(rec):
        seq["n"] += 1
        if seq["n"] == 2:                                        # 1=intent ok, 2=completion fails
            raise OSError("disk on completion")
        return orig(rec)
    pm.audit.emit = flaky
    r = pm.evaluate("sig", market_price=_betrig(), now=NOW)      # must NOT raise
    pm.audit.emit = orig
    # broker applied and in-memory state reflects broker truth
    assert pm.states["sig"]["current_stop"] == m.position_by_ticket(tk).sl
    # restart recovery rebuilds from broker truth, no blind retry
    n = len(m.modify_log)
    pm2 = PositionManager(m, path)
    st = pm2.recover("sig", NOW)
    assert len(m.modify_log) == n
    assert st["current_stop"] == m.position_by_ticket(tk).sl


def test_f1_no_duplicate_modification_across_intent_and_completion():
    pm, m, tk, _ = rig("LONG")
    n = len(m.modify_log)
    pm.evaluate("sig", market_price=_betrig(), now=NOW)
    assert len(m.modify_log) - n == 1                            # exactly one broker modify


def test_f2_be_profitlock_trailing_with_normalized_prices():
    m = _off_grid_mock()
    res = m.order_send({"symbol": "EURUSD", "volume": 0.1, "type": BUY, "price": 1.10003,
                        "sl": 1.09803, "tp": 1.11, "comment": "sig"})   # off-grid inputs
    pm = PositionManager(m, Path(tempfile.mkdtemp()) / "pm.jsonl")
    st = pm.register("sig", res.order, "EURUSD", "LONG", 1.10003, 1.09803, 1.11, NOW)
    assert st is not None                                        # R valid (0.002)
    R = spec.initial_risk("LONG", 1.10003, 1.09803)
    r = pm.evaluate("sig", market_price=spec.breakeven_trigger_price("LONG", 1.10003, R, CFG), now=NOW)
    assert r["reason_code"] == PMReason.BREAKEVEN_SET
    assert r["applied_stop"] == round(r["applied_stop"], 5)      # quantized to grid
