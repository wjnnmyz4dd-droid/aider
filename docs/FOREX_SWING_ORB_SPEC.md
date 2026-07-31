# Forex Swing Opening-Range-Breakout (Swing-ORB) — Strategy Specification

**Status:** DESIGN ONLY — Phase 0 baseline. No implementation, no backtest-engine
changes, no EA, no MT5 connection is authorized by this document.
**Strategy version anchor:** `swing_orb.v0.1.0-draft` (a spec version; no code exists yet).
**Audited platform baseline:** Vibe-Trading `v0.1.12` @ commit `e0b236c` (see
`docs/VIBE_TRADING_PHASE0_AUDIT.md`).

This document defines the *first candidate* strategy. It deliberately fixes a
single, deterministic baseline so a clean, unoptimized result can be produced
before any parameter tuning. Every rule below is intended to be reducible to
code with no discretionary or natural-language-only qualification.

---

## 0. Purpose and scope

- Market: **Forex only**. Initial validation symbol: **EURUSD** (canonical
  internal format `EUR/USD`; see §12 on the symbol-format hazard).
- Style: **Swing trading.** Expected holding period **several hours to several
  days**. This is explicitly **not** a scalping strategy.
- The strategy produces a **signal / trade instruction**. It does **not** place
  orders. Execution is a later, separate concern (future MT5 EA — see the
  integration map in the audit document).

---

## 1. Timeframes and anchoring

| Purpose | Timeframe | Notes |
|---|---|---|
| Directional bias | **D1** and **H4** | Both must align (see §3). |
| Opening range, breakout, retest, continuation | **M15** (default execution TF) | Configurable; must be an intraday TF supported by the engine (`1m/5m/15m/30m/1H/4H`). |

All timeframe interactions use **closed/completed bars only**. A forming
(incomplete) bar is never used for any decision (see §10 Failure semantics).

---

## 2. Opening range

- **Anchor session (initial):** the **London session open**.
- **Timezone handling (must be explicit and deterministic):**
  - The opening range is defined in **Europe/London local time**, then all
    computation is performed on **UTC-timestamped bars**. The London anchor is
    resolved to a UTC window per-day by applying the Europe/London UTC offset in
    effect on that calendar date.
  - **Daylight-saving:** London is **UTC+0 (GMT)** in winter and **UTC+1 (BST)**
    from the last Sunday of March to the last Sunday of October. The engine must
    convert the configured London local window to UTC **using the offset for
    that specific date** (i.e. a proper tz database / `zoneinfo`), never a fixed
    offset. If the offset for a date cannot be resolved unambiguously
    (e.g. the DST-transition hour), the day is **ineligible → no trade** (§10).
- **Range interval (configurable):** `or_window` — default the **first 60
  minutes** from the London open (i.e. 04 bars of M15). Configurable start time
  and duration.
- **Range construction (deterministic, closed bars only):**
  - `range_high = max(high)` over the fully-closed bars whose open timestamp
    falls inside the `or_window`.
  - `range_low  = min(low)` over the same set of closed bars.
  - The range is **frozen** at the first bar close **after** the window ends. No
    later bar modifies `range_high`/`range_low`.
  - If the `or_window` contains fewer closed bars than `or_min_bars`
    (default = expected bar count for the window) → day ineligible → no trade.

---

## 3. Directional bias (H4 + D1 alignment)

Bias is computed on **closed** H4 and D1 bars, deterministically. Baseline
definition (a single, simple, non-optimized rule):

- Let `ema_fast`, `ema_slow` be EMAs on closes with periods
  `bias_ema_fast = 20`, `bias_ema_slow = 50` (configurable).
- **Bullish on a timeframe** iff `close > ema_slow` AND `ema_fast > ema_slow`.
- **Bearish on a timeframe** iff `close < ema_slow` AND `ema_fast < ema_slow`.
- **Neutral** otherwise.

Combined bias:
- **BULLISH** iff both D1 and H4 are bullish.
- **BEARISH** iff both D1 and H4 are bearish.
- **NEUTRAL / CONFLICTING** in every other case (including any single-TF
  neutral, or D1 and H4 disagreeing).

**Fail-closed rule:** a NEUTRAL or CONFLICTING bias → **no trade**. Only a
BULLISH bias permits long setups; only a BEARISH bias permits short setups.

