"""PR-2 B1: production market-data history sufficiency + provider time contract.

Proves (from source, no strategy change) that the production market-data wiring
now supplies the frozen SignalEngine enough correctly-timestamped M15 history for
its INTERNAL D1 resample to yield confirmed pivots — i.e. production no longer
mathematically guarantees trend_d1 == NEUTRAL — while the old 300-bar shape did.
No Windows, no MetaTrader5, no networking; deterministic synthetic data."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from forex_swing_orb.live import mt5_client as mc                          # noqa: E402
from forex_swing_orb.live.providers import Mt5MarketDataProvider, SymbolMap  # noqa: E402
from forex_swing_orb.runtime import wiring                                 # noqa: E402
from forex_swing_orb.producer.strategy_adapter import (load_engine_module,  # noqa: E402
                                                       _to_dataframe)

BASE_MONDAY = datetime(2025, 1, 6, 0, 0, tzinfo=timezone.utc)   # a Monday
_DELTAS = [+0.004, +0.004, +0.004, -0.002, -0.002, -0.002]      # 3 up / 3 down, net up


def _levels(n):
    out = [0.0]
    for i in range(1, n):
        out.append(round(out[-1] + _DELTAS[(i - 1) % 6], 6))
    return out


def _gen_m15(n_trading_days, base=1.10000, scale=1.0, spread=0.0010):
    """Weekday-only M15 bars whose per-day D1 aggregate follows an ascending
    zig-zag (staircase) so the D1 resample produces confirmed higher-highs and
    higher-lows under the frozen fractal rules. Weekends are skipped -> real gaps."""
    lv = _levels(n_trading_days)
    rows = []
    day = cal = 0
    while day < n_trading_days:
        d = BASE_MONDAY + timedelta(days=cal)
        cal += 1
        if d.weekday() >= 5:                     # skip Sat/Sun (weekend gap)
            continue
        c = base + lv[day] * scale
        hi, lo = c + spread * scale, c - spread * scale
        op, cl = c - 0.0005 * scale, c + 0.0005 * scale
        for b in range(96):                      # 96 M15 bars = one full UTC day
            t = d + timedelta(minutes=15 * b)
            rows.append((int(t.timestamp()),
                         op if b == 0 else c, hi, lo,
                         cl if b == 95 else c))
        day += 1
    return rows


def _provider(rows, broker="EURUSD", suffix="", history=None):
    fake = mc.FakeMt5Client()
    fake.add_rates(broker, "M15", rows)
    h = history if history is not None else wiring.PRODUCTION_MARKET_HISTORY_BARS
    return Mt5MarketDataProvider(fake, symbol_map=SymbolMap(suffix=suffix), history=h)


_NOW = BASE_MONDAY + timedelta(days=400)


# --------------------------------------------------------------------------- #
# B1 — history sufficiency for the internal D1 resample
# --------------------------------------------------------------------------- #
def test_production_history_constant_is_deep_enough():
    # ~5 trading days/week * 96 M15 bars -> the constant must hold many weeks
    assert wiring.PRODUCTION_MARKET_HISTORY_BARS >= 5000


def test_old_300_bar_shape_guarantees_neutral_d1():
    mod = load_engine_module()
    rows = _gen_m15(70)
    prov = _provider(rows, history=300)
    bars = prov.get_bars("EURUSD.FX", "M15", _NOW)
    df = _to_dataframe(bars)
    assert len(df) <= 300
    # <5 complete D1 bars -> htf_trend_events returns [] -> trend_d1 forced NEUTRAL
    assert mod.htf_trend_events(df, 1440, mod.DEFAULT_CONFIG) == []


def test_new_production_history_enables_non_neutral_d1():
    mod = load_engine_module()
    rows = _gen_m15(70)                                   # ~66 trading days
    prov = _provider(rows)                                # production history depth
    bars = prov.get_bars("EURUSD.FX", "M15", _NOW)
    df = _to_dataframe(bars)

    d1 = mod.htf_bars(df, 1440)
    assert len(d1) >= 55                                  # enough complete D1 bars
    events = mod.htf_trend_events(df, 1440, mod.DEFAULT_CONFIG)
    assert events, "production wiring must no longer guarantee an empty D1 event set"
    labels = {lbl for (_ct, lbl) in events}
    assert "BULLISH" in labels                            # D1 trend CAN be non-neutral


def test_h4_also_resolvable():
    mod = load_engine_module()
    df = _to_dataframe(_provider(_gen_m15(70)).get_bars("EURUSD.FX", "M15", _NOW))
    h4 = mod.htf_bars(df, 240)
    assert len(h4) >= (2 * mod.DEFAULT_CONFIG["pivot_k"] + 1)
    assert mod.htf_trend_events(df, 240, mod.DEFAULT_CONFIG) is not None


def test_weekend_gaps_present_but_d1_still_sufficient():
    mod = load_engine_module()
    df = _to_dataframe(_provider(_gen_m15(70)).get_bars("EURUSD.FX", "M15", _NOW))
    # prove real weekend gaps exist in the M15 index (Fri close -> Mon open > 15m)
    diffs = df.index.to_series().diff().dropna()
    assert (diffs > timedelta(minutes=15)).any(), "expected weekend gaps"
    # yet D1 resample still yields plenty of complete bars
    assert len(mod.htf_bars(df, 1440)) >= 55


def test_insufficient_history_stays_fail_closed_no_fabrication():
    mod = load_engine_module()
    df = _to_dataframe(_provider(_gen_m15(2)).get_bars("EURUSD.FX", "M15", _NOW))
    # 2 trading days -> <5 complete D1 bars -> [] (never padded/forward-filled)
    assert mod.htf_trend_events(df, 1440, mod.DEFAULT_CONFIG) == []


def test_multi_symbol_data_sufficiency_symbol_independent():
    # JPY-class symbol: only data-volume/timestamp handling is in scope here
    mod = load_engine_module()
    rows = _gen_m15(70, base=150.000, scale=100.0, spread=0.0010)
    prov = _provider(rows, broker="USDJPY")
    bars = prov.get_bars("USDJPY.FX", "M15", _NOW)
    assert bars is not None and len(bars.rows) >= 6000
    assert all(r["open_time"].tzinfo == timezone.utc for r in bars.rows)
    df = _to_dataframe(bars)
    assert len(mod.htf_bars(df, 1440)) >= 55             # enough D1 bars regardless of symbol


# --------------------------------------------------------------------------- #
# Provider closed-bar + UTC time contract (B2 boundary; no arithmetic change)
# --------------------------------------------------------------------------- #
def test_provider_drops_forming_bar():
    rows = _gen_m15(3)                                    # 288 rows
    prov = _provider(rows)
    bars = prov.get_bars("EURUSD.FX", "M15", _NOW)
    assert len(bars.rows) == len(rows) - 1               # exactly one (forming) dropped
    assert int(bars.rows[-1]["open_time"].timestamp()) == rows[-2][0]  # newest closed


def test_provider_timestamps_are_utc_aware_and_monotonic():
    bars = _provider(_gen_m15(5)).get_bars("EURUSD.FX", "M15", _NOW)
    times = [r["open_time"] for r in bars.rows]
    assert all(t.tzinfo is not None and t.utcoffset() == timedelta(0) for t in times)
    assert all(b > a for a, b in zip(times, times[1:]))  # strictly increasing


def test_provider_applies_no_timezone_offset():
    # a known epoch must map to the exact UTC instant (no guessed +/- broker hours)
    rows = _gen_m15(2)
    prov = _provider(rows)
    bars = prov.get_bars("EURUSD.FX", "M15", _NOW)
    first_epoch = rows[0][0]
    assert bars.rows[0]["open_time"] == datetime.fromtimestamp(first_epoch, tz=timezone.utc)


def test_provider_none_when_no_rates():
    prov = _provider([])
    assert prov.get_bars("EURUSD.FX", "M15", _NOW) is None
