"""Deterministic tests for the Windows/MT5 DEMO validation harness (Validation
#15A). No Windows, no MetaTrader5, no networking — every test exercises the pure
analysis layer with injected data. The MT5-touching entrypoint is out of scope
here by construction (it is pragma-excluded and requires a live terminal)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from forex_swing_orb.agents.memory import MemoryStore                       # noqa: E402
from forex_swing_orb.bridge import serialize                               # noqa: E402
from forex_swing_orb.live import mt5_client as mc                          # noqa: E402
from forex_swing_orb.manage import outcome as _outcome                     # noqa: E402
from forex_swing_orb.validation import mt5_outcome_probe as H              # noqa: E402

IN, OUT, INOUT, OUT_BY = H.IN, H.OUT, H.INOUT, H.OUT_BY


def _deal(entry, volume, price, ticket=0, position_id=9, symbol="EURUSD",
          reason=0):
    return {"entry": entry, "volume": volume, "price": price, "ticket": ticket,
            "position_id": position_id, "symbol": symbol, "reason": reason}


# --------------------------------------------------------------------------- #
# DEMO guard + signal_id + account mode
# --------------------------------------------------------------------------- #
def test_demo_guard_true_false_unknown():
    demo = type("A", (), {"trade_mode": mc.ACCOUNT_TRADE_MODE_DEMO})()
    real = type("A", (), {"trade_mode": mc.ACCOUNT_TRADE_MODE_REAL})()
    contest = type("A", (), {"trade_mode": mc.ACCOUNT_TRADE_MODE_CONTEST})()
    unknown = type("A", (), {})()
    assert H.is_demo_account(demo) == (True, "trade_mode=DEMO")
    assert H.is_demo_account(real)[0] is False
    assert H.is_demo_account(contest)[0] is False
    assert H.is_demo_account(unknown) == (None, "trade_mode_unavailable")


def test_invalid_signal_id_rejected():
    assert H.validate_signal_id("0123456789abcdef") is True
    assert H.validate_signal_id("NOT-HEX-SIGNALID") is False
    assert H.validate_signal_id("abc") is False
    assert H.validate_signal_id(None) is False


def test_account_mode_classification():
    assert H.classify_account_mode(type("A", (), {"margin_mode": 0})()) == "NETTING"
    assert H.classify_account_mode(type("A", (), {"margin_mode": 2})()) == "HEDGING"
    assert H.classify_account_mode(type("A", (), {"margin_mode": 1})()) == "EXCHANGE"
    assert H.classify_account_mode(type("A", (), {})()) == "UNKNOWN"


# --------------------------------------------------------------------------- #
# Identity classification
# --------------------------------------------------------------------------- #
def test_identity_ticket_eq_ne_unresolved():
    assert H.classify_identity(5001, 5001) == H.ID_EQ
    assert H.classify_identity(5001, 7777) == H.ID_NE
    assert H.classify_identity(5001, None) == H.ID_UNRESOLVED
    assert H.classify_identity(None, None) == H.ID_UNRESOLVED


# --------------------------------------------------------------------------- #
# Close analysis
# --------------------------------------------------------------------------- #
def test_history_unavailable_no_history():
    a = H.analyze_close([])
    assert a["classification"] == H.C_NO_HISTORY
    assert a["weighted_close"] is None and a["deal_count"] == 0


def test_entry_only_classified():
    a = H.analyze_close([_deal(IN, 0.10, 1.10000)])
    assert a["classification"] == H.C_ENTRY_ONLY
    assert a["net_flat"] is False


def test_partial_close_classified():
    a = H.analyze_close([_deal(IN, 0.10, 1.10000), _deal(OUT, 0.04, 1.10400)])
    assert a["classification"] == H.C_OPEN_OR_PARTIAL


def test_full_close_net_flat_and_weighted():
    a = H.analyze_close([_deal(IN, 0.10, 1.10000), _deal(OUT, 0.10, 1.10400)])
    assert a["classification"] == H.C_NET_FLAT
    assert a["net_flat"] is True
    assert a["weighted_close"] == pytest.approx(1.10400)


def test_weighted_close_multi_exit():
    a = H.analyze_close([_deal(IN, 0.10, 1.10000),
                         _deal(OUT, 0.06, 1.10200),
                         _deal(OUT, 0.04, 1.10450)])
    assert a["classification"] == H.C_NET_FLAT
    assert a["weighted_close"] == pytest.approx((0.06 * 1.10200 + 0.04 * 1.10450) / 0.10)
    assert a["deal_count"] == 3


def test_inout_classified_unsupported():
    a = H.analyze_close([_deal(IN, 0.10, 1.10000), _deal(INOUT, 0.10, 1.10400)])
    assert a["classification"] == H.C_UNSUPPORTED_INOUT


def test_out_by_treated_as_exit():
    a = H.analyze_close([_deal(IN, 0.10, 1.10000), _deal(OUT_BY, 0.10, 1.10400)])
    assert a["classification"] == H.C_NET_FLAT


def test_malformed_deal_values_never_net_flat():
    assert H.analyze_close([_deal(IN, 0.10, 1.10000),
                            _deal(OUT, 0.0, 1.10400)])["net_flat"] is False
    assert H.analyze_close([_deal(IN, 0.10, 1.10000),
                            _deal(OUT, 0.10, float("inf"))])["net_flat"] is False
    assert H.analyze_close([_deal(IN, None, 1.10000),
                            _deal(OUT, 0.10, 1.10400)])["net_flat"] is False


# --------------------------------------------------------------------------- #
# Scoping + duplicates
# --------------------------------------------------------------------------- #
def test_scoping_confirmed_mismatch_unresolved():
    scoped = [_deal(IN, 0.1, 1.1, position_id=9), _deal(OUT, 0.1, 1.104, position_id=9)]
    mixed = [_deal(IN, 0.1, 1.1, position_id=9), _deal(OUT, 0.1, 1.104, position_id=42)]
    assert H.check_scoping(scoped, 9) == H.SCOPE_CONFIRMED
    assert H.check_scoping(mixed, 9) == H.SCOPE_MISMATCH
    assert H.check_scoping([], 9) == H.SCOPE_UNRESOLVED
    assert H.check_scoping(scoped, None) == H.SCOPE_UNRESOLVED


def test_duplicate_deal_tickets_reported():
    deals = [_deal(IN, 0.1, 1.1, ticket=1), _deal(OUT, 0.1, 1.104, ticket=2),
             _deal(OUT, 0.1, 1.104, ticket=2)]
    assert H.find_duplicate_deal_tickets(deals) == [2]


# --------------------------------------------------------------------------- #
# Realized-R cross-check (+ parity with production formula)
# --------------------------------------------------------------------------- #
def test_realized_r_long():
    rr = H.realized_r_crosscheck("LONG", 1.10000, 1.09800, 1.10400)
    assert rr["r_multiple"] == pytest.approx(2.0)
    assert rr["won"] is True and rr["status"] == "CLOSED"


def test_realized_r_short():
    rr = H.realized_r_crosscheck("SHORT", 1.10000, 1.10200, 1.10100)
    assert rr["r_multiple"] == pytest.approx(-0.5)
    assert rr["won"] is False


def test_realized_r_undefined_zero_risk():
    rr = H.realized_r_crosscheck("LONG", 1.10000, 1.10000, 1.10400)
    assert rr["r_multiple"] is None and rr["status"] == "R_UNDEFINED"
    assert rr["won"] is None


def test_realized_r_parity_with_production_formula():
    """The harness R must equal OutcomeReconciler's on identical inputs."""
    for direction, entry, stop, close in [
            ("LONG", 1.10000, 1.09800, 1.10400),
            ("SHORT", 1.10000, 1.10200, 1.10100),
            ("LONG", 1.23456, 1.23000, 1.24000)]:
        R = _outcome.spec.initial_risk(direction, entry, stop)
        prod = _outcome.OutcomeReconciler._realized_r(direction, entry, close, R)
        assert H.realized_r_crosscheck(direction, entry, stop, close)["r_multiple"] == prod