---

## 4. Breakout

- A breakout requires a **completed candle close** beyond the opening-range
  boundary — a wick beyond the boundary alone is **not** a breakout.
  - Long breakout: a closed M15 candle with `close > range_high + buffer`.
  - Short breakout: a closed M15 candle with `close < range_low  - buffer`.
- **Minimum breakout distance / volatility buffer (configurable):** `buffer`.
  Baseline: `buffer = max(breakout_min_pips, atr_mult * ATR14)` where
  `breakout_min_pips` default = 2 pips and `atr_mult` default = 0.25 on the
  execution-TF ATR(14). This filters marginal, spread-width breaks.
- **Direction gating:** a long breakout is only valid when bias is BULLISH; a
  short breakout only when bias is BEARISH. A breakout against bias is ignored.
- **No immediate market entry on the breakout candle.** The breakout only *arms*
  the setup; entry cannot occur on the breakout bar itself (see §6).
- **Setup expiry:** the armed breakout must proceed to retest + confirmation
  within `setup_max_bars` (default 12 execution-TF bars, i.e. 3h on M15) or the
  setup is discarded.

---

## 5. Retest

After a valid breakout, wait for price to **revisit the broken boundary**:

- Long: price trades back **down to** `range_high` within `retest_tol`.
- Short: price trades back **up to** `range_low` within `retest_tol`.
- **Retest tolerance (configurable):** `retest_tol` = `max(retest_min_pips,
  retest_atr_mult * ATR14)`; defaults `retest_min_pips = 2`,
  `retest_atr_mult = 0.15`. A "touch" is confirmed only using **completed
  candles** whose low (long) / high (short) reaches into the tolerance band
  around the broken boundary.
- **Invalidation (fail-closed):** if a **completed** candle **closes decisively
  back inside** the opening range beyond `reentry_tol` (default = `retest_tol`),
  the setup is **rejected** (price reclaimed the range). "Decisively" is defined
  as a close past `range_high - reentry_tol` (for a long) / `range_low +
  reentry_tol` (for a short).
- Retest evidence must use **completed candles only**.

---

## 6. Continuation confirmation

After a valid retest, require **deterministic continuation confirmation** before
entry. No discretionary qualification.

- **Confirmation count (configurable):** `confirm_bars`, default **1**.
  Confirmation requires `confirm_bars` consecutive **completed** candles each
  satisfying the criteria below (in the trade direction).
- **Per-candle criteria (deterministic, baseline):** a confirming candle must
  1. **close beyond the boundary again** in the trade direction
     (long: `close > range_high`; short: `close < range_low`), AND
  2. be a **directional-body candle**: `body >= body_min_frac * range_of_candle`
     with `body_min_frac` default 0.5, and body sign matching the trade
     direction (long: `close > open`; short: `close < open`), AND
  3. **close beyond the prior confirming/retest candle's extreme** in the trade
     direction (a simple structural higher-close / lower-close progression).
- If confirmation is not achieved within the remaining `setup_max_bars` window,
  the setup expires → no trade.

---

## 7. Entry

- Enter **only after** breakout (§4) **and** retest (§5) **and** continuation
  confirmation (§6) have all passed, in the direction permitted by bias (§3).
- **Long and short rules are symmetrical** (mirror of high/low, above/below,
  close>open / close<open). No asymmetry is introduced in this baseline; any
  future asymmetry must be evidence-justified and version-bumped.
- **Entry reference price:** the **close of the final confirming candle**
  (`entry = confirm_close`). Baseline uses this deterministic reference rather
  than a limit that may never fill. (A limit-at-boundary variant is explicitly
  deferred to a later phase.)
- **Signal output object** (the trade instruction) MUST contain, at minimum:
  - `symbol` (e.g. `EUR/USD`)
  - `direction` (`LONG` / `SHORT`)
  - `entry` (price)
  - `stop` (price)
  - `target` (price)
  - `timestamp` (UTC, the confirming-bar close time)
  - `strategy_version` (e.g. `swing_orb.v0.1.0`)
  - `evidence` (structured: range_high, range_low, bias(D1,H4), breakout bar,
    retest bar, confirming bar(s), buffer, ATR, session/date)
  - `expiration` (UTC time after which the instruction is stale/void)
