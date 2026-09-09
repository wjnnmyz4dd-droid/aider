# Session Edge Swing-ORB — Phase 1 SignalEngine

Product name **Session Edge Swing-ORB**. Deterministic implementation of the
frozen strategy spec `docs/FOREX_SWING_ORB_SPEC.md` (`swing_orb.v1.4.0`) as a
**Vibe-Trading run-dir SignalEngine**. This directory is the **single source of
truth** for the strategy — there is no parallel implementation. Phase 1 is
**signal generation + qualification + tests + audit only**. No filesystem bridge,
no MT5, no broker, no networking, no Vibe-Trading core edits. Phantom and Titan
are untouched.

## Layout

```
forex_swing_orb/
  run_dir/
    config.json               # example Vibe-Trading forex backtest config (EURUSD.FX)
    code/signal_engine.py      # the deliverable: self-contained SignalEngine
  tests/                       # deterministic pytest suite (synth fixtures)
  README.md
```

`run_dir/code/signal_engine.py` is loaded exactly the way Vibe-Trading's backtest
runner loads a strategy (`<run_dir>/code/signal_engine.py`), and it passes the
runner's AST security scrubber (no decorators, no import-time execution, no
network/file-write/exec in reachable code).

## SignalEngine contract

`class SignalEngine: def generate(self, data_map) -> Dict[str, pd.Series]`

- **Executable signal:** the returned `Series` per symbol is the **per-bar weight
  to hold during that bar**, in `{-1.0, 0.0, +1.0}`:
  - `+1.0` = full long, `-1.0` = full short, `0.0` = flat.
- **Long/short encoding:** direction is the sign of the weight. Long and short
  rules are symmetrical (mirror of high/low, above/below).
- **No look-ahead:** the series is `decision.shift(1)` — a decision taken from the
  bar closing at *t* is only applied from bar *t+1* (the engine fills at the next
  bar's open). Pivots carry a `pivot_k`-bar confirmation latency, so no pivot is
  used before it is confirmable from closed bars.
- **Stop / target / expiry / evidence / reason codes for audit:** these are
  preserved on the engine instance, not in the weight series:
  - `engine.instructions[symbol]` — the versioned trade instructions (frozen spec
    §8 + bridge §3 fields: `schema_version, signal_id, strategy_id,
    strategy_version, symbol, direction, entry_price, stop_loss, take_profit,
    risk_fraction, generated_timestamp, expiration_timestamp, evidence_summary,
    confidence, news_eligibility, reason_code`). Built **in memory only** — never
    written to the filesystem bridge.
  - `engine.audit[symbol]` — a per-bar decision trail (session/range/trend/
    breakout/retest/price-action/news/risk state + a single `reason_code`),
    explaining both why a signal was generated and why a setup produced no trade.
- **`signal_id` is content-derived** (`sha256` of strategy_version|symbol|
  direction|generated_ts|entry|stop|target) — deterministic, no UUID/clock.
- **Signal reset after invalidation/expiration:** the internal state machine
  (`FLAT → ARMED → RETESTED → IN_POSITION → FLAT`) returns to `FLAT` on any
  invalidation (failed/timed-out retest, gap, trend flip, reclaim) or on
  stop/target/time exit; there is **no skip-and-resume** — a fresh breakout is
  required.
- **Duplicate avoidance / one-position-per-symbol:** the weight is only ever
  `0/+1/-1`, so a position is never averaged or duplicated; `signal_id`s are
  unique per setup.

## Determinism & pipeline order

Identical inputs → identical signals, instructions, and `signal_id`s. Evaluation
order (first failure → no trade + reason code): closed/contiguous data → session
& OR validity → H4+D1 trend → **trend health** → completed-candle breakout →
retest → price-action confirmation → news eligibility → risk eligibility →
versioned instruction.

### News (fail-closed by default, spec §12.2)

News is fail-closed: a setup cannot emit an instruction unless news is present,
valid, fresh (verified from an explicit `news_asof`), and outside a high-impact
lockout — else `NEWS_DATA_UNAVAILABLE` / `NEWS_DATA_STALE` / `NEWS_LOCKOUT` and no
trade. Malformed records fail closed (no exception). There is no default eligible-
on-missing mode; the only bypass is the explicit `news_research_bypass=true`
(research-only), which is audited as `RESEARCH_BYPASS`. News never sets direction.

### Exits & downstream ownership (spec §14.1/§14.2)

Exits use dedicated reason codes `EXIT_STOP_LOSS` / `EXIT_TAKE_PROFIT` /
`EXIT_TIME` / `EXIT_INVALIDATED`; a bar touching both stop and target resolves
**stop-first**. Live spread, broker stop-distance, account equity, daily/total
loss limits, and the execution kill switch are **downstream** (future
Titan/execution layer) — the SignalEngine only enforces what is provable from
candle data (e.g. temporal gaps → `TEMPORAL_GAP`). `DATA_STALE`/`DATA_NOT_CLOSED`
are reserved for that downstream layer and are not emitted here.

### Trend Health Gate (spec §2.5)

A deterministic continuation-quality gate that runs after the trend gate and
before breakout, on both H4 and D1. It **rejects weak continuation trades** — it
does **not** predict reversals (no forecasting, probability, AI opinion, or
reversal model). Purely closed-form from the confirmed swing structure + ATR at
decision time: structure integrity (≥ `health_min_confirmed` clean HH/HL),
progress margin (`health_progress_atr`), latest-leg size (`health_min_leg_atr`),
non-weakening (`health_leg_ratio`). Failure → `TREND_HEALTH_WEAK`, no trade;
never changes trade direction.

## Performance

Per symbol the engine precomputes ATR, H4/D1 trend timelines (resample + fractal
pivots + `merge_asof`), and minor pivots once (each ~O(n) or O(n log n)), then
runs a single O(n) forward pass state machine — no repeated full-history rescans
and no unbounded nested loops. Fractal-pivot inner loops are bounded by the pivot
strength `k` (a small constant), not by n.

## Running the tests

```
# uses an environment with pandas/numpy/pytest (e.g. a Vibe-Trading venv)
cd forex_swing_orb/tests && python -m pytest -q
```
