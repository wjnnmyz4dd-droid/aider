"""PR-3I / M9 — risk-per-trade authority (BLOCKED: execution-sizing contract required).

The compliance risk gate authorizes a declared ``risk_fraction`` and computes a
NOTIONAL monetary amount = ``risk_fraction × initial_balance``. It never sees an
executable volume, tick value, or stop-distance-derived money figure, and the EA
sizes every order from an operator ``DefaultVolume`` (see the companion EA proof).
Therefore compliance cannot prove the ACTUAL monetary risk of a trade before
authorization. These tests CHARACTERIZE that gap (no production change is made):
closing M9 requires an execution-sizing authority contract, which is out of scope
for this PR. Deterministic; no networking.
"""

from __future__ import annotations

from forex_swing_orb.compliance.contract import (FtmoConfig, FtmoProfile,
                                                 candidate_risk_amount)
from forex_swing_orb.compliance.gates import gate_risk
from forex_swing_orb.compliance.contract import ReasonCode

PROF = FtmoProfile(initial_balance=100000.0, daily_loss_pct=0.05, maximum_loss_pct=0.10)
CFG = FtmoConfig(safety_buffer_fraction=0.20, max_risk_per_trade_pct=0.01)
ACCT = {"equity": 100000.0, "day_start_balance": 100000.0,
        "day_start_equity": 100000.0, "initial_balance": 100000.0}
NOW = None            # gate_risk does not use now


def _cand(risk_fraction=0.0025, **extra):
    c = {"risk_fraction": risk_fraction}
    c.update(extra)
    return c


def _true_monetary_risk(volume, entry, stop, tick_size, tick_value):
    """The ACTUAL money at risk if the position hits its stop (the figure compliance
    would need, but cannot obtain pre-authorization)."""
    return abs(entry - stop) / tick_size * tick_value * volume


# --------------------------------------------------------------------------- #
# the declared model is fraction-only
# --------------------------------------------------------------------------- #
def test_candidate_risk_amount_is_declared_fraction_times_initial():
    assert candidate_risk_amount(_cand(0.0025), PROF) == 250.0     # 0.0025 * 100000
    assert candidate_risk_amount(_cand(0.01), PROF) == 1000.0


def test_risk_gate_enforces_declared_fraction_cap():
    ok = gate_risk(_cand(0.01), ACCT, PROF, CFG, NOW)
    over = gate_risk(_cand(0.0101), ACCT, PROF, CFG, NOW)
    assert ok.passed
    assert not over.passed and ReasonCode.RISK_PER_TRADE_EXCEEDED in over.reason_codes


# --------------------------------------------------------------------------- #
# the authority gap — compliance is blind to executable size
# --------------------------------------------------------------------------- #
def test_gate_verdict_independent_of_would_be_execution_size():
    # attaching an (arbitrary) executable volume the EA might use changes NOTHING:
    # the gate never reads it, proving compliance cannot bound true monetary risk.
    base = gate_risk(_cand(0.0025), ACCT, PROF, CFG, NOW)
    tiny = gate_risk(_cand(0.0025, volume=0.01), ACCT, PROF, CFG, NOW)
    huge = gate_risk(_cand(0.0025, volume=50.0), ACCT, PROF, CFG, NOW)
    assert base.passed and tiny.passed and huge.passed
    assert base.reason_codes == tiny.reason_codes == huge.reason_codes


def test_declared_amount_can_diverge_arbitrarily_from_true_risk():
    # same authorized fraction (250.0 declared), wildly different ACTUAL exposure
    # depending on the EA's DefaultVolume — which compliance never sees.
    declared = candidate_risk_amount(_cand(0.0025), PROF)          # 250.0
    true_small = _true_monetary_risk(0.01, 1.10, 1.098, 1e-5, 1.0)   # tiny lots
    true_large = _true_monetary_risk(50.0, 1.10, 1.098, 1e-5, 1.0)   # huge lots
    assert true_small < declared < true_large                      # unbounded either way
    # compliance authorizes the fraction regardless of which volume actually executes
    assert gate_risk(_cand(0.0025), ACCT, PROF, CFG, NOW).passed


def test_candidate_carries_no_executable_volume_field():
    # the compliance candidate has no authoritative volume the gate could size from
    assert "volume" not in _cand()


# --------------------------------------------------------------------------- #
# property B — removing the ability to prove monetary risk is never MORE permissive
# --------------------------------------------------------------------------- #
def test_propB_no_monetary_proof_is_not_more_permissive():
    # the declared-fraction gate is already the ONLY proof; there is no stricter
    # monetary check to remove, so the current authorization is a fixed upper bound
    # on permissiveness (a monetary contract could only TIGHTEN it, never loosen).
    with_proof_absent = gate_risk(_cand(0.0025), ACCT, PROF, CFG, NOW)
    assert with_proof_absent.passed          # today: passes on declared fraction alone
    # an over-cap fraction is still blocked — the fraction bound remains authoritative
    assert not gate_risk(_cand(0.02), ACCT, PROF, CFG, NOW).passed