- This is a **new instruction schema** to be defined in a later phase — the
  audited platform has **no** existing model carrying entry/stop/target/
  expiration/evidence/version (see audit §E). The nearest existing type is
  `OrderIntent` (symbol/side/notional/quantity/instrument_type/asset_class),
  which this instruction would normalize *into* at the execution boundary.

---

## 8. Risk

- **Initial demo risk:** **0.25% of account equity per trade** (`risk_pct = 0.0025`).
- **One open position per symbol** (hard rule). No adding to a position.
- **Correlated exposure bounded:** total simultaneous risk across correlated
  pairs must be capped (`max_correlated_risk_pct`, baseline `0.50%`, i.e. ≤ 2
  concurrent correlated positions at 0.25% each). Correlation grouping is
  configurable (e.g. USD-legged majors grouped).
- **Minimum planned reward-to-risk:** **2.0** (`min_rr = 2.0`). A setup whose
  target/stop geometry cannot meet `min_rr` is **not** traded.
- **Daily and total loss controls (fail-closed):**
  - `daily_max_loss_pct` (baseline `1.0%`): once breached, **no new trades**
    for the rest of the UTC day.
  - `total_max_loss_pct` / max drawdown kill (baseline `6.0%`): once breached,
    the strategy stops issuing signals until manually reset.
  - Both controls **fail closed**: if equity/PnL state cannot be read
    reliably, treat as breached → no trade.
- **Prohibited:** **no averaging down, no martingale, no grid.** Position sizing
  is fixed-fractional off the structural stop only.

---

## 9. Stop loss

- **Structural stop** placed **beyond the retest invalidation point**:
  - Long: `stop = min(retest_low, range_high) - stop_pad`.
  - Short: `stop = max(retest_high, range_low) + stop_pad`.
  - `stop_pad` (configurable) = `max(stop_min_pips, stop_atr_mult * ATR14)`;
    defaults `stop_min_pips = 2`, `stop_atr_mult = 0.25`.
- **Maximum stop-distance protection:** `max_stop_pips` (baseline 60 pips for
  EURUSD, configurable). If the structural stop exceeds `max_stop_pips`, the
  setup is **rejected** — the strategy does **not** fabricate a nearer,
  non-structural stop.
- **No valid structural stop ⇒ no trade.** If a deterministic structural stop
  cannot be established from the retest/range geometry, the setup is discarded.
- Position size is derived from `risk_pct` and the stop distance
  (`units = (equity * risk_pct) / (stop_distance_in_price * pip_value)`),
  respecting broker micro-lot rounding at execution time (execution concern).

---

## 10. Profit management

The first candidate uses **(a) a fixed multiple**:

- `target = entry ± rr_target * stop_distance`, with `rr_target` default **2.0**
  (equals `min_rr`). Long adds, short subtracts.
