"""Phase 3A - end-to-end scenario validation.

engine -> bridge -> execution adapter -> mock MT5 -> ack -> result -> archive.
Deterministic; no networking. Failures fail closed with a deterministic reason.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from forex_swing_orb.bridge import serialize
from forex_swing_orb.bridge.atomic import atomic_write_text
from forex_swing_orb.bridge.contract import ResultState
from forex_swing_orb.bridge.paths import ack_name, instruction_name, result_name
from forex_swing_orb.ea_mt5 import mock_mt5
from forex_swing_orb.ea_mt5.execution_consumer import XReason
from forex_swing_orb.validation import harness as H


# -- normal execution: BUY / SELL ------------------------------------------
def test_normal_execution_buy(tmp_path):
    ec, paths, ledger, audit, mt5 = H.build(tmp_path)
    rec = H.make_instruction(direction="LONG", symbol="EURUSD.FX")
    H.produce(paths, rec)
    result = H.drain(ec)[0]
    assert result["status"] == ResultState.EXECUTED
    assert result["reason_code"] == XReason.OK
    assert mt5.position_by_comment(rec["signal_id"]).type == mock_mt5.ORDER_TYPE_BUY
    assert (paths.archive_accepted / instruction_name(rec["signal_id"])).exists()


def test_normal_execution_sell(tmp_path):
    ec, paths, ledger, audit, mt5 = H.build(tmp_path)
    rec = H.make_instruction(direction="SHORT", symbol="GBPUSD.FX")
    H.produce(paths, rec)
    result = H.drain(ec)[0]
    assert result["status"] == ResultState.EXECUTED
    assert mt5.position_by_comment(rec["signal_id"]).type == mock_mt5.ORDER_TYPE_SELL


# -- multiple symbols, sequential and "simultaneous" -----------------------
def test_multiple_symbols(tmp_path):
    ec, paths, ledger, audit, mt5 = H.build(tmp_path)
    recs = [H.make_instruction(i=i, symbol=s + ".FX")
            for i, s in enumerate(H.SYMBOLS)]
    for r in recs:
        H.produce(paths, r)
    results = H.drain(ec)
    assert len(results) == len(H.SYMBOLS)
    assert all(r["status"] == ResultState.EXECUTED for r in results)
    assert len(mt5.positions) == len(H.SYMBOLS)


def test_multiple_sequential_trades(tmp_path):
    ec, paths, ledger, audit, mt5 = H.build(tmp_path)
    for i in range(25):
        H.produce(paths, H.make_instruction(i=i))
        H.drain(ec)                                   # process each before next
    assert len(mt5.order_log) == 25
    assert H.count_files(paths.results) == 25


def test_simultaneous_signals_single_sweep(tmp_path):
    """All instructions land in pending, then are claimed+executed in one sweep."""
    ec, paths, ledger, audit, mt5 = H.build(tmp_path)
    for i in range(50):
        H.produce(paths, H.make_instruction(i=i))
    results = H.drain(ec)
    assert len(results) == 50
    assert len({r["signal_id"] for r in results}) == 50   # all distinct
    assert len(mt5.order_log) == 50


# -- duplicates -------------------------------------------------------------
def test_duplicate_instruction_same_signal_id(tmp_path):
    ec, paths, ledger, audit, mt5 = H.build(tmp_path)
    rec = H.make_instruction()
    H.produce(paths, rec)
    first = H.drain(ec)[0]
    assert first["status"] == ResultState.EXECUTED
    H.produce(paths, rec)                             # re-deliver identical signal_id
    second = H.drain(ec)[0]
    assert second["status"] == ResultState.DUPLICATE
    assert len(mt5.order_log) == 1                    # never a second order


# -- expired ---------------------------------------------------------------
def test_expired_instruction(tmp_path):
    from datetime import timedelta
    ec, paths, ledger, audit, mt5 = H.build(tmp_path)
    rec = H.make_instruction(expiration=H.NOW - timedelta(seconds=1))
    H.produce(paths, rec)
    result = H.drain(ec)[0]
    assert result["status"] == ResultState.EXPIRED
    assert len(mt5.order_log) == 0


# -- corrupt / digest / schema / strategy ----------------------------------
def test_corrupt_bridge_file_quarantined(tmp_path):
    ec, paths, ledger, audit, mt5 = H.build(tmp_path)
    sid = H.signal_id(1)
    # write non-JSON bytes directly into pending with a valid name
    atomic_write_text(paths.pending / instruction_name(sid), "{not valid json…")
    got = ec.claim_next(H.NOW)
    assert got == sid
    result = ec.process(sid, H.NOW)
    assert result is None                             # quarantined
    assert (paths.quarantine / instruction_name(sid)).exists()
    assert len(mt5.order_log) == 0


def test_digest_mismatch(tmp_path):
    ec, paths, ledger, audit, mt5 = H.build(tmp_path)
    rec = serialize.with_integrity_digest(H.make_instruction())
    rec["entry_price"] = 9.99999                      # tamper after digest
    atomic_write_text(paths.pending / instruction_name(rec["signal_id"]),
                      serialize.dumps(rec))
    result = H.drain(ec)[0]
    assert result["status"] == ResultState.REJECTED
    assert result["reason_code"] == "E_INTEGRITY"
    assert len(mt5.order_log) == 0


def test_schema_mismatch(tmp_path):
    # PR-4A: the multi-session pipeline accepts schema 2 only; a schema OUTSIDE the
    # allow-list (e.g. the retired London-only schema 1) is rejected E_SCHEMA.
    ec, paths, ledger, audit, mt5 = H.build(tmp_path)
    H.produce(paths, H.make_instruction(schema_version=1))
    result = H.drain(ec)[0]
    assert result["status"] == ResultState.REJECTED
    assert result["reason_code"] == "E_SCHEMA"
    assert len(mt5.order_log) == 0


def test_strategy_mismatch(tmp_path):
    ec, paths, ledger, audit, mt5 = H.build(tmp_path)
    H.produce(paths, H.make_instruction(strategy_version="swing_orb.v0.0.1"))
    result = H.drain(ec)[0]
    assert result["status"] == ResultState.REJECTED
    assert result["reason_code"] == "E_STRATEGY"
    assert len(mt5.order_log) == 0


# -- true end-to-end from the REAL strategy engine (pandas-gated) -----------
ENGINE = Path(__file__).resolve().parents[2] / "run_dir" / "code" / "signal_engine.py"
SYNTH = Path(__file__).resolve().parents[2] / "tests"


def _load_engine():
    spec = importlib.util.spec_from_file_location("se_valid_engine", ENGINE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_real_engine_to_execution(tmp_path):
    pytest.importorskip("pandas")
    pytest.importorskip("numpy")
    import sys
    from datetime import datetime, timezone
    if str(SYNTH) not in sys.path:
        sys.path.insert(0, str(SYNTH))
    import synth

    se = _load_engine()
    df = synth.uptrend_frame(days=60)
    df2, _ = synth.inject_bullish_orb(df, "2024-01-25")
    eng = se.SignalEngine({"news_events": [], "news_asof": "2024-01-25T11:15:00Z"})
    eng.generate({"EURUSD.FX": df2})
    instrs = eng.instructions["EURUSD.FX"]
    assert len(instrs) == 1

    now = datetime(2024, 1, 25, 11, 30, tzinfo=timezone.utc)
    ec, paths, ledger, audit, mt5 = H.build(tmp_path)
    for ins in instrs:
        H.produce(paths, ins, now=now, audit=audit)
    result = H.drain(ec, now=now)[0]
    # the strategy signal is executed end-to-end through the adapter
    assert result["status"] == ResultState.EXECUTED
    sid = instrs[0]["signal_id"]
    assert result["signal_id"] == sid
    assert mt5.position_by_comment(sid) is not None
    assert (paths.archive_accepted / instruction_name(sid)).exists()
    # ack + result artifacts written
    ack_id = serialize.result_id(sid, "ACK")
    assert (paths.acks / ack_name(sid, ack_id)).exists()
    rid = serialize.result_id(sid, ResultState.EXECUTED)
    assert (paths.results / result_name(sid, rid)).exists()