# --------------------------------------------------------------------------- #
# Facts from durable PM audit (reuses the accepted tolerant reader)
# --------------------------------------------------------------------------- #
def _write_audit(path, *items):
    with open(path, "w", encoding="utf-8") as fh:
        for it in items:
            fh.write((it if isinstance(it, str)
                      else serialize.canonical_json(it)) + "\n")


def _rec(sid, ticket, direction="LONG", entry=1.10000, stop=1.09800):
    return {"signal_id": sid, "ticket": ticket, "symbol": "EURUSD",
            "direction": direction, "entry_price": entry, "initial_stop": stop}


def test_known_facts_tolerant_and_validated(tmp_path):
    p = tmp_path / "pm_audit.jsonl"
    _write_audit(p, _rec("aaaaaaaaaaaaaaaa", 8001), "{torn line",
                 _rec("bbbbbbbbbbbbbbbb", 8002, "SHORT", 1.1, 1.102))
    a = H.known_facts(p, "aaaaaaaaaaaaaaaa")
    b = H.known_facts(p, "bbbbbbbbbbbbbbbb")
    assert a["ticket"] == 8001 and b["direction"] == "SHORT"
    assert H.known_facts(p, "cccccccccccccccc") is None       # absent


def test_known_facts_rejects_invalid_fields(tmp_path):
    p = tmp_path / "pm_audit.jsonl"
    bad = {"signal_id": "dddddddddddddddd", "ticket": 8003, "symbol": "EURUSD",
           "direction": "SIDEWAYS", "entry_price": "x", "initial_stop": 1.098}
    _write_audit(p, bad)
    assert H.known_facts(p, "dddddddddddddddd") is None


