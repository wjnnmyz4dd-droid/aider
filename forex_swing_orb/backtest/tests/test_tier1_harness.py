"""Tier 1 replay harness — validity tests (HARNESS VALIDITY, not strategy perf).

These prove the harness faithfully drives and measures the REAL frozen engine:
batch-vs-online parity, no-lookahead, determinism, faithful trade reconstruction,
conservative exit pricing, empty history, no episode duplication, signal_id
preservation, session handling, and integration with research.portfolio.

All frames are deterministic synthetic fixtures (forex_swing_orb/tests/synth.py) run
with the explicit news research bypass; NO market data is invented and NO number
here is a strategy-performance claim.
"""

from __future__ import annotations

import pandas as pd
import pytest

from forex_swing_orb.backtest import replay, runner, trade_records

from .conftest import RESEARCH_CONFIG, SYMBOL


def _idx_of(df, iso):
    return df.index.get_loc(pd.Timestamp(iso.replace("Z", "+00:00")))


def _first_signal_index(df, batch, sym=SYMBOL):
    return min(_idx_of(df, s["generated_timestamp"]) for s in batch[sym])


# --- 1. batch produces the expected canonical signal -----------------------
def test_batch_produces_expected_signal(engine_module, golden_bull):
    data, ref = golden_bull
    batch, _ = replay.batch_instructions(engine_module, data, RESEARCH_CONFIG)
    sigs = batch[SYMBOL]
    assert len(sigs) >= 1
    s = sigs[0]
    assert s["direction"] == "LONG"
    assert s["session_id"] == "LONDON"
    assert s["stop_loss"] < s["entry_price"] < s["take_profit"]   # engine geometry


# --- 2. BLOCKING batch-vs-online parity (the acceptance gate) ---------------
def test_batch_vs_online_parity(engine_module, golden_bull):
    data, _ = golden_bull
    df = data[SYMBOL]
    batch, _ = replay.batch_instructions(engine_module, data, RESEARCH_CONFIG)
    first_idx = _first_signal_index(df, batch)
    start = first_idx - 100
    # skipping [0..start) is provably safe: assert batch emits nothing before start
    assert all(_idx_of(df, s["generated_timestamp"]) >= start for s in batch[SYMBOL])
    online = replay.online_instructions(engine_module, data, RESEARCH_CONFIG,
                                        start_index=start)
    ok, first = replay.compare_parity(batch, online)
    assert ok, f"PARITY FAILURE: {first}"
    # and the explicit assert form raises nothing
    replay.assert_parity(batch, online)


# --- 3. no lookahead: mutating bars AFTER the decision cannot change it -----
def test_no_lookahead_future_mutation(engine_module, golden_bull):
    data, _ = golden_bull
    df = data[SYMBOL]
    batch, _ = replay.batch_instructions(engine_module, data, RESEARCH_CONFIG)
    sig = batch[SYMBOL][0]
    ci = _idx_of(df, sig["generated_timestamp"])

    # (a) the signal appears exactly when its confirm bar closes, not before
    before = engine_module.SignalEngine(RESEARCH_CONFIG)
    before.generate({SYMBOL: df.iloc[:ci]})            # data strictly before confirm bar
    assert all(i["generated_timestamp"] != sig["generated_timestamp"]
               for i in before.instructions.get(SYMBOL, []))

    # (b) corrupt EVERY bar after the confirm bar -> the decision is unchanged
    mutated = df.copy()
    tail = mutated.index[ci + 1:]
    for col, val in (("open", 9.0), ("high", 9.5), ("low", 8.5), ("close", 9.0)):
        mutated.loc[tail, col] = val
    mb, _ = replay.batch_instructions(engine_module, {SYMBOL: mutated}, RESEARCH_CONFIG)
    match = [i for i in mb[SYMBOL] if i["generated_timestamp"] == sig["generated_timestamp"]]
    assert len(match) == 1
    for f in ("signal_id", "direction", "entry_price", "stop_loss", "take_profit"):
        assert match[0][f] == sig[f]


# --- 4. deterministic replay -----------------------------------------------
def test_deterministic_replay(golden_bull):
    data, _ = golden_bull
    r1 = runner.run_tier1(data, RESEARCH_CONFIG, run_parity=False)
    r2 = runner.run_tier1(data, RESEARCH_CONFIG, run_parity=False)
    assert r1["trades"] == r2["trades"]
    assert r1["exit_reason_counts"] == r2["exit_reason_counts"]
    assert r1["setup_count"] == r2["setup_count"]


