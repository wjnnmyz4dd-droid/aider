# Phantom

**Status (2026-07-04):** this package (`phantom/`) is **reference material
only**, per `docs/adr/ADR-001-single-authority-architecture.md` (Accepted).
It is not a running authority. The new Phantom system is being rebuilt
from first principles as a single authoritative pipeline (Market Data →
Scanner → Strategy Engine → Scoring Engine → Risk Engine → Compliance
Engine → Execution Validator → MT5 Bridge → Position Manager → Analytics),
one Accepted ADR per stage, starting with ADR-002 (Scanner). Everything
below describes what this package does today and remains accurate as a
description of the reference material — it does not describe the current
authoritative architecture. See `CLAUDE.md` and `.claude/agents/TEAM.md`
for current governance.

A modular FX **scanning & scoring** engine. Phantom evaluates a symbol across
multiple timeframes, produces a composite score, and returns a decision —
`APPROVE` / `WATCHLIST` / `BLOCK`. **It never places orders.** Execution,
if any, lives outside this package and consumes the scanner's decisions.

Pure Python standard library — no third-party dependencies.

## Pipeline

```
market data ─► regime ─► structure ─► guards ─► ORB ─► scorer ─► scanner ─► api
```

| Stage | Module | Responsibility |
|-------|--------|----------------|
| Types            | `phantom/types.py`        | Candle, snapshot, enums, score result |
| Config           | `phantom/config.py`       | Weights, thresholds, session & ORB params |
| Indicators       | `phantom/indicators.py`   | RSI, ATR, EMA, swing pivots |
| Regime engine    | `phantom/regime.py`       | TRENDING/BREAKOUT/RANGING/HIGH_VOLATILITY |
| Structure        | `phantom/structure.py`    | BOS, CHOCH, liquidity sweep, FVG, order block |
| Guards           | `phantom/guards.py`       | News, spread, correlation, exposure, prop, RR, session |
| **ORB**          | `phantom/orb.py`          | **Opening-range breakout engine (+ `/orb/status`)** |
| **Strategies**   | `phantom/strategies/`     | **ORB · Liquidity Reversal · Session Breakout + conflict engine** |
| Analytics        | `phantom/analytics.py`    | Per-strategy performance (real trades only) |
| Scorer           | `phantom/scorer.py`       | Assembles the 18 components, applies caps |
| Scanner          | `phantom/scanner.py`      | Orchestrates, logs, returns the decision |
| Logging sink     | `phantom/logging_sink.py` | JSONL append-only + in-memory recent buffer |
| API              | `phantom/api.py`          | Read-only HTTP; route table incl. `GET /orb/status` |
| App wiring       | `phantom/app.py`          | Shared pipeline state factory |

## Scoring model

Composite score is 0–100.

* **Decision:** `APPROVE ≥ 72`, `WATCHLIST 60–71`, `BLOCK < 60`.
* **NEUTRAL cap 55:** when there is no clear directional bias, or the regime is
  `RANGING`/`NEUTRAL`, the score is capped at 55 (cannot reach APPROVE).
* **Blocking guards** (News, Spread, Correlation, Exposure, RR, Prop
  Compliance) force `BLOCK` when they fail, regardless of the total.

### 18 components
1. H4 Trend Alignment · 2. D1 Trend Alignment · 3. BOS · 4. CHOCH ·
5. Liquidity Sweep · 6. FVG · 7. Order Block · 8. RSI Confirmation ·
9. Volatility Health · 10. Session Filter · 11. News Filter\* ·
12. Market Regime · 13. Spread Filter\* · 14. Correlation Guard\* ·
15. Exposure Guard\* · 16. RR Validation\* · 17. Prop Compliance\* ·
18. ORB Confirmation   (\* = blocking guard)

**De-duplication (vs the earlier 19-component model):**
* **AI Meta Filter removed** — it re-scored trend/structure/momentum already
  counted elsewhere (score inflation). Replaced by an informational **Trade
  Thesis Summary** (`ScoreResult.thesis`) that is logged/displayed but **never
  scored**.
* **ATR + Volatility Ratio → Volatility Health**, a single state-based score:
  `Healthy +5`, `Elevated +3`, `Compressed 0`, `Extreme −5`.
* **Market Regime re-scoped** to *environment classification* (rewards a
  tradeable directional/breakout environment, not the bias direction) so it no
  longer duplicates H4/D1 trend. Weight reduced 10 → 5.

## Strategy layer — signal contributors only

