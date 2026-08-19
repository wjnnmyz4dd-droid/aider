"""H-1 — aggregate account-risk reservation in the FTMO/risk projection.

Proves gate_risk subtracts ALREADY-COMMITTED account risk (open + outstanding +
same-cycle authorized intents, supplied by the runner as ``committed_risk_at_stop``)
from the daily projection, so simultaneous/fan-out candidates cannot each pass against
the same unreserved equity — and that an unverifiable/absent reservation is handled
correctly (fail closed when present-but-untrusted; backward-compatible 0 when absent).
No second risk authority: the gate reads a reserved amount; it still owns the decision.
Deterministic; no MT5, no runner.
"""

from __future__ import annotations

from types import SimpleNamespace

from forex_swing_orb.compliance import gates
from forex_swing_orb.compliance.contract import (FtmoConfig, FtmoProfile, ReasonCode,
                                                 Stage)

PROFILE = FtmoProfile(initial_balance=100000.0, account_currency="USD",
                      rule_source="ftmo.com/en/trading-objectives (2-Step)",
                      rule_source_verified_at="2026-08-05", profile_verified=True)
CFG = FtmoConfig()      # daily 5%, static 10%, safety_buffer 0.20 -> internal daily 4% (96000)


def _acct(**over):
    a = {"equity": 100000.0, "day_start_balance": 100000.0, "day_start_equity": 100000.0,
         "trading_day": None, "open_position_count": 0, "open_symbols": ()}
    a.update(over)
    return a


def _candidate(rf=0.01):
    # entry/stop geometry + a matching volume proven within budget by broker metadata
    return {"symbol": "EURUSD.FX", "direction": "LONG", "entry": 1.10000,
            "stop_loss": 1.09000, "take_profit": 1.12000, "risk_fraction": rf,
            "volume": 0.10}


BH = {"tick_size": 0.00001, "tick_value": 1.0}


def _risk(cand, acct):
    return gates.gate_risk(cand, acct, PROFILE, CFG, None, BH)


# --------------------------------------------------------------------------- #
# helper unit (the aggregation primitive)
# --------------------------------------------------------------------------- #
def test_committed_absent_defaults_zero():
    assert gates._committed_risk(_acct()) == (0.0, None)


def test_committed_present_valid():
    assert gates._committed_risk(_acct(committed_risk_at_stop=1234.0)) == (1234.0, None)


def test_committed_unverifiable_flag_fails_closed():
    amt, reason = gates._committed_risk(_acct(committed_risk_unverifiable=True))
    assert reason == "committed_risk_unverifiable"


def test_committed_none_fails_closed():
    amt, reason = gates._committed_risk(_acct(committed_risk_at_stop=None))
    assert reason == "committed_risk_at_stop"


def test_committed_nonfinite_fails_closed():
    assert gates._committed_risk(_acct(committed_risk_at_stop=float("inf")))[1] is not None
    assert gates._committed_risk(_acct(committed_risk_at_stop=float("nan")))[1] is not None


def test_committed_negative_fails_closed():
    assert gates._committed_risk(_acct(committed_risk_at_stop=-1.0))[1] is not None


# --------------------------------------------------------------------------- #
# gate_risk projection with committed risk
# --------------------------------------------------------------------------- #
def test_baseline_single_candidate_passes():
    v = _risk(_candidate(rf=0.01), _acct())          # committed absent -> 0
    assert v.passed, v.reason_codes


def test_committed_reduces_capacity_but_still_ok():
    # committed 3000 + candidate 1000 = 4000 -> projected 96000 == internal level (safe)
    v = _risk(_candidate(rf=0.01), _acct(committed_risk_at_stop=3000.0))
    assert v.passed, v.reason_codes


def test_committed_pushes_over_internal_daily_buffer_rejects():
    # committed 3001 + candidate 1000 -> projected 95999 < internal 96000 -> REJECT
    v = _risk(_candidate(rf=0.01), _acct(committed_risk_at_stop=3001.0))
    assert not v.passed and ReasonCode.RISK_PROJECTED_BREACH in v.reason_codes


def test_large_open_risk_blocks_candidate():
    v = _risk(_candidate(rf=0.01), _acct(committed_risk_at_stop=5000.0))
    assert not v.passed and ReasonCode.RISK_PROJECTED_BREACH in v.reason_codes


def test_committed_unverifiable_blocks_candidate():
    v = _risk(_candidate(rf=0.01), _acct(committed_risk_unverifiable=True))
    assert not v.passed and ReasonCode.UNKNOWN_STATE in v.reason_codes


def test_committed_never_increases_capacity():
    # a negative committed (impossible/ malformed) must NOT create extra room -> fail closed
    v = _risk(_candidate(rf=0.01), _acct(committed_risk_at_stop=-10000.0))
    assert not v.passed


# --------------------------------------------------------------------------- #
# adversarial: fan-out cannot bypass the internal daily buffer (P.1)
# --------------------------------------------------------------------------- #
def test_P1_five_one_percent_candidates_cannot_all_pass():
    # simulate the runner's cumulative reservation: candidate k sees (k-1)*1000 committed
    outcomes = []
    for k in range(5):
        committed = k * 1000.0                         # A..D already authorized (1% each)
        v = _risk(_candidate(rf=0.01), _acct(committed_risk_at_stop=committed))
        outcomes.append(v.passed)
    # candidates 1-4 fit within the 4% internal buffer; the 5th (cumulative 5%) is rejected
    assert outcomes == [True, True, True, True, False]


def test_PR3J_loss_at_stop_still_proven():
    # a candidate whose volume risks MORE than its budget is still rejected on per-trade
    # grounds (PR-3J unchanged) even with zero committed risk
    cand = _candidate(rf=0.0001)                       # tiny budget (10), but 0.10 lot risks ~100
    v = _risk(cand, _acct())
    assert not v.passed and ReasonCode.RISK_PER_TRADE_EXCEEDED in v.reason_codes
