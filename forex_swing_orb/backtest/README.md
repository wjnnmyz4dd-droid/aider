# Session Edge — Tier 1 Historical Replay Harness

**Measurement/orchestration only. Zero strategy authority.** This package answers
exactly one question:

> Does the frozen Session Edge strategy show historical edge under its **own**
> canonical signal logic and its **own** specified static exits?

It does this by driving the **real** production strategy engine
(`run_dir/code/signal_engine.py`) — the same code the live producer runs via
`producer/strategy_adapter.py` — over historical OHLC bars, then reconstructing
trade records from the engine's **own** audit output and delegating all performance
math to the existing `research/portfolio.py` analytics.

## What this is NOT (Tier 1 limitations — read before quoting any number)

- **NOT** a live MT5 simulation.
- **NOT** a full FTMO/compliance simulation (see *News/compliance* below).
- **NOT** a Position Manager simulation — Tier 1 uses the engine's **static**
  SL/TP/time exits; production break-even/profit-lock/structure-trailing is **not**
  modelled.
- **NOT** production fill simulation — results are **GROSS**; no spread, commission,
  slippage, or swap. `COST MODEL = NOT YET PRODUCTION-FIDELITY`.
- **NOT** historical-news-complete — no archived economic calendar exists in-repo,
  so Tier 1 runs with the engine's explicit `news_research_bypass=True`. Every
  report is labelled `STRATEGY-EDGE RESEARCH — HISTORICAL NEWS/COMPLIANCE NOT FULLY
  REPLAYED`. Historical news is never faked and today's news is never used against
  historical prices.

These are Tier 2 concerns and are deliberately out of scope.

## Architecture (no duplicate authority)

```
historical OHLC (data_map: {symbol: DataFrame[open,high,low,close]})
   -> replay.batch_instructions   -> canonical SignalEngine.generate (UNCHANGED)
   -> replay.compare_parity        -> BLOCKING batch-vs-online parity gate
   -> trade_records.build_trades   -> trades from the engine's OWN audit
   -> research.replay_report        -> performance via research.portfolio (measurement tier)
```

- `replay.py` — loads the engine via the production path; batch + expanding-window
  online generation; the parity gate.
- `trade_records.py` — turns the engine's ENTER/EXIT audit into trade dicts in the
  `research.portfolio` schema (`r_multiple`/`pnl`/`mae`/`mfe`/`session`/`symbol`).
- `runner.py` — orchestration; returns trades + parity + labels. **Imports no
  `research`** (production boundary guard); metrics live in
  `research/replay_report.py`.

The harness computes **no** signal, direction, entry, stop, target, session, trend,
breakout, retest, news, risk, or sizing decision itself.

## Parity gate (mandatory)

Before any performance is trusted, `runner.run_tier1(..., run_parity=True)` proves
BATCH (generate once over full history) == ONLINE (expanding-window walk-forward,
mirroring the live `StrategyAdapter`) on `signal_id`, timestamp, session, symbol,
direction, entry, SL, TP, and planned R. Any divergence returns
`status="PARITY_FAILURE"` with the exact first divergence and **withholds all
performance statistics**.

## Exit model (canonical + conservative; recorded on every record)

- `EXIT_STOP_LOSS`   → exit at the engine's **stop** level (R = −1).
- `EXIT_TAKE_PROFIT` → exit at the engine's **target** level (R = +planned).
- `EXIT_TIME` / `EXIT_INVALIDATED` → the engine defines no fill level, so **fail
  closed** to the conservative worst-case bar extreme (LONG: bar low; SHORT: bar
  high).
- Same-bar stop **and** target is resolved by the engine's own worst-case
  precedence (stop-first) and inherited verbatim.

## Historical data required (Tier 1 is BLOCKED on real data)

No historical market data ships in this repo. To measure the real strategy edge on
EURUSD (or any pair), export bars from the **same MT5/broker** you trade and pass
them as a `data_map`.

**Required format** — one CSV per symbol of **completed M15 bars**, UTC, ascending,
no gaps/duplicates, columns: `time,open,high,low,close` (`volume` optional). In
MT5: *View → Symbols → Bars/Ticks → Export*, or an `iCustom`/script `CopyRates`
dump of `PERIOD_M15`. Load into a tz-aware UTC-indexed pandas DataFrame with
lowercase `open/high/low/close` columns; the engine resamples H4/D1 internally.

M15 OHLC is sufficient for **signal** parity. It cannot resolve intrabar SL-vs-TP
ordering, which is why Tier 1 uses the engine's conservative level/worst-case exits;
**M1** (or tick bid/ask) is preferred for a future higher-fidelity fill model (Tier
2).

## Usage

```python
from forex_swing_orb.backtest import runner
from forex_swing_orb.research import replay_report

data_map = {"EURUSD.FX": df_m15_utc}      # your exported bars
result = runner.run_tier1(data_map, {"news_research_bypass": True})
assert result["status"] == "OK"           # parity passed
perf = replay_report.performance_report(result)   # expectancy/PF/DD/MFE/MAE/...
```
