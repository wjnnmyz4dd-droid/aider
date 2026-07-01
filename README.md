# Phantom

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
| **ORB**          | `phantom/orb.py`          | **Opening-range breakout confirmation layer** |
| Scorer           | `phantom/scorer.py`       | Assembles the 19 components + ORB, applies caps |
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

### 19 components
1. H4 Trend Alignment · 2. D1 Trend Alignment · 3. BOS · 4. CHOCH ·
5. Liquidity Sweep · 6. FVG · 7. Order Block · 8. RSI Confirmation · 9. ATR ·
10. Volatility Ratio · 11. Session Filter · 12. News Filter\* ·
13. Market Regime · 14. Spread Filter\* · 15. Correlation Guard\* ·
16. Exposure Guard\* · 17. RR Validation\* · 18. Prop Compliance\* ·
19. AI Meta Filter   (\* = blocking guard)

## ORB — confirmation layer only

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
| HIGH_VOLATILITY / RANGING w/o breakout / news / range too large or small | **blocked (0)** |

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
