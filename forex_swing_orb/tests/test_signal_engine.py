"""Comprehensive deterministic tests for the Forex Swing-ORB SignalEngine.

Covers the Phase 1 test matrix (frozen spec §18 + mission list items 1-49).
Item 50 (full official Vibe-Trading suite regression) is run separately and
reported in the mission return, not as a unit test here.

All fixtures are deterministic; no clock, no RNG, no network, no MT5.
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
CONFIRM_TS = pd.Timestamp("2024-01-25 11:15", tz="UTC")   # slot 45, decision bar
APPLIED_TS = pd.Timestamp("2024-01-25 11:30", tz="UTC")   # slot 46, position on


def run(se, df, config=None):
    eng = se.SignalEngine(config)
    out = eng.generate({"EURUSD.FX": df})
    return eng, out["EURUSD.FX"]


def audit_by_ts(eng, symbol="EURUSD.FX"):
    return {a["evaluation_timestamp"]: a for a in eng.audit[symbol]}


# --- 1,2,12: determinism ----------------------------------------------------

def test_deterministic_output_identical_inputs(se, bullish_setup):
    df, _ = bullish_setup
    _, s1 = run(se, df)
    _, s2 = run(se, df)
    assert s1.equals(s2)


def test_deterministic_signal_id(se, bullish_setup):
    df, _ = bullish_setup
    e1, _ = run(se, df)
    e2, _ = run(se, df)
    ids1 = [i["signal_id"] for i in e1.instructions["EURUSD.FX"]]
    ids2 = [i["signal_id"] for i in e2.instructions["EURUSD.FX"]]
    assert ids1 == ids2 and len(ids1) >= 1
    # content-derived, not random
    inst = e1.instructions["EURUSD.FX"][0]
    recomputed = se.compute_signal_id(
        inst["strategy_version"], inst["symbol"], inst["direction"],
        inst["generated_timestamp"], inst["entry_price"], inst["stop_loss"], inst["take_profit"],
    )
    assert recomputed == inst["signal_id"]


# --- 3,4: no look-ahead -----------------------------------------------------

def test_no_future_bar_dependency(se, bullish_setup):
    df, _ = bullish_setup
    _, full = run(se, df)
    cut = df.index.get_loc(CONFIRM_TS)
    prefix = df.iloc[: cut + 1]
    _, part = run(se, prefix)
    # compare far from the cut edge (exclude last day) -> must be identical
    horizon = df.index[cut] - pd.Timedelta(days=1)
    a = full[full.index <= horizon]
    b = part[part.index <= horizon]
    assert a.equals(b)


def test_pivot_confirmation_latency_no_lookahead(se):
    # a swing high at index i is only confirmed k bars later
    idx = pd.date_range("2024-01-01", periods=9, freq="15min", tz="UTC")
    highs = [1, 2, 3, 5, 3, 2, 1, 1, 1]
    lows = [h - 1 for h in highs]
    df = pd.DataFrame({"open": highs, "high": highs, "low": lows, "close": highs}, index=idx)
    piv = se.confirmed_pivots(df, 2)
    hi = [p for p in piv if p["kind"] == "H"]
    assert hi and hi[0]["pivot_time"] == idx[3]
    assert hi[0]["confirm_time"] == idx[5]  # i + k = 3 + 2


# --- 5,6,7,8: data semantics ------------------------------------------------

def test_insufficient_history(se):
    idx = pd.date_range("2024-01-01", periods=50, freq="15min", tz="UTC")
    df = pd.DataFrame({"open": 1.1, "high": 1.11, "low": 1.09, "close": 1.1}, index=idx)
    eng, sig = run(se, df)
    assert (sig == 0).all()
    assert eng.audit["EURUSD.FX"][0]["reason_code"] == se.ReasonCode.DATA_INSUFFICIENT


def test_unclosed_last_bar_not_acted_on(se, bullish_setup):
    df, _ = bullish_setup
    cut = df.index.get_loc(CONFIRM_TS)
    prefix = df.iloc[: cut + 1]  # ends exactly on the confirming bar
    eng, sig = run(se, prefix)
    # instruction decided on the final (potentially forming) bar ...
    assert len(eng.instructions["EURUSD.FX"]) == 1
    # ... but the position is never applied on that last bar (shift => no-lookahead)
    assert sig.iloc[-1] == 0.0


def test_non_monotonic_and_duplicate_and_nan(se):
    idx = pd.date_range("2024-01-01", periods=300, freq="15min", tz="UTC")
    base = pd.DataFrame({"open": 1.1, "high": 1.11, "low": 1.09, "close": 1.1}, index=idx)
    cfg = se.merged_config(None)
    # duplicate
    dup = base.copy(); dup.index = base.index[:-1].append(base.index[-2:-1])
    assert se.validate_frame(dup, cfg)[1] == se.ReasonCode.TEMPORAL_GAP
    # non-monotonic
    nm = base.copy(); nm.index = base.index[::-1]
    assert se.validate_frame(nm, cfg)[1] == se.ReasonCode.TEMPORAL_GAP
    # NaN
    nan = base.copy(); nan.iloc[10, nan.columns.get_loc("close")] = np.nan
    assert se.validate_frame(nan, cfg)[1] == se.ReasonCode.DATA_INSUFFICIENT


def test_temporal_gap_during_setup(se, bullish_setup):
    df, ref = bullish_setup
    # drop one bar (slot 41) between breakout(40) and retest(42) to create a gap
    drop_ts = synth.slot_ts("2024-01-25", 41)
    df2 = df.drop(index=drop_ts)
    eng, sig = run(se, df2)
    codes = {a["reason_code"] for a in eng.audit["EURUSD.FX"]}
    assert se.ReasonCode.TEMPORAL_GAP in codes
    # the gap invalidates the setup -> no signal that day
    assert len(eng.instructions["EURUSD.FX"]) == 0


# --- 9,10,11: session / DST -------------------------------------------------

def test_london_window_winter_gmt(se):
    cfg = se.merged_config(None)
    s, e, ok, _ = se.london_window_utc(date(2024, 1, 25), cfg)
    assert ok and s.strftime("%H:%M") == "08:00" and e.strftime("%H:%M") == "09:00"


def test_london_window_summer_bst(se):
    cfg = se.merged_config(None)
    s, e, ok, _ = se.london_window_utc(date(2024, 7, 25), cfg)
    assert ok and s.strftime("%H:%M") == "07:00" and e.strftime("%H:%M") == "08:00"


def test_dst_ambiguity_fails_closed(se):
    # spring-forward: London skips 01:00->02:00 on 2024-03-31; a window anchored
    # there straddles the transition -> ineligible.
    cfg = se.merged_config({"or_start_local_hour": 1, "or_window_minutes": 60})
    s, e, ok, reason = se.london_window_utc(date(2024, 3, 31), cfg)
    assert not ok and reason == se.ReasonCode.DST_AMBIGUOUS


# --- 12,13,14: range validity ----------------------------------------------

def test_valid_opening_range_produces_setup(se, bullish_setup):
    df, _ = bullish_setup
    eng, _ = run(se, df)
    assert len(eng.instructions["EURUSD.FX"]) == 1


def test_invalid_range_width(se, bullish_setup):
    df, ref = bullish_setup
    # blow the OR width far beyond max_width_atr by widening slot 34
    df2 = synth.set_day_bars(df, "2024-01-25", {34: {"high": ref["orh"] + 0.05, "low": ref["orl"] - 0.05}})
    eng, _ = run(se, df2)
    aud = audit_by_ts(eng)
    a = aud[synth.slot_ts("2024-01-25", 40).strftime("%Y-%m-%dT%H:%M:%SZ")]
    assert a["range_state"] == se.ReasonCode.RANGE_INVALID
    assert len(eng.instructions["EURUSD.FX"]) == 0


def test_incomplete_range(se, bullish_setup):
    df, _ = bullish_setup
    # drop OR-window bars (slots 32..35) -> fewer than expected -> incomplete
    drops = [synth.slot_ts("2024-01-25", s) for s in (32, 33, 34, 35)]
    df2 = df.drop(index=drops)
    eng, _ = run(se, df2)
    aud = audit_by_ts(eng)
    a = aud[synth.slot_ts("2024-01-25", 40).strftime("%Y-%m-%dT%H:%M:%SZ")]
    assert a["range_state"] == se.ReasonCode.RANGE_INCOMPLETE
    assert len(eng.instructions["EURUSD.FX"]) == 0


# --- 15,16,17,18: trend -----------------------------------------------------

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


# --- 19,20,21,22: breakout --------------------------------------------------

def test_wick_only_breakout_rejected(se, bullish_setup):
    df, ref = bullish_setup
    # slot 40: high pokes above orh but close stays inside -> wick only
    df2 = synth.set_day_bars(df, "2024-01-25", {
        40: {"open": ref["orh"] - 0.0002, "high": ref["orh"] + 0.0009,
             "low": ref["orh"] - 0.0004, "close": ref["orh"] - 0.0001}})
    eng, _ = run(se, df2)
    aud = audit_by_ts(eng)
    a = aud[synth.slot_ts("2024-01-25", 40).strftime("%Y-%m-%dT%H:%M:%SZ")]
    assert a["reason_code"] == se.ReasonCode.WICK_ONLY_BREAKOUT
    assert len(eng.instructions["EURUSD.FX"]) == 0


def test_completed_bullish_breakout(se, bullish_setup):
    df, _ = bullish_setup
    eng, _ = run(se, df)
    inst = eng.instructions["EURUSD.FX"][0]
    assert inst["direction"] == "LONG"


def test_completed_bearish_breakout(se, bearish_setup):
    df, _ = bearish_setup
    eng, _ = run(se, df)
    inst = eng.instructions["EURUSD.FX"][0]
    assert inst["direction"] == "SHORT"


def test_breakout_buffer_not_met(se, bullish_setup):
    df, _ = bullish_setup
    # require a 100-pip buffer: the setup's ~8-pip close-beyond never qualifies,
    # so every close-beyond-boundary bar is BUFFER_NOT_MET and no trade occurs.
    eng, _ = run(se, df, {"breakout_min_pips": 100.0})
    codes = {a["reason_code"] for a in eng.audit["EURUSD.FX"]}
    assert se.ReasonCode.BREAKOUT_BUFFER_NOT_MET in codes
    assert len(eng.instructions["EURUSD.FX"]) == 0


# --- 23,24,25,26,27,28: retest ---------------------------------------------

def test_valid_retest(se, bullish_setup):
    df, _ = bullish_setup
    eng, _ = run(se, df)
    aud = audit_by_ts(eng)
    a = aud[synth.slot_ts("2024-01-25", 42).strftime("%Y-%m-%dT%H:%M:%SZ")]
    assert a["retest_state"] == "HELD"


def test_retest_close_back_inside_invalidation(se, bullish_setup):
    df, ref = bullish_setup
    # slot 41: decisive close back inside the range -> reclaim -> RETEST_FAILED
    df2 = synth.set_day_bars(df, "2024-01-25", {
        41: {"open": ref["orh"], "high": ref["orh"] + 0.0001,
             "low": ref["orl"] - 0.0002, "close": ref["orl"] - 0.0005}})
    eng, _ = run(se, df2)
    codes = [a["reason_code"] for a in eng.audit["EURUSD.FX"]]
    assert se.ReasonCode.RETEST_FAILED in codes
    assert len(eng.instructions["EURUSD.FX"]) == 0


def test_excessive_retest_penetration(se, bullish_setup):
    df, ref = bullish_setup
    # slot 42 low pierces far below orh (beyond max deviation) but closes above
    df2 = synth.set_day_bars(df, "2024-01-25", {
        42: {"open": ref["orh"] + 0.0006, "high": ref["orh"] + 0.0007,
             "low": ref["orl"] - 0.0030, "close": ref["orh"] + 0.0003}})
    eng, _ = run(se, df2)
    codes = [a["reason_code"] for a in eng.audit["EURUSD.FX"]]
    assert se.ReasonCode.RETEST_FAILED in codes
    assert len(eng.instructions["EURUSD.FX"]) == 0


def test_retest_timeout(se, bullish_setup):
    df, ref = bullish_setup
    # keep price above the boundary (never retests) for > setup_max_bars
    ups = {}
    for s in range(41, 41 + 20):
        lvl = ref["orh"] + 0.0020 + 0.0002 * (s - 41)
        ups[s] = {"open": lvl, "high": lvl + 0.0002, "low": lvl - 0.0001, "close": lvl}
    df2 = synth.set_day_bars(df, "2024-01-25", ups)
    eng, _ = run(se, df2)
    codes = [a["reason_code"] for a in eng.audit["EURUSD.FX"]]
    assert se.ReasonCode.RETEST_EXPIRED in codes
    assert len(eng.instructions["EURUSD.FX"]) == 0


def test_no_resume_after_failed_retest(se, bullish_setup):
    df, ref = bullish_setup
    # force a reclaim at slot 41; even though price later rises, no new
    # breakout+retest+confirm completes -> still no signal from the dead setup
    df2 = synth.set_day_bars(df, "2024-01-25", {
        41: {"open": ref["orh"], "high": ref["orh"] + 0.0001,
             "low": ref["orl"] - 0.0006, "close": ref["orl"] - 0.0006}})
    eng, _ = run(se, df2)
    assert len(eng.instructions["EURUSD.FX"]) == 0


# --- 29,30: price-action confirmation ---------------------------------------

def test_price_action_confirmation_pass(se, bullish_setup):
    df, _ = bullish_setup
    eng, _ = run(se, df)
    aud = audit_by_ts(eng)
    a = aud[CONFIRM_TS.strftime("%Y-%m-%dT%H:%M:%SZ")]
    assert a["price_action_state"] == "CONFIRMED" and a["reason_code"] == se.ReasonCode.SIGNAL_GENERATED


def test_price_action_confirmation_fail(se, bullish_setup):
    df, ref = bullish_setup
    # never close above the minor swing high -> confirmation never happens
    flats = {}
    for s in range(45, 45 + 15):
        lvl = ref["orh"] + 0.0004
        flats[s] = {"open": lvl, "high": ref["minor_swing_high"] - 0.0001, "low": ref["orh"] + 0.0002, "close": lvl}
    df2 = synth.set_day_bars(df, "2024-01-25", flats)
    eng, _ = run(se, df2)
    codes = [a["reason_code"] for a in eng.audit["EURUSD.FX"]]
    assert se.ReasonCode.PRICE_ACTION_NOT_CONFIRMED in codes
    assert len(eng.instructions["EURUSD.FX"]) == 0


# --- 31,32,33,34: news ------------------------------------------------------

def test_missing_news_fails_closed(se, bullish_setup):
    df, _ = bullish_setup
    eng, _ = run(se, df, {"news_required": True})
    codes = [a["reason_code"] for a in eng.audit["EURUSD.FX"]]
    assert se.ReasonCode.NEWS_DATA_UNAVAILABLE in codes
    assert len(eng.instructions["EURUSD.FX"]) == 0


def test_stale_news_fails_closed(se, bullish_setup):
    df, _ = bullish_setup
    cfg = {"news_required": True, "news_events": [], "news_asof": "2024-01-01T00:00:00Z"}
    eng, _ = run(se, df, cfg)
    codes = [a["reason_code"] for a in eng.audit["EURUSD.FX"]]
    assert se.ReasonCode.NEWS_DATA_STALE in codes
    assert len(eng.instructions["EURUSD.FX"]) == 0


def test_high_impact_news_lockout(se, bullish_setup):
    df, _ = bullish_setup
    cfg = {"news_required": True, "news_asof": "2024-01-25T11:15:00Z",
           "news_events": [{"timestamp": "2024-01-25T11:20:00Z", "impact": "high", "currencies": ["USD"]}]}
    eng, _ = run(se, df, cfg)
    codes = [a["reason_code"] for a in eng.audit["EURUSD.FX"]]
    assert se.ReasonCode.NEWS_LOCKOUT in codes
    assert len(eng.instructions["EURUSD.FX"]) == 0


def test_news_does_not_generate_direction(se, synthmod):
    # a flat/neutral series with high-impact news present must NOT yield a trade
    df = synthmod.uptrend_frame(days=10)  # too little history -> neutral, no setup
    cfg = {"news_required": True,
           "news_events": [{"timestamp": "2024-01-05T10:00:00Z", "impact": "high", "currencies": ["EUR"]}]}
    eng, _ = run(se, df, cfg)
    assert len(eng.instructions["EURUSD.FX"]) == 0


# --- 35,36,37: risk ---------------------------------------------------------

def test_valid_structural_stop(se, bullish_setup):
    df, _ = bullish_setup
    eng, _ = run(se, df)
    inst = eng.instructions["EURUSD.FX"][0]
    assert inst["stop_loss"] < inst["entry_price"]


def test_invalid_structural_stop_max_distance(se, bullish_setup):
    df, _ = bullish_setup
    eng, _ = run(se, df, {"max_stop_pips": 0.5})  # ~5 pip cap forces rejection
    codes = [a["reason_code"] for a in eng.audit["EURUSD.FX"]]
    assert se.ReasonCode.STOP_INVALID in codes
    assert len(eng.instructions["EURUSD.FX"]) == 0


def test_fixed_2r_target(se, bullish_setup):
    df, _ = bullish_setup
    eng, _ = run(se, df)
    inst = eng.instructions["EURUSD.FX"][0]
    stop_dist = inst["entry_price"] - inst["stop_loss"]
    assert inst["evidence_summary"]["rr_planned"] == 2.0
    # target is the 2R multiple, at the instruction's 5-dp price precision
    assert abs(inst["take_profit"] - (inst["entry_price"] + 2.0 * stop_dist)) < 2e-5


# --- 38,39,40,41: position mgmt / symmetry / expiry / dedup -----------------

def test_one_position_per_symbol(se, bullish_setup):
    df, _ = bullish_setup
    _, sig = run(se, df)
    assert set(np.unique(sig.to_numpy())).issubset({-1.0, 0.0, 1.0})
    # a single contiguous in-position block, no overlap
    inpos = (sig != 0).to_numpy().astype(int)
    transitions = np.abs(np.diff(inpos)).sum()
    assert transitions <= 2  # at most one enter + one exit


def test_long_short_symmetry(se, bullish_setup, bearish_setup):
    dfl, _ = bullish_setup
    dfs, _ = bearish_setup
    il = run(se, dfl)[0].instructions["EURUSD.FX"][0]
    ish = run(se, dfs)[0].instructions["EURUSD.FX"][0]
    assert il["direction"] == "LONG" and ish["direction"] == "SHORT"
    assert il["stop_loss"] < il["entry_price"] < il["take_profit"]
    assert ish["stop_loss"] > ish["entry_price"] > ish["take_profit"]
    assert il["evidence_summary"]["rr_planned"] == ish["evidence_summary"]["rr_planned"] == 2.0


def test_signal_expiration(se, bullish_setup):
    df, _ = bullish_setup
    eng, _ = run(se, df)
    inst = eng.instructions["EURUSD.FX"][0]
    gen = pd.Timestamp(inst["generated_timestamp"])
    exp = pd.Timestamp(inst["expiration_timestamp"])
    assert (exp - gen) == pd.Timedelta(minutes=15)  # entry_valid_bars=1 * 15m


def test_duplicate_signal_prevention(se, bullish_setup):
    df, _ = bullish_setup
    eng, _ = run(se, df)
    ids = [i["signal_id"] for i in eng.instructions["EURUSD.FX"]]
    assert len(ids) == len(set(ids))


# --- 42: audit --------------------------------------------------------------

def test_per_stage_reason_code_auditability(se, bullish_setup):
    df, _ = bullish_setup
    eng, _ = run(se, df)
    records = eng.audit["EURUSD.FX"]
    assert all(r["reason_code"] for r in records)
    codes = {r["reason_code"] for r in records}
    # both a no-trade reason and the generated signal must be represented
    assert se.ReasonCode.SIGNAL_GENERATED in codes
    assert codes & {se.ReasonCode.SESSION_INELIGIBLE, se.ReasonCode.TREND_NEUTRAL,
                    se.ReasonCode.RETEST_PENDING}
    # a signal record carries structured numeric evidence
    gen = [r for r in records if r["reason_code"] == se.ReasonCode.SIGNAL_GENERATED and r["decision"] == "ENTER"]
    assert gen and "entry_price" in gen[0]["numeric_evidence"]


# --- 43: SignalEngine output contract ---------------------------------------

def test_signalengine_output_contract(se, bullish_setup):
    df, _ = bullish_setup
    eng = se.SignalEngine()
    out = eng.generate({"EURUSD.FX": df})
    assert isinstance(out, dict) and set(out.keys()) == {"EURUSD.FX"}
    s = out["EURUSD.FX"]
    assert isinstance(s, pd.Series)
    assert s.index.equals(df.index)
    assert set(np.unique(s.to_numpy())).issubset({-1.0, 0.0, 1.0})


def test_symbol_fs_safe_never_contains_slash(se):
    assert "/" not in se.fs_safe_symbol("EUR/USD")
    df = synth.uptrend_frame(days=60)
    df2, _ = synth.inject_bullish_orb(df, "2024-01-25")
    eng, _ = run(se, df2)
    inst = eng.instructions["EURUSD.FX"][0]
    assert "/" not in inst["symbol_fs_safe"]


# --- 44,45,46,47,48,49: boundaries (bridge/network/mt5/titan/phantom/core) --

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
    # no file-writing / directory-creating calls anywhere in the source
    write_calls = {"makedirs", "mkdir", "write_text", "write_bytes", "to_csv",
                   "to_json", "to_parquet", "to_pickle"}
    for node in ast.walk(_module_ast()):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name):
                assert f.id != "open", "open() must not appear in the engine"
            if isinstance(f, ast.Attribute):
                assert f.attr not in write_calls, f"forbidden write call {f.attr}"
    # generate() must not create any file on disk
    before = set(os.listdir(tmp_path))
    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        run(se, bullish_setup[0])
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
    # no Vibe-Trading core imports -> only stdlib + pandas/numpy
    assert not ({"backtest", "src", "agent", "vibe_trading"} & roots)
    assert {"pandas", "numpy"}.issubset(roots)


def test_no_decorators_scrubber_clean(se):
    for node in ast.walk(_module_ast()):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            assert not node.decorator_list, f"decorator on {node.name}"