Five institutional-style strategies live under `phantom/strategies/`. **None
opens a trade**; each returns a score influence that the `StrategyEngine`
consolidates into the single **Strategy Confirmation** component (#18).

| Strategy | Fires on | Scoring |
|----------|----------|---------|
| **ORB** (`orb_strategy.py`) | London/NY opening-range breakout + BOS + H4/D1 + regime | +8 / +5 trend / +5 BOS · −10 false breakout |
| **Liquidity Reversal** (`liquidity_reversal.py`) | Sweep beyond swing + rejection wick + CHOCH (regime≠HIGH_VOL, news safe) | Sweep+CHOCH +10 · +OB 5 · +FVG 5 |
| **Session Breakout** (`session_breakout.py`) | Asia-range breakout + BOS + H4 trend + regime | +8 / +5 trend / +5 BOS |
| **Support & Resistance Bounce** (`support_resistance.py`) | Rejection wick at a well-tested S/R zone (≥ min touches) + close back through + H4 trend aligned | +8 / +5 trend / +5 strong zone |
| **Momentum Continuation** (`momentum_continuation.py`) | Sustained ATR expansion + monotonic closes + BOS in trend direction + regime trending (not ranging) | +8 / +5 BOS / +5 strong expansion |

**Consolidation (anti-inflation by construction):**
* Agreeing strategies use `max(score) + small capped confluence bonus` — never a
  raw sum, so shared BOS/trend inputs can't double-count.
* Opposing strategies **cancel to their difference, then dampen** (×0.5) and set
  a `conflict` flag — a conflict can never raise the score.
* The layer's positive contribution is **hard-capped at +18** (the prior ORB
  max), so it can never inflate the score above the previous model.
* Every strategy is **gated behind News / Exposure / Correlation** in the engine
  — no strategy can bypass a protection.

Analytics: `GET /strategies/performance` returns per-strategy Trades / Win Rate /
Profit Factor / P&L plus best & worst, computed from **real recorded trades
only** (`app.record_trade(strategy, pnl)` — fed by the execution layer).

Metrics: `GET /metrics` exposes the same dashboard data in **Prometheus text
exposition format** (v0.0.4) for Grafana — gauges (per-strategy performance, ORB
status, last score) plus counters (scans by decision, strategy signals/conflicts,
ORB confirmed/false-breakout/duplicate-suppressed, guard blocks). Export only —
counters are incremented after each decision and change nothing in the pipeline.

Risk intelligence (advisory, additive): `phantom/risk.py` adapts per-trade risk %
(DEFENSIVE 0.25 / NORMAL 0.50 / AGGRESSIVE 0.75, band [0.25, 1.00]) from rolling
win rate / profit factor / sample and progressive drawdown levels (DD>2 reduce
tier, >3 min, >4 pause, >5 lockout). It never executes and never loosens a
protection — the ComplianceEngine remains authoritative. Fail-safe: any error →
DEFENSIVE/min, risk never auto-increased. Feed live state via
`app.update_account(...)` and `app.record_trade(strategy, pnl)`. Endpoints:
`GET /risk/status`, `GET /risk/analytics`; telemetry in `/metrics`
(`phantom_risk_mode`, `phantom_current_risk_pct`, `phantom_compliance_score`, …).

Live account feed: `POST /account/snapshot` (`balance/equity/margin/free_margin/
positions_open/timestamp`) drives the ComplianceEngine off **live equity**,
updates risk telemetry, and refreshes gauges; `GET /account/status` returns
balance/equity/daily+total DD/trading_allowed/killswitch/daily_lockout/positions/
`last_update_age_seconds`. Fail-safe: once the feed is active, a snapshot older
than `account_feed_ttl_seconds` (60s) marks it stale (`phantom_account_feed_stale`
= 1) and `TradeRouter` **refuses to size**. Compliance stays final authority.

## ORB — opening-range engine

The ORB layer (`phantom/orb.py`) tracks the first 15 minutes after the **London**
(08:00 Europe/London) and **New York** (09:30 America/New_York) opens, records
the range high/low, and detects breakouts and *false* breakouts. It returns an
`ORBDecision` whose `score_impact` the scorer folds into the total. It **cannot
open a trade** — it only nudges or blocks the score:

| Situation | Score impact |
|-----------|-------------:|
| ORB confirmed (close beyond range + regime/news/spread/exposure OK) | **+8** |
| … and H4/D1 trend aligned | **+5** |
| … and BOS aligned | **+5** |
| False breakout (broke then closed back inside) | **−10** |
| HIGH_VOLATILITY / news / spread / exposure / **correlation** / range too large or small | **blocked (0)** |

## Run

```bash
python3 validate.py          # Part-5 validation suite (5 checks)
python3 -m unittest tests.test_pipeline   # unit tests
python3 run_demo.py          # scan a sample symbol, print decision + /orb/status
```

Serve the read-only API:

```python
from phantom.app import create_app
from phantom.api import serve
app = create_app(log_path="phantom.log.jsonl")
serve(app, "127.0.0.1", 8080).serve_forever()
# GET /health  /orb/status  /orb/log  /scan/log
```
