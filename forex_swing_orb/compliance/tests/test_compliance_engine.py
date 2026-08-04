"""Comprehensive regression tests for the deterministic FTMO Compliance Engine.

Covers: PASS path; every rejection path; every FTMO/session/news/broker-health/
kill-switch rule; every deterministic reason code; audit + decision determinism;
no-bridge-write-on-reject; restart (audit persistence); boundary conditions;
mapping; and the read-only dashboard.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from forex_swing_orb.bridge import serialize
from forex_swing_orb.compliance import (ComplianceAuditLog, ComplianceConfig,
                                        ComplianceDashboard, ComplianceEngine,
                                        Decision, FtmoConfig, NewsLockoutConfig,
                                        ReasonCode, SessionConfig, Stage,
                                        mapping, validate_reason)
from forex_swing_orb.compliance import gates
from conftest import NOW, SATURDAY, SUNDAY, FRIDAY


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _engine(config=None, audit_log=None, writer=None):
    return ComplianceEngine(config=config, audit_log=audit_log, bridge_writer=writer)


def _writer_recorder():
    calls = []
    return calls, (lambda cand, dec: calls.append((cand, dec)))


def _evaluate(engine, candidate, market, account, broker, news, now=NOW,
              kill_switch=False, dry_run=False):
    return engine.evaluate(candidate, market_state=market, account_state=account,
                           broker_health=broker, news_bundle=news, now=now,
                           kill_switch=kill_switch, dry_run=dry_run)


# --------------------------------------------------------------------------- #
# PASS path
# --------------------------------------------------------------------------- #
def test_pass_path(make_candidate, make_market, make_account, make_broker, make_news):
    calls, writer = _writer_recorder()
    eng = _engine(writer=writer)
    d = _evaluate(eng, make_candidate(), make_market(), make_account(),
                  make_broker(), make_news())
    assert d.decision == Decision.PASS
    assert d.primary_reason_code == ReasonCode.COMPLIANCE_PASS
    assert d.is_pass and len(calls) == 1
    # every stage ran and passed
    assert tuple(v.stage for v in d.gate_verdicts) == Stage.ORDER
    assert all(v.passed for v in d.gate_verdicts)


def test_macro_is_advisory_not_a_blocker(make_candidate, make_market, make_account,
                                         make_broker, make_news):
    # a macro reference on the candidate is IGNORED by compliance (advisory only)
    cand = make_candidate(macro_ref={"bias": "HAWKISH", "risk_sentiment": "RISK_OFF"})
    d = _evaluate(_engine(), cand, make_market(), make_account(),
                  make_broker(), make_news())
    assert d.is_pass


# --------------------------------------------------------------------------- #
# Kill switch (stage 1)
# --------------------------------------------------------------------------- #
def test_kill_switch(make_candidate, make_market, make_account, make_broker, make_news):
    calls, writer = _writer_recorder()
    eng = _engine(writer=writer)
    d = _evaluate(eng, make_candidate(), make_market(), make_account(),
                  make_broker(), make_news(), kill_switch=True)
    assert d.decision == Decision.REJECT
    assert d.primary_reason_code == ReasonCode.KILL_SWITCH
    assert calls == []                              # NO bridge write
    # short-circuit: only the kill-switch stage ran
    assert tuple(v.stage for v in d.gate_verdicts) == (Stage.KILL_SWITCH,)


# --------------------------------------------------------------------------- #
# Market compliance (stage 2)
# --------------------------------------------------------------------------- #
def test_market_candidate_missing_field(make_candidate, make_market, make_account,
                                        make_broker, make_news):
    cand = make_candidate()
    del cand["stop_loss"]
    d = _evaluate(_engine(), cand, make_market(), make_account(), make_broker(), make_news())
    assert d.primary_reason_code == ReasonCode.CANDIDATE_MALFORMED


def test_market_symbol_not_forex(make_candidate, make_market, make_account,
                                 make_broker, make_news):
    for bad in ("XAUUSD.FX", "BTCUSD.FX", "SPX500.FX", "USDXXX.FX", "EURUSD"):
        d = _evaluate(_engine(), make_candidate(symbol=bad), make_market(),
                      make_account(), make_broker(), make_news())
        assert d.primary_reason_code == ReasonCode.SYMBOL_NOT_FOREX, bad


def test_market_bad_direction(make_candidate, make_market, make_account,
                              make_broker, make_news):
    d = _evaluate(_engine(), make_candidate(direction="FLAT"), make_market(),
                  make_account(), make_broker(), make_news())
    assert d.primary_reason_code == ReasonCode.CANDIDATE_MALFORMED


@pytest.mark.parametrize("direction,entry,sl,tp", [
    ("LONG", 1.10, 1.11, 1.12),     # sl above entry
    ("LONG", 1.10, 1.09, 1.09),     # tp not above
    ("SHORT", 1.10, 1.09, 1.08),    # sl below entry
])
def test_market_bad_geometry(direction, entry, sl, tp, make_candidate, make_market,
                             make_account, make_broker, make_news):
    cand = make_candidate(direction=direction, entry=entry, stop_loss=sl, take_profit=tp)
    d = _evaluate(_engine(), cand, make_market(), make_account(), make_broker(), make_news())
    assert d.primary_reason_code == ReasonCode.CANDIDATE_MALFORMED


def test_market_mtf_not_aligned(make_candidate, make_market, make_account,
                                make_broker, make_news):
    mtf = {"daily_bias": "UP", "h4_structure": "DOWN", "h1_setup": "X",
           "m15_timing": "Y", "aligned": False}
    d = _evaluate(_engine(), make_candidate(mtf=mtf), make_market(),
                  make_account(), make_broker(), make_news())
    assert d.primary_reason_code == ReasonCode.MTF_CONFLICT


def test_market_mtf_incomplete(make_candidate, make_market, make_account,
                               make_broker, make_news):
    d = _evaluate(_engine(), make_candidate(mtf={"aligned": True}), make_market(),
                  make_account(), make_broker(), make_news())
    assert d.primary_reason_code == ReasonCode.MTF_CONFLICT


def test_market_closed(make_candidate, make_market, make_account, make_broker, make_news):
    d = _evaluate(_engine(), make_candidate(), make_market(market_open=False),
                  make_account(), make_broker(), make_news())
    assert d.primary_reason_code == ReasonCode.MARKET_CLOSED


def test_market_symbol_not_tradable(make_candidate, make_market, make_account,
                                    make_broker, make_news):
    d = _evaluate(_engine(), make_candidate(), make_market(symbol_tradable=False),
                  make_account(), make_broker(), make_news())
    assert d.primary_reason_code == ReasonCode.SYMBOL_NOT_FOREX


# --------------------------------------------------------------------------- #
# FTMO compliance (stage 3)
# --------------------------------------------------------------------------- #
def test_ftmo_weekend_block(make_candidate, make_market, make_account, make_broker, make_news):
    d = _evaluate(_engine(), make_candidate(), make_market(), make_account(),
                  make_broker(), make_news(as_of=serialize.iso_utc(SATURDAY)), now=SATURDAY)
    assert d.primary_reason_code == ReasonCode.WEEKEND_BLOCK


def test_ftmo_one_per_symbol(make_candidate, make_market, make_account, make_broker, make_news):
    acct = make_account(open_symbols=("EURUSD.FX",), open_position_count=1)
    d = _evaluate(_engine(), make_candidate(), make_market(), acct, make_broker(), make_news())
    assert d.primary_reason_code == ReasonCode.ONE_PER_SYMBOL


def test_ftmo_max_positions(make_candidate, make_market, make_account, make_broker, make_news):
    cfg = ComplianceConfig(ftmo=FtmoConfig(max_open_positions=3))
    acct = make_account(open_position_count=3, open_symbols=("GBPUSD.FX",))
    d = _evaluate(_engine(cfg), make_candidate(), make_market(), acct, make_broker(), make_news())
    assert d.primary_reason_code == ReasonCode.MAX_POSITIONS


def test_ftmo_internal_buffer_trips_before_ftmo(make_candidate, make_market,
                                                make_account, make_broker, make_news):
    # anchor 100k, daily 5% => FTMO 5000, internal 4000. Put projected between.
    acct = make_account(current_daily_loss=3600.0, open_risk_at_stop=0.0)
    # candidate risk = 100000*0.005 = 500 => projected 4100 in (4000, 5000)
    d = _evaluate(_engine(), make_candidate(), make_market(), acct, make_broker(), make_news())
    assert d.primary_reason_code == ReasonCode.DAILY_LOSS_LIMIT
    assert ReasonCode.INTERNAL_BUFFER_TRIP in d.reason_codes   # internal before FTMO


def test_ftmo_daily_hard_limit(make_candidate, make_market, make_account, make_broker, make_news):
    acct = make_account(current_daily_loss=4800.0)   # projected 5300 >= FTMO 5000
    d = _evaluate(_engine(), make_candidate(), make_market(), acct, make_broker(), make_news())
    assert d.primary_reason_code == ReasonCode.DAILY_LOSS_LIMIT
    assert ReasonCode.INTERNAL_BUFFER_TRIP not in d.reason_codes


def test_ftmo_max_account_loss(make_candidate, make_market, make_account, make_broker, make_news):
    # max loss 10% => FTMO 10000, internal 8000. equity down 7800 + risk 500 = 8300 >= 8000
    acct = make_account(equity=92200.0, current_daily_loss=0.0)
    d = _evaluate(_engine(), make_candidate(), make_market(), acct, make_broker(), make_news())
    assert d.primary_reason_code == ReasonCode.MAX_ACCOUNT_LOSS


def test_internal_limits_strictly_below_ftmo():
    from forex_swing_orb.compliance.contract import ftmo_limits
    lim = ftmo_limits({"daily_anchor_equity": 100000.0, "initial_balance": 100000.0},
                      FtmoConfig())
    assert lim["internal_daily_limit"] < lim["ftmo_daily_limit"]
    assert lim["internal_max_loss"] < lim["ftmo_max_loss"]


# --------------------------------------------------------------------------- #
# Session compliance (stage 4)
# --------------------------------------------------------------------------- #
def test_session_outside_session(make_candidate, make_market, make_account, make_broker, make_news):
    cfg = ComplianceConfig(session=SessionConfig(allowed_sessions=("LONDON",)))
    # 02:00 UTC Wednesday: London (07-16) not active
    two_am = NOW.replace(hour=2)
    d = _evaluate(_engine(cfg), make_candidate(), make_market(), make_account(),
                  make_broker(), make_news(as_of=serialize.iso_utc(two_am)), now=two_am)
    assert d.primary_reason_code == ReasonCode.OUTSIDE_SESSION


def test_session_friday_close(make_candidate, make_market, make_account, make_broker, make_news):
    # disable weekend gate so FTMO passes; Friday 21:00 UTC, cutoff 20:00 (1200)
    cfg = ComplianceConfig(
        ftmo=FtmoConfig(weekend_flat_required=False),
        session=SessionConfig(friday_close_min=1200))
    d = _evaluate(_engine(cfg), make_candidate(), make_market(), make_account(),
                  make_broker(), make_news(as_of=serialize.iso_utc(FRIDAY)), now=FRIDAY)
    assert d.primary_reason_code == ReasonCode.SESSION_BLOCK


def test_session_sunday_open(make_candidate, make_market, make_account, make_broker, make_news):
    cfg = ComplianceConfig(
        ftmo=FtmoConfig(weekend_flat_required=False),
        session=SessionConfig(sunday_open_min=1320))    # no entries before 22:00 UTC Sun
    d = _evaluate(_engine(cfg), make_candidate(), make_market(), make_account(),
                  make_broker(), make_news(as_of=serialize.iso_utc(SUNDAY)), now=SUNDAY)
    assert d.primary_reason_code == ReasonCode.SESSION_BLOCK


# --------------------------------------------------------------------------- #
# News compliance (stage 5)
# --------------------------------------------------------------------------- #
def test_news_high_impact_lockout(make_candidate, make_market, make_account,
                                  make_broker, make_news, make_event):
    news = make_news(events=[make_event(currency="USD", impact="HIGH", offset_min=0)])
    d = _evaluate(_engine(), make_candidate(), make_market(), make_account(), make_broker(), news)
    assert d.primary_reason_code == ReasonCode.NEWS_LOCKOUT
    assert ReasonCode.PAIR_BLOCKED in d.reason_codes
    news_v = {v.stage: v for v in d.gate_verdicts}[Stage.NEWS]
    assert news_v.evidence["lockout_expires_at"] is not None


def test_news_auto_resume_after_window(make_candidate, make_market, make_account,
                                       make_broker, make_news, make_event):
    # event 30 min ago, post window 15 => resumed
    news = make_news(events=[make_event(currency="USD", impact="HIGH", offset_min=-30)])
    d = _evaluate(_engine(), make_candidate(), make_market(), make_account(), make_broker(), news)
    assert d.is_pass


def test_news_unrelated_currency_not_blocked(make_candidate, make_market, make_account,
                                             make_broker, make_news, make_event):
    news = make_news(events=[make_event(currency="JPY", impact="HIGH", offset_min=0)])
    d = _evaluate(_engine(), make_candidate(symbol="EURUSD.FX"), make_market(),
                  make_account(), make_broker(), news)
    assert d.is_pass


def test_news_data_unavailable(make_candidate, make_market, make_account, make_broker):
    d = _evaluate(_engine(), make_candidate(), make_market(), make_account(),
                  make_broker(), None)
    assert d.primary_reason_code == ReasonCode.NEWS_DATA_UNAVAILABLE


def test_news_stale(make_candidate, make_market, make_account, make_broker, make_news, make_event):
    old = serialize.iso_utc(NOW - timedelta(hours=5))
    news = make_news(events=[make_event(currency="USD", offset_min=0)], as_of=old)
    d = _evaluate(_engine(), make_candidate(), make_market(), make_account(), make_broker(), news)
    assert d.primary_reason_code == ReasonCode.NEWS_DATA_STALE


def test_news_unverified(make_candidate, make_market, make_account, make_broker,
                         make_news, make_event):
    ev = make_event(currency="USD", impact="HIGH", offset_min=0, verification_state="RUMORED")
    news = make_news(events=[ev], verified=False)
    d = _evaluate(_engine(), make_candidate(), make_market(), make_account(), make_broker(), news)
    assert d.primary_reason_code == ReasonCode.NEWS_SOURCE_UNVERIFIED


def test_news_conflicting_records(make_candidate, make_market, make_account,
                                  make_broker, make_news, make_event):
    e1 = make_event(currency="USD", impact="HIGH", offset_min=0, event_id="DUP")
    e2 = make_event(currency="USD", impact="LOW", offset_min=0, event_id="DUP")
    news = make_news(events=[e1, e2])
    d = _evaluate(_engine(), make_candidate(), make_market(), make_account(), make_broker(), news)
    assert d.primary_reason_code == ReasonCode.NEWS_CONFLICTING_RECORDS


@pytest.mark.parametrize("offset,blocked", [(15, True), (16, False), (-15, True), (-16, False)])
def test_news_window_boundaries(offset, blocked, make_candidate, make_market,
                                make_account, make_broker, make_news, make_event):
    news = make_news(events=[make_event(currency="USD", impact="HIGH", offset_min=offset)])
    d = _evaluate(_engine(), make_candidate(), make_market(), make_account(), make_broker(), news)
    assert (d.primary_reason_code == ReasonCode.NEWS_LOCKOUT) is blocked


# --------------------------------------------------------------------------- #
# Broker health (stage 6)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("over,primary", [
    ({"terminal_connected": False}, ReasonCode.TERMINAL_DISCONNECTED),
    ({"bridge_healthy": False}, ReasonCode.BRIDGE_UNHEALTHY),
    ({"spread_points": 25.0}, ReasonCode.SPREAD_TOO_HIGH),
    ({"recent_slippage_points": 12.0}, ReasonCode.SLIPPAGE_TOO_HIGH),
    ({"missing_ack_count": 2}, ReasonCode.ACK_MISSING),
    ({"quote_age_sec": 120.0}, ReasonCode.MARKET_DATA_STALE),
])
def test_broker_health_rejections(over, primary, make_candidate, make_market,
                                  make_account, make_broker, make_news):
    d = _evaluate(_engine(), make_candidate(), make_market(), make_account(),
                  make_broker(**over), make_news())
    assert d.primary_reason_code == primary
    assert ReasonCode.BROKER_UNHEALTHY in d.reason_codes


def test_broker_health_missing_field_fail_closed(make_candidate, make_market,
                                                 make_account, make_broker, make_news):
    b = make_broker()
    b["spread_points"] = None
    d = _evaluate(_engine(), make_candidate(), make_market(), make_account(), b, make_news())
    assert d.decision == Decision.REJECT
    assert ReasonCode.UNKNOWN_STATE in d.reason_codes


# --------------------------------------------------------------------------- #
# Risk (stage 7) — gate-level (FTMO shadows projected breach in the pipeline)
# --------------------------------------------------------------------------- #
def test_risk_per_trade_exceeded(make_candidate, make_market, make_account,
                                 make_broker, make_news):
    d = _evaluate(_engine(), make_candidate(risk_fraction=0.02), make_market(),
                  make_account(), make_broker(), make_news())
    assert d.primary_reason_code == ReasonCode.RISK_PER_TRADE_EXCEEDED


def test_risk_gate_projected_breach_defense_in_depth(make_candidate, make_account):
    # direct gate test: projected >= internal daily limit
    acct = make_account(current_daily_loss=3800.0)   # +500 risk => 4300 >= 4000
    v = gates.gate_risk(make_candidate(), acct, FtmoConfig(), NOW)
    assert not v.passed and v.reason_codes[0] == ReasonCode.RISK_PROJECTED_BREACH


# --------------------------------------------------------------------------- #
# Determinism + audit
# --------------------------------------------------------------------------- #
def test_decision_and_audit_determinism(make_candidate, make_market, make_account,
                                        make_broker, make_news):
    eng = _engine()
    a = _evaluate(eng, make_candidate(), make_market(), make_account(),
                  make_broker(), make_news(), dry_run=True)
    b = _evaluate(eng, make_candidate(), make_market(), make_account(),
                  make_broker(), make_news(), dry_run=True)
    assert a.decision_id == b.decision_id
    assert a.audit_record == b.audit_record


def test_decision_id_changes_with_inputs(make_candidate, make_market, make_account,
                                         make_broker, make_news):
    eng = _engine()
    a = _evaluate(eng, make_candidate(), make_market(), make_account(),
                  make_broker(), make_news(), dry_run=True)
    b = _evaluate(eng, make_candidate(signal_id="different0000000"), make_market(),
                  make_account(), make_broker(), make_news(), dry_run=True)
    assert a.decision_id != b.decision_id


def test_audit_record_fields(make_candidate, make_market, make_account, make_broker, make_news):
    d = _evaluate(_engine(), make_candidate(), make_market(), make_account(),
                  make_broker(), make_news(), dry_run=True)
    r = d.audit_record
    for k in ("decision_id", "schema_version", "engine_version", "config_digest",
              "timestamp", "signal_id", "symbol", "direction", "decision",
              "primary_reason_code", "reason_codes", "gate_verdicts"):
        assert k in r
    # canonical + reproducible
    serialize.canonical_json(r)


def test_registry_is_internally_consistent():
    # every public string reason code is registered (no code can escape REQUIRED)
    from forex_swing_orb.compliance.contract import ReasonCode as RC
    for name in dir(RC):
        if name.isupper() and isinstance(getattr(RC, name), str):
            assert validate_reason(getattr(RC, name)), name


# --------------------------------------------------------------------------- #
# No bridge write on rejection
# --------------------------------------------------------------------------- #
def test_no_bridge_write_on_reject_but_audit_written(tmp_path, make_candidate, make_market,
                                                     make_account, make_broker, make_news):
    calls, writer = _writer_recorder()
    log = ComplianceAuditLog(str(tmp_path / "compliance.jsonl"))
    eng = _engine(audit_log=log, writer=writer)
    d = _evaluate(eng, make_candidate(), make_market(), make_account(),
                  make_broker(), make_news(), kill_switch=True)
    assert d.decision == Decision.REJECT
    assert calls == []                          # NO bridge write
    assert len(log.read_all()) == 1             # audit still written


def test_bridge_write_on_pass(tmp_path, make_candidate, make_market, make_account,
                              make_broker, make_news):
    calls, writer = _writer_recorder()
    log = ComplianceAuditLog(str(tmp_path / "compliance.jsonl"))
    eng = _engine(audit_log=log, writer=writer)
    d = _evaluate(eng, make_candidate(), make_market(), make_account(),
                  make_broker(), make_news())
    assert d.is_pass and len(calls) == 1 and len(log.read_all()) == 1


def test_bridge_writer_receives_only_pass(tmp_path, make_candidate, make_market,
                                          make_account, make_broker, make_news):
    seen = []
    eng = _engine(writer=lambda c, d: seen.append(d.decision))
    # one reject, one pass
    _evaluate(eng, make_candidate(), make_market(), make_account(),
              make_broker(), make_news(), kill_switch=True)
    _evaluate(eng, make_candidate(), make_market(), make_account(),
              make_broker(), make_news())
    assert seen == [Decision.PASS]


# --------------------------------------------------------------------------- #
# Restart behavior (audit persistence + reproducible decision_id)
# --------------------------------------------------------------------------- #
def test_audit_persists_across_restart(tmp_path, make_candidate, make_market,
                                       make_account, make_broker, make_news):
    path = str(tmp_path / "compliance.jsonl")
    eng1 = _engine(audit_log=ComplianceAuditLog(path))
    d1 = _evaluate(eng1, make_candidate(), make_market(), make_account(),
                   make_broker(), make_news())
    # "restart": brand-new engine + log instance over the same file
    log2 = ComplianceAuditLog(path)
    persisted = log2.read_all()
    assert len(persisted) == 1
    assert persisted[0]["decision_id"] == d1.decision_id
    # re-evaluating identical inputs reproduces the same decision_id
    eng2 = _engine()
    d2 = _evaluate(eng2, make_candidate(), make_market(), make_account(),
                   make_broker(), make_news(), dry_run=True)
    assert d2.decision_id == d1.decision_id


# --------------------------------------------------------------------------- #
# Boundary conditions
# --------------------------------------------------------------------------- #
def test_daily_loss_exact_internal_boundary(make_candidate, make_market, make_account,
                                            make_broker, make_news):
    # internal daily limit = 4000; make projected exactly 4000 => reject (>=)
    acct = make_account(current_daily_loss=3500.0)   # +500 => 4000
    d = _evaluate(_engine(), make_candidate(), make_market(), acct, make_broker(), make_news())
    assert d.primary_reason_code == ReasonCode.DAILY_LOSS_LIMIT
    # just below => pass
    acct2 = make_account(current_daily_loss=3499.0)  # 3999 < 4000
    d2 = _evaluate(_engine(), make_candidate(), make_market(), acct2, make_broker(), make_news())
    assert d2.is_pass


def test_risk_exact_cap_boundary(make_candidate, make_market, make_account,
                                 make_broker, make_news):
    # cap 0.01; == cap passes (check is strictly '>'); above rejects
    d_eq = _evaluate(_engine(), make_candidate(risk_fraction=0.01), make_market(),
                     make_account(), make_broker(), make_news())
    assert d_eq.is_pass
    d_gt = _evaluate(_engine(), make_candidate(risk_fraction=0.0100001), make_market(),
                     make_account(), make_broker(), make_news())
    assert d_gt.primary_reason_code == ReasonCode.RISK_PER_TRADE_EXCEEDED


def test_max_positions_boundary(make_candidate, make_market, make_account, make_broker, make_news):
    cfg = ComplianceConfig(ftmo=FtmoConfig(max_open_positions=5))
    ok = make_account(open_position_count=4, open_symbols=("GBPUSD.FX",))
    assert _evaluate(_engine(cfg), make_candidate(), make_market(), ok, make_broker(), make_news()).is_pass
    full = make_account(open_position_count=5, open_symbols=("GBPUSD.FX",))
    d = _evaluate(_engine(cfg), make_candidate(), make_market(), full, make_broker(), make_news())
    assert d.primary_reason_code == ReasonCode.MAX_POSITIONS


# --------------------------------------------------------------------------- #
# Currency <-> pair mapping
# --------------------------------------------------------------------------- #
def test_mapping_universe_is_28_majors():
    assert len(mapping.MAJOR_PAIRS) == 28
    assert len(set(mapping.MAJOR_PAIRS)) == 28


def test_mapping_gbp_affects_exactly_seven():
    got = mapping.affects("GBP")
    assert got == {"GBPUSD", "GBPJPY", "EURGBP", "GBPAUD", "GBPCAD", "GBPNZD", "GBPCHF"}
    assert "EURUSD" not in got and "USDJPY" not in got


def test_mapping_is_forex_symbol():
    assert mapping.is_forex_symbol("EURUSD.FX")
    assert mapping.is_forex_symbol("GBPJPY.FX")
    assert not mapping.is_forex_symbol("XAUUSD.FX")
    assert not mapping.is_forex_symbol("BTCUSD.FX")
    assert not mapping.is_forex_symbol("EURUSD")


# --------------------------------------------------------------------------- #
# Read-only dashboard
# --------------------------------------------------------------------------- #
def test_dashboard_readonly_no_side_effects(tmp_path, make_candidate, make_market,
                                            make_account, make_broker, make_news):
    calls, writer = _writer_recorder()
    log = ComplianceAuditLog(str(tmp_path / "compliance.jsonl"))
    eng = _engine(audit_log=log, writer=writer)
    dash = ComplianceDashboard(eng)
    s = dash.status(make_candidate(), market_state=make_market(),
                    account_state=make_account(), broker_health=make_broker(),
                    news_bundle=make_news(), now=NOW)
    assert s["compliance_status"] == Decision.PASS
    assert calls == []                       # dashboard never writes to the bridge
    assert log.read_all() == []              # dashboard never writes audit


def test_dashboard_budgets_and_fields(make_candidate, make_market, make_account,
                                      make_broker, make_news):
    dash = ComplianceDashboard(_engine())
    s = dash.status(make_candidate(), market_state=make_market(),
                    account_state=make_account(current_daily_loss=1000.0),
                    broker_health=make_broker(), news_bundle=make_news(), now=NOW)
    # internal daily 4000 - (1000 + 0) = 3000
    assert s["remaining_daily_loss_budget"] == pytest.approx(3000.0)
    # internal max 8000 - (100000-100000) = 8000
    assert s["remaining_max_loss_budget"] == pytest.approx(8000.0)
    assert s["active_session"] == "LONDON"
    for k in ("ftmo_status", "broker_health", "kill_switch_active",
              "active_news_lockout", "lockout_expiration", "active_reason_codes"):
        assert k in s


def test_dashboard_reports_news_lockout(make_candidate, make_market, make_account,
                                        make_broker, make_news, make_event):
    dash = ComplianceDashboard(_engine())
    news = make_news(events=[make_event(currency="USD", impact="HIGH", offset_min=0)])
    s = dash.status(make_candidate(), market_state=make_market(),
                    account_state=make_account(), broker_health=make_broker(),
                    news_bundle=news, now=NOW)
    assert s["active_news_lockout"] is True
    assert s["lockout_expiration"] is not None
    assert s["compliance_status"] == Decision.REJECT


def test_dashboard_kill_switch(make_candidate, make_market, make_account,
                               make_broker, make_news):
    dash = ComplianceDashboard(_engine())
    s = dash.status(make_candidate(), market_state=make_market(),
                    account_state=make_account(), broker_health=make_broker(),
                    news_bundle=make_news(), now=NOW, kill_switch=True)
    assert s["kill_switch_active"] is True
    assert s["compliance_status"] == Decision.REJECT
