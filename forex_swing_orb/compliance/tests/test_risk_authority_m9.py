"""PR-3J / M9 — compliance risk-per-trade AUTHORITY (closed).

The risk gate now RE-PROVES the actual monetary loss-at-stop from the approved
execution ``volume`` + broker tick metadata + capital base, and requires it within
``risk_fraction × initial_balance``. A declared ``risk_fraction`` is a policy cap,
never the sole proof. Missing volume/metadata fails closed. Deterministic; no networking.
"""

from __future__ import annotations

import pytest

from forex_swing_orb.compliance.contract import (FtmoConfig, FtmoProfile,
                                                 ReasonCode)
from forex_swing_orb.compliance.gates import gate_risk

PROF = FtmoProfile(initial_balance=100000.0, daily_loss_pct=0.05, maximum_loss_pct=0.10)
CFG = FtmoConfig(safety_buffer_fraction=0.20, max_risk_per_trade_pct=0.01)
ACCT = {"equity": 100000.0, "day_start_balance": 100000.0,
        "day_start_equity": 100000.0, "initial_balance": 100000.0}
# EURUSD-like metadata; tick_value account-currency-denominated.
BH = {"tick_size": 0.00001, "tick_value": 1.0}
NOW = None


def _cand(volume=0.10, risk_fraction=0.005, entry=1.10000, stop=1.09500, **extra):
    c = {"risk_fraction": risk_fraction, "entry": entry, "stop_loss": stop, "volume": volume}
    c.update(extra)
    return c


def _g(cand, bh=BH):
    return gate_risk(cand, ACCT, PROF, CFG, NOW, broker_health=bh)


# --------------------------------------------------------------------------- #
# authoritative recompute
# --------------------------------------------------------------------------- #
def test_passes_when_actual_loss_within_budget():
    # loss = 0.005/1e-5 * 1.0 * 0.10 = 50 <= permitted 0.005*100000 = 500
    v = _g(_cand(volume=0.10))
    assert v.passed and v.evidence["loss_at_stop"] == pytest.approx(50.0)


def test_rejects_when_actual_loss_exceeds_budget():
    # volume 2.0 -> loss = 0.005/1e-5 * 1.0 * 2.0 = 1000 > 500
    v = _g(_cand(volume=2.0))
    assert not v.passed and ReasonCode.RISK_PER_TRADE_EXCEEDED in v.reason_codes


def test_declared_fraction_alone_is_not_proof():
    # identical risk_fraction, oversize volume -> the ACTUAL loss is what's judged
    ok = _g(_cand(volume=0.10, risk_fraction=0.005))
    bad = _g(_cand(volume=5.0, risk_fraction=0.005))
    assert ok.passed and not bad.passed


# --------------------------------------------------------------------------- #
# fail closed on missing volume / metadata (§10, §27)
# --------------------------------------------------------------------------- #
def test_missing_volume_fails_closed():
    v = _g(_cand(volume=None))
    assert not v.passed and ReasonCode.RISK_MONETARY_UNVERIFIABLE in v.reason_codes


def test_missing_tick_value_fails_closed():
    v = _g(_cand(volume=0.10), bh={"tick_size": 0.00001})   # no tick_value
    assert not v.passed and ReasonCode.RISK_MONETARY_UNVERIFIABLE in v.reason_codes


def test_missing_broker_health_fails_closed():
    v = gate_risk(_cand(), ACCT, PROF, CFG, NOW)            # no broker_health
    assert not v.passed and ReasonCode.RISK_MONETARY_UNVERIFIABLE in v.reason_codes


def test_zero_tick_size_fails_closed():
    v = _g(_cand(volume=0.10), bh={"tick_size": 0.0, "tick_value": 1.0})
    assert not v.passed and ReasonCode.RISK_MONETARY_UNVERIFIABLE in v.reason_codes


def test_entry_equals_stop_fails_closed():
    v = _g(_cand(volume=0.10, entry=1.10000, stop=1.10000))
    assert not v.passed and ReasonCode.RISK_MONETARY_UNVERIFIABLE in v.reason_codes


# --------------------------------------------------------------------------- #
# tamper resistance (§39.3-4, property E)
# --------------------------------------------------------------------------- #
def test_tamper_volume_upward_rejected():
    assert _g(_cand(volume=0.10)).passed
    assert not _g(_cand(volume=3.0)).passed         # inflated volume -> actual loss > limit


def test_tamper_risk_fraction_down_cannot_hide_actual_risk():
    # lowering risk_fraction only TIGHTENS the permitted budget; it cannot license a
    # large actual loss. volume 2.0 loss=1000; lowering rf to 0.001 -> permit 100 -> reject.
    v = _g(_cand(volume=2.0, risk_fraction=0.001))
    assert not v.passed and ReasonCode.RISK_PER_TRADE_EXCEEDED in v.reason_codes


# --------------------------------------------------------------------------- #
# risk_fraction policy cap still enforced (before the monetary recompute)
# --------------------------------------------------------------------------- #
def test_risk_fraction_over_cap_still_rejected():
    v = _g(_cand(volume=0.10, risk_fraction=0.02))          # > max_risk_per_trade_pct 0.01
    assert not v.passed and ReasonCode.RISK_PER_TRADE_EXCEEDED in v.reason_codes


# --------------------------------------------------------------------------- #
# property D — removing monetary metadata is never more permissive
# --------------------------------------------------------------------------- #
def test_propD_removing_metadata_never_more_permissive():
    with_meta = _g(_cand(volume=0.10))
    without = _g(_cand(volume=0.10), bh={})
    assert with_meta.passed and not without.passed


def test_propE_exact_limit_boundary_deterministic():
    # choose volume so loss == permitted exactly: loss=500 -> volume = 500/(0.005/1e-5*1.0)=1.0
    v = _g(_cand(volume=1.0))                                # loss = 500 == permitted 500 (approx)
    assert v.passed and v.evidence["loss_at_stop"] == pytest.approx(500.0)
    over = _g(_cand(volume=1.01))                           # meaningfully over -> reject
    assert not over.passed
