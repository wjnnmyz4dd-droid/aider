"""PR-3G / M3 — producer per-symbol/session fault isolation.

One deterministic symbol or session exception must fail ONLY that unit (fail-closed,
no instruction written, no capacity reserved) and must not starve unrelated symbols/
sessions or suppress end-of-cycle reconciliation. Global prerequisite failures
(account/news/kill) still block the whole cycle. Deterministic; mock providers.
"""

from __future__ import annotations

from datetime import datetime, timezone

from forex_swing_orb.producer import ProducerRunner, RunnerConfig, RunnerMode
from forex_swing_orb.producer.contract import CycleOutcome, RunnerReason
from forex_swing_orb.producer.mock_providers import (MockAccountProvider,
                                                     MockBrokerHealthProvider,
                                                     MockMarketDataProvider,
                                                     MockNewsProvider, StubEngine)
from forex_swing_orb.compliance import ComplianceConfig, FtmoConfig, FtmoProfile
from forex_swing_orb.session.profiles import profiles_for
from conftest import NOW

BOTH = datetime(2026, 1, 7, 14, 0, 0, tzinfo=timezone.utc)   # LONDON + NEW_YORK active
FOUR = ("EURUSD.FX", "GBPUSD.FX", "USDJPY.FX", "AUDUSD.FX")


def _compliance():
    return ComplianceConfig(
        profile=FtmoProfile(initial_balance=100000.0, account_currency="USD",
                            rule_source="ftmo (2-Step)", rule_source_verified_at="2026-08-05",
                            profile_verified=True),
        ftmo=FtmoConfig(max_open_positions=10, one_position_per_symbol=True))


def _runner(tmp_path, symbols=FOUR, enabled=("LONDON",), now=BOTH, account=None, news=None):
    from forex_swing_orb.bridge.paths import BridgePaths
    paths = BridgePaths(tmp_path / "bridge").ensure()
    profiles = profiles_for(enabled)
    cfg = RunnerConfig(symbols=symbols, mode=RunnerMode.DEMO, ftmo_profile_verified=True,
                       compliance=_compliance(), session_profiles=profiles)
    by_session = {p.session_id: StubEngine(emit=True, session_id=p.session_id) for p in profiles}
    runner = ProducerRunner(
        cfg, bridge_paths=paths, market=MockMarketDataProvider(symbols, now),
        account=account or MockAccountProvider(now), news=news if news is not None else MockNewsProvider(now),
        broker=MockBrokerHealthProvider(), strategy_by_session=by_session,
        state_path=str(tmp_path / "state.json"),
        runner_audit_path=str(tmp_path / "ra.jsonl"),
        compliance_audit_path=str(tmp_path / "ca.jsonl"))
    return runner, paths


def _count_reconcile(runner):
    calls = {"n": 0}
    orig = runner._ingest_and_reconcile

    def wrap(now):
        calls["n"] += 1
        return orig(now)
    runner._ingest_and_reconcile = wrap
    return calls


def _outcomes(res):
    return [r.outcome for r in res]


# --------------------------------------------------------------------------- #
# per-symbol isolation (§29.1-2, 4)
# --------------------------------------------------------------------------- #
def test_first_symbol_raises_others_processed(tmp_path):
    runner, paths = _runner(tmp_path)
    orig = runner._prepare_symbol

    def boom(sym, now):
        if sym == "EURUSD.FX":
            raise RuntimeError("prep boom")
        return orig(sym, now)
    runner._prepare_symbol = boom
    res = runner.run_cycle(BOTH)
    by = {r.symbol: r for r in res}
    assert by["EURUSD.FX"].outcome == CycleOutcome.UNIT_ERROR
    # the other three symbols were still evaluated (produced non-UNIT_ERROR results)
    for s in ("GBPUSD.FX", "USDJPY.FX", "AUDUSD.FX"):
        assert by[s].outcome != CycleOutcome.UNIT_ERROR


def test_middle_symbol_raises_others_processed(tmp_path):
    runner, paths = _runner(tmp_path)
    orig = runner._prepare_symbol

    def boom(sym, now):
        if sym == "USDJPY.FX":
            raise RuntimeError("prep boom")
        return orig(sym, now)
    runner._prepare_symbol = boom
    res = runner.run_cycle(BOTH)
    by = {r.symbol: r for r in res}
    assert by["USDJPY.FX"].outcome == CycleOutcome.UNIT_ERROR
    assert by["EURUSD.FX"].outcome != CycleOutcome.UNIT_ERROR
    assert by["AUDUSD.FX"].outcome != CycleOutcome.UNIT_ERROR


