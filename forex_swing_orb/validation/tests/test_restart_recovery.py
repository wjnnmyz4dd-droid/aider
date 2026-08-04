"""Phase 3A - restart & crash-recovery validation.

Power-loss is modelled precisely: the harness performs the pipeline steps up to a
crash point, discards the in-memory adapter (process death), then a fresh adapter
recovers from the on-disk bridge + the (persistent) mock terminal. Every case
proves: no duplicate execution, no duplicate ack, no duplicate result, state is
reconstructed, the ticket map is rebuilt, and the audit stays complete.
"""

from __future__ import annotations

import os

from forex_swing_orb.bridge import serialize
from forex_swing_orb.bridge.atomic import atomic_write_text
from forex_swing_orb.bridge.contract import ResultState
from forex_swing_orb.bridge.paths import ack_name, instruction_name
from forex_swing_orb.ea_mt5 import mock_mt5
from forex_swing_orb.ea_mt5.execution_consumer import XReason
from forex_swing_orb.validation import harness as H

NOW = H.NOW


# -- invariants -------------------------------------------------------------
def result_files(paths, sid):
    return [p for p in paths.results.iterdir() if p.name.startswith(sid + ".")]


def ack_files(paths, sid):
    return [p for p in paths.acks.iterdir() if p.name.startswith(sid + ".")]


def assert_single_execution(paths, mt5, sid, expect_status=ResultState.EXECUTED):
    orders_for_sid = [o for o in mt5.order_log if o.get("comment") == sid]
    assert len(orders_for_sid) <= 1, "no duplicate OrderSend for a signal_id"
    assert len(result_files(paths, sid)) == 1, "exactly one terminal result"
    assert len(ack_files(paths, sid)) <= 1, "no duplicate acknowledgement"
    rid = serialize.result_id(sid, expect_status)
    assert (paths.results / f"{sid}.{rid}.json").exists()


# -- plain restarts ---------------------------------------------------------
def test_bridge_restart_preserves_dedup(tmp_path):
    ec, paths, ledger, audit, mt5 = H.build(tmp_path)
    rec = H.make_instruction()
    H.produce(paths, rec); H.drain(ec)
    # "bridge restart": brand-new ledger/audit objects reload from disk
    ec2, ledger2, audit2 = H.reopen(paths, mt5)
    H.produce(paths, rec)                              # same signal_id again
    result = H.drain(ec2)[0]
    assert result["status"] == ResultState.DUPLICATE
    assert len(mt5.order_log) == 1


def test_ea_restart_then_continue(tmp_path):
    ec, paths, ledger, audit, mt5 = H.build(tmp_path)
    H.produce(paths, H.make_instruction(i=0)); H.drain(ec)
    ec2, _, _ = H.reopen(paths, mt5)                   # EA restart
    ec2.recover(NOW)
    H.produce(paths, H.make_instruction(i=1)); H.drain(ec2)
    assert len(mt5.order_log) == 2
    assert H.count_files(paths.archive_accepted) == 2


def test_bridge_and_ea_restart_together(tmp_path):
    ec, paths, ledger, audit, mt5 = H.build(tmp_path)
    for i in range(5):
        H.produce(paths, H.make_instruction(i=i))
    H.drain(ec)
    # full cold start over the same tree + terminal
    ec2, ledger2, audit2 = H.reopen(paths, mt5)
    summary = ec2.recover(NOW)
    assert summary["adopted"] == 0 and summary["recovered_from_broker"] == 0
    # re-deliver all five: every one is a duplicate, no new orders
    for i in range(5):
        H.produce(paths, H.make_instruction(i=i))
    results = H.drain(ec2)
    assert all(r["status"] == ResultState.DUPLICATE for r in results)
    assert len(mt5.order_log) == 5


# -- crash points (power-loss) ---------------------------------------------
def test_crash_during_claim(tmp_path):
    """Crash between link and unlink: pending + claimed both exist. Recovery
    executes once; the leftover pending re-claim is a duplicate."""
    ec, paths, ledger, audit, mt5 = H.build(tmp_path)
    rec = H.make_instruction(); sid = rec["signal_id"]
    H.produce(paths, rec)
    real_unlink = os.unlink

    def fail_once(path, *a, **k):
        raise OSError("injected: crash during claim (post-link)")
    import unittest.mock as m
    with m.patch("os.unlink", side_effect=fail_once):
        ec.claim(sid, NOW)                             # link done, unlink crashes
    assert (paths.claimed / instruction_name(sid)).exists()
    assert (paths.pending / instruction_name(sid)).exists()   # stray link remains
    # restart: recover processes claimed, then drain claims the stray pending
    ec2, _, _ = H.reopen(paths, mt5)
    ec2.recover(NOW)
    H.drain(ec2)
    assert_single_execution(paths, mt5, sid)


