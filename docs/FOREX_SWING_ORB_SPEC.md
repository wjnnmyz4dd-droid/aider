# Forex Swing Opening-Range-Breakout (Swing-ORB) — Strategy Specification

**Status:** **FROZEN v1.0.0 — DESIGN ONLY (awaiting approval to begin Phase 1).**
No implementation, no backtest-engine changes, no EA, and no MT5 connection is
authorized by this document.
**Strategy version anchor:** `swing_orb.v1.0.0` (the version the first
implementation must stamp into every emitted signal's `strategy_version`).
**Audited platform baseline:** Vibe-Trading `v0.1.12` @ commit `e0b236c` (see
`docs/VIBE_TRADING_PHASE0_AUDIT.md`).

This document defines the *first candidate* strategy. It deliberately fixes a
single, deterministic baseline so a clean, unoptimized result can be produced
before any parameter tuning. Every rule below is reducible to code with no
discretionary or natural-language-only qualification.

---

## 0. Purpose and scope

- Market: **Forex only**. Initial validation symbol: **EURUSD** (canonical
  internal format `EURUSD.FX`; see §12 on the symbol-format hazard).
- Style: **Swing trading.** Expected holding period **several hours to several
  days**. This is explicitly **not** a scalping strategy.
- The strategy produces a **signal / trade instruction**. It does **not** place
  orders. Execution is a later, separate concern (future MT5 EA — see the
  integration map in the audit document).

### 0.1 Freeze status & change control

- This spec is **frozen at v1.0.0**. It is the authoritative reference for Phase 1.
- Once approved, any change to a **rule or a default value** requires a version
  bump (v1.0.0 → v1.0.1 for clarifications/fixes; → v1.1.0 for a rule change),
  recorded in §15 Change log, and the code's `strategy_version` must track it.
- Phase 1 implements **exactly** this baseline — **no optimization, no rule
  additions** beyond what is written here. Anything discovered during
  implementation that requires a rule change is raised as a spec change, not
  silently coded.

---

## 1. Timeframes and anchoring

| Purpose | Timeframe | Notes |
|---|---|---|
| Directional bias | **D1** and **H4** | Both must align (see §3). |
| Opening range, breakout, retest, continuation | **M15** (default execution TF) | Configurable; must be an intraday TF supported by the engine (`1m/5m/15m/30m/1H/4H`). |

All timeframe interactions use **closed/completed bars only**. A forming
(incomplete) bar is never used for any decision (see §12 Failure semantics).

### 1.1 Single-interval backtest constraint → deterministic multi-TF derivation (NORMATIVE)

**Platform fact (audit §E):** the backtest `SignalEngine.generate(data_map)`
receives OHLCV for each symbol at **one** interval only — the run's configured
`interval`. It is **not** handed separate H4/D1 frames. Therefore:

- **Backtest path (authoritative for validation):** the strategy runs at the
  **execution timeframe** (`execution_tf`, default `15m`) and **derives** the H4
  and D1 bias frames by **resampling the execution-TF closed bars** up to H4 and
  D1 inside `generate()`. Resampling is standard OHLC aggregation
  (`open=first, high=max, low=min, close=last`) on right-closed, right-labeled
  calendar buckets, using **only bars whose higher-TF bucket has fully closed**
  (a partially-formed H4/D1 bucket is excluded — fail-closed, §12).
- **Live path (later phase):** the MT5 data layer *can* provide native H4/D1
  bars; the live adapter MAY use native higher-TF bars provided the bias
  definition (§3) yields identical results to the resampled definition. Any
  divergence is a spec change.
- Consequence: `execution_tf` must be a divisor of H4 (so H4/D1 buckets are
  well-formed). `15m`, `30m`, `1H` satisfy this; `5m` also works. The config
  validator must reject an `execution_tf` that does not divide H4.

### 1.2 No-lookahead rule (NORMATIVE)

A decision made from a bar that closes at time *t* may only affect positions
**from the next bar (*t+1*) onward**. Concretely, the signal series returned by
`generate()` for each symbol is computed on closed bars up to and including *t*
and then **shifted forward by one bar** before being returned, so the engine
(which fills at the following bar's open) cannot act on same-bar close
information. No indicator, range, breakout, retest, or confirmation may read a
bar that has not fully closed.

---

## 2. Opening range

- **Anchor session (initial):** the **London session open**.
- **Timezone handling (explicit, deterministic):**
  - The opening range is defined in **Europe/London local time**, then all
    computation is performed on **UTC-timestamped bars**. The London anchor is
    resolved to a UTC window per-day by applying the Europe/London UTC offset in
    effect on that calendar date, via a **tz database (`zoneinfo`)** — never a
    fixed offset.
  - **Daylight-saving:** London is **UTC+0 (GMT)** in winter and **UTC+1 (BST)**
    from the last Sunday of March to the last Sunday of October. If the offset
    for a date/instant is ambiguous or non-existent (the DST-transition hour) →
    day **ineligible → no trade** (§12).
- **Range interval (configurable):** `or_window` — default the **first 60
  minutes** from the London open. Configurable start offset and duration.
- **Expected bar count:** `or_expected_bars = or_window_minutes / tf_minutes`
  (e.g. 60 / 15 = 4 M15 bars). `or_min_bars` defaults to `or_expected_bars`.
- **Range construction (deterministic, closed bars only):**
  - `range_high = max(high)` over the fully-closed bars whose **open timestamp**
    falls inside `[london_open, london_open + or_window)`.
  - `range_low  = min(low)` over the same set of closed bars.
  - The range is **frozen** at the first bar close **after** the window ends; no
    later bar modifies it.
  - If the window yields fewer than `or_min_bars` closed bars → day ineligible →
    no trade.

---

## 3. Directional bias (H4 + D1 alignment)

Computed on **closed** H4 and D1 bars (derived per §1.1), deterministically:

- EMAs on closes: `bias_ema_fast = 20`, `bias_ema_slow = 50` (configurable).
- **Bullish on a timeframe** iff `close > ema_slow` AND `ema_fast > ema_slow`.
- **Bearish on a timeframe** iff `close < ema_slow` AND `ema_fast < ema_slow`.
- **Neutral** otherwise.

Combined bias:
- **BULLISH** iff both D1 and H4 are bullish.
- **BEARISH** iff both D1 and H4 are bearish.
- **NEUTRAL / CONFLICTING** in every other case.

**Fail-closed:** NEUTRAL/CONFLICTING bias → **no trade**. BULLISH permits only
longs; BEARISH permits only shorts. Insufficient warmup for either EMA on either
TF → no trade.

---

## 4. Breakout

- Requires a **completed candle close** beyond the opening-range boundary — a
  wick beyond the boundary alone is **not** a breakout.
  - Long: closed execution-TF candle with `close > range_high + buffer`.
  - Short: closed execution-TF candle with `close < range_low  - buffer`.
- **Minimum breakout distance / volatility buffer (configurable):**
  `buffer = max(breakout_min_pips_in_price, atr_mult * ATR14)` where
  `breakout_min_pips` default = 2 pips and `atr_mult` default = 0.25 on the
  execution-TF ATR(14).
- **Direction gating:** long breakout valid only when bias BULLISH; short only
  when bias BEARISH. Breakouts against bias are ignored.
- **No entry on the breakout candle.** The breakout only *arms* the setup.
- **Setup expiry:** breakout must reach retest + confirmation within
  `setup_max_bars` (default 12 execution-TF bars) or the setup is discarded.

---

## 5. Retest

After a valid breakout, wait for price to **revisit the broken boundary**:

- Long: a completed candle whose **low** reaches `range_high` within `retest_tol`.
- Short: a completed candle whose **high** reaches `range_low` within `retest_tol`.
- **Retest tolerance (configurable):** `retest_tol = max(retest_min_pips_in_price,
  retest_atr_mult * ATR14)`; defaults `retest_min_pips = 2`,
  `retest_atr_mult = 0.15`.
- **Invalidation (fail-closed):** if a **completed** candle **closes decisively
  back inside** the range — past `range_high - reentry_tol` (long) /
  `range_low + reentry_tol` (short), `reentry_tol` default = `retest_tol` — the
  setup is **rejected**.
- Retest evidence uses **completed candles only**.

---

## 6. Continuation confirmation

- **Confirmation count (configurable):** `confirm_bars`, default **1**.
  Requires `confirm_bars` consecutive **completed** candles each satisfying, in
  the trade direction:
  1. **close beyond the boundary again** (long: `close > range_high`; short:
     `close < range_low`), AND
  2. **directional body**: `abs(close-open) >= body_min_frac * (high-low)` with
     `body_min_frac` default 0.5, body sign matching direction (long:
     `close > open`; short: `close < open`), AND
  3. **structural progression**: close beyond the prior confirming/retest
     candle's extreme in the trade direction (higher-close for long, lower-close
     for short).
- If not achieved within the remaining `setup_max_bars` window → setup expires →
  no trade.

---

## 7. Entry

- Enter **only after** breakout (§4) **and** retest (§5) **and** continuation
  confirmation (§6), in the direction permitted by bias (§3).
- **Long and short rules are symmetrical** (mirror of high/low, above/below,
  close>open / close<open). No asymmetry in this baseline; any future asymmetry
  is evidence-justified and version-bumped.
- **Entry reference price:** the **close of the final confirming candle**
  (`entry = confirm_close`). Per §1.2 the position is taken on the **next** bar;
  the backtest fill is that next bar's open adjusted by modeled spread/slippage.
- **Signal / trade-instruction fields (all required):**
  `symbol`, `direction` (`LONG`/`SHORT`), `entry`, `stop`, `target`,
  `timestamp` (UTC, confirming-bar close), `strategy_version`
  (`swing_orb.v1.0.0`), `evidence` (§7.2), `expiration` (§7.3).
- This is a **new instruction schema** (audit §E: no existing model carries
  entry/stop/target/expiration/evidence/version). It normalizes into the
  platform's `OrderIntent` only at the execution boundary (future phase).

### 7.1 Engine-contract mapping (NORMATIVE — how ORB maps onto a per-bar weight)

The backtest engine consumes a **per-bar signal weight in `[-1.0, 1.0]`**, not a
bracket order (audit §E). The multi-step ORB state machine is therefore
implemented **inside** `generate()` as an explicit per-symbol state machine that
emits a weight series:

- States: `FLAT → ARMED (post-breakout) → RETESTED → IN_POSITION → FLAT`.
- While `FLAT`/`ARMED`/`RETESTED`: emitted weight = `0.0`.
- On confirmed entry: emitted weight = `+1.0` (long) or `-1.0` (short) and stays
  until exit.
- **Stop/target are enforced in-`generate()`** by tracking the open position bar
  by bar: when a completed bar's low/high crosses `stop` or `target` (or a §11
  time/weekend rule fires), the weight returns to `0.0` on the exit bar (shifted
  per §1.2). Because the engine models no broker-side SL/TP, the strategy owns
  exit detection. Fixed fractional sizing (§8/§9) is represented by the weight
  magnitude at the engine level and reconciled to true risk-based units in the
  emitted instruction and in live execution.
