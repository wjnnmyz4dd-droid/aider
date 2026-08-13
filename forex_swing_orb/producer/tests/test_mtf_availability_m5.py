"""PR-3H / M5 — unsafe multi-timeframe alignment (not-applicable proof).

M5 concerns a lower timeframe overriding a higher one, or an unavailable/forming
HTF bar leaking into an alignment decision. In Session Edge there is NO separate
per-timeframe feed reaching the strategy and NO runner-side alignment surface to
misorder:

  * the runner fetches ``required_timeframes`` ONLY for data-health validation and
    feeds the strategy adapter EXACTLY the M15 exec frame (``adapter.evaluate``
    passes ``{symbol: exec_df}`` — one frame, keyed by symbol);
  * the frozen engine derives H4/D1 bias INTERNALLY by resampling that single
    exec frame with CONFIRMED (availability-correct) pivots — the hierarchy lives
    entirely inside the frozen artifact, which this PR does not touch;
  * the adapter only accepts an instruction generated AT the just-closed exec bar,
    so a forming/misaligned bar cannot leak a candidate.

These tests PROVE the single-feed contract at the adapter boundary; NO production
change is made for M5. Deterministic; no networking.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from forex_swing_orb.producer.strategy_adapter import (
    StrategyAdapter, _ENGINE_PATH, _iso)

NOW = datetime(2024, 1, 25, 12, 0, 0, tzinfo=timezone.utc)
SYMBOL = "EURUSD.FX"


class _Bars:
    """Minimal exec-frame stand-in (mirrors the provider Bars surface used by the
    adapter: ``.rows`` list-of-dicts and ``.last``)."""

    def __init__(self, rows):
        self.rows = rows

    @property
    def last(self):
        return self.rows[-1]


def _exec_frame(n=8, step_min=15):
    """A run of ``n`` closed M15 bars ending at NOW - 15m (last CLOSED bar)."""
    start = NOW - timedelta(minutes=step_min * n)
    rows = []
    for i in range(n):
        t = start + timedelta(minutes=step_min * i)
        rows.append({"open_time": t, "open": 1.1000, "high": 1.1010,
                     "low": 1.0990, "close": 1.1005})
    return _Bars(rows)


class _RecordingEngine:
    """Fake engine that records EXACTLY what payload ``generate`` receives and can
    be primed with an instruction to surface for the symbol."""

    def __init__(self, instr=None):
        self.instructions = {}
        self.calls = []
        self._primed = instr

    def generate(self, data_map):
        self.calls.append(data_map)
        self.instructions = {SYMBOL: [self._primed]} if self._primed else {}


# --------------------------------------------------------------------------- #
# single-feed contract: only the M15 exec frame reaches the strategy
# --------------------------------------------------------------------------- #
def test_adapter_feeds_only_the_exec_frame():
    eng = _RecordingEngine()
    StrategyAdapter(eng).evaluate(SYMBOL, _exec_frame())
    assert len(eng.calls) == 1
    payload = eng.calls[0]
    # exactly one frame, keyed by the symbol — no H4/D1/H1 feed is ever passed
    assert set(payload.keys()) == {SYMBOL}


def test_adapter_payload_is_a_single_dataframe():
    eng = _RecordingEngine()
    bars = _exec_frame(n=6)
    StrategyAdapter(eng).evaluate(SYMBOL, bars)
    df = eng.calls[0][SYMBOL]
    assert isinstance(df, pd.DataFrame)
    assert len(df) == len(bars.rows)                 # exactly the exec bars, nothing else
    assert list(df.columns) == ["open", "high", "low", "close"]


def test_no_separate_timeframe_key_in_payload():
    eng = _RecordingEngine()
    StrategyAdapter(eng).evaluate(SYMBOL, _exec_frame())
    payload = eng.calls[0]
    for tf in ("M15", "H1", "H4", "D1", "H4.FX", "D1.FX"):
        assert tf not in payload                      # no timeframe-keyed alignment surface


# --------------------------------------------------------------------------- #
# forming/misaligned-bar guard: only an instruction AT the just-closed bar counts
# --------------------------------------------------------------------------- #
def test_evaluate_rejects_instruction_not_at_last_closed_bar():
    bars = _exec_frame()
    # instruction generated at a DIFFERENT (earlier) bar than the last closed one
    stale = {"signal_id": "x", "generated_timestamp":
             _iso(bars.rows[-2]["open_time"])}
    assert StrategyAdapter(_RecordingEngine(stale)).evaluate(SYMBOL, bars) is None


def test_evaluate_accepts_instruction_at_last_closed_bar():
    bars = _exec_frame()
    instr = {"signal_id": "ok", "generated_timestamp":
             _iso(bars.last["open_time"])}
    out = StrategyAdapter(_RecordingEngine(instr)).evaluate(SYMBOL, bars)
    assert out is instr                               # verbatim, never rebuilt


def test_evaluate_none_when_engine_emits_nothing():
    assert StrategyAdapter(_RecordingEngine(None)).evaluate(SYMBOL, _exec_frame()) is None


# --------------------------------------------------------------------------- #
# structural: the frozen engine derives HTF bias from the SINGLE exec frame
# (higher timeframe is resampled internally, not supplied as a separate feed)
# --------------------------------------------------------------------------- #
def test_frozen_engine_derives_htf_from_exec_frame_internally():
    src = _ENGINE_PATH.read_text()                    # the production frozen-engine path
    # H4 (240m) and D1 (1440m) bias are resampled from the exec df inside the engine
    assert "resample" in src
    assert "htf_trend_events(df, 240" in src and "htf_trend_events(df, 1440" in src
    # generate consumes a single data_map of exec frames (no HTF feed argument)
    assert "def generate(self, data_map)" in src
