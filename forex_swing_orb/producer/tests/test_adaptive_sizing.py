"""Adaptive, account-aware position sizing via the EXISTING PR-3J authority.

Proves the risk-profile POLICY (a per-trade risk_fraction cap) flows through the
producer so PR-3J (compliance.sizing.allowable_volume) — the SOLE sizer — produces a
deterministic, explainable, account-aware volume; that it is subordinate to the
compliance/FTMO ceiling and H-1 (it can only reduce, never exceed the safe max); that
identical inputs are identical (no randomness/jitter); and that different LEGITIMATE
account/risk inputs naturally produce different volumes. No second sizing engine, no
random variation, no similarity-evasion.
"""

from __future__ import annotations

import dataclasses

import pytest

from forex_swing_orb.bridge import serialize
from forex_swing_orb.compliance import ComplianceConfig, FtmoProfile
from forex_swing_orb.compliance import sizing
from forex_swing_orb.compliance.contract import candidate_risk_amount
from forex_swing_orb.producer.contract import CycleOutcome
from forex_swing_orb.producer.mock_providers import MockBrokerHealthProvider
from conftest import NOW


def _profile(initial_balance=100000.0):
    return ComplianceConfig(profile=FtmoProfile(
        initial_balance=initial_balance, account_currency="USD",
        rule_source="ftmo.com/en/trading-objectives (2-Step)",
        rule_source_verified_at="2026-08-05", profile_verified=True))


def _with_policy(make_runner, *, risk_fraction, initial_balance=100000.0):
    runner, ctx = make_runner(now=NOW, compliance=_profile(initial_balance))
    # stamp the resolved policy cap exactly as wiring.build_runner_config would
    runner.config = dataclasses.replace(runner.config, policy_risk_fraction=risk_fraction,
                                        sizing_mode="ADAPTIVE")
    return runner, ctx


def _written(paths):
    files = sorted(paths.pending.glob("*.json"))
    assert len(files) == 1
    ok, rec = serialize.loads(files[0].read_text())
    assert ok
    return rec


# geometry from StubEngine: entry 1.10000, stop 1.09800 -> d=0.00200; tick 1e-5,
# tick_value 1.0 -> per_lot = 200 money/lot. So volume = risk_fraction*initial/200,
# step-rounded to 0.01, capped at volume_max=100.

# --- profiles resolve to deterministic volumes (items 1-3, 5) --------------
def test_moderate_profile_volume(make_runner):
    runner, ctx = _with_policy(make_runner, risk_fraction=0.005)   # 0.5% of 100k = 500
    res = runner.run_cycle(NOW)
    assert any(r.outcome == CycleOutcome.INSTRUCTION_WRITTEN for r in res)
    rec = _written(ctx["paths"])
    assert rec["risk_fraction"] == 0.005                # policy applied to the instruction
    assert rec["volume"] == 2.5                         # 500/200 = 2.5


def test_conservative_lt_moderate_lt_aggressive(make_runner):
    vols = {}
    for name, rf in (("C", 0.0025), ("M", 0.005), ("A", 0.01)):
        runner, ctx = _with_policy(make_runner, risk_fraction=rf)
        runner.run_cycle(NOW)
        vols[name] = _written(ctx["paths"])["volume"]
    assert vols["C"] == 1.25 and vols["M"] == 2.5 and vols["A"] == 5.0
    assert vols["C"] < vols["M"] < vols["A"]            # monotonic in risk fraction


# --- account-aware basis (items 5, 6, 25) ----------------------------------
# Proven at the PR-3J sizing level (candidate_risk_amount = risk_fraction ×
# initial_balance -> allowable_volume), which isolates the account-basis effect from
# the independent FTMO drawdown gate (a mismatched live balance vs a larger funded
# base would separately, and correctly, trip that gate).
def test_account_basis_scales_volume_deterministically(make_runner):
    bh = MockBrokerHealthProvider().snapshot("EURUSD.FX", NOW)
    cand = {"entry": 1.10000, "stop_loss": 1.09800, "risk_fraction": 0.0025}
    r1, _ = _with_policy(make_runner, risk_fraction=0.0025, initial_balance=100000.0)
    r2, _ = _with_policy(make_runner, risk_fraction=0.0025, initial_balance=200000.0)
    v1 = r1._size_volume(cand, bh)                       # 250/200
    v2 = r2._size_volume(cand, bh)                       # 500/200 (double funded capital)
    assert v1 == 1.25 and v2 == 2.5
    assert v2 == 2 * v1                                  # deterministic, proportional


def test_smaller_account_smaller_volume(make_runner):
    bh = MockBrokerHealthProvider().snapshot("EURUSD.FX", NOW)
    cand = {"entry": 1.10000, "stop_loss": 1.09800, "risk_fraction": 0.0025}
    big, _ = _with_policy(make_runner, risk_fraction=0.0025, initial_balance=100000.0)
    small, _ = _with_policy(make_runner, risk_fraction=0.0025, initial_balance=50000.0)
    assert big._size_volume(cand, bh) == 1.25
    assert small._size_volume(cand, bh) == 0.62         # 125/200 = 0.625 -> step-down 0.62


# --- determinism / no randomness (items 7, 8, 24) --------------------------
def test_identical_inputs_identical_volume(make_runner):
    outs = []
    for _ in range(6):
        r, c = _with_policy(make_runner, risk_fraction=0.005)
        r.run_cycle(NOW)
        outs.append(_written(c["paths"])["volume"])
    assert set(outs) == {2.5}                            # zero variation across runs