- **One position per symbol** is structurally guaranteed: the weight is only ever
  `0`, `+1`, or `−1`; the machine never adds to or averages a position (§8).

### 7.2 Evidence schema (required contents)

`evidence` is a structured object (not free text) containing at least:
`range_high`, `range_low`, `or_window` (start/end UTC), `session_date`,
`bias_d1`, `bias_h4`, `breakout_bar_ts`, `breakout_close`, `buffer`,
`atr14`, `retest_bar_ts`, `retest_extreme`, `confirm_bar_ts` (list),
`confirm_closes` (list), `stop_basis`, `rr_planned`.

### 7.3 Expiration rule

`expiration = timestamp + entry_valid_bars * tf_minutes` (`entry_valid_bars`
default 1 — i.e. the instruction is valid only for the immediately following
bar, matching the §1.2 next-bar fill). An instruction consumed after
`expiration`, or whose entry/stop geometry no longer holds, is **stale → no
trade** (§12). This bounds how long a downstream executor may act on a signal.

---

## 8. Risk

- **Initial demo risk:** **0.25% of account equity per trade** (`risk_pct = 0.0025`).
- **One open position per symbol** (hard rule; enforced by §7.1). No adds.
- **Correlated exposure bounded:** `max_correlated_risk_pct` (baseline `0.50%`).
  Correlation grouping is configurable (e.g. USD-legged majors grouped). For the
  **single-symbol EURUSD baseline this bound is not exercised**, but the control
  must exist and be enforced once a second correlated pair is added.
