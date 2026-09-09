"""M-6 full-close confirmation hardening (PR-3M).

The Position Manager must NEVER enter the terminal CLOSED phase until authoritative
broker truth proves the position is FULLY closed. A success-like close retcode
(DONE / EA NO_OP_CLOSED) is only REQUEST-ACCEPTED — it is not proof of a flat book
under partial fills, residual volume, delayed terminal state, or DONE_PARTIAL-like
conditions.

Canonical closure proof is the single shared owner ``position.closure.
confirm_full_close`` (via ``PositionManager._confirmed_closed``) — the SAME proof
reconcile/recover already require. No second "is closed" algorithm, no new broker
seam, no new reconciliation path. Deterministic; MockMT5 test double; no real MT5.
"""

from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from forex_swing_orb.ea_mt5 import mock_mt5                                  # noqa: E402
from forex_swing_orb.ea_mt5.position_manager import PositionManager          # noqa: E402
from forex_swing_orb.position import DEFAULT_PM_CONFIG                        # noqa: E402
from forex_swing_orb.position.contract import StopPhase, PMReason            # noqa: E402

NOW = datetime(2024, 1, 25, 12, 0, tzinfo=timezone.utc)
FRI_2000_UTC = datetime(2026, 1, 9, 20, 0, tzinfo=timezone.utc)   # Friday flatten cutoff
SID = "0123456789abcdef"
CFG = DEFAULT_PM_CONFIG
BUY = mock_mt5.ORDER_TYPE_BUY


def _rig(entry=1.1000, sl=1.0980, tp=1.1100, cfg=CFG, volume=0.10, audit_path=None):
    m = mock_mt5.MockMT5(); m.add_symbol("EURUSD")
    res = m.order_send({"symbol": "EURUSD", "volume": volume, "type": BUY,
                        "price": entry, "sl": sl, "tp": tp, "comment": SID})
    path = audit_path or (Path(tempfile.mkdtemp()) / "pm.jsonl")
    pm = PositionManager(m, path, cfg)
    pm.register(SID, res.order, "EURUSD", "LONG", entry, sl, tp, NOW)
    return pm, m, res.order, path


def _kill(pm):
    return pm.evaluate(SID, market_price=1.1005, now=NOW, kill_switch=True)


# ============================================================================
# FULL CLOSE
# ============================================================================
def test_1_successful_close_position_absent_marks_closed():
    pm, m, tk, _ = _rig()
    r = _kill(pm)                                   # mock full-closes -> deals confirm flat
    assert r["reason_code"] == PMReason.KILL_SWITCH
    assert pm.states[SID]["phase"] == StopPhase.CLOSED
    assert r["reconciliation_status"] == "close_confirmed_flat"


def test_2_absent_without_deal_proof_not_closed():
    # position present at reconcile; close returns DONE and the position becomes
    # absent, but deal history is unavailable -> absence alone is NOT proof of
    # closure (H1) -> NOT CLOSED (reached via the _confirm_close verification path).
    pm, m, tk, _ = _rig()
    m.deals_for_position = lambda _t: None         # no positive netted-flat proof
    r = _kill(pm)
    assert pm.states[SID]["phase"] != StopPhase.CLOSED
    assert r["reason_code"] == PMReason.RECONCILIATION_REQUIRED
    assert r["reconciliation_status"] == "close_absent_unconfirmed"


def test_3_already_absent_confirmed_closed_idempotent():
    pm, m, tk, _ = _rig()
    _kill(pm)                                       # -> CLOSED
    assert pm.states[SID]["phase"] == StopPhase.CLOSED
    n = len(m.close_log)
    r = pm.evaluate(SID, market_price=1.1005, now=NOW, kill_switch=True)
    assert r["reason_code"] == PMReason.POSITION_CLOSED   # reconcile short-circuits
    assert len(m.close_log) == n                   # NO second close on a flat book


# ============================================================================
# PARTIAL / RESIDUAL
# ============================================================================
def test_4_successful_result_residual_position_not_closed():
    pm, m, tk, _ = _rig()
    m.script_close("residual")                     # DONE, but position fully remains
    r = _kill(pm)
    assert pm.states[SID]["phase"] != StopPhase.CLOSED
    assert r["reason_code"] == PMReason.RECONCILIATION_REQUIRED
    assert r["reconciliation_status"] == "residual_after_close"