# --- 5. faithful trade-record construction ---------------------------------
def test_trade_record_construction(engine_module, golden_bull):
    data, _ = golden_bull
    batch, engine = replay.batch_instructions(engine_module, data, RESEARCH_CONFIG)
    trades, open_end = trade_records.build_trades(engine_module, engine, data)
    assert len(trades) >= 1 and open_end == []
    t = trades[0]
    for key in ("r_multiple", "pnl", "session", "symbol", "signal_id", "direction",
                "entry", "stop_loss", "take_profit", "exit_reason",
                "exit_price_assumption", "planned_r"):
        assert key in t
    assert isinstance(t["r_multiple"], float)
    # a take-profit episode realizes ~ +planned R at the engine's target level
    if t["exit_reason"] == "EXIT_TAKE_PROFIT":
        assert t["exit_price_assumption"] == "TARGET_LEVEL"
        assert abs(t["r_multiple"] - float(t["planned_r"])) < 0.05


# --- 6. conservative exit pricing (same-bar stop; time worst-case) ----------
class _StubEngine:
    def __init__(self, audit, instructions):
        self.audit = audit
        self.instructions = instructions


def _mini_frame():
    idx = pd.date_range("2024-02-01 08:00", periods=5, freq="15min", tz="UTC")
    return pd.DataFrame({"open": [1.1000] * 5, "high": [1.1006] * 5,
                         "low": [1.0995] * 5, "close": [1.1000] * 5}, index=idx)


def _episode(module, df, exit_reason, same_bar=False):
    fmt = module.format_ts
    enter_ts = fmt(df.index[1])
    exit_ts = fmt(df.index[3])
    instr = {"signal_id": "abc1234567890def", "direction": "LONG",
             "entry_price": 1.1000, "stop_loss": 1.0990, "take_profit": 1.1020,
             "session_id": "LONDON", "generated_timestamp": enter_ts,
             "evidence_summary": {"rr_planned": 2.0}}
    audit = [
        {"decision": "ENTER", "reason_code": module.ReasonCode.SIGNAL_GENERATED,
         "signal_id": "abc1234567890def", "evaluation_timestamp": enter_ts},
        {"decision": "EXIT", "reason_code": exit_reason, "evaluation_timestamp": exit_ts,
         "numeric_evidence": {"same_bar_stop_and_target": same_bar}},
    ]
    return _StubEngine({SYMBOL: audit}, {SYMBOL: [instr]})


def test_same_bar_stop_conservative(engine_module):
    df = _mini_frame()
    eng = _episode(engine_module, df, engine_module.ReasonCode.EXIT_STOP_LOSS, same_bar=True)
    trades, _ = trade_records.build_trades(engine_module, eng, {SYMBOL: df})
    t = trades[0]
    assert t["exit_reason"] == "EXIT_STOP_LOSS"
    assert t["exit_price"] == pytest.approx(1.0990)         # exit at the STOP level
    assert t["exit_price_assumption"] == trade_records.EXIT_AT_STOP
    assert t["r_multiple"] == pytest.approx(-1.0)           # canonical -1R
    assert t["same_bar_stop_and_target"] is True            # engine's flag inherited


def test_time_exit_worst_case(engine_module):
    df = _mini_frame()                                       # bar low = 1.0995
    eng = _episode(engine_module, df, engine_module.ReasonCode.EXIT_TIME)
    trades, _ = trade_records.build_trades(engine_module, eng, {SYMBOL: df})
    t = trades[0]
    assert t["exit_price_assumption"] == trade_records.EXIT_AT_WORST_CASE
    assert t["exit_price"] == pytest.approx(1.0995)         # LONG worst-case = bar low
    assert t["r_multiple"] == pytest.approx((1.0995 - 1.1000) / 0.0010, abs=1e-6)


# --- 7. empty / no-signal history ------------------------------------------
def test_empty_history_no_signals(engine_module):
    import synth
    df = synth.uptrend_frame(days=5)                         # insufficient warmup -> no setup
    data = {SYMBOL: df}
    rep = runner.run_tier1(data, RESEARCH_CONFIG, run_parity=True)
    assert rep["status"] == "OK"
    assert rep["setup_count"] == 0 and rep["trade_count"] == 0
    assert rep["trades"] == []
    assert rep["parity"]["passed"] is True


