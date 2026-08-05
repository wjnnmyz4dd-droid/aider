"""Phase 8E-R G4 — manager restart phase-recovery orchestration.

The production ManagerService must reconstruct each open position's lifecycle phase
on restart through the accepted PositionManager.recover() (the sole phase engine),
not reset it to INITIAL via register(). These tests drive the register-vs-recover
decision, the phase allow-list (only verified terminal outcomes advance phase),
broker-truth fast-forward via the accepted evaluate path, and every fail-closed
conflict case. Deterministic; FakeMt5Client; injected time; no networking.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from forex_swing_orb.bridge import serialize
from forex_swing_orb.bridge.paths import BridgePaths
from forex_swing_orb.live import mt5_client as mc
from forex_swing_orb.manage.service import ManagerService
from forex_swing_orb.position import spec
from forex_swing_orb.position.contract import (DEFAULT_PM_CONFIG as CFG, PMReason,
                                              StopPhase, build_audit_record)
from conftest import NOW, make_client

SID = "a1b2c3d4e5f60718"
SID2 = "00ff00ff00ff00ff"
TICKET = 5000001
TICKET2 = 5000002
ENTRY, ISTOP = 1.10000, 1.09800
R = spec.initial_risk("LONG", ENTRY, ISTOP)                 # 0.00200
BE = spec.breakeven_stop("LONG", ENTRY, CFG)               # 1.10020
BE_TRIG = spec.breakeven_trigger_price("LONG", ENTRY, R, CFG)      # 1.10200
LOCK = spec.profit_lock_stop("LONG", ENTRY, R, CFG)        # 1.10100
LOCK_TRIG = spec.profit_lock_trigger_price("LONG", ENTRY, R, CFG)  # 1.10300


# --------------------------------------------------------------------------- #
# harness
# --------------------------------------------------------------------------- #
def _rec(phase, reason, applied_stop=None, *, sid=SID, ticket=TICKET, entry=ENTRY,
         initial_stop=ISTOP, symbol="EURUSD", direction="LONG", broker_result=None,
         reconciliation_status=None):
    return build_audit_record(
        reason, serialize.iso_utc(NOW), signal_id=sid, ticket=ticket, symbol=symbol,
        direction=direction, phase=phase, entry_price=entry, initial_stop=initial_stop,
        immutable_initial_R=spec.initial_risk(direction, entry, initial_stop),
        applied_stop=applied_stop, broker_result=broker_result,
        reconciliation_status=reconciliation_status)


def _pos(ticket=TICKET, sl=ISTOP, comment=SID, price_current=1.10050, symbol="EURUSD"):
    return SimpleNamespace(ticket=ticket, symbol=symbol, type=mc.POSITION_TYPE_BUY,
                           volume=0.1, price_open=ENTRY, sl=sl, tp=1.10600,
                           price_current=price_current, comment=comment)


def _write_audit(runtime_dir, records, *, raw=None):
    p = Path(runtime_dir) / "pm_audit.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        if raw is not None:
            f.write(raw)
            return
        for r in records:
            f.write(serialize.canonical_json(r) + "\n")


def _manager(env_config, positions, records=None, *, raw=None, now=NOW):
    """Build a manager (simulating a restart) with pre-existing PM audit history and
    broker truth. Returns (mgr, paths)."""
    env, paths = env_config()
    client = make_client(positions)
    mgr = ManagerService.build_from_env(env=env, client=client, now_fn=lambda: now)
    if records is not None or raw is not None:
        _write_audit(paths["runtime_dir"], records, raw=raw)
    return mgr, paths


def _archive_enter(paths, sid=SID, entry=ENTRY, sl=ISTOP, tp=1.10600):
    bp = BridgePaths(paths["bridge_root"]).ensure()
    instr = {"signal_id": sid, "symbol": "EURUSD", "direction": "LONG",
             "entry_price": entry, "stop_loss": sl, "take_profit": tp}
    (bp.archive_accepted / f"{sid}.json").write_text(
        serialize.canonical_json(instr), encoding="utf-8")


# --------------------------------------------------------------------------- #
# 1-6: phase is reconstructed from verified terminal outcomes
# --------------------------------------------------------------------------- #
def test_restart_after_initial(env_config):
    mgr, _ = _manager(env_config, [_pos(sl=ISTOP)],
                      [_rec(StopPhase.INITIAL, PMReason.INITIAL, ISTOP)])
    mgr.discover_and_register(NOW)
    assert mgr.pm.states[SID]["phase"] == StopPhase.INITIAL
    assert mgr.pm.states[SID]["current_stop"] == ISTOP


def test_restart_after_breakeven(env_config):
    mgr, _ = _manager(env_config, [_pos(sl=BE)], [
        _rec(StopPhase.INITIAL, PMReason.INITIAL, ISTOP),
        _rec(StopPhase.BREAKEVEN, PMReason.BREAKEVEN_SET, BE, broker_result="DONE")])
    mgr.discover_and_register(NOW)
    assert mgr.pm.states[SID]["phase"] == StopPhase.BREAKEVEN
    assert mgr.pm.states[SID]["current_stop"] == BE


def test_restart_after_locked(env_config):
    mgr, _ = _manager(env_config, [_pos(sl=LOCK)], [
        _rec(StopPhase.INITIAL, PMReason.INITIAL, ISTOP),
        _rec(StopPhase.BREAKEVEN, PMReason.BREAKEVEN_SET, BE, broker_result="DONE"),
        _rec(StopPhase.LOCKED, PMReason.PROFIT_LOCK_SET, LOCK, broker_result="DONE")])
    mgr.discover_and_register(NOW)
    assert mgr.pm.states[SID]["phase"] == StopPhase.LOCKED
    assert mgr.pm.states[SID]["current_stop"] == LOCK


def test_restart_after_one_trailing_advance(env_config):
    trail = 1.10150
    mgr, _ = _manager(env_config, [_pos(sl=trail)], [
        _rec(StopPhase.INITIAL, PMReason.INITIAL, ISTOP),
        _rec(StopPhase.BREAKEVEN, PMReason.BREAKEVEN_SET, BE, broker_result="DONE"),
        _rec(StopPhase.LOCKED, PMReason.PROFIT_LOCK_SET, LOCK, broker_result="DONE"),
        _rec(StopPhase.TRAILING, PMReason.TRAIL_ADVANCED, trail, broker_result="DONE")])
    mgr.discover_and_register(NOW)
    assert mgr.pm.states[SID]["phase"] == StopPhase.TRAILING
    assert mgr.pm.states[SID]["current_stop"] == trail


def test_restart_after_multiple_trailing_advances(env_config):
    t1, t2 = 1.10150, 1.10250
    mgr, _ = _manager(env_config, [_pos(sl=t2)], [
        _rec(StopPhase.INITIAL, PMReason.INITIAL, ISTOP),
        _rec(StopPhase.BREAKEVEN, PMReason.BREAKEVEN_SET, BE, broker_result="DONE"),
        _rec(StopPhase.LOCKED, PMReason.PROFIT_LOCK_SET, LOCK, broker_result="DONE"),
        _rec(StopPhase.TRAILING, PMReason.TRAIL_ADVANCED, t1, broker_result="DONE"),
        _rec(StopPhase.TRAILING, PMReason.TRAIL_ADVANCED, t2, broker_result="DONE")])
    mgr.discover_and_register(NOW)
    assert mgr.pm.states[SID]["phase"] == StopPhase.TRAILING
    assert mgr.pm.states[SID]["current_stop"] == t2      # latest verified trail


def test_restart_after_manual_tighter_adoption(env_config):
    manual = 1.10050
    mgr, _ = _manager(env_config, [_pos(sl=manual)], [
        _rec(StopPhase.INITIAL, PMReason.INITIAL, ISTOP),
        _rec(StopPhase.BREAKEVEN, PMReason.BREAKEVEN_SET, BE, broker_result="DONE"),
        _rec(StopPhase.BREAKEVEN, PMReason.MANUAL_CHANGE_ADOPTED, manual)])
    mgr.discover_and_register(NOW)
    assert mgr.pm.states[SID]["phase"] == StopPhase.BREAKEVEN
    assert mgr.pm.states[SID]["current_stop"] == manual


def test_restart_after_protective_close(env_config):
    # position closed at broker -> not discovered -> not resurrected as active
    mgr, _ = _manager(env_config, [], [
        _rec(StopPhase.INITIAL, PMReason.INITIAL, ISTOP),
        _rec(StopPhase.CLOSED, PMReason.POSITION_CLOSED)])
    mgr.discover_and_register(NOW)
    assert SID not in mgr.pm.states


# --------------------------------------------------------------------------- #
# 8-11: non-terminal / intent records never advance phase
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("reason", [
    PMReason.BREAKEVEN_PENDING, PMReason.BREAKEVEN_TRIGGERED,
    PMReason.PROFIT_LOCK_TRIGGERED, PMReason.TRAIL_PENDING,
    PMReason.TRAIL_NO_IMPROVEMENT, PMReason.RECONCILIATION_REQUIRED,
    PMReason.MANUAL_CHANGE_REJECTED, PMReason.BROKER_CONSTRAINT,
    PMReason.DATA_STALE, PMReason.NO_ACTION])
def test_non_terminal_record_does_not_advance_phase(env_config, reason):
    # a non-terminal record carries the PRE-advance phase (INITIAL); recovery must
    # not treat it as a BREAKEVEN/LOCKED/TRAILING advance.
    mgr, _ = _manager(env_config, [_pos(sl=ISTOP)], [
        _rec(StopPhase.INITIAL, PMReason.INITIAL, ISTOP),
        _rec(StopPhase.INITIAL, reason)])
    mgr.discover_and_register(NOW)
    assert mgr.pm.states[SID]["phase"] == StopPhase.INITIAL


def test_intent_record_does_not_advance_phase(env_config):
    # a BREAKEVEN_SET INTENT (broker_result=INTENT) is written at the pre-advance
    # phase; without a verified DONE it must not advance recovery to BREAKEVEN.
    mgr, _ = _manager(env_config, [_pos(sl=ISTOP)], [
        _rec(StopPhase.INITIAL, PMReason.INITIAL, ISTOP),
        _rec(StopPhase.INITIAL, PMReason.BREAKEVEN_SET, broker_result="INTENT")])
    mgr.discover_and_register(NOW)
    assert mgr.pm.states[SID]["phase"] == StopPhase.INITIAL


# --------------------------------------------------------------------------- #
# 12-14: broker-truth fast-forward via the accepted evaluate path
# --------------------------------------------------------------------------- #
def test_broker_stop_at_be_target_fast_forwards_to_breakeven(env_config):
    # audit only INITIAL, but broker stop already at BE and price past BE trigger:
    # recover adopts the stop, the accepted evaluate path fast-forwards the phase.
    mgr, _ = _manager(env_config, [_pos(sl=BE, price_current=1.10250)],
                      [_rec(StopPhase.INITIAL, PMReason.INITIAL, ISTOP)])
    mgr.run_once(NOW)
    assert mgr.pm.states[SID]["phase"] == StopPhase.BREAKEVEN


def test_broker_stop_at_lock_target_fast_forwards_to_locked(env_config):
    mgr, _ = _manager(env_config, [_pos(sl=LOCK, price_current=1.10350)], [
        _rec(StopPhase.INITIAL, PMReason.INITIAL, ISTOP),
        _rec(StopPhase.BREAKEVEN, PMReason.BREAKEVEN_SET, BE, broker_result="DONE")])
    mgr.run_once(NOW)
    assert mgr.pm.states[SID]["phase"] == StopPhase.LOCKED


def test_broker_stop_beyond_latest_trail_preserves_trailing(env_config):
    beyond = 1.10200
    mgr, _ = _manager(env_config, [_pos(sl=beyond)], [
        _rec(StopPhase.INITIAL, PMReason.INITIAL, ISTOP),
        _rec(StopPhase.TRAILING, PMReason.TRAIL_ADVANCED, 1.10150, broker_result="DONE")])
    mgr.discover_and_register(NOW)
    assert mgr.pm.states[SID]["phase"] == StopPhase.TRAILING
    assert mgr.pm.states[SID]["current_stop"] == beyond   # adopted tighter broker truth


# --------------------------------------------------------------------------- #
# 15-17, conflicts: fail closed to reconciliation
# --------------------------------------------------------------------------- #
def test_broker_stop_looser_than_audit_requires_reconciliation(env_config):
    mgr, _ = _manager(env_config, [_pos(sl=1.09900)], [   # broker looser than BE
        _rec(StopPhase.INITIAL, PMReason.INITIAL, ISTOP),
        _rec(StopPhase.BREAKEVEN, PMReason.BREAKEVEN_SET, BE, broker_result="DONE")])
    mgr.discover_and_register(NOW)
    st = mgr.pm.states[SID]
    assert st["phase"] == StopPhase.BREAKEVEN            # phase preserved
    assert st["current_stop"] == BE                     # never loosened to broker value
    assert SID in mgr._recovery_reconcile
    assert mgr.status(NOW)["recovery_reconciliation_count"] == 1


def test_malformed_pm_audit_fails_closed(env_config):
    mgr, _ = _manager(env_config, [_pos(sl=BE)], None, raw="{ not json\n")
    mgr.discover_and_register(NOW)
    assert SID not in mgr.pm.states                      # not adopted at a guessed phase
    assert SID in mgr._recovery_reconcile


def test_conflicting_audit_fails_closed(env_config):
    mgr, _ = _manager(env_config, [_pos(sl=BE)], [
        _rec(StopPhase.INITIAL, PMReason.INITIAL, ISTOP, entry=1.10000),
        _rec(StopPhase.BREAKEVEN, PMReason.BREAKEVEN_SET, BE, entry=1.20000)])  # conflict
    mgr.discover_and_register(NOW)
    assert SID not in mgr.pm.states
    assert SID in mgr._recovery_reconcile


def test_ticket_mismatch_fails_closed(env_config):
    # audit ticket is TICKET, but the discovered position carries a different ticket
    mgr, _ = _manager(env_config, [_pos(ticket=TICKET2, sl=BE)], [
        _rec(StopPhase.INITIAL, PMReason.INITIAL, ISTOP, ticket=TICKET),
        _rec(StopPhase.BREAKEVEN, PMReason.BREAKEVEN_SET, BE, ticket=TICKET,
             broker_result="DONE")])
    mgr.discover_and_register(NOW)
    assert SID not in mgr.pm.states
    assert SID in mgr._recovery_reconcile


def test_manage_terminal_without_pm_audit_fails_closed(env_config):
    # a manage terminal result exists for the ticket but there is NO PM audit
    mgr, _ = _manager(env_config, [_pos(sl=BE)], [])     # empty audit file
    mgr.ledger.record_terminal("deadbeefdeadbeef", TICKET, "APPLIED", 1)
    mgr.discover_and_register(NOW)
    assert SID not in mgr.pm.states
    assert SID in mgr._recovery_reconcile


def test_pm_completion_audit_without_broker_truth_recovers_closed(env_config):
    # audit says BREAKEVEN but the broker no longer holds the ticket -> CLOSED
    mgr, _ = _manager(env_config, [], [
        _rec(StopPhase.INITIAL, PMReason.INITIAL, ISTOP),
        _rec(StopPhase.BREAKEVEN, PMReason.BREAKEVEN_SET, BE, broker_result="DONE")])
    rec = mgr.pm.recover(SID, NOW)                        # direct: broker truth wins
    assert rec["phase"] == StopPhase.CLOSED


# --------------------------------------------------------------------------- #
# 18-24: in-flight, no-duplicate, idempotency, register, independence, health
# --------------------------------------------------------------------------- #
def test_unresolved_inflight_remains_reconciliation_required(env_config):
    mgr, paths = _manager(env_config, [_pos(sl=ISTOP)], None)
    _archive_enter(paths)                                 # genuinely new -> register
    mgr.discover_and_register(NOW)
    assert mgr.pm.states[SID]["phase"] == StopPhase.INITIAL
    mgr.ledger.set_inflight(TICKET, "cafecafecafecafe")  # simulate unresolved in-flight
    mgr.run_cycle(NOW, market={TICKET: 1.10050})
    st = mgr.status(NOW)
    assert st["in_flight_count"] == 1 and st["unresolved_reconciliation_count"] == 1


def test_recovery_emits_no_manage_instruction(env_config):
    mgr, _ = _manager(env_config, [_pos(sl=BE)], [
        _rec(StopPhase.INITIAL, PMReason.INITIAL, ISTOP),
        _rec(StopPhase.BREAKEVEN, PMReason.BREAKEVEN_SET, BE, broker_result="DONE")])
    mgr.discover_and_register(NOW)
    pend = list(mgr.paths.pending.glob("*.json"))
    claimed = list(mgr.paths.claimed.glob("*.json"))
    assert pend == [] and claimed == []                  # recovery wrote no instruction


def test_rediscovery_same_session_is_idempotent(env_config):
    # re-running discovery within a session must not re-recover or duplicate state
    mgr, _ = _manager(env_config, [_pos(sl=BE)], [
        _rec(StopPhase.INITIAL, PMReason.INITIAL, ISTOP),
        _rec(StopPhase.BREAKEVEN, PMReason.BREAKEVEN_SET, BE, broker_result="DONE")])
    mgr.discover_and_register(NOW)
    before = dict(mgr.pm.states[SID])
    out = mgr.discover_and_register(NOW)                  # second pass, same session
    assert out == []                                     # already tracked -> no-op
    assert mgr.pm.states[SID] == before
    assert before["phase"] == StopPhase.BREAKEVEN


def test_second_process_restart_recovers_same_phase(env_config, tmp_path):
    # two independent ManagerService instances over one shared bridge/runtime dir
    env = {
        "SESSION_EDGE_BRIDGE_ROOT": str(tmp_path / "bridge"),
        "SESSION_EDGE_RUNTIME_DIR": str(tmp_path / "runtime"),
        "SESSION_EDGE_SYMBOLS": "EURUSD.FX", "SESSION_EDGE_INITIAL_BALANCE": "100000",
        "SESSION_EDGE_ACCOUNT_CURRENCY": "USD",
        "SESSION_EDGE_FTMO_RULE_SOURCE": "x", "SESSION_EDGE_FTMO_RULE_VERIFIED_AT": "2026-08-05",
        "SESSION_EDGE_FTMO_PROFILE_VERIFIED": "true",
        "SESSION_EDGE_NEWS_FILE": str(tmp_path / "news.json")}
    (tmp_path / "news.json").write_text(
        serialize.canonical_json({"as_of": serialize.iso_utc(NOW), "events": []}),
        encoding="utf-8")
    records = [_rec(StopPhase.INITIAL, PMReason.INITIAL, ISTOP),
               _rec(StopPhase.BREAKEVEN, PMReason.BREAKEVEN_SET, BE, broker_result="DONE"),
               _rec(StopPhase.LOCKED, PMReason.PROFIT_LOCK_SET, LOCK, broker_result="DONE")]
    for _ in range(2):
        client = make_client([_pos(sl=LOCK)])
        mgr = ManagerService.build_from_env(env=env, client=client, now_fn=lambda: NOW)
        _write_audit(env["SESSION_EDGE_RUNTIME_DIR"], records)
        mgr.discover_and_register(NOW)
        assert mgr.pm.states[SID]["phase"] == StopPhase.LOCKED
        assert mgr.pm.states[SID]["current_stop"] == LOCK


def test_genuinely_new_position_uses_register(env_config):
    mgr, paths = _manager(env_config, [_pos(sl=ISTOP)], None)   # no PM audit
    _archive_enter(paths)
    out = mgr.discover_and_register(NOW)
    assert out and out[0]["mode"] == "register"
    assert mgr.pm.states[SID]["phase"] == StopPhase.INITIAL
    assert mgr.pm.states[SID]["current_stop"] == ISTOP


def test_missing_immutable_entry_not_guessed(env_config):
    mgr, _ = _manager(env_config, [_pos(sl=ISTOP)], None)  # no PM audit, no ENTER instr
    mgr.discover_and_register(NOW)
    assert SID not in mgr.pm.states
    assert SID in mgr._recovery_reconcile


def test_different_tickets_recover_independently(env_config):
    positions = [_pos(ticket=TICKET, sl=BE, comment=SID),
                 _pos(ticket=TICKET2, sl=LOCK, comment=SID2)]
    records = [
        _rec(StopPhase.INITIAL, PMReason.INITIAL, ISTOP, sid=SID, ticket=TICKET),
        _rec(StopPhase.BREAKEVEN, PMReason.BREAKEVEN_SET, BE, sid=SID, ticket=TICKET,
             broker_result="DONE"),
        _rec(StopPhase.INITIAL, PMReason.INITIAL, ISTOP, sid=SID2, ticket=TICKET2),
        _rec(StopPhase.BREAKEVEN, PMReason.BREAKEVEN_SET, BE, sid=SID2, ticket=TICKET2,
             broker_result="DONE"),
        _rec(StopPhase.LOCKED, PMReason.PROFIT_LOCK_SET, LOCK, sid=SID2, ticket=TICKET2,
             broker_result="DONE")]
    mgr, _ = _manager(env_config, positions, records)
    mgr.discover_and_register(NOW)
    assert mgr.pm.states[SID]["phase"] == StopPhase.BREAKEVEN
    assert mgr.pm.states[SID2]["phase"] == StopPhase.LOCKED


def test_health_reports_unresolved_recovery(env_config):
    mgr, _ = _manager(env_config, [_pos(sl=1.09900)], [   # looser -> reconciliation
        _rec(StopPhase.INITIAL, PMReason.INITIAL, ISTOP),
        _rec(StopPhase.BREAKEVEN, PMReason.BREAKEVEN_SET, BE, broker_result="DONE")])
    mgr.discover_and_register(NOW)
    st = mgr.status(NOW)
    assert st["recovery_reconciliation_count"] == 1
    assert SID in st["recovery_reconciliation_required"]
