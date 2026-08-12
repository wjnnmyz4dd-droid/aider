"""Comprehensive deterministic tests for the Session Edge Swing-ORB SignalEngine.

Covers the Phase 1 matrix plus the acceptance-review corrections (F1-F7, spec
v1.4.0). All fixtures are deterministic; no clock, no RNG, no network, no MT5.

News is fail-closed by default (spec §12.2), so positive-signal tests supply a
present+fresh empty news calendar via `run_ok` / NEWS_OK.
"""

from __future__ import annotations

import ast
import os
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import synth

ENGINE_PATH = Path(__file__).resolve().parents[1] / "run_dir" / "code" / "signal_engine.py"
DAY = "2024-01-25"
CONFIRM_TS = pd.Timestamp("2024-01-25 11:15", tz="UTC")   # slot 45, decision bar
APPLIED_TS = pd.Timestamp("2024-01-25 11:30", tz="UTC")   # slot 46, position on
# present + fresh, empty high-impact calendar -> news VERIFIED (eligible)
NEWS_OK = {"news_events": [], "news_asof": "2024-01-25T11:15:00Z"}


def run(se, df, config=None):
    eng = se.SignalEngine(config)
    out = eng.generate({"EURUSD.FX": df})
    return eng, out["EURUSD.FX"]


def run_ok(se, df, extra=None):
    cfg = dict(NEWS_OK)
    if extra:
        cfg.update(extra)
    return run(se, df, cfg)


def audit_by_ts(eng, symbol="EURUSD.FX"):
    return {a["evaluation_timestamp"]: a for a in eng.audit[symbol]}


# --- determinism ------------------------------------------------------------

def test_deterministic_output_identical_inputs(se, bullish_setup):
    df, _ = bullish_setup
    _, s1 = run_ok(se, df)
    _, s2 = run_ok(se, df)
    assert s1.equals(s2)


def test_deterministic_signal_id(se, bullish_setup):
    df, _ = bullish_setup
    e1, _ = run_ok(se, df)
    e2, _ = run_ok(se, df)
    ids1 = [i["signal_id"] for i in e1.instructions["EURUSD.FX"]]
    ids2 = [i["signal_id"] for i in e2.instructions["EURUSD.FX"]]
    assert ids1 == ids2 and len(ids1) >= 1
    inst = e1.instructions["EURUSD.FX"][0]
    assert inst["session_id"] == "LONDON"                 # PR-4A: default profile
    recomputed = se.compute_signal_id(
        inst["strategy_version"], inst["session_id"], inst["symbol"], inst["direction"],
        inst["generated_timestamp"], inst["entry_price"], inst["stop_loss"], inst["take_profit"],
    )
    assert recomputed == inst["signal_id"]


# --- no look-ahead (signal + minor pivots) ----------------------------------

def test_no_future_bar_dependency(se, bullish_setup):
    df, _ = bullish_setup
    _, full = run_ok(se, df)
    cut = df.index.get_loc(CONFIRM_TS)
    prefix = df.iloc[: cut + 1]
    _, part = run_ok(se, prefix)
    horizon = df.index[cut] - pd.Timedelta(days=1)
    assert full[full.index <= horizon].equals(part[part.index <= horizon])


def test_pivot_confirmation_latency_no_lookahead(se):
    idx = pd.date_range("2024-01-01", periods=9, freq="15min", tz="UTC")
    highs = [1, 2, 3, 5, 3, 2, 1, 1, 1]
    lows = [h - 1 for h in highs]
    df = pd.DataFrame({"open": highs, "high": highs, "low": lows, "close": highs}, index=idx)
    piv = se.confirmed_pivots(df, 2)
    hi = [p for p in piv if p["kind"] == "H"]
    assert hi and hi[0]["pivot_time"] == idx[3]
    assert hi[0]["confirm_time"] == idx[5]  # i + k = 3 + 2


# --- F1: higher-timeframe causal confirmation timing ------------------------