# --- 8. one episode is not duplicated --------------------------------------
def test_one_episode_not_duplicated(engine_module, golden_bull):
    data, _ = golden_bull
    batch, engine = replay.batch_instructions(engine_module, data, RESEARCH_CONFIG)
    trades, _ = trade_records.build_trades(engine_module, engine, data)
    ids = [t["signal_id"] for t in trades]
    assert len(ids) == len(set(ids))                        # no duplicate episodes
    assert len(trades) <= len(batch[SYMBOL])                # never more trades than signals


# --- 9. signal_id preserved verbatim from the engine instruction -----------
def test_signal_id_preserved(engine_module, golden_bull):
    data, _ = golden_bull
    batch, engine = replay.batch_instructions(engine_module, data, RESEARCH_CONFIG)
    trades, _ = trade_records.build_trades(engine_module, engine, data)
    engine_ids = {i["signal_id"] for i in batch[SYMBOL]}
    for t in trades:
        assert t["signal_id"] in engine_ids                 # harness never re-derives ids


# --- 10. session/DST handling surfaced faithfully --------------------------
def test_session_handling(engine_module, golden_bull):
    data, _ = golden_bull
    df = data[SYMBOL]
    batch, _ = replay.batch_instructions(engine_module, data, RESEARCH_CONFIG)
    for s in batch[SYMBOL]:
        assert s["session_id"] == "LONDON"
        ts = pd.Timestamp(s["generated_timestamp"].replace("Z", "+00:00"))
        # winter London == UTC; OR window is 08:00-09:00 -> entries only AFTER it,
        # on a weekday (engine's session gate), never on Sat/Sun.
        assert ts.tz_convert("UTC").hour >= 9
        assert ts.weekday() < 5


# --- harness stays research-free + carries the research labels --------------
def test_harness_labels_and_no_research_import(golden_bull):
    data, _ = golden_bull
    rep = runner.run_tier1(data, RESEARCH_CONFIG, run_parity=False)
    assert rep["labels"]["cost_model"].startswith("GROSS")
    assert "NOT FULLY REPLAYED" in rep["labels"]["news_compliance"]
    assert "performance" not in rep          # metrics are the measurement tier's job
    # NB: the harness package staying decoupled from the measurement package is
    # enforced by the existing whole-package guard
    # (research/tests::test_production_does_not_import_research), which scans
    # backtest/ too — no duplicate check needed here.


# --- parity gate actually catches divergence -------------------------------
def _instr(sid, ts, direction="LONG", entry=1.1, sl=1.09, tp=1.12, rr=2.0):
    return {"signal_id": sid, "generated_timestamp": ts, "session_id": "LONDON",
            "symbol": SYMBOL, "direction": direction, "entry_price": entry,
            "stop_loss": sl, "take_profit": tp, "evidence_summary": {"rr_planned": rr}}


def test_parity_gate_detects_divergence():
    base = {SYMBOL: [_instr("a" * 16, "2024-01-25T09:15:00Z")]}
    # missing signal online
    ok, first = replay.compare_parity(base, {SYMBOL: []})
    assert not ok and first["kind"] == "COUNT_MISMATCH"
    # changed entry price online
    changed = {SYMBOL: [_instr("a" * 16, "2024-01-25T09:15:00Z", entry=1.2)]}
    ok2, first2 = replay.compare_parity(base, changed)
    assert not ok2 and first2["kind"] == "FIELD_MISMATCH"
    assert "entry_price" in first2["differing_fields"]
    with pytest.raises(replay.ParityError):
        replay.assert_parity(base, changed)


def test_runner_withholds_metrics_on_parity_failure(engine_module, golden_bull, monkeypatch):
    data, _ = golden_bull
    # force an online divergence -> runner must refuse to emit performance
    monkeypatch.setattr(replay, "online_instructions", lambda *a, **k: {SYMBOL: []})
    rep = runner.run_tier1(data, RESEARCH_CONFIG, run_parity=True)
    assert rep["status"] == "PARITY_FAILURE"
    assert "performance" not in rep
