"""Phase 9A — canonical session model, config, overlaps, DST, capability tests."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from forex_swing_orb.session import model as M
from forex_swing_orb.session.model import (SessionModel, SessionConfigError, OverlapMode,
                                          SessionReason)
from forex_swing_orb.session.capability import LONDON_ORB_CAPABILITY as CAP
from forex_swing_orb.runtime.config import load_config, ConfigError


def utc(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc)


ALL = M.SESSION_IDS
JAN_WED = utc(2026, 1, 7, 10)     # London active, winter


def _model(**kw):
    base = dict(enabled_sessions=ALL, enabled_overlaps=M.OVERLAP_IDS,
                overlap_mode=OverlapMode.ALLOW)
    base.update(kw)
    return SessionModel(**base).validate()


# ---- configuration (1-12) --------------------------------------------------
@pytest.mark.parametrize("sid", ["SYDNEY", "TOKYO", "LONDON", "NEW_YORK"])
def test_enable_each_session_independently(sid):
    m = SessionModel(enabled_sessions=(sid,), overlap_mode=OverlapMode.DISABLE).validate()
    assert m.enabled_sessions == (sid,)


def test_enable_multiple_sessions():
    assert _model(enabled_sessions=("LONDON", "NEW_YORK"),
                  enabled_overlaps=("LONDON_NEW_YORK",)).enabled_sessions == ("LONDON", "NEW_YORK")


def test_disable_all_invalidly_fails_closed():
    with pytest.raises(SessionConfigError):
        SessionModel(enabled_sessions=(), overlap_mode=OverlapMode.DISABLE).validate()


def test_unknown_session_rejected():
    with pytest.raises(SessionConfigError):
        SessionModel(enabled_sessions=("MARS",), overlap_mode=OverlapMode.DISABLE).validate()


def test_unknown_overlap_rejected():
    with pytest.raises(SessionConfigError):
        SessionModel(enabled_sessions=("LONDON",), enabled_overlaps=("NOPE",),
                     overlap_mode=OverlapMode.ALLOW).validate()


def test_overlap_allow_require_disable_valid():
    assert _model(overlap_mode=OverlapMode.ALLOW)
    assert SessionModel(enabled_sessions=(), enabled_overlaps=("TOKYO_LONDON",),
                        overlap_mode=OverlapMode.REQUIRE).validate()
    assert SessionModel(enabled_sessions=("LONDON",),
                        overlap_mode=OverlapMode.DISABLE).validate()


def test_overlap_require_without_overlap_rejected():
    with pytest.raises(SessionConfigError):
        SessionModel(enabled_sessions=("LONDON",), enabled_overlaps=(),
                     overlap_mode=OverlapMode.REQUIRE).validate()


def test_invalid_overlap_member_combo_rejected():
    # ALLOW/DISABLE: an enabled overlap must have both members enabled
    with pytest.raises(SessionConfigError):
        SessionModel(enabled_sessions=("LONDON",), enabled_overlaps=("LONDON_NEW_YORK",),
                     overlap_mode=OverlapMode.ALLOW).validate()


def test_config_json_and_env(tmp_path):
    news = tmp_path / "news.json"; news.write_text('{"as_of":"x","events":[]}', encoding="utf-8")
    env = {
        "SESSION_EDGE_BRIDGE_ROOT": str(tmp_path / "b"), "SESSION_EDGE_RUNTIME_DIR": str(tmp_path / "r"),
        "SESSION_EDGE_SYMBOLS": "EURUSD.FX", "SESSION_EDGE_INITIAL_BALANCE": "100000",
        "SESSION_EDGE_ACCOUNT_CURRENCY": "USD", "SESSION_EDGE_FTMO_RULE_SOURCE": "x",
        "SESSION_EDGE_FTMO_RULE_VERIFIED_AT": "y", "SESSION_EDGE_FTMO_PROFILE_VERIFIED": "true",
        "SESSION_EDGE_NEWS_FILE": str(news),
        "SESSION_EDGE_ENABLED_SESSIONS": "LONDON,NEW_YORK",
        "SESSION_EDGE_ENABLED_OVERLAPS": "LONDON_NEW_YORK",
        "SESSION_EDGE_OVERLAP_MODE": "ALLOW"}
    cfg = load_config(env=env)
    assert cfg.enabled_sessions == ("LONDON", "NEW_YORK")
    assert cfg.enabled_overlaps == ("LONDON_NEW_YORK",)
    assert cfg.session_model().overlap_mode == "ALLOW"
    # env override of overlap_mode
    cfg2 = load_config(env={**env, "SESSION_EDGE_OVERLAP_MODE": "DISABLE"})
    assert cfg2.overlap_mode == "DISABLE"


def test_config_no_silent_all_session_default(tmp_path):
    news = tmp_path / "n.json"; news.write_text('{"as_of":"x","events":[]}', encoding="utf-8")
    env = {
        "SESSION_EDGE_BRIDGE_ROOT": str(tmp_path / "b"), "SESSION_EDGE_RUNTIME_DIR": str(tmp_path / "r"),
        "SESSION_EDGE_SYMBOLS": "EURUSD.FX", "SESSION_EDGE_INITIAL_BALANCE": "100000",
        "SESSION_EDGE_ACCOUNT_CURRENCY": "USD", "SESSION_EDGE_FTMO_RULE_SOURCE": "x",
        "SESSION_EDGE_FTMO_RULE_VERIFIED_AT": "y", "SESSION_EDGE_FTMO_PROFILE_VERIFIED": "true",
        "SESSION_EDGE_NEWS_FILE": str(news), "SESSION_EDGE_OVERLAP_MODE": "ALLOW"}
    with pytest.raises(ConfigError):        # enabled_sessions required (no silent all)
        load_config(env=env)


def test_config_unknown_session_env_fails_closed(tmp_path):
    news = tmp_path / "n.json"; news.write_text('{"as_of":"x","events":[]}', encoding="utf-8")
    env = {
        "SESSION_EDGE_BRIDGE_ROOT": str(tmp_path / "b"), "SESSION_EDGE_RUNTIME_DIR": str(tmp_path / "r"),
        "SESSION_EDGE_SYMBOLS": "EURUSD.FX", "SESSION_EDGE_INITIAL_BALANCE": "100000",
        "SESSION_EDGE_ACCOUNT_CURRENCY": "USD", "SESSION_EDGE_FTMO_RULE_SOURCE": "x",
        "SESSION_EDGE_FTMO_RULE_VERIFIED_AT": "y", "SESSION_EDGE_FTMO_PROFILE_VERIFIED": "true",
        "SESSION_EDGE_NEWS_FILE": str(news), "SESSION_EDGE_ENABLED_SESSIONS": "ATLANTIS",
        "SESSION_EDGE_OVERLAP_MODE": "ALLOW"}
    with pytest.raises(ConfigError):
        load_config(env=env)


# ---- session calculations (13-26) -----------------------------------------
def test_each_session_active():
    m = _model()
    assert "SYDNEY" in M.active_sessions(m, utc(2026, 1, 7, 23))
    assert "TOKYO" in M.active_sessions(m, utc(2026, 1, 7, 3))
    assert "LONDON" in M.active_sessions(m, utc(2026, 1, 7, 10))
    assert "NEW_YORK" in M.active_sessions(m, utc(2026, 1, 7, 18))


def test_overlaps_active():
    m = _model()
    assert "SYDNEY_TOKYO" in M.active_overlaps(m, utc(2026, 1, 7, 2))
    assert "TOKYO_LONDON" in M.active_overlaps(m, utc(2026, 1, 7, 8))
    assert "LONDON_NEW_YORK" in M.active_overlaps(m, utc(2026, 1, 7, 14))


def test_wrap_around_sydney():
    m = _model()
    # Sydney wraps past local midnight; active late UTC evening and early UTC morning
    assert "SYDNEY" in M.active_sessions(m, utc(2026, 1, 7, 22))
    assert "SYDNEY" in M.active_sessions(m, utc(2026, 1, 7, 4))


def test_dst_winter_vs_summer_london_ny_overlap():
    m = SessionModel(enabled_sessions=("LONDON", "NEW_YORK"),
                     enabled_overlaps=("LONDON_NEW_YORK",), overlap_mode=OverlapMode.ALLOW).validate()
    # summer (BST/EDT) shifts the overlap earlier in UTC than winter (GMT/EST)
    assert "LONDON_NEW_YORK" in M.active_overlaps(m, utc(2026, 7, 8, 12, 30))
    assert "LONDON_NEW_YORK" not in M.active_overlaps(m, utc(2026, 1, 7, 12, 30))


def test_next_session_next_overlap_countdown():
    m = _model()
    ns = M.next_session(m, utc(2026, 1, 7, 6, 30))   # before London 08:00 local (winter=08Z)
    assert ns and ns[0] in M.SESSION_IDS
    assert isinstance(M.session_countdown(m, utc(2026, 1, 7, 6, 30)), int)
    no = M.next_overlap(m, utc(2026, 1, 7, 10))       # London-only now; next overlap later
    assert no is None or no[0] in M.OVERLAP_IDS


def test_snapshot_deterministic_id():
    m = _model()
    a = M.session_snapshot(m, JAN_WED, CAP)
    b = M.session_snapshot(m, JAN_WED, CAP)
    assert a["snapshot_id"] == b["snapshot_id"] and len(a["snapshot_id"]) == 16
    assert a["primary_session"] == "LONDON"


# ---- strategy capability truth (35-39) ------------------------------------
def test_london_capability_reported_accurately():
    d = CAP.as_dict()
    assert d["opening_range_session"] == "LONDON"
    assert d["supports_multi_session_scanning"] is False
    assert d["strategy_supported_sessions"] == ["LONDON"]


@pytest.mark.parametrize("sid,hour", [("SYDNEY", 23), ("TOKYO", 3), ("NEW_YORK", 18)])
def test_nonlondon_only_not_falsely_supported(sid, hour):
    m = SessionModel(enabled_sessions=(sid,), overlap_mode=OverlapMode.DISABLE).validate()
    e = M.eligibility(m, utc(2026, 1, 7, hour), CAP)
    assert e["eligible"] is False
    assert e["reason"] == SessionReason.STRATEGY_SESSION_UNSUPPORTED


def test_london_ny_overlap_policy_documented_and_eligible():
    m = SessionModel(enabled_sessions=("LONDON", "NEW_YORK"),
                     enabled_overlaps=("LONDON_NEW_YORK",), overlap_mode=OverlapMode.ALLOW).validate()
    # at 14:00Z both London and NY active -> London session supported -> eligible
    e = M.eligibility(m, utc(2026, 1, 7, 14), CAP)
    assert e["eligible"] is True


def test_report_only_policy_flags_but_allows():
    m = SessionModel(enabled_sessions=("TOKYO",), overlap_mode=OverlapMode.DISABLE,
                     strategy_session_policy="REPORT_ONLY").validate()
    e = M.eligibility(m, utc(2026, 1, 7, 3), CAP)
    assert e["eligible"] is True and e["strategy_supported"] is False


# ---- overlap modes eligibility --------------------------------------------
def test_overlap_require_only_in_overlap():
    m = SessionModel(enabled_sessions=("LONDON", "NEW_YORK"),
                     enabled_overlaps=("LONDON_NEW_YORK",),
                     overlap_mode=OverlapMode.REQUIRE).validate()
    assert M.eligibility(m, utc(2026, 1, 7, 10), CAP)["eligible"] is False   # London only
    assert M.eligibility(m, utc(2026, 1, 7, 14), CAP)["eligible"] is True    # overlap


def test_overlap_disable_ignores_overlap_window():
    m = SessionModel(enabled_sessions=("LONDON",), overlap_mode=OverlapMode.DISABLE).validate()
    # London active at 14:00Z too -> eligible via session (overlap irrelevant)
    assert M.eligibility(m, utc(2026, 1, 7, 14), CAP)["eligible"] is True


def test_stale_context_fails_closed():
    m = _model()
    e = M.eligibility(m, JAN_WED, CAP, max_age_sec=60, context_age_sec=120)
    assert e["eligible"] is False and e["reason"] == SessionReason.SESSION_CONTEXT_STALE