def _raw_htf(u, mins):
    return u.resample(f"{mins}min", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()


def _assert_confirm_is_close(se, synthmod, mins):
    u = se.to_utc_index(synthmod.uptrend_frame(days=60))
    span = pd.Timedelta(minutes=mins)
    raw = _raw_htf(u, mins)
    hb = se.htf_bars(u, mins)
    piv = se.confirmed_pivots(hb, 2)
    assert piv
    checked = 0
    for p in piv:
        pivot_open = p["pivot_time"] - span      # hb is close-labelled -> recover open
        if pivot_open not in raw.index:
            continue
        pos = raw.index.get_loc(pivot_open)
        if pos + 2 >= len(raw):
            continue
        confirming_open = raw.index[pos + 2]     # pivot_k = 2
        # confirm_time must be the confirming bar's CLOSE, strictly after its open
        assert p["confirm_time"] == confirming_open + span
        assert p["confirm_time"] > confirming_open
        checked += 1
    assert checked >= 3


def test_h4_confirm_time_is_confirming_bar_close(se, synthmod):
    _assert_confirm_is_close(se, synthmod, 240)


def test_d1_confirm_time_is_confirming_bar_close(se, synthmod):
    _assert_confirm_is_close(se, synthmod, 1440)


def _truncation_invariance(se, synthmod, mins):
    u = se.to_utc_index(synthmod.uptrend_frame(days=60))
    cfg = se.merged_config(None)
    span = pd.Timedelta(minutes=mins)
    # a clean HTF close boundary well inside the data
    close_b = pd.Timestamp("2024-01-20 12:00" if mins == 240 else "2024-01-20 00:00", tz="UTC")
    mid = close_b - pd.Timedelta(minutes=15)   # confirming HTF bar still incomplete
    a = u[u.index <= mid]
    b = u[u.index <= close_b]
    ta = se.map_trend_to_exec(a.index, se.htf_trend_events(a, mins, cfg))
    tb = se.map_trend_to_exec(b.index, se.htf_trend_events(b, mins, cfg))
    ha = se.map_label_to_exec(a.index, se.htf_health_events(a, mins, cfg), "WEAK")
    hb = se.map_label_to_exec(b.index, se.htf_health_events(b, mins, cfg), "WEAK")
    # adding data up to the close must not change any state at/earlier than mid
    assert ta.equals(tb.loc[:mid])
    assert ha.equals(hb.loc[:mid])


def test_h4_truncation_invariance(se, synthmod):
    _truncation_invariance(se, synthmod, 240)


def test_d1_truncation_invariance(se, synthmod):
    _truncation_invariance(se, synthmod, 1440)


def test_trend_health_uses_corrected_htf_timeline(se, synthmod):
    u = se.to_utc_index(synthmod.uptrend_frame(days=60))
    cfg = se.merged_config(None)
    for mins in (240, 1440):
        te = [t[0] for t in se.htf_trend_events(u, mins, cfg)]
        he = [h[0] for h in se.htf_health_events(u, mins, cfg)]
        assert te == he and len(te) >= 3   # health shares the corrected close-based timeline


# --- data semantics ---------------------------------------------------------

def test_insufficient_history(se):
    idx = pd.date_range("2024-01-01", periods=50, freq="15min", tz="UTC")
    df = pd.DataFrame({"open": 1.1, "high": 1.11, "low": 1.09, "close": 1.1}, index=idx)
    eng, sig = run(se, df)
    assert (sig == 0).all()
    assert eng.audit["EURUSD.FX"][0]["reason_code"] == se.ReasonCode.DATA_INSUFFICIENT


def test_unclosed_last_bar_not_acted_on(se, bullish_setup):
    df, _ = bullish_setup
    cut = df.index.get_loc(CONFIRM_TS)
    prefix = df.iloc[: cut + 1]     # ends exactly on the confirming bar
    eng, sig = run_ok(se, prefix)
    assert len(eng.instructions["EURUSD.FX"]) == 1
    assert sig.iloc[-1] == 0.0      # not applied on the last (potentially forming) bar


def test_non_monotonic_and_duplicate_and_nan(se):
    idx = pd.date_range("2024-01-01", periods=300, freq="15min", tz="UTC")
    base = pd.DataFrame({"open": 1.1, "high": 1.11, "low": 1.09, "close": 1.1}, index=idx)
    cfg = se.merged_config(None)
    dup = base.copy(); dup.index = base.index[:-1].append(base.index[-2:-1])
    assert se.validate_frame(dup, cfg)[1] == se.ReasonCode.TEMPORAL_GAP
    nm = base.copy(); nm.index = base.index[::-1]
    assert se.validate_frame(nm, cfg)[1] == se.ReasonCode.TEMPORAL_GAP
    nan = base.copy(); nan.iloc[10, nan.columns.get_loc("close")] = np.nan
    assert se.validate_frame(nan, cfg)[1] == se.ReasonCode.DATA_INSUFFICIENT


def test_temporal_gap_during_setup(se, bullish_setup):
    df, ref = bullish_setup
    drop_ts = synth.slot_ts(DAY, 41)
    df2 = df.drop(index=drop_ts)
    eng, _ = run_ok(se, df2)
    codes = {a["reason_code"] for a in eng.audit["EURUSD.FX"]}
    assert se.ReasonCode.TEMPORAL_GAP in codes
    assert len(eng.instructions["EURUSD.FX"]) == 0


# --- session / DST ----------------------------------------------------------

def test_london_window_winter_gmt(se):
    cfg = se.merged_config(None)
    s, e, ok, _ = se.london_window_utc(date(2024, 1, 25), cfg)
    assert ok and s.strftime("%H:%M") == "08:00" and e.strftime("%H:%M") == "09:00"


def test_london_window_summer_bst(se):
    cfg = se.merged_config(None)
    s, e, ok, _ = se.london_window_utc(date(2024, 7, 25), cfg)
    assert ok and s.strftime("%H:%M") == "07:00" and e.strftime("%H:%M") == "08:00"


def test_dst_ambiguity_fails_closed(se):
    cfg = se.merged_config({"or_start_local_hour": 1, "or_window_minutes": 60})
    s, e, ok, reason = se.london_window_utc(date(2024, 3, 31), cfg)
    assert not ok and reason == se.ReasonCode.DST_AMBIGUOUS


# --- range validity ---------------------------------------------------------

def test_valid_opening_range_produces_setup(se, bullish_setup):
    df, _ = bullish_setup
    eng, _ = run_ok(se, df)
    assert len(eng.instructions["EURUSD.FX"]) == 1


def test_invalid_range_width(se, bullish_setup):
    df, ref = bullish_setup
    df2 = synth.set_day_bars(df, DAY, {34: {"high": ref["orh"] + 0.05, "low": ref["orl"] - 0.05}})
    eng, _ = run_ok(se, df2)
    a = audit_by_ts(eng)[synth.slot_ts(DAY, 40).strftime("%Y-%m-%dT%H:%M:%SZ")]
    assert a["range_state"] == se.ReasonCode.RANGE_INVALID
    assert len(eng.instructions["EURUSD.FX"]) == 0


def test_incomplete_range(se, bullish_setup):
    df, _ = bullish_setup
    drops = [synth.slot_ts(DAY, s) for s in (32, 33, 34, 35)]
    df2 = df.drop(index=drops)
    eng, _ = run_ok(se, df2)
    a = audit_by_ts(eng)[synth.slot_ts(DAY, 40).strftime("%Y-%m-%dT%H:%M:%SZ")]
    assert a["range_state"] == se.ReasonCode.RANGE_INCOMPLETE
    assert len(eng.instructions["EURUSD.FX"]) == 0


# --- trend ------------------------------------------------------------------

def _piv(kind_prices):
    return [{"kind": k, "price": p, "pivot_time": i, "confirm_time": i} for i, (k, p) in enumerate(kind_prices)]


def test_trend_bullish(se):
    cfg = se.merged_config(None)
    piv = _piv([("L", 1.0), ("H", 1.02), ("L", 1.01), ("H", 1.03), ("L", 1.02), ("H", 1.04)])
    assert se.trend_from_pivots(piv, cfg, 0.0001) == "BULLISH"


def test_trend_bearish(se):
    cfg = se.merged_config(None)
    piv = _piv([("H", 1.04), ("L", 1.02), ("H", 1.03), ("L", 1.01), ("H", 1.02), ("L", 1.00)])
    assert se.trend_from_pivots(piv, cfg, 0.0001) == "BEARISH"


def test_trend_neutral_mixed_and_insufficient(se):
    cfg = se.merged_config(None)
    mixed = _piv([("H", 1.04), ("L", 1.02), ("H", 1.05), ("L", 1.01), ("H", 1.03), ("L", 1.02)])
    assert se.trend_from_pivots(mixed, cfg, 0.0001) == "NEUTRAL"
    assert se.trend_from_pivots(_piv([("H", 1.0), ("L", 0.9)]), cfg, 0.0001) == "NEUTRAL"


def test_trend_conflict_h4_d1(se):
    assert se.combined_trend("BULLISH", "BEARISH") == "NEUTRAL"
    assert se.combined_trend("BULLISH", "NEUTRAL") == "NEUTRAL"
    assert se.combined_trend("BULLISH", "BULLISH") == "BULLISH"
    assert se.combined_trend("BEARISH", "BEARISH") == "BEARISH"


# --- Trend Health Gate ------------------------------------------------------

def _zigzag_pivots(n_each, up_leg, down_leg, start=1.0):
    piv, price, direction, t = [], start, 1, 0
    piv.append({"kind": "L", "price": price, "pivot_time": t, "confirm_time": t})
    for _ in range(2 * n_each - 1):
        t += 1
        price = price + up_leg if direction > 0 else price - down_leg
        piv.append({"kind": "H" if direction > 0 else "L", "price": price,
                    "pivot_time": t, "confirm_time": t})
        direction *= -1
    return piv


def test_trend_health_pass(se):
    cfg = se.merged_config(None)
    assert se.trend_health(_zigzag_pivots(4, 0.020, 0.013), 1, cfg, 0.001) is True


def test_trend_health_weak_insufficient_swings(se):
    cfg = se.merged_config(None)
    assert se.trend_health(_zigzag_pivots(2, 0.020, 0.013), 1, cfg, 0.001) is False


def test_trend_health_weak_marginal_progress(se):
    cfg = se.merged_config(None)
    assert se.trend_health(_zigzag_pivots(4, 0.01002, 0.01000), 1, cfg, 0.001) is False


def test_trend_health_weak_shrinking_leg(se):
    cfg = se.merged_config(None)
    piv = _zigzag_pivots(4, 0.020, 0.013)
    piv[-1]["price"] = piv[-2]["price"] + 0.001
    assert se.trend_health(piv, 1, cfg, 0.001) is False


def test_trend_health_gate_blocks_weak_setup(se, bullish_setup):
    df, _ = bullish_setup
    eng, _ = run_ok(se, df, {"health_min_leg_atr": 100.0})
    codes = {a["reason_code"] for a in eng.audit["EURUSD.FX"]}
    assert se.ReasonCode.TREND_HEALTH_WEAK in codes
    assert len(eng.instructions["EURUSD.FX"]) == 0


def test_trend_health_gate_allows_healthy_setup(se, bullish_setup):
    df, _ = bullish_setup
    eng, _ = run_ok(se, df)
    assert len(eng.instructions["EURUSD.FX"]) == 1
    assert "OK" in {a["trend_health_state"] for a in eng.audit["EURUSD.FX"]}


# --- breakout ---------------------------------------------------------------

def test_wick_only_breakout_rejected(se, bullish_setup):
    df, ref = bullish_setup
    df2 = synth.set_day_bars(df, DAY, {
        40: {"open": ref["orh"] - 0.0002, "high": ref["orh"] + 0.0009,
             "low": ref["orh"] - 0.0004, "close": ref["orh"] - 0.0001}})
    eng, _ = run_ok(se, df2)
    a = audit_by_ts(eng)[synth.slot_ts(DAY, 40).strftime("%Y-%m-%dT%H:%M:%SZ")]
    assert a["reason_code"] == se.ReasonCode.WICK_ONLY_BREAKOUT
    assert len(eng.instructions["EURUSD.FX"]) == 0


def test_completed_bullish_breakout(se, bullish_setup):
    df, _ = bullish_setup
    eng, _ = run_ok(se, df)
    assert eng.instructions["EURUSD.FX"][0]["direction"] == "LONG"


def test_completed_bearish_breakout(se, bearish_setup):
    df, _ = bearish_setup
    eng, _ = run_ok(se, df)
    assert eng.instructions["EURUSD.FX"][0]["direction"] == "SHORT"


def test_breakout_buffer_not_met(se, bullish_setup):
    df, _ = bullish_setup
    eng, _ = run_ok(se, df, {"breakout_min_pips": 100.0})
    codes = {a["reason_code"] for a in eng.audit["EURUSD.FX"]}
    assert se.ReasonCode.BREAKOUT_BUFFER_NOT_MET in codes
    assert len(eng.instructions["EURUSD.FX"]) == 0


# --- retest -----------------------------------------------------------------

def test_valid_retest(se, bullish_setup):
    df, _ = bullish_setup
    eng, _ = run_ok(se, df)
    a = audit_by_ts(eng)[synth.slot_ts(DAY, 42).strftime("%Y-%m-%dT%H:%M:%SZ")]
    assert a["retest_state"] == "HELD"


def test_retest_close_back_inside_invalidation(se, bullish_setup):
    df, ref = bullish_setup
    df2 = synth.set_day_bars(df, DAY, {
        41: {"open": ref["orh"], "high": ref["orh"] + 0.0001,
             "low": ref["orl"] - 0.0002, "close": ref["orl"] - 0.0005}})
    eng, _ = run_ok(se, df2)
    assert se.ReasonCode.RETEST_FAILED in [a["reason_code"] for a in eng.audit["EURUSD.FX"]]
    assert len(eng.instructions["EURUSD.FX"]) == 0


def test_excessive_retest_penetration(se, bullish_setup):
    df, ref = bullish_setup
    df2 = synth.set_day_bars(df, DAY, {
        42: {"open": ref["orh"] + 0.0006, "high": ref["orh"] + 0.0007,
             "low": ref["orl"] - 0.0030, "close": ref["orh"] + 0.0003}})
    eng, _ = run_ok(se, df2)
    assert se.ReasonCode.RETEST_FAILED in [a["reason_code"] for a in eng.audit["EURUSD.FX"]]
    assert len(eng.instructions["EURUSD.FX"]) == 0


def test_retest_timeout(se, bullish_setup):
    df, ref = bullish_setup
    ups = {}
    for s in range(41, 41 + 20):
        lvl = ref["orh"] + 0.0020 + 0.0002 * (s - 41)
        ups[s] = {"open": lvl, "high": lvl + 0.0002, "low": lvl - 0.0001, "close": lvl}
    df2 = synth.set_day_bars(df, DAY, ups)
    eng, _ = run_ok(se, df2)
    assert se.ReasonCode.RETEST_EXPIRED in [a["reason_code"] for a in eng.audit["EURUSD.FX"]]
    assert len(eng.instructions["EURUSD.FX"]) == 0


def test_no_resume_after_failed_retest(se, bullish_setup):
    df, ref = bullish_setup
    df2 = synth.set_day_bars(df, DAY, {
        41: {"open": ref["orh"], "high": ref["orh"] + 0.0001,
             "low": ref["orl"] - 0.0006, "close": ref["orl"] - 0.0006}})
    eng, _ = run_ok(se, df2)
    assert len(eng.instructions["EURUSD.FX"]) == 0


# --- price action -----------------------------------------------------------

def test_price_action_confirmation_pass(se, bullish_setup):
    df, _ = bullish_setup
    eng, _ = run_ok(se, df)
    a = audit_by_ts(eng)[CONFIRM_TS.strftime("%Y-%m-%dT%H:%M:%SZ")]
    assert a["price_action_state"] == "CONFIRMED" and a["reason_code"] == se.ReasonCode.SIGNAL_GENERATED


def test_price_action_confirmation_fail(se, bullish_setup):
    df, ref = bullish_setup
    flats = {}
    for s in range(45, 45 + 15):
        lvl = ref["orh"] + 0.0004
        flats[s] = {"open": lvl, "high": ref["minor_swing_high"] - 0.0001, "low": ref["orh"] + 0.0002, "close": lvl}
    df2 = synth.set_day_bars(df, DAY, flats)
    eng, _ = run_ok(se, df2)
    assert se.ReasonCode.PRICE_ACTION_NOT_CONFIRMED in [a["reason_code"] for a in eng.audit["EURUSD.FX"]]
    assert len(eng.instructions["EURUSD.FX"]) == 0


# --- news (fail-closed default) ---------------------------------------------

def test_default_missing_news_fails_closed(se, bullish_setup):
    df, _ = bullish_setup
    eng, _ = run(se, df)   # DEFAULT config: no news dataset
    codes = {a["reason_code"] for a in eng.audit["EURUSD.FX"]}
    assert se.ReasonCode.NEWS_DATA_UNAVAILABLE in codes
    assert len(eng.instructions["EURUSD.FX"]) == 0


def test_stale_news_fails_closed(se, bullish_setup):
    df, _ = bullish_setup
    eng, _ = run(se, df, {"news_events": [], "news_asof": "2024-01-01T00:00:00Z"})
    codes = {a["reason_code"] for a in eng.audit["EURUSD.FX"]}
    assert se.ReasonCode.NEWS_DATA_STALE in codes
    assert len(eng.instructions["EURUSD.FX"]) == 0


def test_high_impact_news_lockout(se, bullish_setup):
    df, _ = bullish_setup
    cfg = {"news_asof": "2024-01-25T11:15:00Z",
           "news_events": [{"timestamp": "2024-01-25T11:20:00Z", "impact": "high", "currencies": ["USD"]}]}
    eng, _ = run(se, df, cfg)
    codes = {a["reason_code"] for a in eng.audit["EURUSD.FX"]}
    assert se.ReasonCode.NEWS_LOCKOUT in codes
    assert len(eng.instructions["EURUSD.FX"]) == 0


def test_malformed_news_fails_closed_no_exception(se, bullish_setup):
    df, _ = bullish_setup
    # record missing 'timestamp' — must fail closed, never raise
    cfg = {"news_asof": "2024-01-25T11:15:00Z",
           "news_events": [{"impact": "high", "currencies": ["USD"]}]}
    eng, _ = run(se, df, cfg)   # no exception
    codes = {a["reason_code"] for a in eng.audit["EURUSD.FX"]}
    assert se.ReasonCode.NEWS_DATA_UNAVAILABLE in codes
    assert len(eng.instructions["EURUSD.FX"]) == 0


def test_news_does_not_generate_direction(se, synthmod):
    df = synthmod.uptrend_frame(days=10)   # too little history -> neutral, no setup
    cfg = {"news_asof": "2024-01-05T10:00:00Z",
           "news_events": [{"timestamp": "2024-01-05T10:00:00Z", "impact": "high", "currencies": ["EUR"]}]}
    eng, _ = run(se, df, cfg)
    assert len(eng.instructions["EURUSD.FX"]) == 0


def test_news_research_bypass_is_explicit_and_audited(se, bullish_setup):
    df, _ = bullish_setup
    eng, _ = run(se, df, {"news_research_bypass": True})   # explicit, no news dataset
    assert len(eng.instructions["EURUSD.FX"]) == 1
    assert "RESEARCH_BYPASS" in {a["news_state"] for a in eng.audit["EURUSD.FX"]}


# --- risk -------------------------------------------------------------------

def test_valid_structural_stop(se, bullish_setup):
    df, _ = bullish_setup
    eng, _ = run_ok(se, df)
    inst = eng.instructions["EURUSD.FX"][0]
    assert inst["stop_loss"] < inst["entry_price"]


def test_invalid_structural_stop_max_distance(se, bullish_setup):
    df, _ = bullish_setup
    eng, _ = run_ok(se, df, {"max_stop_pips": 0.5})
    codes = {a["reason_code"] for a in eng.audit["EURUSD.FX"]}
    assert se.ReasonCode.STOP_INVALID in codes
    assert len(eng.instructions["EURUSD.FX"]) == 0


def test_fixed_2r_target(se, bullish_setup):
    df, _ = bullish_setup
    eng, _ = run_ok(se, df)
    inst = eng.instructions["EURUSD.FX"][0]
    stop_dist = inst["entry_price"] - inst["stop_loss"]
    assert inst["evidence_summary"]["rr_planned"] == 2.0
    assert abs(inst["take_profit"] - (inst["entry_price"] + 2.0 * stop_dist)) < 2e-5


# --- position mgmt / symmetry / expiry / dedup ------------------------------

def test_one_position_per_symbol(se, bullish_setup):
    df, _ = bullish_setup
    _, sig = run_ok(se, df)
    assert set(np.unique(sig.to_numpy())).issubset({-1.0, 0.0, 1.0})
    inpos = (sig != 0).to_numpy().astype(int)
    assert int(np.abs(np.diff(inpos)).sum()) <= 2   # at most one enter + one exit


def test_long_short_symmetry(se, bullish_setup, bearish_setup):
    il = run_ok(se, bullish_setup[0])[0].instructions["EURUSD.FX"][0]
    ish = run_ok(se, bearish_setup[0])[0].instructions["EURUSD.FX"][0]
    assert il["direction"] == "LONG" and ish["direction"] == "SHORT"
    assert il["stop_loss"] < il["entry_price"] < il["take_profit"]
    assert ish["stop_loss"] > ish["entry_price"] > ish["take_profit"]
    assert il["evidence_summary"]["rr_planned"] == ish["evidence_summary"]["rr_planned"] == 2.0


def test_expiration_strictly_after_execution_bar(se, bullish_setup):
    df, _ = bullish_setup
    eng, sig = run_ok(se, df)
    inst = eng.instructions["EURUSD.FX"][0]
    first_exec = sig[sig != 0].index[0]
    exp = pd.Timestamp(inst["expiration_timestamp"])
    gen = pd.Timestamp(inst["generated_timestamp"])
    assert exp > first_exec                                   # F4: strictly after
    assert (exp - gen) == pd.Timedelta(minutes=30)           # (entry_valid_bars+1)*tf


def test_expiration_comparison_operator(se, bullish_setup):
    df, _ = bullish_setup
    eng, sig = run_ok(se, df)
    inst = eng.instructions["EURUSD.FX"][0]
    first_exec = sig[sig != 0].index[0]
    exp = pd.Timestamp(inst["expiration_timestamp"])
    # future executor uses: expired iff evaluation_time >= expiration_timestamp
    assert not (first_exec >= exp)    # valid at the first effective execution bar
    assert (exp >= exp)               # expired exactly at the expiration instant


def test_duplicate_signal_prevention(se, bullish_setup):
    df, _ = bullish_setup
    eng, _ = run_ok(se, df)
    ids = [i["signal_id"] for i in eng.instructions["EURUSD.FX"]]
    assert len(ids) == len(set(ids)) >= 1


# --- exits (F5/F6) ----------------------------------------------------------

def test_same_bar_stop_and_target_resolves_stop_first(se, bullish_setup):
    df, _ = bullish_setup
    inst = run_ok(se, df)[0].instructions["EURUSD.FX"][0]
    stop, tp = inst["stop_loss"], inst["take_profit"]
    df3 = synth.set_day_bars(df, DAY, {
        47: {"open": inst["entry_price"], "high": tp + 0.0005, "low": stop - 0.0005, "close": inst["entry_price"]}})
    eng, _ = run_ok(se, df3)
    a = audit_by_ts(eng)["2024-01-25T11:45:00Z"]
    assert a["reason_code"] == se.ReasonCode.EXIT_STOP_LOSS
    assert a["numeric_evidence"]["same_bar_stop_and_target"] is True


def test_exit_take_profit_code(se, bullish_setup):
    df, _ = bullish_setup
    eng, _ = run_ok(se, df)   # injected continuation runs to target
    exits = [a["reason_code"] for a in eng.audit["EURUSD.FX"] if a["decision"] == "EXIT"]
    assert se.ReasonCode.EXIT_TAKE_PROFIT in exits


def test_exit_stop_loss_code(se, bullish_setup):
    df, _ = bullish_setup
    inst = run_ok(se, df)[0].instructions["EURUSD.FX"][0]
    stop, tp = inst["stop_loss"], inst["take_profit"]
    df3 = synth.set_day_bars(df, DAY, {
        47: {"open": inst["entry_price"], "high": inst["entry_price"] + 0.0002,
             "low": stop - 0.0003, "close": stop - 0.0002}})
    eng, _ = run_ok(se, df3)
    exits = [a["reason_code"] for a in eng.audit["EURUSD.FX"] if a["decision"] == "EXIT"]
    assert se.ReasonCode.EXIT_STOP_LOSS in exits


def test_exit_time_code(se, synthmod):
    # Friday setup held flat past the Friday cut-off -> EXIT_TIME
    df = synthmod.uptrend_frame(days=60)
    fri = "2024-01-26"   # Friday
    df2, ref = synthmod.inject_bullish_orb(df, fri)
    # flatten post-entry bars so neither stop nor target is hit before the cut-off
    lvl = ref["minor_swing_high"] + 0.0004
    flat = {s: {"open": lvl, "high": lvl + 0.0001, "low": lvl - 0.0001, "close": lvl}
            for s in range(46, 80)}
    df2 = synthmod.set_day_bars(df2, fri, flat)
    cfg = {"news_events": [], "news_asof": f"{fri}T11:15:00Z", "friday_no_new_entry_local_hour": 13}
    eng, _ = run(se, df2, cfg)
    exits = [a["reason_code"] for a in eng.audit["EURUSD.FX"] if a["decision"] == "EXIT"]
    assert se.ReasonCode.EXIT_TIME in exits


# --- audit ------------------------------------------------------------------

def test_per_stage_reason_code_auditability(se, bullish_setup):
    df, _ = bullish_setup
    eng, _ = run_ok(se, df)
    records = eng.audit["EURUSD.FX"]
    assert all(r["reason_code"] for r in records)
    codes = {r["reason_code"] for r in records}
    assert se.ReasonCode.SIGNAL_GENERATED in codes
    assert codes & {se.ReasonCode.SESSION_INELIGIBLE, se.ReasonCode.TREND_NEUTRAL, se.ReasonCode.RETEST_PENDING}
    gen = [r for r in records if r["reason_code"] == se.ReasonCode.SIGNAL_GENERATED and r["decision"] == "ENTER"]
    assert gen and "entry_price" in gen[0]["numeric_evidence"]


# --- output contract --------------------------------------------------------

def test_signalengine_output_contract(se, bullish_setup):
    df, _ = bullish_setup
    eng = se.SignalEngine(dict(NEWS_OK))
    out = eng.generate({"EURUSD.FX": df})
    assert isinstance(out, dict) and set(out.keys()) == {"EURUSD.FX"}
    s = out["EURUSD.FX"]
    assert isinstance(s, pd.Series) and s.index.equals(df.index)
    assert set(np.unique(s.to_numpy())).issubset({-1.0, 0.0, 1.0})


def test_symbol_fs_safe_never_contains_slash(se, bullish_setup):
    assert "/" not in se.fs_safe_symbol("EUR/USD")
    eng, _ = run_ok(se, bullish_setup[0])
    assert "/" not in eng.instructions["EURUSD.FX"][0]["symbol_fs_safe"]


# --- architectural boundaries -----------------------------------------------

def _module_ast():
    return ast.parse(ENGINE_PATH.read_text(encoding="utf-8"))


def _imported_roots():
    roots = set()
    for node in ast.walk(_module_ast()):
        if isinstance(node, ast.Import):
            for a in node.names:
                roots.add(a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            roots.add((node.module or "").split(".")[0])
    return roots


def test_no_bridge_writes(se, bullish_setup, tmp_path):
    write_calls = {"makedirs", "mkdir", "write_text", "write_bytes", "to_csv",
                   "to_json", "to_parquet", "to_pickle"}
    for node in ast.walk(_module_ast()):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name):
                assert f.id != "open"
            if isinstance(f, ast.Attribute):
                assert f.attr not in write_calls
    before = set(os.listdir(tmp_path))
    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        run_ok(se, bullish_setup[0])
    finally:
        os.chdir(cwd)
    assert set(os.listdir(tmp_path)) == before


def test_no_networking_imports(se):
    forbidden = {"socket", "urllib", "http", "requests", "httpx", "aiohttp",
                 "ftplib", "smtplib", "telnetlib", "asyncio", "ssl", "websockets"}
    assert not (_imported_roots() & forbidden)


def test_no_mt5_titan_phantom_core_imports(se):
    roots = _imported_roots()
    assert not ({"MetaTrader5", "mt5"} & roots)
    assert "titan" not in {r.lower() for r in roots}
    assert "phantom" not in {r.lower() for r in roots}
    assert not ({"backtest", "src", "agent", "vibe_trading"} & roots)
    assert {"pandas", "numpy"}.issubset(roots)


def test_no_decorators_scrubber_clean(se):
    for node in ast.walk(_module_ast()):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            assert not node.decorator_list, f"decorator on {node.name}"