def test_symbol_error_diagnostics(tmp_path):
    runner, paths = _runner(tmp_path)

    def boom(sym, now):
        raise ValueError("bars corrupt")
    runner._prepare_symbol = boom
    res = runner.run_cycle(BOTH)
    assert all(r.outcome == CycleOutcome.UNIT_ERROR for r in res)
    assert all(RunnerReason.UNIT_ERROR in r.reason_codes for r in res)


# --------------------------------------------------------------------------- #
# per-session isolation (§29.3, 5)
# --------------------------------------------------------------------------- #
def test_one_session_raises_siblings_continue(tmp_path):
    runner, paths = _runner(tmp_path, symbols=("EURUSD.FX", "GBPUSD.FX"),
                            enabled=("LONDON", "NEW_YORK"))
    orig = runner._run_symbol_session

    def boom(sym, profile, *a, **k):
        if sym == "EURUSD.FX" and profile.session_id == "NEW_YORK":
            raise RuntimeError("session boom")
        return orig(sym, profile, *a, **k)
    runner._run_symbol_session = boom
    res = runner.run_cycle(BOTH)
    units = {(r.symbol, r.detail.get("session_id")): r.outcome for r in res}
    assert units[("EURUSD.FX", "NEW_YORK")] == CycleOutcome.UNIT_ERROR
    # sibling sessions/symbols still evaluated
    assert units[("EURUSD.FX", "LONDON")] != CycleOutcome.UNIT_ERROR
    assert units[("GBPUSD.FX", "NEW_YORK")] != CycleOutcome.UNIT_ERROR
    assert units[("GBPUSD.FX", "LONDON")] != CycleOutcome.UNIT_ERROR


# --------------------------------------------------------------------------- #
# reconciliation MUST still run after local faults (§26, §39 G)
# --------------------------------------------------------------------------- #
def test_reconcile_runs_despite_symbol_fault(tmp_path):
    runner, paths = _runner(tmp_path)
    calls = _count_reconcile(runner)

    def boom(sym, now):
        raise RuntimeError("prep boom")
    runner._prepare_symbol = boom
    runner.run_cycle(BOTH)
    assert calls["n"] == 1                       # reconciliation still ran


def test_reconcile_runs_despite_session_fault(tmp_path):
    runner, paths = _runner(tmp_path, enabled=("LONDON", "NEW_YORK"))
    calls = _count_reconcile(runner)

    def boom(*a, **k):
        raise RuntimeError("session boom")
    runner._run_symbol_session = boom
    runner.run_cycle(BOTH)
    assert calls["n"] == 1


# --------------------------------------------------------------------------- #
# global prerequisite failures still block the whole cycle (§27, §39 F)
# --------------------------------------------------------------------------- #
def test_global_account_failure_blocks_all(tmp_path):
    bad_acct = MockAccountProvider(BOTH); bad_acct.set(is_demo=False, account_type="REAL")
    runner, paths = _runner(tmp_path, account=bad_acct)
    res = runner.run_cycle(BOTH)
    assert res and all(r.outcome == CycleOutcome.ACCOUNT_REJECTED for r in res)
    assert not list(paths.pending.glob("*.json"))       # no entries written


def test_kill_switch_blocks_all(tmp_path):
    runner, paths = _runner(tmp_path)
    runner._kill_switch = lambda now: True
    r = runner.run_cycle(BOTH)
    assert r[0].outcome == CycleOutcome.KILL_SWITCH
    assert not list(paths.pending.glob("*.json"))


# --------------------------------------------------------------------------- #
# property E: one unit fault cannot reduce unrelated safe evaluations to zero
# --------------------------------------------------------------------------- #
def test_unit_fault_does_not_zero_out_others(tmp_path):
    runner, paths = _runner(tmp_path)
    baseline = runner.run_cycle(BOTH)
    written = sum(1 for r in baseline if r.outcome == CycleOutcome.INSTRUCTION_WRITTEN)
    assert written >= 1
    runner2, paths2 = _runner(tmp_path / "b")
    orig = runner2._prepare_symbol
    runner2._prepare_symbol = lambda s, n: (_ for _ in ()).throw(RuntimeError("x")) if s == "EURUSD.FX" else orig(s, n)
    res2 = runner2.run_cycle(BOTH)
    written2 = sum(1 for r in res2 if r.outcome == CycleOutcome.INSTRUCTION_WRITTEN)
    assert written2 >= 1                          # unrelated symbols still wrote