def test_5_partial_volume_remains_reconciliation():
    pm, m, tk, _ = _rig(volume=1.00)
    m.script_close(("partial", 0.40))              # closed 0.60, 0.40 residual remains
    r = _kill(pm)
    assert pm.states[SID]["phase"] != StopPhase.CLOSED
    assert r["reason_code"] == PMReason.PARTIAL_CLOSED
    assert pm.states[SID]["volume"] == 0.40


def test_6_residual_remains_managed_and_owned():
    pm, m, tk, _ = _rig()
    m.script_close("residual")
    _kill(pm)
    # still tracked and still owned by the same signal (never abandoned)
    assert SID in pm.states
    assert pm._ticket_owner[tk] == SID
    assert m.position_by_ticket(tk) is not None     # residual exposure still open


def test_7_next_cycle_reattempts_close_on_residual():
    pm, m, tk, _ = _rig()
    m.script_close("residual")                      # cycle 1: residual remains
    _kill(pm)
    n = len(m.close_log)
    _kill(pm)                                        # cycle 2: mock full-closes now
    assert len(m.close_log) == n + 1                # close was re-attempted
    assert pm.states[SID]["phase"] == StopPhase.CLOSED


def test_8_friday_flatten_stays_active_on_residual():
    pm, m, tk, _ = _rig(cfg=CFG)
    m.script_close("residual")                         # Friday flatten fires but leaves residual
    r = pm.evaluate(SID, market_price=1.1005, now=FRI_2000_UTC)
    # the flatten trigger fired (WEEKEND_EXIT), but the returned outcome is the
    # broker-truth confirmation: residual remains, so NOT CLOSED and still managed.
    assert pm.states[SID]["phase"] != StopPhase.CLOSED
    assert r["reconciliation_status"] == "residual_after_close"
    assert m.position_by_ticket(tk) is not None        # residual not abandoned into the weekend
    assert pm._ticket_owner[tk] == SID


# ============================================================================
# DISCONNECT
# ============================================================================
def test_9_successful_result_verification_disconnect_not_closed():
    pm, m, tk, _ = _rig()
    m.script_close("disconnect_after")             # close DONE, then link drops
    r = _kill(pm)
    assert pm.states[SID]["phase"] != StopPhase.CLOSED
    assert r["reason_code"] == PMReason.RECONCILIATION_REQUIRED
    assert r["reconciliation_status"] == "close_unverified_disconnected"


def test_10_reconnect_absent_marks_closed():
    pm, m, tk, _ = _rig()
    m.script_close("disconnect_after")
    _kill(pm)                                       # NOT closed (unverified)
    m.connected = True                             # reconnect; broker confirms flat
    r = pm.evaluate(SID, market_price=1.1005, now=NOW, kill_switch=True)
    assert pm.states[SID]["phase"] == StopPhase.CLOSED
    assert r["reconciliation_status"] == "no_position_confirmed"


def test_11_reconnect_residual_continues_management():
    pm, m, tk, _ = _rig()
    m.script_close("residual", "disconnect_after")  # residual + a disconnect on verify
    # first: residual (still connected) -> not closed
    _kill(pm)
    assert pm.states[SID]["phase"] != StopPhase.CLOSED
    m.connected = True
    # position still open (residual) -> management continues, not CLOSED
    r = pm.evaluate(SID, market_price=1.1005, now=NOW)
    assert pm.states[SID]["phase"] != StopPhase.CLOSED
    assert m.position_by_ticket(tk) is not None


# ============================================================================
# RETCODES
# ============================================================================
def test_12_done_alone_does_not_imply_closed():
    pm, m, tk, _ = _rig()
    m.script_close("residual")                     # retcode DONE but not flat
    _kill(pm)
    assert pm.states[SID]["phase"] != StopPhase.CLOSED


def test_13_done_partial_like_does_not_imply_closed():
    pm, m, tk, _ = _rig(volume=1.00)
    m.script_close(("partial", 0.25))              # DONE_PARTIAL-like: residual 0.25
    _kill(pm)
    assert pm.states[SID]["phase"] != StopPhase.CLOSED