# --------------------------------------------------------------------------- #
# Stored-outcome inspection + comparison
# --------------------------------------------------------------------------- #
def _independent(**over):
    d = {"signal_id": "aaaaaaaaaaaaaaaa", "ticket": 8001, "direction": "LONG",
         "entry": 1.10000, "initial_stop": 1.09800, "weighted_close": 1.10400,
         "r_multiple": 2.0, "deal_count": 2, "closed_volume": 0.10}
    d.update(over)
    return d


def _stored_content(**over):
    c = {"signal_id": "aaaaaaaaaaaaaaaa", "ticket": 8001, "direction": "LONG",
         "entry": 1.10000, "initial_stop": 1.09800, "weighted_close": 1.10400,
         "r_multiple": 2.0, "deal_count": 2, "closed_volume": 0.10,
         "status": "CLOSED", "won": True, "taken": True}
    c.update(over)
    return {"content": c, "source": "outcome_reconciler", "id": "x", "timestamp": "t",
            "correlation_id": c["signal_id"]}


def test_outcome_not_present():
    assert H.sanitized_outcome(None) == "OUTCOME_NOT_PRESENT"
    cmp = H.compare_outcome(_independent(), "OUTCOME_NOT_PRESENT")
    assert cmp["overall"] == "OUTCOME_NOT_YET_RECORDED"


def test_stored_outcome_match():
    stored = H.sanitized_outcome(_stored_content())
    cmp = H.compare_outcome(_independent(), stored)
    assert cmp["overall"] == "OUTCOME_MATCH"
    assert cmp["fields"]["r_multiple"] == "MATCH"


def test_stored_outcome_mismatch():
    stored = H.sanitized_outcome(_stored_content(r_multiple=1.0, weighted_close=1.10200))
    cmp = H.compare_outcome(_independent(), stored)
    assert cmp["overall"] == "OUTCOME_MISMATCH"
    assert cmp["fields"]["r_multiple"] == "MISMATCH"


def test_sanitized_outcome_reads_real_record(tmp_path):
    """End-to-end: a record written like production is read back sanitized."""
    mem = MemoryStore(str(tmp_path / "memory"))
    content = _stored_content()["content"]
    mem.write_raw(_outcome.OUTCOME_KIND, "EURUSD", content, source="outcome_reconciler",
                  timestamp="2026-01-07T12:00:00Z", correlation_id=content["signal_id"])
    row = H._stored_outcome(mem, "aaaaaaaaaaaaaaaa")
    s = H.sanitized_outcome(row)
    assert s["signal_id"] == "aaaaaaaaaaaaaaaa" and s["r_multiple"] == 2.0
    assert H._stored_outcome(mem, "ffffffffffffffff") is None


# --------------------------------------------------------------------------- #
# Sensitive-field & authority guards
# --------------------------------------------------------------------------- #
def test_extract_deal_fields_excludes_sensitive():
    raw = type("D", (), {"ticket": 1, "order": 2, "position_id": 9, "entry": IN,
                         "volume": 0.1, "price": 1.1, "symbol": "EURUSD",
                         "reason": 0, "time": 0, "profit": 123.45,
                         "commission": -1.0, "swap": -0.5})()
    fields = H.extract_deal_fields(raw)
    for forbidden in ("profit", "commission", "swap"):
        assert forbidden not in fields
    assert fields["price"] == 1.1 and fields["entry"] == IN