- **Minimum planned reward-to-risk:** **2.0** (`min_rr = 2.0`). A setup that
  cannot meet `min_rr` is **not** traded.
- **Daily and total loss controls (fail-closed):**
  - `daily_max_loss_pct` (baseline `1.0%`): once breached, no new trades for the
    rest of the UTC day.
  - `total_max_loss_pct` / max-drawdown kill (baseline `6.0%`): once breached,
    stop issuing signals until manually reset.
  - Both **fail closed**: if equity/PnL state can't be read reliably → treat as
    breached → no trade.
- **Prohibited:** no averaging down, no martingale, no grid. Sizing is
  fixed-fractional off the structural stop only.

---

## 9. Stop loss

- **Structural stop** beyond the retest invalidation point:
  - Long: `stop = min(retest_low, range_high) - stop_pad`.
  - Short: `stop = max(retest_high, range_low) + stop_pad`.
  - `stop_pad = max(stop_min_pips_in_price, stop_atr_mult * ATR14)`; defaults
    `stop_min_pips = 2`, `stop_atr_mult = 0.25`.
- **Maximum stop-distance protection:** `max_stop_pips` (baseline 60 for EURUSD).
  If the structural stop distance exceeds it → setup **rejected** (no nearer,
  non-structural stop is fabricated).
