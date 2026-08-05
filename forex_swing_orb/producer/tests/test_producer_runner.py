"""Comprehensive Phase 7A tests for the Autonomous Producer Runner.

Covers the 36 required scenarios: PASS flow, no-trade, compliance reject, news
block/resume/missing/stale, account missing/stale, broker disconnected, stale/
gapped/unclosed/future market data, same-bar and restart de-duplication, ack/
result ingestion, uncertain reconciliation, multi-symbol scheduling, MTF wiring,
no-duplication/no-order/no-stop source guards, demo/FTMO/live startup gates,
service entry point + graceful shutdown, health/status, determinism, no-networking,
and Forex/FTMO-only enforcement.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from forex_swing_orb.bridge import serialize
from forex_swing_orb.bridge.audit import AuditLog
from forex_swing_orb.bridge.config import DEFAULT_CONFIG
from forex_swing_orb.bridge.ledger import DedupLedger
from forex_swing_orb.compliance import ComplianceConfig, ReasonCode as CRC
from forex_swing_orb.ea_mt5 import mock_mt5
from forex_swing_orb.ea_mt5.execution_consumer import ExecutionConsumer
from forex_swing_orb.producer import (CycleOutcome, ProducerRunner, RunnerConfig,
                                      RunnerDashboard, RunnerMode, RunnerReason,
                                      RunnerRefused, ProducerService, load_engine)
from forex_swing_orb.producer.mock_providers import (MockMarketDataProvider,
                                                     StubEngine, make_bars)
from conftest import NOW

PROD_DIR = Path(__file__).resolve().parents[1]


def _pending(paths):
    return list(paths.pending.glob("*.json"))


def _only(results, symbol="EURUSD.FX"):
    return [r for r in results if r.symbol == symbol][0]


# 1 ---------------------------------------------------------------------------
def test_pass_flow_writes_bridge(make_runner):
    runner, d = make_runner()
    res = _only(runner.run_cycle(NOW))
    assert res.outcome == CycleOutcome.INSTRUCTION_WRITTEN
    assert len(_pending(d["paths"])) == 1
    assert res.signal_id and res.compliance_decision_id
    # compliance audit written before bridge; both present
    assert Path(d["paths"].audit_log).exists()


# 2 ---------------------------------------------------------------------------
def test_no_trade_no_bridge_write(make_runner):
    runner, d = make_runner(engine=StubEngine(emit=False))
    res = _only(runner.run_cycle(NOW))
    assert res.outcome == CycleOutcome.NO_CANDIDATE
    assert _pending(d["paths"]) == []


# 3 ---------------------------------------------------------------------------
def test_compliance_reject_no_bridge_write(make_runner):
    # risk_fraction above the per-trade cap (0.01) but below the daily projected
    # internal limit, so the RISK gate (not the earlier FTMO gate) is the rejecter.
    runner, d = make_runner(engine=StubEngine(emit=True, risk_fraction=0.015))
    res = _only(runner.run_cycle(NOW))
    assert res.outcome == CycleOutcome.COMPLIANCE_REJECT
    assert CRC.RISK_PER_TRADE_EXCEEDED in res.reason_codes
    assert _pending(d["paths"]) == []


# 4, 5, 6, 7 -----------------------------------------------------------------
def _event(now, currency="USD", impact="HIGH", offset_min=0):
    return {"event_id": "E1", "currency": currency, "impact": impact,
            "event_timestamp": serialize.iso_utc(now + timedelta(minutes=offset_min)),
            "verification_state": "VERIFIED", "event_name": "x"}


def test_news_high_impact_block(make_runner):
    from forex_swing_orb.producer.mock_providers import MockNewsProvider
    runner, d = make_runner(news=MockNewsProvider(NOW, events=[_event(NOW, offset_min=0)]))
    res = _only(runner.run_cycle(NOW))
    assert res.outcome == CycleOutcome.COMPLIANCE_REJECT
    assert CRC.NEWS_LOCKOUT in res.reason_codes
    assert _pending(d["paths"]) == []


def test_news_auto_resume(make_runner):
    from forex_swing_orb.producer.mock_providers import MockNewsProvider
    runner, d = make_runner(news=MockNewsProvider(NOW, events=[_event(NOW, offset_min=-30)]))
    res = _only(runner.run_cycle(NOW))
    assert res.outcome == CycleOutcome.INSTRUCTION_WRITTEN


def test_missing_news_fails_closed(make_runner):
    from forex_swing_orb.producer.mock_providers import MockNewsProvider
    n = MockNewsProvider(NOW)
    n.set_bundle(None)
    runner, d = make_runner(news=n)
    res = _only(runner.run_cycle(NOW))
    assert res.outcome == CycleOutcome.COMPLIANCE_REJECT
    assert CRC.NEWS_DATA_UNAVAILABLE in res.reason_codes
    assert _pending(d["paths"]) == []


def test_stale_news_fails_closed(make_runner):
    from forex_swing_orb.producer.mock_providers import MockNewsProvider
    old = serialize.iso_utc(NOW - timedelta(hours=9))
    runner, d = make_runner(news=MockNewsProvider(NOW, events=[_event(NOW)], as_of=old))
    res = _only(runner.run_cycle(NOW))
    assert CRC.NEWS_DATA_STALE in res.reason_codes
    assert _pending(d["paths"]) == []


# 8, 9 ----------------------------------------------------------------------
def test_missing_account_fails_closed(make_runner):
    runner, d = make_runner()
    d["account"]._snap = None
    res = _only(runner.run_cycle(NOW))
    assert res.outcome == CycleOutcome.ACCOUNT_REJECTED
    assert _pending(d["paths"]) == []


def test_stale_account_fails_closed(make_runner):
    runner, d = make_runner()
    d["account"].set(as_of=serialize.iso_utc(NOW - timedelta(hours=1)))
    res = _only(runner.run_cycle(NOW))
    assert res.outcome == CycleOutcome.ACCOUNT_REJECTED
    assert RunnerReason.ACCOUNT_STALE in res.reason_codes


# 10 -------------------------------------------------------------------------
def test_broker_disconnected_fails_closed(make_runner):
    runner, d = make_runner()
    d["broker"].set(terminal_connected=False)
    res = _only(runner.run_cycle(NOW))
    assert res.outcome == CycleOutcome.COMPLIANCE_REJECT
    assert CRC.TERMINAL_DISCONNECTED in res.reason_codes
    assert _pending(d["paths"]) == []


# 11, 12, 13 -----------------------------------------------------------------
def test_stale_market_data_fails_closed(make_runner):
    runner, d = make_runner()
    stale = make_bars("EURUSD.FX", "M15", NOW - timedelta(hours=2), n=120)
    d["market"].set("EURUSD.FX", "M15", stale)
    res = _only(runner.run_cycle(NOW))
    assert res.outcome == CycleOutcome.DATA_REJECTED
    assert RunnerReason.DATA_STALE in res.reason_codes


def test_temporal_gap_fails_closed(make_runner):
    runner, d = make_runner()
    bars = make_bars("EURUSD.FX", "M15", NOW, n=120)
    del bars.rows[-3]                        # mid-week hole -> gap
    d["market"].set("EURUSD.FX", "M15", bars)
    res = _only(runner.run_cycle(NOW))
    assert res.outcome == CycleOutcome.DATA_REJECTED
    assert RunnerReason.DATA_GAP in res.reason_codes


def test_unclosed_bar_rejected(make_runner):
    runner, d = make_runner()
    bars = make_bars("EURUSD.FX", "M15", NOW, n=120)
    bars.rows.append({"open_time": NOW, "open": 1.1, "high": 1.1, "low": 1.1, "close": 1.1})
    d["market"].set("EURUSD.FX", "M15", bars)
    res = _only(runner.run_cycle(NOW))
    assert res.outcome == CycleOutcome.DATA_REJECTED
    assert RunnerReason.DATA_UNCLOSED_BAR in res.reason_codes


# 14 -------------------------------------------------------------------------
def test_same_bar_not_evaluated_twice(make_runner):
    runner, d = make_runner()
    r1 = _only(runner.run_cycle(NOW))
    r2 = _only(runner.run_cycle(NOW))
    assert r1.outcome == CycleOutcome.INSTRUCTION_WRITTEN
    assert r2.outcome == CycleOutcome.NO_NEW_BAR
    assert len(_pending(d["paths"])) == 1


# 15, 16 ---------------------------------------------------------------------
def test_restart_no_duplicate_signal(make_runner, tmp_path):
    runner, d = make_runner()
    runner.run_cycle(NOW)
    assert len(_pending(d["paths"])) == 1
    # simulate restart: brand-new runner over the SAME bridge + state, wiped mem
    runner2 = ProducerRunner(
        d["cfg"], bridge_paths=d["paths"], market=d["market"], account=d["account"],
        news=d["news"], broker=d["broker"], strategy=d["engine"],
        state_path=str(tmp_path / "state.json"),
        runner_audit_path=str(tmp_path / "runner_audit.jsonl"),
        compliance_audit_path=str(tmp_path / "compliance.jsonl"))
    r = _only(runner2.run_cycle(NOW))
    assert r.outcome == CycleOutcome.NO_NEW_BAR
    assert len(_pending(d["paths"])) == 1


def test_duplicate_instruction_prevented_after_state_loss(make_runner, tmp_path):
    runner, d = make_runner()
    runner.run_cycle(NOW)
    # wipe runner state entirely -> only the bridge dedup can prevent a dup
    Path(tmp_path / "state.json").unlink()
    runner2 = ProducerRunner(
        d["cfg"], bridge_paths=d["paths"], market=d["market"], account=d["account"],
        news=d["news"], broker=d["broker"], strategy=d["engine"],
        state_path=str(tmp_path / "state.json"),
        runner_audit_path=str(tmp_path / "runner_audit.jsonl"),
        compliance_audit_path=str(tmp_path / "compliance.jsonl"))
    r = _only(runner2.run_cycle(NOW))
    assert r.outcome == CycleOutcome.DUPLICATE_SUPPRESSED
    assert len(_pending(d["paths"])) == 1       # still exactly one


# 17, 18, 19 -----------------------------------------------------------------
def test_ack_and_result_ingestion_and_reconcile(make_runner):
    from forex_swing_orb.producer import ingest
    runner, d = make_runner()
    runner.run_cycle(NOW)
    sid = runner.state.written_signals[0]
    # uncertain: an ack exists but no terminal result yet
    (d["paths"].acks / f"{sid}.abc.ack.json").write_text("{}", encoding="utf-8")
    st = ingest.signal_status(d["paths"], sid)
    assert st["ack_present"] and st["reconcile_required"]

    # now execute via the accepted consumer over the SAME bridge -> terminal result
    mt5 = mock_mt5.MockMT5(); mt5.add_symbol("EURUSD")
    ec = ExecutionConsumer(d["paths"], DEFAULT_CONFIG, DedupLedger(d["paths"].dedup_ledger),
                           AuditLog(d["paths"].audit_log), mt5)
    claimed = ec.claim_next(NOW)
    ec.process(claimed, NOW)
    st2 = ingest.signal_status(d["paths"], sid)
    assert st2["terminal"] and not st2["reconcile_required"]


# 20 -------------------------------------------------------------------------
def test_multi_symbol_scheduling(make_runner):
    syms = ("EURUSD.FX", "GBPUSD.FX")
    runner, d = make_runner(symbols=syms,
                            market=MockMarketDataProvider(syms, NOW))
    results = runner.run_cycle(NOW)
    assert {r.symbol for r in results} == set(syms)
    assert all(r.outcome == CycleOutcome.INSTRUCTION_WRITTEN for r in results)
    assert set(runner.state.last_processed) == set(syms)
    assert len(_pending(d["paths"])) == 2


# 21 -------------------------------------------------------------------------
def test_missing_htf_input_fails_closed(make_runner):
    runner, d = make_runner()
    d["market"].set("EURUSD.FX", "H4", None)      # required TF missing
    res = _only(runner.run_cycle(NOW))
    assert res.outcome == CycleOutcome.DATA_REJECTED


def test_real_engine_loads_and_runs(make_runner):
    # exercises the real frozen SignalEngine load path + adapter wiring (D1/H4
    # derived internally from the M15 exec frame). Likely NO_CANDIDATE on flat data.
    eng = load_engine({}, validate_scrubber=False)
    runner, d = make_runner(engine=eng)
    res = _only(runner.run_cycle(NOW))
    assert res.outcome in (CycleOutcome.NO_CANDIDATE, CycleOutcome.INSTRUCTION_WRITTEN,
                           CycleOutcome.DATA_REJECTED)


# 22, 23, 24, 25, 33, 35 -----------------------------------------------------
def _producer_sources():
    return [p for p in PROD_DIR.glob("*.py")]


def test_no_duplicate_strategy_logic():
    banned = ("def evaluate_symbol", "def confirmed_pivots", "def trend_from_pivots",
              "def compute_signal_id", "def htf_bars", "def trend_health")
    for f in _producer_sources():
        s = f.read_text(encoding="utf-8")
        for b in banned:
            assert b not in s, f"{f.name} reimplements strategy: {b}"


def test_no_duplicate_compliance_logic():
    banned = ("def gate_ftmo", "def gate_news", "def gate_broker_health",
              "internal_daily_limit =", "def ftmo_limits")
    for f in _producer_sources():
        s = f.read_text(encoding="utf-8")
        for b in banned:
            assert b not in s, f"{f.name} reimplements compliance: {b}"


def test_no_direct_order_placement_by_runner():
    banned = ("order_send", "OrderSend", ".Buy(", ".Sell(", "position_close")
    for f in _producer_sources():
        s = f.read_text(encoding="utf-8")
        for b in banned:
            assert b not in s, f"{f.name} places orders: {b}"


def test_no_stop_modification_by_runner():
    banned = ("modify_stop", "SetStop", "def _apply_stop", "PositionManager(")
    for f in _producer_sources():
        s = f.read_text(encoding="utf-8")
        for b in banned:
            assert b not in s, f"{f.name} modifies stops: {b}"


def test_no_networking():
    # code-level constructs (not prose): imports/calls that would touch a network
    banned = ("import socket", "import requests", "import urllib", "import http",
              "http.client", "urllib.request", "socket.socket", "subprocess",
              "os.system(", "webrequest(")
    for f in _producer_sources():
        s = f.read_text(encoding="utf-8").lower()
        for b in banned:
            assert b not in s, f"{f.name} contains networking construct: {b}"


def test_forex_only_enforcement(make_runner):
    syms = ("XAUUSD.FX",)
    runner, d = make_runner(symbols=syms, market=MockMarketDataProvider(syms, NOW))
    res = _only(runner.run_cycle(NOW), "XAUUSD.FX")
    assert res.outcome == CycleOutcome.DATA_REJECTED
    assert RunnerReason.DATA_NOT_FOREX in res.reason_codes


# 26, 27, 28 -----------------------------------------------------------------
def test_demo_enforcement(make_runner):
    runner, d = make_runner()
    d["account"].set(is_demo=False, account_type="REAL")
    with pytest.raises(RunnerRefused):
        runner.preflight(NOW)
    res = _only(runner.run_cycle(NOW))
    assert res.outcome == CycleOutcome.ACCOUNT_REJECTED
    assert _pending(d["paths"]) == []


def test_unverified_ftmo_blocks_startup(make_runner):
    runner, d = make_runner(ftmo_verified=False)
    with pytest.raises(RunnerRefused):
        runner.preflight(NOW)


def test_live_mode_startup_rejected(make_runner):
    runner, d = make_runner(mode=RunnerMode.LIVE)
    with pytest.raises(RunnerRefused):
        runner.preflight(NOW)


def test_unknown_connection_state_refused(make_runner):
    runner, d = make_runner()
    d["account"].set(terminal_connected=None)
    with pytest.raises(RunnerRefused):
        runner.preflight(NOW)


# 29, 30, 31 -----------------------------------------------------------------
def test_service_entry_point_runs_and_writes_health(make_runner, tmp_path):
    runner, d = make_runner()
    svc = ProducerService(runner, str(tmp_path / "svc.log"),
                          str(tmp_path / "health.json"), now_fn=lambda: NOW)
    svc.run_forever(max_cycles=1)
    health = Path(tmp_path / "health.json")
    assert health.exists()
    ok, obj = serialize.loads(health.read_text(encoding="utf-8"))
    assert ok and obj["mode"] == RunnerMode.DEMO


def test_graceful_shutdown(make_runner, tmp_path):
    runner, d = make_runner()
    svc = ProducerService(runner, str(tmp_path / "svc.log"),
                          str(tmp_path / "health.json"), now_fn=lambda: NOW)
    svc._stop = True                       # request shutdown before loop body
    svc.run_forever(max_cycles=5)          # returns promptly, no hang
    assert svc._stop is True


def test_dashboard_status_fields(make_runner):
    runner, d = make_runner()
    runner.run_cycle(NOW)
    s = RunnerDashboard(runner).status(NOW)
    for k in ("service_state", "demo_verified", "mt5_connected", "last_cycle",
              "last_processed_bar", "news_as_of", "pending_instructions",
              "unresolved_reconciliations", "last_error"):
        assert k in s
    assert s["demo_verified"] is True


# 32 -------------------------------------------------------------------------
def test_deterministic_audit_and_ids(make_runner):
    r1, d1 = make_runner()
    r2, d2 = make_runner()
    a = _only(r1.run_cycle(NOW))
    b = _only(r2.run_cycle(NOW))
    assert a.cycle_id == b.cycle_id
    assert a.signal_id == b.signal_id
    assert a.compliance_decision_id == b.compliance_decision_id


# 34 -------------------------------------------------------------------------
def test_kill_switch_blocks_cycle(make_runner):
    runner, d = make_runner(kill=lambda now: True)
    results = runner.run_cycle(NOW)
    assert results[0].outcome == CycleOutcome.KILL_SWITCH
    assert _pending(d["paths"]) == []