def test_no_random_or_hash_or_jitter_tokens_in_sizing_sources():
    import ast
    from pathlib import Path
    for mod in ("compliance/sizing.py", "runtime/risk_profile.py"):
        src = Path(__file__).resolve().parents[2] / mod   # parents[2] == forex_swing_orb/
        code = ast.dump(ast.parse(src.read_text(encoding="utf-8")))
        for banned in ("random", "uniform", "getpid", "monotonic", "perf_counter",
                       "md5", "sha1", "sha256", "getrandom", "urandom"):
            assert banned not in code, f"{mod} must not use {banned!r} in sizing"


# --- broker constraints (items 9, 10, 11) ----------------------------------
def test_broker_volume_step_rounds_down(make_runner):
    # 0.0025 * 100k = 250 -> raw 1.25; with step 0.5 -> rounds DOWN to 1.0
    broker = MockBrokerHealthProvider(volume_step=0.5, volume_min=0.5)
    runner, ctx = make_runner(now=NOW, compliance=_profile(), broker=broker)
    runner.config = dataclasses.replace(runner.config, policy_risk_fraction=0.0025)
    runner.run_cycle(NOW)
    assert _written(ctx["paths"])["volume"] == 1.0


def test_broker_volume_max_caps(make_runner):
    broker = MockBrokerHealthProvider(volume_max=2.0)
    runner, ctx = make_runner(now=NOW, compliance=_profile(), broker=broker)
    runner.config = dataclasses.replace(runner.config, policy_risk_fraction=0.01)   # raw 5.0
    runner.run_cycle(NOW)
    assert _written(ctx["paths"])["volume"] == 2.0       # capped at broker max


def test_wider_stop_reduces_volume(make_runner):
    runner, _ = _with_policy(make_runner, risk_fraction=0.005)
    bh = MockBrokerHealthProvider().snapshot("EURUSD.FX", NOW)
    tight = runner._size_volume({"entry": 1.10000, "stop_loss": 1.09900,
                                 "risk_fraction": 0.005}, bh)   # d=0.001 -> per_lot 100
    wide = runner._size_volume({"entry": 1.10000, "stop_loss": 1.09700,
                                "risk_fraction": 0.005}, bh)    # d=0.003 -> per_lot 300
    assert tight > wide                                  # wider stop -> smaller size


# --- subordinate to compliance/FTMO ceiling (items 12, 13, 14, 26, 27) -----
def test_policy_above_ceiling_is_rejected_by_compliance(make_runner):
    # a policy fraction above max_risk_per_trade_pct (0.01) must NOT authorize a trade:
    # the compliance RISK gate rejects it -> no write. User config cannot override the
    # ceiling (defense in depth even if config validation were bypassed).
    runner, ctx = make_runner(now=NOW, compliance=_profile())
    runner.config = dataclasses.replace(runner.config, policy_risk_fraction=0.02)
    res = runner.run_cycle(NOW)
    assert not any(r.wrote_bridge for r in res)
    assert not list(ctx["paths"].pending.glob("*.json"))


def test_unknown_metadata_fails_closed(make_runner):
    broker = MockBrokerHealthProvider(tick_value=None)   # UNKNOWN tick value
    runner, ctx = make_runner(now=NOW, compliance=_profile(), broker=broker)
    runner.config = dataclasses.replace(runner.config, policy_risk_fraction=0.005)
    res = runner.run_cycle(NOW)
    assert not any(r.wrote_bridge for r in res)          # UNKNOWN -> no trade (no fixed lot)


# --- PR-3J is the SOLE sizer + H-1 consistency (items 20, 27) ---------------
def test_pr3j_is_the_sole_sizer(make_runner):
    # the written volume EXACTLY equals an independent PR-3J computation from the same
    # inputs -> the runner adds no second sizing algorithm.
    runner, ctx = _with_policy(make_runner, risk_fraction=0.005)
    runner.run_cycle(NOW)
    rec = _written(ctx["paths"])
    bh = MockBrokerHealthProvider().snapshot("EURUSD.FX", NOW)
    permitted = candidate_risk_amount({"risk_fraction": 0.005},
                                      runner.config.compliance.profile)
    expect = sizing.allowable_volume(rec["entry_price"], rec["stop_loss"], permitted,
                                     bh["tick_size"], bh["tick_value"],
                                     bh["volume_min"], bh["volume_max"], bh["volume_step"])
    assert rec["volume"] == expect


def test_written_risk_fraction_feeds_h1_consistently(make_runner):
    # H-1 committed-risk reads risk_fraction off the written instruction; the policy cap
    # must be the value written, so sizer, compliance, and H-1 all agree on one number.
    runner, ctx = _with_policy(make_runner, risk_fraction=0.0025)
    runner.run_cycle(NOW)
    assert _written(ctx["paths"])["risk_fraction"] == 0.0025


# --- explainability (item 7 UX) --------------------------------------------
def test_sizing_diagnostics_are_explainable(make_runner):
    runner, ctx = _with_policy(make_runner, risk_fraction=0.005)
    res = runner.run_cycle(NOW)
    written = [r for r in res if r.outcome == CycleOutcome.INSTRUCTION_WRITTEN]
    assert written
    s = written[0].detail["sizing"]
    assert s["authority"].startswith("PR-3J")
    assert s["capital_basis"] == 100000.0 and s["risk_fraction"] == 0.005
    assert s["risk_amount"] == 500.0 and s["final_volume"] == 2.5
    assert s["stop_distance"] == pytest.approx(0.00200) and s["raw_volume"] == pytest.approx(2.5)