- **No valid structural stop ⇒ no trade.**
- Risk-based size: `units = (equity * risk_pct) / (stop_distance_price * pip_value)`;
  micro-lot rounding is an execution concern.

---

## 10. Profit management

First candidate uses **(a) a fixed multiple**:

- `target = entry ± rr_target * stop_distance`, `rr_target` default **2.0**
  (= `min_rr`). Long adds, short subtracts.
- **Rationale:** most deterministic, cleanest baseline before optimization.
  Alternatives **(b) higher-TF structure target** and **(c) partial-profit +
  structure trail** are documented as intended *later* options and are
  **explicitly not selected or optimized** in this baseline.

---

## 11. Time / news / data filters

- **Session eligibility:** setups armed only during the configured
  London-anchored window. Outside eligible hours, no new setup is armed.
- **Friday / weekend holding policy:** **no position held over the weekend.** Any
  open position is closed before Friday session end (`friday_close_utc`); no new
  entries after `friday_no_new_entry_utc`. The signal layer must not emit entries
  that would necessarily straddle the weekend. In backtest, the state machine
  (§7.1) force-exits (weight→0) at `friday_close_utc`.
- **High-impact-news lockout:** entries blocked within `news_lockout_min`
  (baseline ±30 min) of a configured high-impact event for the traded
  currencies. **Fail-closed:** if the calendar is unavailable/stale, treat the
  window as locked out. (Backtest requires a supplied event dataset; absent one,
  the run must record that the news filter was inactive — see §13.)
- **Spread rejection:** if current spread `> max_spread_pips` (baseline 2.0),
  reject entry.
- **Stale-data rejection:** if the latest completed bar is older than
  `max_data_age` (a small multiple of the bar interval), reject → no trade.

---

## 12. Failure semantics (all fail-closed → NO TRADE)

Return **no trade** (never a guess) in every one of these:
missing data; incomplete/forming candles where a completed candle is required;
ambiguous session/timezone (incl. DST-transition); insufficient history
(EMA/ATR warmup, or `< or_min_bars` in the range, or an incomplete higher-TF
bucket per §1.1); neutral/conflicting H4/D1 bias; invalid or stale instruction
(expired `expiration` or broken geometry).

> **Platform hazard (audit §F):** the backtest classifier recognizes forex only
> as `EUR/USD` or `EURUSD.FX`, but artifact CSV writing breaks on the `/` in
> `EUR/USD`. **Canonical for run configs is `EURUSD.FX`** (verified working). Any
> unrecognized/misrouted symbol → no trade.

---

## 13. Validation plan (design-only; executed in a later phase)

- **In-sample / out-of-sample separation** with a held-out final period that is
  **never** used for parameter selection.
- **Walk-forward** testing. *Caveat (audit §D/§F):* the platform's built-in
  `walk_forward_analysis` is a **consistency-across-windows** check, not true
  anchored/rolling WFO (no IS/OOS re-fit). Genuine walk-forward is
  **orchestrated externally** (repeat fit-on-IS / test-on-OOS runs).