def test_14_rejection_does_not_imply_closed():
    pm, m, tk, _ = _rig()
    m.script_close("reject")
    r = _kill(pm)
    assert pm.states[SID]["phase"] != StopPhase.CLOSED
    assert r["reason_code"] == PMReason.RECONCILIATION_REQUIRED
    assert r["broker_result"] == "CONSTRAINT"


def test_15_malformed_result_fails_closed():
    pm, m, tk, _ = _rig()

    class _Bad:
        retcode = 999999                            # unknown retcode object
    m.position_close = lambda _t, reason=None: _Bad()
    r = _kill(pm)
    assert pm.states[SID]["phase"] != StopPhase.CLOSED
    assert r["reason_code"] == PMReason.RECONCILIATION_REQUIRED


def test_16_unknown_retcode_fails_closed():
    pm, m, tk, _ = _rig()
    m.position_close = lambda _t, reason=None: mock_mt5.OrderResult(
        retcode=mock_mt5.TRADE_RETCODE_TIMEOUT, position=_t)
    r = _kill(pm)
    assert pm.states[SID]["phase"] != StopPhase.CLOSED
    assert r["reason_code"] == PMReason.RECONCILIATION_REQUIRED


# ============================================================================
# RESTART
# ============================================================================
def test_17_restart_after_full_close_recovers_closed():
    pm, m, tk, path = _rig()
    _kill(pm)                                       # -> CLOSED (confirmed)
    pm2 = PositionManager(m, path, CFG)
    rec = pm2.recover(SID, NOW)
    assert rec["phase"] == StopPhase.CLOSED
    assert rec["reconciliation_status"] == "no_position_confirmed"


def test_18_restart_after_partial_close_recovers_residual():
    pm, m, tk, path = _rig(volume=1.00)
    m.script_close(("partial", 0.40))
    _kill(pm)                                       # residual 0.40, not CLOSED
    pm2 = PositionManager(m, path, CFG)
    rec = pm2.recover(SID, NOW)
    assert rec["phase"] != StopPhase.CLOSED         # residual recovered as active
    assert m.position_by_ticket(tk) is not None


def test_19_restart_result_before_verification_broker_truth_decides():
    pm, m, tk, path = _rig()
    m.script_close("disconnect_after")
    _kill(pm)                                       # unverified, not CLOSED
    m.connected = True
    pm2 = PositionManager(m, path, CFG)
    rec = pm2.recover(SID, NOW)                   # broker truth: flat -> CLOSED
    assert rec["phase"] == StopPhase.CLOSED


def test_20_repeated_restart_idempotent():
    pm, m, tk, path = _rig()
    _kill(pm)
    p1 = PositionManager(m, path, CFG).recover(SID, NOW)
    p2 = PositionManager(m, path, CFG).recover(SID, NOW)
    assert p1["phase"] == p2["phase"] == StopPhase.CLOSED
    assert len(m.close_log) == 1                    # recovery never issues a close


# ============================================================================
# OUTCOME (realized-R authority unchanged)
# ============================================================================
def test_21_partial_close_writes_no_final_outcome():
    pm, m, tk, path = _rig(volume=1.00)
    m.script_close(("partial", 0.40))
    _kill(pm)
    from forex_swing_orb.agents.memory import MemoryStore
    from forex_swing_orb.manage.outcome import OutcomeReconciler
    mem = MemoryStore(str(Path(tempfile.mkdtemp()) / "memory"))
    OutcomeReconciler(m, pm.audit, mem, now_fn=lambda: NOW).run(NOW)
    assert mem.query(kind="execution_outcome", limit=100) == []   # residual -> no outcome


def test_22_full_close_writes_final_outcome_once():
    pm, m, tk, path = _rig()
    _kill(pm)                                       # confirmed CLOSED
    from forex_swing_orb.agents.memory import MemoryStore
    from forex_swing_orb.manage.outcome import OutcomeReconciler
    mem = MemoryStore(str(Path(tempfile.mkdtemp()) / "memory"))
    rc = OutcomeReconciler(m, pm.audit, mem, now_fn=lambda: NOW)
    out1 = rc.run(NOW)
    assert len(out1) == 1 and out1[0]["status"] in ("CLOSED", "R_UNDEFINED")
    out2 = rc.run(NOW)                              # idempotent
    assert out2 == []
    assert len(mem.query(kind="execution_outcome", limit=100)) == 1


