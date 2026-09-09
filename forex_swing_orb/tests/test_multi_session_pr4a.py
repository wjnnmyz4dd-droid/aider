"""PR-4A — engine-level multi-session proofs:

* the frozen engine's session window is placed correctly per session/DST;
* signal_id is session-sensitive (no cross-session collision);
* the LONDON profile reproduces the default (frozen) engine EXACTLY (golden);
* session_id is threaded into the instruction;
* a session's opening range cannot authorize another session (no leakage).

The engine is session-agnostic: its ONLY session-dependent input is the OR window
(session_window_utc + the session config). So identical price geometry under a
different session_id must yield an identical entry/stop/target but a different
signal_id — the controlled experiment below isolates exactly that variable.
No MT5; deterministic synthetic frames.
"""

from __future__ import annotations

from datetime import date

import pytest


# news must be satisfiable or the engine's news gate fails closed (no signal).
_NEWS_OK = {"news_events": [], "news_asof": "2024-01-25T11:15:00Z"}


def _eng(se, overrides):
    cfg = dict(_NEWS_OK)
    if overrides:
        cfg.update(overrides)
    return se.SignalEngine(se.merged_config(cfg))


def _run(engine, df, symbol="EURUSD.FX"):
    engine.generate({symbol: df})
    return engine.instructions.get(symbol) or []


# --------------------------------------------------------------------------- #
# session_window_utc: correct per-session UTC window incl. DST (§21, §22)
# --------------------------------------------------------------------------- #
def _win(se, sid, d):
    from forex_swing_orb.session.profiles import profile_for
    cfg = se.merged_config(profile_for(sid).engine_overrides())
    s, e, ok, _ = se.session_window_utc(d, cfg)
    return s, e, ok


def test_window_london_winter_and_summer(se):
    s, e, ok = _win(se, "LONDON", date(2026, 1, 7))          # GMT
    assert ok and s.hour == 8 and e.hour == 9
    s, e, ok = _win(se, "LONDON", date(2026, 7, 7))          # BST (UTC+1)
    assert ok and s.hour == 7 and e.hour == 8


def test_window_tokyo_non_dst(se):
    for month in (1, 7):                                     # Asia/Tokyo has no DST
        s, e, ok = _win(se, "TOKYO", date(2026, month, 7))
        assert ok and s.hour == 0 and e.hour == 1           # 09:00 JST == 00:00 UTC


def test_window_new_york_dst(se):
    s, _e, ok = _win(se, "NEW_YORK", date(2026, 1, 7))      # EST (UTC-5)
    assert ok and s.hour == 13                               # 08:00 EST == 13:00 UTC
    s, _e, ok = _win(se, "NEW_YORK", date(2026, 7, 7))      # EDT (UTC-4)
    assert ok and s.hour == 12


def test_window_sessions_are_disjoint_same_date(se):
    # per-session OR isolation at the window level: each session's UTC window differs
    wins = {sid: _win(se, sid, date(2026, 1, 7))[0].hour
            for sid in ("SYDNEY", "TOKYO", "LONDON", "NEW_YORK")}
    assert len(set(wins.values())) == 4                      # all four start at distinct UTC hours


# --------------------------------------------------------------------------- #
# signal_id is session-sensitive (§6, §10, §26)
# --------------------------------------------------------------------------- #
def test_compute_signal_id_session_sensitive(se):
    args = ("EURUSD.FX", "LONG", "2026-01-07T09:15:00Z", 1.10000, 1.09800, 1.10400)
    a = se.compute_signal_id("swing_orb.v1.4.0", "LONDON", *args)
    b = se.compute_signal_id("swing_orb.v1.4.0", "NEW_YORK", *args)
    assert a != b                                            # only session_id differs
    assert a == se.compute_signal_id("swing_orb.v1.4.0", "LONDON", *args)   # deterministic


def test_compute_signal_id_requires_session(se):
    with pytest.raises(ValueError):
        se.compute_signal_id("swing_orb.v1.4.0", "", "EURUSD.FX", "LONG",
                             "2026-01-07T09:15:00Z", 1.1, 1.09, 1.11)


# --------------------------------------------------------------------------- #
# LONDON GOLDEN: the LONDON profile == the frozen default engine, exactly (§8, §27)
# --------------------------------------------------------------------------- #
def _strip_ids(instr):
    return {k: v for k, v in instr.items() if k not in ("signal_id",)}


def test_london_profile_matches_default_engine_bullish(se, bullish_setup):
    from forex_swing_orb.session.profiles import profile_for
    df, _ = bullish_setup
    default_i = _run(_eng(se, None), df)
    london_i = _run(_eng(se, profile_for("LONDON").engine_overrides()), df)
    assert len(default_i) == len(london_i) >= 1
    for a, b in zip(default_i, london_i):
        assert a == b                                        # identical incl. signal_id + session_id


def test_london_profile_matches_default_engine_bearish(se, bearish_setup):
    from forex_swing_orb.session.profiles import profile_for
    df, _ = bearish_setup
    default_i = _run(_eng(se, None), df)
    london_i = _run(_eng(se, profile_for("LONDON").engine_overrides()), df)
    assert default_i == london_i and len(default_i) >= 1


def test_default_engine_stamps_london_session(se, bullish_setup):
    df, _ = bullish_setup
    instrs = _run(_eng(se, None), df)
    assert instrs and all(i["session_id"] == "LONDON" for i in instrs)
    assert all(i["schema_version"] == 2 for i in instrs)


# --------------------------------------------------------------------------- #
# same geometry + different session -> identical entry/stop/target, DIFFERENT id
# (controlled experiment: hold the clock fixed, vary ONLY session_id) (§6, §26)
# --------------------------------------------------------------------------- #
def test_same_geometry_different_session_distinct_signal_id(se, bullish_setup):
    df, _ = bullish_setup
    lon = _run(_eng(se, {"session_id": "LONDON"}), df)
    # NEW_YORK identity but London's clock -> isolates session_id as the only change
    nyc = _run(_eng(se, {"session_id": "NEW_YORK"}), df)
    assert len(lon) == len(nyc) >= 1
    for a, b in zip(lon, nyc):
        assert a["session_id"] == "LONDON" and b["session_id"] == "NEW_YORK"
        assert (a["entry_price"], a["stop_loss"], a["take_profit"]) == \
               (b["entry_price"], b["stop_loss"], b["take_profit"])   # identical geometry
        assert a["generated_timestamp"] == b["generated_timestamp"]
        assert a["signal_id"] != b["signal_id"]                        # but distinct identity


# --------------------------------------------------------------------------- #
# per-session OR isolation: a real non-London profile does NOT fire on London data
# (London's 08:00-09:00 OR cannot authorize NY/Tokyo/Sydney state) (§8, §11)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("sid", ["NEW_YORK", "TOKYO", "SYDNEY"])
def test_london_data_does_not_authorize_other_session(se, bullish_setup, sid):
    from forex_swing_orb.session.profiles import profile_for
    df, _ = bullish_setup
    # sanity: London fires on this data
    assert len(_run(_eng(se, profile_for("LONDON").engine_overrides()), df)) >= 1
    # a real other-session profile (its OR window is at a different UTC time) does not
    assert _run(_eng(se, profile_for(sid).engine_overrides()), df) == []


def test_session_configured_engine_deterministic(se, bullish_setup):
    from forex_swing_orb.session.profiles import profile_for
    df, _ = bullish_setup
    ov = profile_for("LONDON").engine_overrides()
    assert _run(_eng(se, ov), df) == _run(_eng(se, ov), df)