def test_no_sensitive_fields_in_serialized_report():
    """A representative full report (incl. deal + account-ish data) must serialize
    without any sensitive key."""
    account = type("A", (), {"trade_mode": mc.ACCOUNT_TRADE_MODE_DEMO,
                             "margin_mode": 0, "server": "Demo-Server",
                             "login": 123456, "balance": 100000.0,
                             "equity": 100000.0, "password": "secret"})()
    report = {
        "environment": {"account_trade_mode_is_demo": H.is_demo_account(account)[0],
                        "account_mode": H.classify_account_mode(account),
                        "server": H._get(account, "server")},
        "observed_deals": [H.extract_deal_fields(
            type("D", (), {"ticket": 1, "entry": IN, "volume": 0.1, "price": 1.1,
                           "profit": 9.9, "commission": -1.0, "swap": -0.2})())],
        "close_analysis": H.analyze_close([_deal(IN, 0.1, 1.1), _deal(OUT, 0.1, 1.104)]),
        "realized_r_crosscheck": H.realized_r_crosscheck("LONG", 1.1, 1.098, 1.104),
        "stored_outcome": H.sanitized_outcome(_stored_content()),
    }
    assert H.find_sensitive(report) == []


def test_find_sensitive_detects_leak():
    assert H.find_sensitive({"a": {"password": "x"}}) == ["$.a.password"]
    assert H.find_sensitive({"deals": [{"profit": 1.0}]}) == ["$.deals[0].profit"]


def test_static_no_trading_or_write_authority():
    """The harness source performs no trading and no MemoryStore write."""
    src = (Path(__file__).resolve().parents[1] / "mt5_outcome_probe.py").read_text()
    for token in ("order_send", "order_check", "positions_close", "position_close",
                  "PositionClose", "PositionModify", "modify_stop",
                  "write_instruction", "build_instruction", "CTrade", ".Buy(",
                  ".Sell(", "write_raw", "write_derived", "position_close",
                  ".run("):
        assert token not in src, f"forbidden token present: {token}"


# --------------------------------------------------------------------------- #
# Overall status decision (pure)
# --------------------------------------------------------------------------- #
def test_decide_status_transitions():
    base = dict(mt5_available=True, demo_confirmed=True, identity_class=H.ID_EQ,
                position_present=False, close_classification=H.C_NO_HISTORY,
                outcome_present=False, comparison_overall="OUTCOME_NOT_YET_RECORDED")
    assert H.decide_status(**{**base, "mt5_available": False}) == H.S_MT5_UNAVAILABLE
    assert H.decide_status(**{**base, "demo_confirmed": False}) == H.S_DEMO_NOT_CONFIRMED
    assert H.decide_status(**{**base, "position_present": True}) == H.S_OPEN
    assert H.decide_status(**{**base, "position_present": True,
                             "close_classification": H.C_OPEN_OR_PARTIAL}) == H.S_PARTIAL
    assert H.decide_status(**{**base, "close_classification": H.C_NET_FLAT}) == H.S_PENDING
    assert H.decide_status(**{**base, "close_classification": H.C_NET_FLAT,
                             "outcome_present": True,
                             "comparison_overall": "OUTCOME_MATCH"}) == H.S_MATCH
    assert H.decide_status(**{**base, "close_classification": H.C_NET_FLAT,
                             "outcome_present": True,
                             "comparison_overall": "OUTCOME_MISMATCH"}) == H.S_MISMATCH
    assert H.decide_status(**base) == H.S_NO_EPISODE


def test_package_enum_report_shape():
    fake = type("M", (), {"DEAL_ENTRY_IN": 0, "DEAL_ENTRY_OUT": 1,
                          "DEAL_ENTRY_INOUT": 2, "DEAL_ENTRY_OUT_BY": 3,
                          "DEAL_REASON_TP": 4, "DEAL_REASON_SL": 3})()
    rep = H.package_enum_report(fake)
    assert rep["source_assumed"]["DEAL_ENTRY_IN"] == 0
    assert rep["package_constant"]["DEAL_ENTRY_OUT"] == 1
    assert rep["package_constant"]["DEAL_REASON_CLIENT"] == "NOT_OBSERVED"
    none_rep = H.package_enum_report(None)
    assert none_rep["package_constant"]["DEAL_ENTRY_IN"] == "NOT_OBSERVED"


def test_repo_state_shape():
    st = H.repo_state(cwd=str(REPO_ROOT))
    assert set(st) == {"commit", "dirty"}