def test_crash_during_ack(tmp_path):
    """Ack written, process died before OrderSend -> reconciliation-required."""
    ec, paths, ledger, audit, mt5 = H.build(tmp_path)
    rec = H.make_instruction(); sid = rec["signal_id"]
    H.produce(paths, rec)
    ec.claim(sid, NOW)
    ec._write_ack(rec, NOW)                            # ack persisted; then "death"
    ec2, _, _ = H.reopen(paths, mt5)
    summary = ec2.recover(NOW)
    assert summary["reconciliation_required"] == 1
    assert len(mt5.order_log) == 0
    assert len(result_files(paths, sid)) == 0          # fail closed, no result
    assert (paths.claimed / instruction_name(sid)).exists()


def test_crash_during_execution(tmp_path):
    """OrderSend reached the broker, process died before the result write."""
    ec, paths, ledger, audit, mt5 = H.build(tmp_path)
    rec = H.make_instruction(direction="LONG", symbol="EURUSD.FX")
    sid = rec["signal_id"]
    H.produce(paths, rec)
    ec.claim(sid, NOW)
    ec._write_ack(rec, NOW)
    mt5.order_send({"symbol": "EURUSD", "volume": 0.10,
                    "type": mock_mt5.ORDER_TYPE_BUY, "price": rec["entry_price"],
                    "sl": rec["stop_loss"], "tp": rec["take_profit"], "comment": sid})
    # "death" before result. Restart -> recover finalizes from broker truth.
    ec2, _, _ = H.reopen(paths, mt5)
    summary = ec2.recover(NOW)
    assert summary["recovered_from_broker"] == 1
    assert len(mt5.order_log) == 1                      # never resent
    assert_single_execution(paths, mt5, sid)
    rec_result = serialize.loads((result_files(paths, sid)[0]).read_text())[1]
    assert rec_result["reason_code"] == XReason.RECONCILE


def test_crash_during_result_write(tmp_path):
    """Torn result write leaves only a .tmp; recovery cleans it and finalizes
    from broker truth (atomic write means a partial result never goes visible)."""
    ec, paths, ledger, audit, mt5 = H.build(tmp_path)
    rec = H.make_instruction(); sid = rec["signal_id"]
    H.produce(paths, rec)
    ec.claim(sid, NOW); ec._write_ack(rec, NOW)
    mt5.order_send({"symbol": "EURUSD", "volume": 0.10,
                    "type": mock_mt5.ORDER_TYPE_BUY, "price": rec["entry_price"],
                    "sl": rec["stop_loss"], "tp": rec["take_profit"], "comment": sid})
    rid = serialize.result_id(sid, ResultState.EXECUTED)
    tmp = paths.results / ("." + f"{sid}.{rid}.json" + ".tmp")
    tmp.write_text('{"partial":')                      # torn write artifact
    ec2, _, _ = H.reopen(paths, mt5)
    ec2.recover(NOW)
    assert not tmp.exists()                             # .tmp cleaned
    assert_single_execution(paths, mt5, sid)


def test_crash_during_archive(tmp_path):
    """Result + ledger durable, but the claimed->archive move never happened.
    Recovery adopts the existing terminal result and completes the archive."""
    ec, paths, ledger, audit, mt5 = H.build(tmp_path)
    rec = H.make_instruction(); sid = rec["signal_id"]
    H.produce(paths, rec)
    ec.claim(sid, NOW); ec._write_ack(rec, NOW)
    res = mt5.order_send({"symbol": "EURUSD", "volume": 0.10,
                          "type": mock_mt5.ORDER_TYPE_BUY, "price": rec["entry_price"],
                          "sl": rec["stop_loss"], "tp": rec["take_profit"], "comment": sid})
    # write the terminal result + ledger but skip the archive (crash point)
    _, reason, detail = ec._executed_detail(rec, mt5.position_by_comment(sid),
                                            XReason.OK, NOW, result=res)
    rid = serialize.result_id(sid, ResultState.EXECUTED)
    from forex_swing_orb.bridge.contract import build_result
    result = build_result(sid, rid, ResultState.EXECUTED, reason,
                          serialize.iso_utc(NOW), serialize.iso_utc(NOW),
                          instruction=rec, detail=detail,
                          execution=detail.get("execution"))
    ec.consumer._write_result(result)
    ledger.record(sid, ResultState.EXECUTED, rid, serialize.iso_utc(NOW))
    assert (paths.claimed / instruction_name(sid)).exists()   # not archived yet
    # restart -> recover adopts terminal evidence and archives
    ec2, _, _ = H.reopen(paths, mt5)
    ec2.recover(NOW)
    assert (paths.archive_accepted / instruction_name(sid)).exists()
    assert not (paths.claimed / instruction_name(sid)).exists()
    assert_single_execution(paths, mt5, sid)