- **Rationale for choosing (a):** it is the most deterministic and the cleanest
  baseline to validate before any optimization. Options **(b) higher-timeframe
  structure target** and **(c) partial-profit + structure trail** are documented
  here as the intended *later* alternatives but are **explicitly not selected or
  optimized in this baseline** (per the contract: "Do not optimize this choice
  before producing a clean baseline").

---

## 11. Time / news / data filters

- **Session eligibility:** setups are armed **only** during the configured
  London-anchored eligibility window (and, later, optionally the London/NY
  overlap). Outside eligible hours, no new setup is armed.
- **Friday / weekend holding policy:** **no position may be held over the
  weekend.** Any open position is flagged for close before the Friday session
  end (`friday_close_utc`, configurable). No new entries after
  `friday_no_new_entry_utc`. (Enforcement is an execution concern; the signal
  layer must not emit entries that would necessarily straddle the weekend.)
- **High-impact-news lockout:** entries are **blocked** within
  `news_lockout_min` (baseline ±30 min) of a configured high-impact event for
  the traded currencies. **Fail-closed:** if the news calendar is unavailable or
  stale, treat the window as locked out for the affected currencies → no trade.
- **Spread rejection:** if current spread `> max_spread_pips` (baseline 2.0 for
  EURUSD), reject entry.
- **Stale-data rejection:** if the latest completed bar is older than
  `max_data_age` (a small multiple of the bar interval), reject → no trade.

---

## 12. Failure semantics (all fail-closed → NO TRADE)

The strategy must return **no trade** (never a guess) in every one of these:

- Missing data.
- Incomplete / still-forming candles where a completed candle is required.
- Ambiguous session or timezone resolution (incl. DST-transition ambiguity).
- Insufficient history (not enough bars for ATR/EMA warmup, or fewer than
  `or_min_bars` in the opening range).
- Conflicting or neutral higher-timeframe bias (§3).
- Invalid or stale execution instruction (expired `expiration`, or geometry that
  no longer holds).

> **Platform hazard to encode (from audit):** the backtest engine's own market
> classifier recognizes forex only as `EUR/USD` or `EURUSD.FX`, while artifact
> writing breaks on the `/` in `EUR/USD`. The strategy/config layer must pick a
> single safe canonical handling (verified working: `EURUSD.FX` for run configs)
> and treat any unrecognized/misrouted symbol as **no trade**. See audit §F.

---

## 13. Validation plan (design-only; to be executed in a later phase)

- **In-sample / out-of-sample separation** with a held-out final period that is
  **never** used for parameter selection.
- **Walk-forward** testing. *Note (audit §D/§F):* the platform's built-in
  `walk_forward_analysis` is a **consistency-across-windows** check, **not** true
  anchored/rolling walk-forward optimization (no IS/OOS re-fit). Genuine
  walk-forward must therefore be **orchestrated externally** (repeated
  fit-on-IS / test-on-OOS runs), not assumed from the built-in tool.
- **Monte Carlo** testing. *Note:* the built-in `monte_carlo_test` is a
  **trade-order permutation** test, not synthetic price-path simulation. Use it
  for path-order robustness and add price-path / parametric MC separately if
  required.
- **Bootstrap** confidence intervals. *Note:* built-in is **IID** bootstrap
  (no block bootstrap) — autocorrelation is not preserved.
- **Costs included** where applicable: spread (modeled per-pair), swap
  (modeled incl. Wednesday triple), slippage (modeled). **Commission is hard-zero
  in the forex engine** — acceptable for spread-cost FX, but must be stated.
- **Breakdowns required:** regime, pair-by-pair, long-vs-short, session, and
  day-of-week.
- **No parameter selection using final holdout data.**

---

## 14. Configurable parameters (summary)

| Param | Default | Meaning |
|---|---|---|
| `execution_tf` | `15m` | Opening-range / breakout / retest / confirm TF |
| `bias_tfs` | `H4,D1` | Bias timeframes (both must align) |
| `bias_ema_fast/slow` | `20 / 50` | Bias EMAs |
| `session_anchor` | `London` | Opening-range session anchor |
| `session_tz` | `Europe/London` | DST-aware tz for the anchor |
| `or_window` | `60m` | Opening-range duration from session open |
| `or_min_bars` | window-derived | Min closed bars to form a range |
| `buffer` | `max(2 pip, 0.25·ATR14)` | Min breakout distance |
| `setup_max_bars` | `12` | Bars allowed breakout→entry |
| `retest_tol` | `max(2 pip, 0.15·ATR14)` | Retest touch tolerance |
| `reentry_tol` | `= retest_tol` | Range-reclaim invalidation band |
| `confirm_bars` | `1` | Continuation confirmation count |
| `body_min_frac` | `0.5` | Min body fraction of confirming candle |
| `risk_pct` | `0.0025` | Risk per trade (0.25%) |
| `min_rr` / `rr_target` | `2.0 / 2.0` | Min and target reward-to-risk |
| `max_correlated_risk_pct` | `0.005` | Correlated exposure cap |
| `daily_max_loss_pct` | `0.01` | Daily loss kill |
| `total_max_loss_pct` | `0.06` | Total loss / drawdown kill |
| `stop_pad` | `max(2 pip, 0.25·ATR14)` | Structural stop padding |
| `max_stop_pips` | `60` | Max stop distance (else no trade) |
| `news_lockout_min` | `30` | High-impact news lockout (± min) |
| `max_spread_pips` | `2.0` | Max spread to allow entry |
| `friday_no_new_entry_utc` / `friday_close_utc` | configurable | Weekend policy |

All defaults are **provisional baseline values**, chosen to be simple and
deterministic — **not** optimized. Optimization is out of scope for Phase 0.
