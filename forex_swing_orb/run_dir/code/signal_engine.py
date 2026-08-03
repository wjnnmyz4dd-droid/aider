"""Forex Swing Opening-Range-Breakout (Swing-ORB) SignalEngine — Phase 1.

Deterministic, no-lookahead implementation of the frozen strategy specification
`docs/FOREX_SWING_ORB_SPEC.md` (swing_orb.v1.2.0). This file is a self-contained
Vibe-Trading run-dir signal engine: it defines module-level helpers + constants
(literals only, no decorators, no import-time execution) and a `SignalEngine`
class exposing `generate(data_map) -> Dict[str, pd.Series]`.

EXECUTION BOUNDARY (frozen spec §0.2): this engine performs research /
qualification / signal formation ONLY. It never connects to MT5 or any broker,
never writes to the filesystem bridge, and never performs network I/O. It emits
a per-bar weight series (the executable signal) plus, for audit, an in-memory
versioned trade instruction and a per-bar decision trail.

Signal encoding (the returned Series):
  * +1.0 = hold a full long position during that bar
  * -1.0 = hold a full short position during that bar
  *  0.0 = flat
The returned series is `decision.shift(1)`: a decision computed from the bar
closing at t is applied only from bar t+1 (no bar uses its own or future data).
Stop/target/expiry exits are detected on completed bars and applied on the next
bar (the engine models no broker-side SL/TP). Weight is only ever 0/+1/-1, so
one-position-per-symbol and no-averaging are structural.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd


STRATEGY_ID = "forex_swing_orb"
STRATEGY_VERSION = "swing_orb.v1.3.0"
INSTRUCTION_SCHEMA_VERSION = 1

DEFAULT_CONFIG = {
    "execution_tf_minutes": 15,
    "atr_period": 14,
    "min_history_bars": 200,
    "pivot_k": 2,
    "min_confirmed_highs": 2,
    "min_confirmed_lows": 2,
    "health_min_confirmed": 3,
    "health_progress_atr": 0.10,
    "health_min_leg_atr": 0.5,
    "health_leg_ratio": 0.5,
    "eq_min_pips": 1.0,
    "eq_atr_mult": 0.1,
    "minor_pivot_k": 1,
    "confirm_bars": 1,
    "session_tz": "Europe/London",
    "or_start_local_hour": 8,
    "or_start_local_minute": 0,
    "or_window_minutes": 60,
    "session_end_local_hour": 21,
    "min_width_atr": 0.5,
    "max_width_atr": 5.0,
    "breakout_min_pips": 2.0,
    "breakout_atr_mult": 0.25,
    "setup_max_bars": 12,
    "retest_min_pips": 2.0,
    "retest_atr_mult": 0.15,
    "retest_dev_atr_mult": 0.5,
    "risk_pct": 0.0025,
    "rr_target": 2.0,
    "min_rr": 2.0,
    "stop_min_pips": 2.0,
    "stop_atr_mult": 0.25,
    "max_stop_pips": 60.0,
    "entry_valid_bars": 1,
    "news_required": False,
    "news_max_age_min": 1440,
    "news_pre_lockout_min": 30,
    "news_post_lockout_min": 30,
    "friday_no_new_entry_local_hour": 20,
}


class ReasonCode:
    """Stable, deterministic per-stage reason codes (frozen spec §14)."""

    DATA_INSUFFICIENT = "DATA_INSUFFICIENT"
    DATA_NOT_CLOSED = "DATA_NOT_CLOSED"
    DATA_STALE = "DATA_STALE"
    TEMPORAL_GAP = "TEMPORAL_GAP"
    SESSION_INELIGIBLE = "SESSION_INELIGIBLE"
    DST_AMBIGUOUS = "DST_AMBIGUOUS"
    RANGE_INCOMPLETE = "RANGE_INCOMPLETE"
    RANGE_INVALID = "RANGE_INVALID"
    TREND_BULLISH = "TREND_BULLISH"
    TREND_BEARISH = "TREND_BEARISH"
    TREND_NEUTRAL = "TREND_NEUTRAL"
    TREND_CONFLICT = "TREND_CONFLICT"
    TREND_HEALTH_WEAK = "TREND_HEALTH_WEAK"
    BREAKOUT_NOT_CONFIRMED = "BREAKOUT_NOT_CONFIRMED"
    WICK_ONLY_BREAKOUT = "WICK_ONLY_BREAKOUT"
    BREAKOUT_BUFFER_NOT_MET = "BREAKOUT_BUFFER_NOT_MET"
    RETEST_PENDING = "RETEST_PENDING"
    RETEST_FAILED = "RETEST_FAILED"
    RETEST_EXPIRED = "RETEST_EXPIRED"
    PRICE_ACTION_NOT_CONFIRMED = "PRICE_ACTION_NOT_CONFIRMED"
    NEWS_DATA_UNAVAILABLE = "NEWS_DATA_UNAVAILABLE"
    NEWS_DATA_STALE = "NEWS_DATA_STALE"
    NEWS_LOCKOUT = "NEWS_LOCKOUT"
    RISK_INVALID = "RISK_INVALID"
    STOP_INVALID = "STOP_INVALID"
    REWARD_RISK_INVALID = "REWARD_RISK_INVALID"
    SIGNAL_GENERATED = "SIGNAL_GENERATED"


# --- small deterministic helpers -------------------------------------------

def merged_config(config):
    """Return DEFAULT_CONFIG overlaid with a user config dict (copy)."""
    cfg = dict(DEFAULT_CONFIG)
    if config:
        for key, value in config.items():
            cfg[key] = value
    return cfg


def pip_size(symbol):
    """Pip size in price units: 0.01 for JPY-quoted pairs, else 0.0001."""
    base_quote = symbol.replace(".FX", "").replace("/", "")
    if base_quote[-3:].upper() == "JPY":
        return 0.01
    return 0.0001


def symbol_currencies(symbol):
    """Deterministic base/quote split, e.g. EURUSD.FX -> ('EUR','USD')."""
    core = symbol.replace(".FX", "").replace("/", "").upper()
    if len(core) < 6:
        return (core, "")
    return (core[0:3], core[3:6])


def fs_safe_symbol(symbol):
    """Filesystem-safe form of a symbol (never contains '/')."""
    return symbol.replace("/", "_")


def to_utc_index(df):
    """Return df with a tz-aware UTC DatetimeIndex (assume naive == UTC)."""
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    else:
        idx = idx.tz_convert("UTC")
    out = df.copy()
    out.index = idx
    return out


def infer_tf_minutes(index):
    """Infer the dominant bar interval (minutes) from index spacing."""
    if len(index) < 2:
        return None
    diffs = np.diff(index.asi8) // 60_000_000_000
    diffs = diffs[diffs > 0]
    if len(diffs) == 0:
        return None
    return int(np.bincount(diffs.astype(np.int64)).argmax())


def true_range(high, low, close):
    """Vectorized true range."""
    prev_close = close.shift(1)
    a = high - low
    b = (high - prev_close).abs()
    c = (low - prev_close).abs()
    return pd.concat([a, b, c], axis=1).max(axis=1)


def atr(df, period):
    """Deterministic ATR: simple rolling mean of true range (min_periods=period)."""
    tr = true_range(df["high"], df["low"], df["close"])
    return tr.rolling(window=period, min_periods=period).mean()


def fractal_pivot_high_mask(high, k):
    """Boolean mask: strict fractal swing high of strength k (no future leak here;
    confirmation latency is applied by the caller when mapping to decision time)."""
    values = high.to_numpy()
    n = len(values)
    mask = np.zeros(n, dtype=bool)
    for i in range(k, n - k):
        center = values[i]
        ok = True
        for j in range(1, k + 1):
            if not (center > values[i - j] and center > values[i + j]):
                ok = False
                break
        mask[i] = ok
    return mask


def fractal_pivot_low_mask(low, k):
    """Boolean mask: strict fractal swing low of strength k."""
    values = low.to_numpy()
    n = len(values)
    mask = np.zeros(n, dtype=bool)
    for i in range(k, n - k):
        center = values[i]
        ok = True
        for j in range(1, k + 1):
            if not (center < values[i - j] and center < values[i + j]):
                ok = False
                break
        mask[i] = ok
    return mask


def confirmed_pivots(df, k):
    """Return a chronologically-alternating list of confirmed pivots.

    Each entry: {"pivot_time","confirm_time","price","kind"} where kind is
    "H"/"L". A pivot at bar i is only *confirmed* once bar i+k has closed, so
    confirm_time = close time of bar i+k (bar open + tf). Alternation keeps the
    more extreme pivot when two same-type pivots occur in a row (frozen §2.1).
    """
    idx = df.index
    n = len(idx)
    if n < (2 * k + 1):
        return []
    hi = fractal_pivot_high_mask(df["high"], k)
    lo = fractal_pivot_low_mask(df["low"], k)
    raw = []
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    for i in range(n):
        confirm_i = i + k
        if confirm_i >= n:
            continue
        confirm_time = idx[confirm_i]
        if hi[i]:
            raw.append((idx[i], confirm_time, float(highs[i]), "H"))
        if lo[i]:
            raw.append((idx[i], confirm_time, float(lows[i]), "L"))
    raw.sort(key=lambda r: (r[1], r[0]))
    alt = []
    for pivot_time, confirm_time, price, kind in raw:
        if alt and alt[-1][3] == kind:
            prev = alt[-1]
            better = price > prev[2] if kind == "H" else price < prev[2]
            if better:
                alt[-1] = (pivot_time, confirm_time, price, kind)
            continue
        alt.append((pivot_time, confirm_time, price, kind))
    return [
        {"pivot_time": p[0], "confirm_time": p[1], "price": p[2], "kind": p[3]}
        for p in alt
    ]


def trend_from_pivots(pivots, cfg, eq_tol):
    """Classify BULLISH/BEARISH/NEUTRAL from a confirmed-pivot list (frozen §2.3)."""
    highs = [p["price"] for p in pivots if p["kind"] == "H"]
    lows = [p["price"] for p in pivots if p["kind"] == "L"]
    need_h = cfg["min_confirmed_highs"]
    need_l = cfg["min_confirmed_lows"]
    if len(highs) < need_h or len(lows) < need_l:
        return "NEUTRAL"
    h2 = highs[-2:]
    l2 = lows[-2:]
    higher = (h2[-1] > h2[-2] + eq_tol) and (l2[-1] > l2[-2] + eq_tol)
    lower = (h2[-1] < h2[-2] - eq_tol) and (l2[-1] < l2[-2] - eq_tol)
    if higher and not lower:
        return "BULLISH"
    if lower and not higher:
        return "BEARISH"
    return "NEUTRAL"


def htf_bars(df, minutes):
    """Resample execution bars (open-labeled) into complete higher-TF OHLC bars.

    Buckets are left-closed/left-labeled by open time; a bucket is kept only when
    it is fully elapsed within the available data, so no partial trailing bucket
    leaks. Returns a DataFrame with a 'close_time' column (bucket open + span).
    """
    rule = "{}min".format(int(minutes))
    agg = df.resample(rule, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}
    )
    agg = agg.dropna(subset=["high", "low", "close"])
    if len(agg) == 0:
        return agg.assign(close_time=pd.NaT)
    span = pd.Timedelta(minutes=minutes)
    exec_tf = infer_tf_minutes(df.index) or 1
    last_open = df.index[-1]
    close_time = agg.index + span
    agg = agg.assign(close_time=close_time)
    complete = agg["close_time"] <= (last_open + pd.Timedelta(minutes=exec_tf))
    return agg[complete]


def htf_trend_events(df_exec, minutes, cfg):
    """Compute (confirm_time, trend) change-events for one higher timeframe."""
    bars = htf_bars(df_exec, minutes)
    if len(bars) < (2 * cfg["pivot_k"] + 1):
        return []
    piv = confirmed_pivots(bars, cfg["pivot_k"])
    if not piv:
        return []
    hatr = atr(bars, cfg["atr_period"])
    pip = pip_size("EURUSD.FX")
    events = []
    for i in range(len(piv)):
        upto = piv[: i + 1]
        ct = piv[i]["confirm_time"]
        atr_at = hatr.reindex([ct], method="ffill").iloc[0]
        atr_val = float(atr_at) if atr_at == atr_at else 0.0
        eq_tol = max(cfg["eq_min_pips"] * pip, cfg["eq_atr_mult"] * atr_val)
        events.append((ct, trend_from_pivots(upto, cfg, eq_tol)))
    return events


def map_label_to_exec(exec_index, events, default):
    """Map higher-TF (confirm_time, label) change-events onto exec bars (as-of)."""
    if not events:
        return pd.Series([default] * len(exec_index), index=exec_index)
    ev = pd.DataFrame(events, columns=["confirm_time", "label"]).sort_values("confirm_time")
    ev = ev.drop_duplicates(subset=["confirm_time"], keep="last")
    base = pd.DataFrame({"t": exec_index})
    merged = pd.merge_asof(
        base, ev, left_on="t", right_on="confirm_time", direction="backward"
    )
    return pd.Series(merged["label"].fillna(default).to_numpy(), index=exec_index)


def map_trend_to_exec(exec_index, events):
    """Map higher-TF trend change-events onto exec bars (default NEUTRAL)."""
    return map_label_to_exec(exec_index, events, "NEUTRAL")


def trend_health(pivots, direction, cfg, atr_val):
    """Deterministic Trend Health Gate (frozen spec §2.5). No prediction.

    Rejects weak continuation from the already-confirmed swing structure only:
      (a) structure integrity  — >= health_min_confirmed highs AND lows
      (b) progress margin       — latest HH/HL advance >= health_progress_atr*ATR
      (c) continuation quality  — latest leg >= health_min_leg_atr*ATR
      (d) not weakening         — latest leg >= health_leg_ratio * prior leg
    Returns True only if all pass for the given (non-zero) trend direction.
    """
    if direction == 0 or not (atr_val == atr_val) or atr_val <= 0:
        return False
    highs = [p["price"] for p in pivots if p["kind"] == "H"]
    lows = [p["price"] for p in pivots if p["kind"] == "L"]
    need = cfg["health_min_confirmed"]
    if len(highs) < need or len(lows) < need:
        return False
    prog = cfg["health_progress_atr"] * atr_val
    if direction > 0:
        if (highs[-1] - highs[-2]) < prog or (lows[-1] - lows[-2]) < prog:
            return False
    else:
        if (highs[-2] - highs[-1]) < prog or (lows[-2] - lows[-1]) < prog:
            return False
    if len(pivots) < 3:
        return False
    last_leg = abs(pivots[-1]["price"] - pivots[-2]["price"])
    prior_leg = abs(pivots[-2]["price"] - pivots[-3]["price"])
    if last_leg < cfg["health_min_leg_atr"] * atr_val:
        return False
    if prior_leg > 0 and last_leg < cfg["health_leg_ratio"] * prior_leg:
        return False
    return True


def htf_health_events(df, minutes, cfg):
    """Compute (confirm_time, "OK"/"WEAK") trend-health events for one HTF."""
    bars = htf_bars(df, minutes)
    if len(bars) < (2 * cfg["pivot_k"] + 1):
        return []
    piv = confirmed_pivots(bars, cfg["pivot_k"])
    if not piv:
        return []
    hatr = atr(bars, cfg["atr_period"])
    pip = pip_size("EURUSD.FX")
    events = []
    for i in range(len(piv)):
        upto = piv[: i + 1]
        ct = piv[i]["confirm_time"]
        atr_at = hatr.reindex([ct], method="ffill").iloc[0]
        atr_val = float(atr_at) if atr_at == atr_at else 0.0
        eq_tol = max(cfg["eq_min_pips"] * pip, cfg["eq_atr_mult"] * atr_val)
        tr = trend_from_pivots(upto, cfg, eq_tol)
        direction = 1 if tr == "BULLISH" else (-1 if tr == "BEARISH" else 0)
        ok = trend_health(upto, direction, cfg, atr_val)
        events.append((ct, "OK" if ok else "WEAK"))
    return events


def combined_trend(bull_h4, bull_d1):
    """Combine two per-bar trend labels (frozen §2.4)."""
    if bull_h4 == "BULLISH" and bull_d1 == "BULLISH":
        return "BULLISH"
    if bull_h4 == "BEARISH" and bull_d1 == "BEARISH":
        return "BEARISH"
    return "NEUTRAL"


def london_window_utc(local_date, cfg):
    """Return (start_utc, end_utc, ok, reason) for the London OR window on a date.

    Fail-closed on DST-transition ambiguity: if the UTC offset at the window
    start differs from the offset at the window end, the window straddles a
    transition -> ineligible.
    """
    tz = ZoneInfo(cfg["session_tz"])
    start_local = datetime(
        local_date.year, local_date.month, local_date.day,
        cfg["or_start_local_hour"], cfg["or_start_local_minute"], tzinfo=tz,
    )
    end_local = start_local + timedelta(minutes=cfg["or_window_minutes"])
    off_start = start_local.utcoffset()
    off_end = end_local.utcoffset()
    if off_start is None or off_end is None or off_start != off_end:
        return (None, None, False, ReasonCode.DST_AMBIGUOUS)
    return (
        start_local.astimezone(timezone.utc),
        end_local.astimezone(timezone.utc),
        True,
        "",
    )


def session_end_utc(local_date, cfg, hour):
    tz = ZoneInfo(cfg["session_tz"])
    end_local = datetime(local_date.year, local_date.month, local_date.day, hour, 0, tzinfo=tz)
    return end_local.astimezone(timezone.utc)


def format_price(value):
    return "{:.5f}".format(float(value))


def format_ts(ts):
    return pd.Timestamp(ts).tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


def compute_signal_id(strategy_version, symbol, direction, generated_ts, entry, stop, target):
    payload = "|".join([
        strategy_version, symbol, direction, generated_ts,
        format_price(entry), format_price(stop), format_price(target),
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def news_eligibility(decision_time_utc, symbol, cfg):
    """Deterministic news risk-filter (frozen spec §12). Never sets direction.

    Returns (ok, reason, detail). Modes:
      * news_required False  -> filter inactive (recorded, does not block).
      * news_required True   -> require fresh, present data; block on high-impact
                                lockout windows for affected currencies.
    """
    base, quote = symbol_currencies(symbol)
    affected = {base, quote}
    if not cfg.get("news_required", False):
        return (True, "", {"active": False, "affected": sorted(affected)})
    events = cfg.get("news_events", None)
    if events is None:
        return (False, ReasonCode.NEWS_DATA_UNAVAILABLE, {"active": True, "affected": sorted(affected)})
    asof = cfg.get("news_asof", None)
    if asof is not None:
        asof_ts = pd.Timestamp(asof)
        if asof_ts.tz is None:
            asof_ts = asof_ts.tz_localize("UTC")
        age_min = (decision_time_utc - asof_ts).total_seconds() / 60.0
        if age_min > cfg["news_max_age_min"]:
            return (False, ReasonCode.NEWS_DATA_STALE, {"active": True, "asof": format_ts(asof_ts)})
    pre = cfg["news_pre_lockout_min"]
    post = cfg["news_post_lockout_min"]
    for ev in events:
        if str(ev.get("impact", "")).lower() != "high":
            continue
        ev_ccy = {str(c).upper() for c in ev.get("currencies", [])}
        if not (ev_ccy & affected):
            continue
        ev_ts = pd.Timestamp(ev["timestamp"])
        if ev_ts.tz is None:
            ev_ts = ev_ts.tz_localize("UTC")
        lo = ev_ts - pd.Timedelta(minutes=pre)
        hi = ev_ts + pd.Timedelta(minutes=post)
        if lo <= decision_time_utc <= hi:
            return (False, ReasonCode.NEWS_LOCKOUT,
                    {"active": True, "event": format_ts(ev_ts), "currencies": sorted(ev_ccy)})
    return (True, "", {"active": True, "affected": sorted(affected)})


# --- core evaluation --------------------------------------------------------

def validate_frame(df, cfg):
    """Whole-frame data validity (frozen spec §13 data semantics)."""
    if df is None or len(df) < cfg["min_history_bars"]:
        return (False, ReasonCode.DATA_INSUFFICIENT)
    idx = df.index
    if not idx.is_monotonic_increasing:
        return (False, ReasonCode.TEMPORAL_GAP)
    if idx.has_duplicates:
        return (False, ReasonCode.TEMPORAL_GAP)
    for col in ("open", "high", "low", "close"):
        if col not in df.columns:
            return (False, ReasonCode.DATA_INSUFFICIENT)
    if df[["open", "high", "low", "close"]].isna().any().any():
        return (False, ReasonCode.DATA_INSUFFICIENT)
    return (True, "")


def evaluate_symbol(symbol, df_in, cfg):
    """Run the full deterministic pipeline for one symbol.

    Returns (signal_series, audit_records, instructions).
    signal_series: per-bar weight to hold DURING each bar (decision.shift(1)).
    """
    ok, reason = validate_frame(df_in, cfg)
    if not ok:
        empty = pd.Series(dtype=float)
        if df_in is not None and len(df_in) > 0:
            empty = pd.Series(0.0, index=df_in.index)
        rec = new_audit(symbol, None, cfg, reason)
        return (empty, [rec], [])

    orig_index = df_in.index

    df = to_utc_index(df_in)
    idx = df.index
    n = len(idx)
    tf = infer_tf_minutes(idx) or cfg["execution_tf_minutes"]
    pip = pip_size(symbol)

    atr_series = atr(df, cfg["atr_period"])
    trend_h4 = map_trend_to_exec(idx, htf_trend_events(df, 240, cfg))
    trend_d1 = map_trend_to_exec(idx, htf_trend_events(df, 1440, cfg))
    health_h4 = map_label_to_exec(idx, htf_health_events(df, 240, cfg), "WEAK")
    health_d1 = map_label_to_exec(idx, htf_health_events(df, 1440, cfg), "WEAK")
    minor = confirmed_pivots(df, cfg["minor_pivot_k"])
    minor_events = [(m["confirm_time"], m["price"], m["kind"]) for m in minor]
    minor_pos = [m["pivot_time"] for m in minor]

    o = df["open"].to_numpy(dtype=float)
    h = df["high"].to_numpy(dtype=float)
    l = df["low"].to_numpy(dtype=float)
    c = df["close"].to_numpy(dtype=float)
    atr_np = atr_series.to_numpy(dtype=float)
    gap_ns = int(tf) * 60_000_000_000
    ts_ns = idx.asi8
    gap_before = np.zeros(n, dtype=bool)
    if n > 1:
        gap_before[1:] = np.diff(ts_ns) > gap_ns
    th4 = trend_h4.to_numpy()
    td1 = trend_d1.to_numpy()
    hh4 = health_h4.to_numpy()
    hd1 = health_d1.to_numpy()

    # Per-day London opening range table (deterministic).
    tz = ZoneInfo(cfg["session_tz"])
    local_dates = idx.tz_convert(tz)
    or_table = {}
    day_keys = pd.Series(local_dates.date, index=range(n))
    unique_days = sorted(set(day_keys.tolist()))
    for day in unique_days:
        start_utc, end_utc, dok, dreason = london_window_utc(day, cfg)
        if not dok:
            or_table[day] = (None, None, False, dreason)
            continue
        in_win = np.asarray((idx >= start_utc) & (idx < end_utc))
        bars_in = int(in_win.sum())
        if bars_in < 1:
            or_table[day] = (None, None, False, ReasonCode.RANGE_INCOMPLETE)
            continue
        expected = max(1, int(cfg["or_window_minutes"] // max(1, tf)))
        if bars_in < expected:
            # contiguity/gap check inside the range window
            or_table[day] = (None, None, False, ReasonCode.RANGE_INCOMPLETE)
            continue
        rh = float(h[in_win].max())
        rl = float(l[in_win].min())
        # width sanity (volatility-normalized) at window end
        end_pos = int(np.where(in_win)[0][-1])
        aval = atr_np[end_pos]
        if aval != aval or aval <= 0:
            or_table[day] = (None, None, False, ReasonCode.RANGE_INVALID)
            continue
        width_atr = (rh - rl) / aval
        if width_atr < cfg["min_width_atr"] or width_atr > cfg["max_width_atr"]:
            or_table[day] = (rh, rl, False, ReasonCode.RANGE_INVALID)
            continue
        or_table[day] = (rh, rl, True, "")

    decision = np.zeros(n, dtype=float)
    audit = []
    instructions = []

    # state machine
    state = "FLAT"
    direction = 0
    boundary = 0.0
    setup_day = None
    breakout_i = -1
    retest_extreme = 0.0
    entry_price = 0.0
    stop = 0.0
    target = 0.0
    expiry_ts = None

    def minor_ref_before(pos_i, want_high, after_time):
        """Most recent confirmed minor swing (high/low) usable at bar pos_i and
        formed at/after `after_time` (the retest). No-lookahead: confirm_time<=t."""
        t = idx[pos_i]
        best = None
        for m_idx in range(len(minor_events)):
            ct, price, kind = minor_events[m_idx]
            if ct > t:
                break
            if minor_pos[m_idx] < after_time:
                continue
            if want_high and kind == "H":
                best = price
            if (not want_high) and kind == "L":
                best = price
        return best

    for i in range(n):
        day = local_dates[i].date()
        aval = atr_np[i]
        rec = new_audit(symbol, idx[i], cfg, ReasonCode.SESSION_INELIGIBLE)
        rec["trend_state"] = combined_trend(th4[i], td1[i])
        rh, rl, rok, rreason = or_table.get(day, (None, None, False, ReasonCode.RANGE_INCOMPLETE))
        rec["range_state"] = "VALID" if rok else rreason

        # ----- manage an open position first (exits) -----
        if state == "IN_POSITION":
            rec["stage"] = "IN_POSITION"
            hit_stop = (l[i] <= stop) if direction > 0 else (h[i] >= stop)
            hit_tp = (h[i] >= target) if direction > 0 else (l[i] <= target)
            local_hour = local_dates[i].hour
            weekday = local_dates[i].weekday()
            friday_exit = (weekday == 4 and local_hour >= cfg["friday_no_new_entry_local_hour"])
            if hit_stop or hit_tp or friday_exit:
                decision[i] = 0.0
                rec["decision"] = "EXIT"
                rec["reason_code"] = "SIGNAL_GENERATED" if hit_tp else "RISK_INVALID"
                rec["price_action_state"] = "EXIT_STOP" if hit_stop else ("EXIT_TP" if hit_tp else "EXIT_TIME")
                state = "FLAT"
                direction = 0
            else:
                decision[i] = float(direction)
                rec["decision"] = "HOLD"
                rec["reason_code"] = "SIGNAL_GENERATED"
            audit.append(rec)
            continue

        # ----- flat / arming: require a well-formed OR and after-window session -----
        if aval != aval:
            rec["reason_code"] = ReasonCode.DATA_INSUFFICIENT
            audit.append(rec)
            continue

        start_utc, end_utc, dok, _ = london_window_utc(day, cfg)
        eligible = dok and (idx[i] >= end_utc) and (idx[i] < session_end_utc(day, cfg, cfg["session_end_local_hour"]))
        if not eligible:
            rec["reason_code"] = ReasonCode.DST_AMBIGUOUS if (not dok) else ReasonCode.SESSION_INELIGIBLE
            # abandon any cross-day setup
            if state != "FLAT" and (setup_day is not None and day != setup_day):
                state = "FLAT"
                direction = 0
            audit.append(rec)
            continue
        if not rok:
            rec["reason_code"] = rreason
            audit.append(rec)
            continue

        trend = combined_trend(th4[i], td1[i])
        buffer = max(cfg["breakout_min_pips"] * pip, cfg["breakout_atr_mult"] * aval)

        # temporal gap during a live setup invalidates it (frozen spec §4.1)
        if state in ("ARMED", "RETESTED") and gap_before[i]:
            state = "FLAT"; direction = 0
            rec["retest_state"] = "GAP"; rec["reason_code"] = ReasonCode.TEMPORAL_GAP
            audit.append(rec)
            continue

        # setup expiry (timeout)
        if state in ("ARMED", "RETESTED") and breakout_i >= 0 and (i - breakout_i) > cfg["setup_max_bars"]:
            state = "FLAT"
            direction = 0
            rec["retest_state"] = "EXPIRED"
            rec["reason_code"] = ReasonCode.RETEST_EXPIRED
            audit.append(rec)
            continue

        if state == "FLAT":
            rec["stage"] = "BREAKOUT"
            if trend == "NEUTRAL":
                rec["reason_code"] = ReasonCode.TREND_NEUTRAL
                audit.append(rec)
                continue
            # Trend Health Gate (frozen spec §2.5): both H4 and D1 must be healthy
            if not (hh4[i] == "OK" and hd1[i] == "OK"):
                rec["trend_health_state"] = "WEAK"
                rec["reason_code"] = ReasonCode.TREND_HEALTH_WEAK
                audit.append(rec)
                continue
            rec["trend_health_state"] = "OK"
            if trend == "BULLISH":
                if c[i] > rh + buffer:
                    state = "ARMED"; direction = 1; boundary = rh
                    setup_day = day; breakout_i = i
                    rec["breakout_state"] = "BULLISH_CONFIRMED"; rec["reason_code"] = ReasonCode.RETEST_PENDING
                elif c[i] > rh:  # closed beyond the boundary but inside the buffer
                    rec["breakout_state"] = "BUFFER_NOT_MET"; rec["reason_code"] = ReasonCode.BREAKOUT_BUFFER_NOT_MET
                elif h[i] > rh:  # only a wick pierced the boundary
                    rec["breakout_state"] = "WICK_ONLY"; rec["reason_code"] = ReasonCode.WICK_ONLY_BREAKOUT
                else:
                    rec["reason_code"] = ReasonCode.BREAKOUT_NOT_CONFIRMED
            else:  # BEARISH (already gated: trend != NEUTRAL here)
                if c[i] < rl - buffer:
                    state = "ARMED"; direction = -1; boundary = rl
                    setup_day = day; breakout_i = i
                    rec["breakout_state"] = "BEARISH_CONFIRMED"; rec["reason_code"] = ReasonCode.RETEST_PENDING
                elif c[i] < rl:
                    rec["breakout_state"] = "BUFFER_NOT_MET"; rec["reason_code"] = ReasonCode.BREAKOUT_BUFFER_NOT_MET
                elif l[i] < rl:
                    rec["breakout_state"] = "WICK_ONLY"; rec["reason_code"] = ReasonCode.WICK_ONLY_BREAKOUT
                else:
                    rec["reason_code"] = ReasonCode.BREAKOUT_NOT_CONFIRMED
            audit.append(rec)
            continue

        # trend flip invalidates a live setup (no reversal trading)
        permit = "BULLISH" if direction > 0 else "BEARISH"
        if trend != permit:
            state = "FLAT"; direction = 0
            rec["reason_code"] = ReasonCode.TREND_CONFLICT
            audit.append(rec)
            continue

        retest_tol = max(cfg["retest_min_pips"] * pip, cfg["retest_atr_mult"] * aval)
        reentry_tol = retest_tol
        max_dev = max(retest_tol, cfg["retest_dev_atr_mult"] * aval)

        if state == "ARMED":
            rec["stage"] = "RETEST"
            # decisive reclaim invalidation (close back inside)
            reclaim = (c[i] < boundary - reentry_tol) if direction > 0 else (c[i] > boundary + reentry_tol)
            if reclaim:
                state = "FLAT"; direction = 0
                rec["retest_state"] = "RECLAIM"; rec["reason_code"] = ReasonCode.RETEST_FAILED
                audit.append(rec); continue
            if direction > 0:
                touched = (l[i] <= boundary + retest_tol)
                overpen = (l[i] < boundary - max_dev)
            else:
                touched = (h[i] >= boundary - retest_tol)
                overpen = (h[i] > boundary + max_dev)
            if overpen:
                state = "FLAT"; direction = 0
                rec["retest_state"] = "OVER_PENETRATION"; rec["reason_code"] = ReasonCode.RETEST_FAILED
                audit.append(rec); continue
            if touched:
                state = "RETESTED"; retest_extreme = (l[i] if direction > 0 else h[i])
                rec["retest_state"] = "HELD"; rec["reason_code"] = ReasonCode.RETEST_PENDING
            else:
                rec["retest_state"] = "PENDING"; rec["reason_code"] = ReasonCode.RETEST_PENDING
            audit.append(rec); continue

        if state == "RETESTED":
            rec["stage"] = "CONFIRM"
            reclaim = (c[i] < boundary - reentry_tol) if direction > 0 else (c[i] > boundary + reentry_tol)
            if reclaim:
                state = "FLAT"; direction = 0
                rec["retest_state"] = "RECLAIM"; rec["reason_code"] = ReasonCode.RETEST_FAILED
                audit.append(rec); continue
            want_high = direction > 0
            ref = minor_ref_before(i, want_high, idx[breakout_i])
            confirmed = False
            if ref is not None:
                confirmed = (c[i] > ref) if direction > 0 else (c[i] < ref)
            if not confirmed:
                rec["price_action_state"] = "PENDING"; rec["reason_code"] = ReasonCode.PRICE_ACTION_NOT_CONFIRMED
                audit.append(rec); continue

            # ---- news eligibility ----
            neok, nereason, nedetail = news_eligibility(idx[i], symbol, cfg)
            rec["news_state"] = "OK" if neok else nereason
            if not neok:
                state = "FLAT"; direction = 0
                rec["reason_code"] = nereason
                audit.append(rec); continue

            # ---- risk: structural stop, max-stop, RR ----
            if direction > 0:
                stop_pad = max(cfg["stop_min_pips"] * pip, cfg["stop_atr_mult"] * aval)
                stop_lvl = min(retest_extreme, boundary) - stop_pad
                entry = c[i]
                stop_dist = entry - stop_lvl
            else:
                stop_pad = max(cfg["stop_min_pips"] * pip, cfg["stop_atr_mult"] * aval)
                stop_lvl = max(retest_extreme, boundary) + stop_pad
                entry = c[i]
                stop_dist = stop_lvl - entry
            rec["price_action_state"] = "CONFIRMED"
            if stop_dist <= 0:
                state = "FLAT"; direction = 0
                rec["risk_state"] = "NO_STRUCTURAL_STOP"; rec["reason_code"] = ReasonCode.STOP_INVALID
                audit.append(rec); continue
            if stop_dist > cfg["max_stop_pips"] * pip:
                state = "FLAT"; direction = 0
                rec["risk_state"] = "STOP_TOO_WIDE"; rec["reason_code"] = ReasonCode.STOP_INVALID
                audit.append(rec); continue
            tgt = entry + cfg["rr_target"] * stop_dist if direction > 0 else entry - cfg["rr_target"] * stop_dist
            planned_rr = abs(tgt - entry) / stop_dist
            if planned_rr < cfg["min_rr"]:
                state = "FLAT"; direction = 0
                rec["risk_state"] = "RR_TOO_LOW"; rec["reason_code"] = ReasonCode.REWARD_RISK_INVALID
                audit.append(rec); continue

            # ---- emit signal + instruction ----
            entry_price = entry; stop = stop_lvl; target = tgt
            expiry_ts = idx[i] + pd.Timedelta(minutes=cfg["entry_valid_bars"] * tf)
            state = "IN_POSITION"
            # apply position from next bar (no-lookahead handled by final shift)
            decision[i] = float(direction)
            rec["risk_state"] = "OK"; rec["decision"] = "ENTER"; rec["reason_code"] = ReasonCode.SIGNAL_GENERATED
            instr = build_instruction(
                symbol, direction, entry_price, stop, target, idx[i], expiry_ts, cfg,
                {
                    "trend_d1": td1[i], "trend_h4": th4[i], "range_high": rh, "range_low": rl,
                    "atr14": float(aval), "boundary": boundary, "retest_extreme": retest_extreme,
                    "minor_swing_ref": ref, "confirm_close": entry_price, "stop_basis": stop_lvl,
                    "rr_planned": planned_rr, "news": nedetail,
                },
                nedetail,
            )
            rec["signal_id"] = instr["signal_id"]
            rec["numeric_evidence"] = {
                "entry_price": entry_price, "stop_loss": stop, "take_profit": target,
                "stop_distance": stop_dist, "rr_planned": planned_rr,
            }
            instructions.append(instr)
            audit.append(rec); continue

        audit.append(rec)

    # Return the executable weight indexed to the ORIGINAL input index (so it
    # aligns with the engine's data_map), shifted one bar for no-lookahead.
    signal = pd.Series(decision, index=orig_index).shift(1).fillna(0.0)
    return (signal, audit, instructions)


def new_audit(symbol, ts, cfg, reason):
    """Build a deterministic per-bar audit record (frozen spec Auditability)."""
    return {
        "evaluation_timestamp": (format_ts(ts) if ts is not None else None),
        "symbol": symbol,
        "strategy_id": STRATEGY_ID,
        "strategy_version": STRATEGY_VERSION,
        "stage": "SESSION",
        "session_state": "",
        "range_state": "",
        "trend_state": "",
        "trend_health_state": "",
        "breakout_state": "",
        "retest_state": "",
        "price_action_state": "",
        "news_state": "",
        "risk_state": "",
        "decision": "NO_TRADE",
        "reason_code": reason,
        "signal_id": None,
        "numeric_evidence": {},
    }


def build_instruction(symbol, direction, entry, stop, target, gen_ts, exp_ts, cfg, evidence, news_detail):
    """Build the versioned trade instruction (frozen spec §8 + bridge §3 fields).

    In-memory / audit only — Phase 1 never writes this to the filesystem bridge.
    """
    dir_str = "LONG" if direction > 0 else "SHORT"
    gen_s = format_ts(gen_ts)
    exp_s = format_ts(exp_ts)
    sid = compute_signal_id(STRATEGY_VERSION, symbol, dir_str, gen_s, entry, stop, target)
    return {
        "schema_version": INSTRUCTION_SCHEMA_VERSION,
        "signal_id": sid,
        "strategy_id": STRATEGY_ID,
        "strategy_version": STRATEGY_VERSION,
        "symbol": symbol,
        "symbol_fs_safe": fs_safe_symbol(symbol),
        "direction": dir_str,
        "entry_price": round(float(entry), 5),
        "stop_loss": round(float(stop), 5),
        "take_profit": round(float(target), 5),
        "risk_fraction": cfg["risk_pct"],
        "generated_timestamp": gen_s,
        "expiration_timestamp": exp_s,
        "evidence_summary": {
            "trend_d1": evidence["trend_d1"],
            "trend_h4": evidence["trend_h4"],
            "range_high": round(float(evidence["range_high"]), 5),
            "range_low": round(float(evidence["range_low"]), 5),
            "atr14": round(float(evidence["atr14"]), 6),
            "boundary": round(float(evidence["boundary"]), 5),
            "retest_extreme": round(float(evidence["retest_extreme"]), 5),
            "minor_swing_ref": (round(float(evidence["minor_swing_ref"]), 5)
                                if evidence["minor_swing_ref"] is not None else None),
            "confirm_close": round(float(evidence["confirm_close"]), 5),
            "stop_basis": round(float(evidence["stop_basis"]), 5),
            "rr_planned": round(float(evidence["rr_planned"]), 4),
        },
        "confidence": 1.0,
        "news_eligibility": news_detail,
        "reason_code": ReasonCode.SIGNAL_GENERATED,
    }


class SignalEngine:
    """Vibe-Trading SignalEngine contract for the Forex Swing-ORB strategy.

    Instantiated with no required args by the backtest runner. `generate` maps
    each symbol's OHLCV frame to a per-bar weight Series in {-1, 0, +1}. The
    versioned trade instructions and the per-bar audit trail are exposed as
    instance attributes for audit output (never written to the bridge).
    """

    def __init__(self, config=None):
        self.config = merged_config(config)
        self.audit = {}
        self.instructions = {}

    def generate(self, data_map):
        """Return {symbol: pd.Series(weight)} for every symbol in data_map."""
        out = {}
        self.audit = {}
        self.instructions = {}
        for symbol in sorted(data_map.keys()):
            df = data_map[symbol]
            signal, audit_records, instrs = evaluate_symbol(symbol, df, self.config)
            out[symbol] = signal
            self.audit[symbol] = audit_records
            self.instructions[symbol] = instrs
        return out