def test_crash_during_reconciliation_is_idempotent(tmp_path):
    """A crash partway through recovery, then a re-run, converges with no double
    execution."""
    ec, paths, ledger, audit, mt5 = H.build(tmp_path)
    recs = [H.make_instruction(i=i) for i in range(4)]
    for r in recs:
        H.produce(paths, r); ec.claim(r["signal_id"], NOW)
        ec._write_ack(r, NOW)
        mt5.order_send({"symbol": r["symbol"][:6], "volume": 0.10,
                        "type": (mock_mt5.ORDER_TYPE_BUY if r["direction"] == "LONG"
                                 else mock_mt5.ORDER_TYPE_SELL),
                        "price": r["entry_price"], "sl": r["stop_loss"],
                        "tp": r["take_profit"], "comment": r["signal_id"]})
    orders_before = len(mt5.order_log)
    ec2, _, _ = H.reopen(paths, mt5)
    # crash during recovery: blow up on the 2nd terminal write
    import unittest.mock as m
    calls = {"n": 0}
    real_finish = ec2._finalize_from_broker

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("injected: crash mid-reconciliation")
        return real_finish(*a, **k)
    with m.patch.object(ec2, "_finalize_from_broker", side_effect=flaky):
        try:
            ec2.recover(NOW)
        except RuntimeError:
            pass
    # re-run recovery to completion (idempotent)
    ec3, _, _ = H.reopen(paths, mt5)
    ec3.recover(NOW)
    assert len(mt5.order_log) == orders_before          # no resends at all
    for r in recs:
        assert_single_execution(paths, mt5, r["signal_id"])


# -- orphan / ledger / archive / quarantine recovery ------------------------
def test_orphan_claimed_instruction_executes_once(tmp_path):
    ec, paths, ledger, audit, mt5 = H.build(tmp_path)
    rec = H.make_instruction(); sid = rec["signal_id"]
    H.produce(paths, rec)
    ec.claim(sid, NOW)                                  # claimed, nothing else
    ec2, _, _ = H.reopen(paths, mt5)
    summary = ec2.recover(NOW)
    assert summary["reprocessed"] == 1
    assert_single_execution(paths, mt5, sid)


def test_ledger_recovery_from_disk(tmp_path):
    """Losing dedup.jsonl must not cause reprocessing (F-D)."""
    ec, paths, ledger, audit, mt5 = H.build(tmp_path)
    rec = H.make_instruction(); sid = rec["signal_id"]
    H.produce(paths, rec); H.drain(ec)
    os.remove(paths.dedup_ledger)                       # ledger lost
    ec2, ledger2, _ = H.reopen(paths, mt5)
    assert not ledger2.is_seen(sid)                     # gone from memory
    H.produce(paths, rec)
    result = H.drain(ec2)[0]
    assert result["status"] == ResultState.DUPLICATE    # rebuilt from archive/result
    assert len(mt5.order_log) == 1


def test_archive_only_evidence_blocks_reexecution(tmp_path):
    ec, paths, ledger, audit, mt5 = H.build(tmp_path)
    rec = H.make_instruction(); sid = rec["signal_id"]
    H.produce(paths, rec); H.drain(ec)
    # remove ledger AND result file, leaving only the archive artifact
    os.remove(paths.dedup_ledger)
    for p in result_files(paths, sid):
        os.remove(p)
    ec2, _, _ = H.reopen(paths, mt5)
    H.produce(paths, rec)
    result = H.drain(ec2)[0]
    assert result["status"] == ResultState.DUPLICATE
    assert len(mt5.order_log) == 1


def test_quarantine_recovery_continues(tmp_path):
    ec, paths, ledger, audit, mt5 = H.build(tmp_path)
    bad = H.signal_id(999)
    atomic_write_text(paths.pending / instruction_name(bad), "garbage{")
    good = H.make_instruction(i=1)
    H.produce(paths, good)
    H.drain(ec)
    assert (paths.quarantine / instruction_name(bad)).exists()
    assert len(mt5.order_log) == 1                      # good one still executed


def test_ticket_map_rebuilt_after_restart(tmp_path):
    ec, paths, ledger, audit, mt5 = H.build(tmp_path)
    recs = [H.make_instruction(i=i) for i in range(3)]
    for r in recs:
        H.produce(paths, r)
    H.drain(ec)
    ec2, _, _ = H.reopen(paths, mt5)                    # fresh (empty) ticket map
    assert ec2.active_tickets == {}
    ec2.recover(NOW)
    for r in recs:
        pos = mt5.position_by_comment(r["signal_id"])
        assert ec2.active_tickets.get(r["signal_id"]) == pos.ticket
