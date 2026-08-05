"""Phase 7B-B manage-channel tests (mock terminal; no real MT5, no networking)."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from forex_swing_orb.bridge import serialize
from forex_swing_orb.ea_mt5 import mock_mt5
from forex_swing_orb.manage import (BridgeMt5Adapter, ManageAction, ManageConsumer,
                                    ManagePaths, ManageStatus, build_instruction,
                                    compute_manage_id, initial_r_digest,
                                    validate_instruction, write_manage_instruction)
from forex_swing_orb.manage import contract as MC
from conftest import NOW

MANAGE_DIR = Path(__file__).resolve().parents[1]
BUY, SELL = mock_mt5.ORDER_TYPE_BUY, mock_mt5.ORDER_TYPE_SELL


def _instr(**over):
    f = {"signal_id": "0123456789abcdef", "ticket": 5000001, "symbol": "EURUSD",
         "direction": "LONG", "action": ManageAction.MODIFY_STOP, "target_stop": 1.10020,
         "expected_current_stop": 1.09800, "prior_stop": 1.09800, "pm_phase": "INITIAL",
         "pm_reason": "PM_MODIFY@INITIAL", "structure_reference": None,
         "market_reference": 1.10200, "point": 0.00001, "digits": 5,
         "broker_min_stop_distance": 0.0, "per_ticket_sequence": 1,
         "generated_timestamp": serialize.iso_utc(NOW),
         "expiration_timestamp": serialize.iso_utc(NOW + timedelta(seconds=120)),
         "initial_r_digest": initial_r_digest("LONG", 1.10000, 1.09800)}
    f.update(over)
    return build_instruction(f)


def _emit(mpaths, mt5, instr, now=NOW):
    write_manage_instruction(mpaths, instr, now)
    c = ManageConsumer(mt5, mpaths)
    return c.run_once(now)


def _mt5_with_long(sl=1.09800, ticket=5000001):
    m = mock_mt5.MockMT5(); m.add_symbol("EURUSD")
    m.positions[ticket] = mock_mt5.Position(ticket, "EURUSD", BUY, 0.1, 1.10000, sl,
                                            1.10600, "0123456789abcdef")
    return m


# --- manage_id / contract determinism ---------------------------------------
def test_manage_id_deterministic_and_distinct_from_signal():
    a = _instr(); b = _instr()
    assert a["manage_id"] == b["manage_id"]      # deterministic
    assert a["manage_id"] != a["signal_id"]      # distinct identity
    assert len(a["manage_id"]) == 16


def test_manage_id_changes_with_target():
    assert _instr(target_stop=1.10020)["manage_id"] != _instr(target_stop=1.10030,
        per_ticket_sequence=2)["manage_id"]


def test_many_manage_ids_under_one_signal():
    ids = {_instr(target_stop=1.10000 + i * 0.00010, per_ticket_sequence=i)["manage_id"]
           for i in range(1, 6)}
    assert len(ids) == 5      # one signal_id, many manage_id


def test_validate_fails_closed():
    bad = _instr(); bad["schema_version"] = 999
    assert validate_instruction(bad)[0] is False
    bad2 = _instr(); del bad2["ticket"]
    assert validate_instruction(bad2)[0] is False
    bad3 = _instr(action=ManageAction.MODIFY_STOP, target_stop=None)
    assert validate_instruction(bad3)[0] is False


# --- consumer 18-step behaviors --------------------------------------------
def test_apply_success_updates_broker_and_writes_result(tmp_path):
    mp = ManagePaths(tmp_path).ensure(); mt5 = _mt5_with_long()
    res = _emit(mp, mt5, _instr())
    assert res["status"] == ManageStatus.APPLIED
    assert mt5.positions[5000001].sl == pytest.approx(1.10020)
    assert list(mp.results.glob("*.json"))


def test_cas_mismatch_rejected_stale(tmp_path):
    mp = ManagePaths(tmp_path).ensure()
    mt5 = _mt5_with_long(sl=1.09850)                  # broker moved (manual tighten)
    res = _emit(mp, mt5, _instr(expected_current_stop=1.09800))
    assert res["status"] == ManageStatus.REJECTED_STALE
    assert mt5.positions[5000001].sl == pytest.approx(1.09850)  # untouched


def test_loosen_rejected(tmp_path):
    mp = ManagePaths(tmp_path).ensure(); mt5 = _mt5_with_long(sl=1.09900)
    res = _emit(mp, mt5, _instr(expected_current_stop=1.09900, target_stop=1.09700))
    assert res["status"] == ManageStatus.REJECTED_LOOSEN
    assert mt5.positions[5000001].sl == pytest.approx(1.09900)


def test_expired_rejected(tmp_path):
    mp = ManagePaths(tmp_path).ensure(); mt5 = _mt5_with_long()
    instr = _instr(generated_timestamp=serialize.iso_utc(NOW - timedelta(hours=2)),
                   expiration_timestamp=serialize.iso_utc(NOW - timedelta(hours=1)))
    res = _emit(mp, mt5, instr)
    assert res["status"] == ManageStatus.REJECTED_EXPIRED


def test_min_stop_rejected(tmp_path):
    mp = ManagePaths(tmp_path).ensure(); mt5 = _mt5_with_long()
    res = _emit(mp, mt5, _instr(broker_min_stop_distance=0.0050, market_reference=1.10030))
    assert res["status"] == ManageStatus.REJECTED_BROKER_CONSTRAINT


def test_no_position(tmp_path):
    mp = ManagePaths(tmp_path).ensure(); mt5 = mock_mt5.MockMT5(); mt5.add_symbol("EURUSD")
    res = _emit(mp, mt5, _instr())
    assert res["status"] == ManageStatus.NO_POSITION


def test_broker_invalid_stops(tmp_path):
    mp = ManagePaths(tmp_path).ensure(); mt5 = _mt5_with_long()
    mt5.script_modify("invalid_stops")
    res = _emit(mp, mt5, _instr())
    assert res["status"] == ManageStatus.REJECTED_BROKER_CONSTRAINT


def test_terminal_disconnect_nonterminal(tmp_path):
    mp = ManagePaths(tmp_path).ensure(); mt5 = _mt5_with_long()
    mt5.connected = False
    res = _emit(mp, mt5, _instr())
    assert res["status"] == ManageStatus.TERMINAL_DISCONNECTED
    assert not list(mp.results.glob("*.json"))          # no terminal result written
    assert list(mp.claimed.glob("*.json"))              # left for recovery


def test_dedup_idempotent(tmp_path):
    mp = ManagePaths(tmp_path).ensure(); mt5 = _mt5_with_long()
    c = ManageConsumer(mt5, mp)
    write_manage_instruction(mp, _instr(), NOW); c.run_once(NOW)
    write_manage_instruction(mp, _instr(), NOW)          # same manage_id again
    res2 = c.run_once(NOW)
    assert res2["status"] == ManageStatus.ALREADY_APPLIED


def test_old_sequence_rejected(tmp_path):
    mp = ManagePaths(tmp_path).ensure(); mt5 = _mt5_with_long(sl=1.10020)
    c = ManageConsumer(mt5, mp)
    write_manage_instruction(mp, _instr(per_ticket_sequence=5, expected_current_stop=1.10020,
                                        target_stop=1.10040), NOW); c.run_once(NOW)
    write_manage_instruction(mp, _instr(per_ticket_sequence=3), NOW)   # older
    res = c.run_once(NOW)
    assert res["status"] == ManageStatus.REJECTED_STALE


def test_protective_close(tmp_path):
    mp = ManagePaths(tmp_path).ensure(); mt5 = _mt5_with_long()
    instr = _instr(action=ManageAction.PROTECTIVE_CLOSE, target_stop=None,
                   expected_current_stop=None, pm_reason="PM_PROTECTIVE_CLOSE")
    res = _emit(mp, mt5, instr)
    assert res["status"] == ManageStatus.NO_OP_CLOSED
    assert mt5.positions[5000001].closed is True


# --- EA recovery ------------------------------------------------------------
def test_recovery_adopts_already_applied(tmp_path):
    mp = ManagePaths(tmp_path).ensure(); mt5 = _mt5_with_long()
    instr = _instr()
    write_manage_instruction(mp, instr, NOW)
    c = ManageConsumer(mt5, mp)
    c.claim_next(NOW)                        # claim, then simulate crash before apply
    mt5.positions[5000001].sl = 1.10020      # broker actually applied it (crash after apply)
    out = c.recover(NOW)
    assert out and out[0]["status"] == ManageStatus.ALREADY_APPLIED


# --- adapter bounded-wait ---------------------------------------------------
def test_adapter_bounded_wait_success(wired, long_pos):
    sid, ticket = long_pos()
    res = wired["adapter"].modify_stop(ticket, 1.10020)
    assert res.retcode == mock_mt5.TRADE_RETCODE_DONE
    assert wired["mt5"].positions[ticket].sl == pytest.approx(1.10020)
    assert wired["adapter"].ledger.get_inflight(ticket) is None   # cleared


def test_adapter_timeout_uncertain_no_dupe(tmp_path):
    mt5 = _mt5_with_long()
    mp = ManagePaths(tmp_path).ensure()
    ad = BridgeMt5Adapter(mt5, mp, now_fn=lambda: NOW, timeout_sec=2,
                          poll_interval_sec=1, sleep_fn=lambda s: None, pump=None)

    class _PM:
        _ticket_owner = {5000001: "0123456789abcdef"}
        states = {"0123456789abcdef": {"signal_id": "0123456789abcdef", "symbol": "EURUSD",
                  "direction": "LONG", "current_stop": 1.09800, "phase": "INITIAL",
                  "entry": 1.10000, "initial_stop": 1.09800, "last_structure_ref": None}}
    ad.bind(_PM())
    res = ad.modify_stop(5000001, 1.10020)               # no consumer -> timeout
    assert res.retcode == mock_mt5.TRADE_RETCODE_CONNECTION
    assert len(list(mp.pending.glob("*.json"))) == 1     # exactly one emitted, no dupe
    assert ad.ledger.get_inflight(5000001) is not None   # in-flight persists


# --- PM integration through the channel -------------------------------------
def test_breakeven_end_to_end(wired, long_pos):
    sid, ticket = long_pos()
    rec = wired["pm"].evaluate(sid, market_price=1.10200, now=NOW)   # +1R => BE
    assert wired["mt5"].positions[ticket].sl > 1.09800               # stop moved up
    from forex_swing_orb.position.contract import StopPhase
    assert wired["pm"].states[sid]["phase"] == StopPhase.BREAKEVEN


def test_phase_does_not_advance_without_apply(wired, long_pos):
    # break the consumer (disconnect) so the modify is UNCERTAIN -> no phase advance
    sid, ticket = long_pos()
    wired["mt5"].connected = False
    rec = wired["pm"].evaluate(sid, market_price=1.10200, now=NOW)
    from forex_swing_orb.position.contract import StopPhase
    assert wired["pm"].states[sid]["phase"] == StopPhase.INITIAL


def test_manager_one_in_flight(wired, long_pos):
    sid, ticket = long_pos()
    # first cycle applies BE and clears in-flight (pump resolves within the wait)
    wired["manager"].run_cycle(NOW, market={ticket: 1.10200})
    assert wired["adapter"].ledger.get_inflight(ticket) is None
    assert wired["mt5"].positions[ticket].sl > 1.09800


def test_manager_restart_rebuilds_inflight(wired, long_pos, tmp_path):
    sid, ticket = long_pos()
    # force an unresolved in-flight (no pump), then a fresh adapter over same ledger
    wired["adapter"]._pump = None
    wired["adapter"].timeout_sec = 1
    wired["pm"].evaluate(sid, market_price=1.10200, now=NOW)
    assert wired["adapter"].ledger.get_inflight(ticket) is not None
    from forex_swing_orb.manage import ManageLedger
    reloaded = ManageLedger(wired["mpaths"].ledger)
    assert reloaded.get_inflight(ticket) is not None    # survived "restart"


# --- audit correlation ------------------------------------------------------
def test_audit_correlation_fields(tmp_path):
    from forex_swing_orb.manage.ledger import ManageLedger
    mp = ManagePaths(tmp_path).ensure(); mt5 = _mt5_with_long()
    from forex_swing_orb.producer.state import RunnerAudit  # reuse jsonl audit
    audit = RunnerAudit(str(mp.audit_log))
    c = ManageConsumer(mt5, mp, audit=audit)
    write_manage_instruction(mp, _instr(), NOW, audit=audit); c.run_once(NOW)
    recs = audit.read_all()
    res_rec = [r for r in recs if r.get("kind") == "manage_result"][0]
    for k in ("manage_id", "signal_id", "ticket", "per_ticket_sequence", "action",
              "status", "correlation_id", "expected_current_stop", "target_stop"):
        assert k in res_rec
    assert res_rec["correlation_id"] == res_rec["manage_id"]


# --- source guards: no dup PM logic / no networking / no entry --------------
def _sources():
    return [p for p in MANAGE_DIR.glob("*.py")]


def test_no_duplicate_pm_arithmetic():
    banned = ("def breakeven_trigger_price", "def profit_lock_stop",
              "def trailing_stop_candidate", "def is_stop_improvement",
              "def evaluate_symbol")
    for f in _sources():
        s = f.read_text(encoding="utf-8")
        for b in banned:
            assert b not in s, f"{f.name} duplicates PM arithmetic: {b}"


def test_no_networking():
    banned = ("import socket", "import requests", "import urllib", "import http",
              "http.client", "socket.socket", "subprocess", "os.system(")
    for f in _sources():
        s = f.read_text(encoding="utf-8").lower()
        for b in banned:
            assert b not in s, f"{f.name}: {b}"


def test_no_entry_creation_in_manage():
    banned = ("order_send", "def order_send", ".Buy(", "ORDER_TYPE_BUY =", "open_trade")
    for f in _sources():
        s = f.read_text(encoding="utf-8")
        for b in banned:
            assert b not in s, f"{f.name}: {b}"