def test_23_no_duplicate_outcome_across_cycles():
    pm, m, tk, path = _rig()
    _kill(pm)
    from forex_swing_orb.agents.memory import MemoryStore
    from forex_swing_orb.manage.outcome import OutcomeReconciler
    mem = MemoryStore(str(Path(tempfile.mkdtemp()) / "memory"))
    rc = OutcomeReconciler(m, pm.audit, mem, now_fn=lambda: NOW)
    rc.run(NOW); rc.run(NOW); rc.run(NOW)
    assert len(mem.query(kind="execution_outcome", limit=100)) == 1


# ============================================================================
# FRIDAY
# ============================================================================
def test_25_friday_full_close_marks_closed():
    pm, m, tk, _ = _rig()
    r = pm.evaluate(SID, market_price=1.1005, now=FRI_2000_UTC)
    assert r["reason_code"] == PMReason.WEEKEND_EXIT
    assert pm.states[SID]["phase"] == StopPhase.CLOSED


def test_26_friday_partial_still_managed():
    pm, m, tk, _ = _rig(volume=1.00)
    m.script_close(("partial", 0.30))
    r = pm.evaluate(SID, market_price=1.1005, now=FRI_2000_UTC)
    assert r["reason_code"] == PMReason.PARTIAL_CLOSED
    assert pm.states[SID]["phase"] != StopPhase.CLOSED


def test_27_friday_disconnect_reconciliation_required():
    pm, m, tk, _ = _rig()
    m.script_close("disconnect_after")
    r = pm.evaluate(SID, market_price=1.1005, now=FRI_2000_UTC)
    assert pm.states[SID]["phase"] != StopPhase.CLOSED
    assert r["reconciliation_status"] == "close_unverified_disconnected"


def test_28_weekend_residual_not_silently_abandoned():
    pm, m, tk, _ = _rig()
    m.script_close("residual")
    pm.evaluate(SID, market_price=1.1005, now=FRI_2000_UTC)
    # residual exposure remains owned and managed into the weekend attempt
    assert pm.states[SID]["phase"] != StopPhase.CLOSED
    assert m.position_by_ticket(tk) is not None
    assert pm._ticket_owner[tk] == SID


# ============================================================================
# AUTHORITY
# ============================================================================
def test_32_confirm_full_close_is_the_sole_closure_proof():
    # _protective_exit's confirmation path must delegate to the shared closure owner.
    src = (Path(__file__).resolve().parents[1] / "position_manager.py").read_text()
    assert "_confirmed_closed" in src               # PM uses the shared proof
    from forex_swing_orb.position import closure
    assert hasattr(closure, "confirm_full_close")   # single source of truth exists


def test_33_no_duplicate_close_authority_in_pm_source():
    src = (Path(__file__).resolve().parents[1] / "position_manager.py").read_text()
    # exactly one place transitions to CLOSED from a close request (via _confirm_close),
    # and closure proof is never re-implemented (no second netted-flat aggregator).
    assert "def _confirm_close" in src
    assert "def confirm_full_close" not in src      # not redefined here


def test_36_pr3j_and_strategy_untouched_by_close_fix():
    src = (Path(__file__).resolve().parents[1] / "position_manager.py").read_text()
    for banned in ("def order_send", "risk_fraction =", "def evaluate_symbol"):
        assert banned not in src


def test_39_disconnect_before_close_request_still_uncertain():
    # pre-existing behavior preserved: a disconnect DURING the close request (not
    # after) is UNCERTAIN, never CLOSED.
    pm, m, tk, _ = _rig()
    m.connected = False
    r = pm.evaluate(SID, market_price=1.1005, now=NOW, kill_switch=True)
    assert pm.states[SID]["phase"] != StopPhase.CLOSED
    assert r["reason_code"] in (PMReason.DATA_STALE, PMReason.RECONCILIATION_REQUIRED)