- **Monte Carlo.** *Caveat:* built-in `monte_carlo_test` is a **trade-order
  permutation** test, not synthetic price paths. Add price-path MC separately if
  required.
- **Bootstrap** CIs. *Caveat:* built-in is **IID** (no block bootstrap).
- **Costs included** where applicable: spread (modeled per-pair), swap (incl.
  Wednesday triple), slippage. **Commission is hard-zero in the FX engine** —
  state this in every result.
- **Breakdowns required:** regime, pair-by-pair, long-vs-short, session, and
  day-of-week.
- **No parameter selection using final holdout data.**
- **Reproducibility:** fixed seeds; the run must record whether the news filter
  had an event dataset (else it is reported inactive, not silently "passed").

---

## 14. Configurable parameters (summary)

| Param | Default | Meaning |
|---|---|---|
| `execution_tf` | `15m` | OR/breakout/retest/confirm TF (must divide H4) |
| `bias_tfs` | `H4,D1` | Bias timeframes (both must align) |
| `bias_ema_fast/slow` | `20 / 50` | Bias EMAs |
| `session_anchor` / `session_tz` | `London` / `Europe/London` | DST-aware anchor |
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
| `daily_max_loss_pct` / `total_max_loss_pct` | `0.01 / 0.06` | Loss kills |
| `stop_pad` | `max(2 pip, 0.25·ATR14)` | Structural stop padding |
| `max_stop_pips` | `60` | Max stop distance (else no trade) |
| `entry_valid_bars` | `1` | Instruction validity horizon (→ `expiration`) |
| `news_lockout_min` | `30` | High-impact news lockout (± min) |
| `max_spread_pips` | `2.0` | Max spread to allow entry |
| `max_data_age` | `1.5×` bar | Stale-data cutoff |
| `friday_no_new_entry_utc` / `friday_close_utc` | configurable | Weekend policy |

`pip` = 0.0001 for non-JPY pairs (0.01 for JPY quote); `*_in_price` denotes the
pip value converted to price units. All defaults are **provisional baseline
values**, chosen to be simple and deterministic — **not** optimized.

---

## 15. Phase 1 acceptance criteria (definition of done)

Phase 1 is complete when **all** hold:

1. A `SignalEngine` (per audit §E `strategy-generate` contract) implements §§2–12
   **exactly**, added via the file/run-dir extension point with **zero changes**
   to Vibe-Trading's engine, loaders, validation, export, swarm, agent, or memory
   subsystems; **Phantom and Titan untouched**; no live/MT5 connection.
2. The engine is **deterministic**: identical inputs → identical signals/trades
   (seeded; no wall-clock/randomness in logic).
3. **No-lookahead (§1.2) is demonstrated** by a test proving a signal at bar *t*
   depends only on data ≤ *t* and takes effect at *t+1*.
4. Every emitted instruction carries all §7 fields with a valid §7.2 evidence
   object and §7.3 expiration; `strategy_version == swing_orb.v1.0.0`.
5. All §12 failure paths return **no trade** (covered by unit tests).
6. A minimal **EURUSD** backtest runs end-to-end through the existing `ForexEngine`
   (symbol `EURUSD.FX`) producing metrics + the platform validation artifacts,
   with spread/swap/slippage modeled and commission noted as zero.
7. Unit tests cover: opening-range determinism, DST/session eligibility, bias
   truth table (incl. fail-closed neutral/conflict), wick-vs-close breakout,
   retest + range-reclaim invalidation, continuation criteria, structural stop &
   max-stop rejection, RR≥2.0 gating, and the state machine's single-position /
   no-averaging guarantee.
8. The repo's official validation (safety gates, syntax check, full pytest suite)
   stays green.

Validation *analysis* (walk-forward/MC/bootstrap/breakdowns, §13) is planned but
its full external orchestration may extend into a Phase 1.x task; the minimal
end-to-end run and the unit-test suite above are the hard gate.

---

## 16. Change log

- **v1.0.0** — Frozen baseline. Adds normative platform-fit rules: single-interval
  backtest constraint & multi-TF derivation (§1.1), no-lookahead (§1.2),
  engine-contract/state-machine mapping (§7.1), evidence schema (§7.2),
  expiration rule (§7.3), Phase 1 acceptance criteria (§15). Canonical symbol set
  to `EURUSD.FX`. Supersedes the pre-freeze `v0.1.0-draft`.
