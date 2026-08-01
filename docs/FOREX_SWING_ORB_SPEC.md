# Forex Swing Opening-Range-Breakout (Swing-ORB) — Strategy Specification

**Status:** **FROZEN v1.1.0 — DESIGN ONLY (awaiting approval to begin Phase 1).**
No implementation, no backtest-engine changes, no EA, and no MT5 connection is
authorized by this document.
**Strategy version anchor:** `swing_orb.v1.1.0` (the version the first
implementation must stamp into every emitted signal's `strategy_version`).
**Trade-instruction schema version:** `1` (see §8).
**Audited platform baseline:** Vibe-Trading `v0.1.12` @ commit `e0b236c` (see
`docs/VIBE_TRADING_PHASE0_AUDIT.md`).

This document defines the *first candidate* strategy. It deliberately fixes a
single, deterministic baseline so a clean, unoptimized result can be produced
before any parameter tuning. Every rule below is reducible to code with no
discretionary or natural-language-only qualification.

---

## 0. Purpose and scope

- Market: **Forex only**. Initial validation symbol: **EURUSD** (canonical
  internal format `EURUSD.FX`; see §13 on the symbol-format hazard).
- Style: **Swing trading.** Expected holding period **several hours to several
  days**. This is explicitly **not** a scalping strategy.
- The strategy produces a **signal / trade instruction**. It does **not** place
  orders (see §0.2 Execution boundary).

### 0.1 Freeze status & change control

- This spec is **frozen at v1.1.0**. It is the authoritative reference for Phase 1.
- Once approved, any change to a **rule or a default value** requires a version
  bump (patch `v1.1.x` for clarifications/fixes; minor `v1.y.0` for a rule or
  schema change), recorded in §17 Change log, and the code's `strategy_version`
  must track it.
- Phase 1 implements **exactly** this baseline — **no optimization, no rule
  additions** beyond what is written here. Anything discovered during
  implementation that requires a rule change is raised as a spec change, not
  silently coded.

### 0.2 Execution boundary (NORMATIVE)

- The Swing-ORB `SignalEngine` **generates trade instructions only** (§8). It
  performs **research, qualification, and signal formation** and nothing else.
- It **does not** connect to, authenticate with, send orders to, modify orders
  on, or read live account state from **MT5 or any broker**. It performs **no**
  network I/O to any execution venue.
- The instruction it emits is a **passive data object**. Whether, when, and how
  an instruction is ever executed is the sole responsibility of a **separate,
  later execution layer** (the future Titan MT5 EA), which is out of scope for
  this document and for Phase 1.
- This boundary is a **frozen invariant**: no Phase 1 code may cross it.

---

## 1. Timeframes and anchoring

| Purpose | Timeframe | Notes |
|---|---|---|
| Directional bias | **D1** and **H4** | Both must align (see §3). |
| Opening range, breakout, retest, continuation | **M15** (default execution TF) | Configurable; must be an intraday TF supported by the engine (`1m/5m/15m/30m/1H/4H`). |

All timeframe interactions use **closed/completed bars only**. A forming
(incomplete) bar is never used for any decision (see §13 Failure semantics).

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
  (a partially-formed H4/D1 bucket is excluded — fail-closed, §13).
- **Live path (later phase):** the MT5 data layer *can* provide native H4/D1
  bars; the live adapter MAY use native higher-TF bars provided the bias
  definition (§3) yields identical results to the resampled definition. Any
  divergence is a spec change.
- Consequence: `execution_tf` must be a divisor of H4. `5m`, `15m`, `30m`, `1H`
  satisfy this. The config validator must reject an `execution_tf` that does not
  divide H4.

### 1.2 No-lookahead rule (NORMATIVE)

A decision made from a bar that closes at time *t* may only affect positions
**from the next bar (*t+1*) onward**. The signal series returned by `generate()`
for each symbol is computed on closed bars up to and including *t* and then
**shifted forward by one bar** before being returned, so the engine (which fills
at the following bar's open) cannot act on same-bar close information. No
indicator, range, breakout, retest, or confirmation may read a bar that has not
fully closed.

---

## 2. Opening range (FROZEN — exact window, timezone, DST)

- **Session anchor (FROZEN):** the **London session open at 08:00 local time**.
- **Timezone (FROZEN):** **`Europe/London`** (IANA tz database), resolved with
  `zoneinfo`. No fixed numeric offset is ever hard-coded.
- **Opening-range window (FROZEN default):** the **first 60 minutes** from the
  London open, i.e. the local clock interval **`[08:00, 09:00)` Europe/London**.
  The 60-minute duration and 08:00 start are configurable (`or_start_local`,
  `or_window`) but the frozen baseline is 08:00–09:00 London.
- **Daylight-saving handling (FROZEN, explicit):** the local window is converted
  to UTC **per calendar date** using the Europe/London offset in effect that day:

  | Period | London offset | Range window in **UTC** |
  |---|---|---|
  | Winter (GMT) | UTC+0 | **08:00–09:00 UTC** |
  | Summer (BST, last Sun Mar → last Sun Oct) | UTC+1 | **07:00–08:00 UTC** |

  The DST boundary is taken from `zoneinfo`, not from a hard-coded date. If the
  offset for a date/instant is **ambiguous or non-existent** (a DST-transition
  hour) → the day is **ineligible → no trade** (§13).
- **Expected bar count:** `or_expected_bars = or_window_minutes / tf_minutes`
  (e.g. 60 / 15 = 4 M15 bars). `or_min_bars` defaults to `or_expected_bars`.
- **Range construction (deterministic, closed bars only):**
  - `range_high = max(high)` over the fully-closed bars whose **open timestamp**
    falls inside the UTC window above.
  - `range_low  = min(low)` over the same set of closed bars.
  - The range is **frozen** at the first bar close **after** the window ends; no
    later bar modifies it.
  - Fewer than `or_min_bars` closed bars in the window → day ineligible → no trade.

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

## 5. Retest contract

After a valid breakout, price must **revisit the broken boundary** and hold it.
The following four states are **deterministic and mutually exclusive**; evidence
uses **completed candles only**.

- **Valid retest.** A completed candle whose retest extreme reaches the boundary
  zone **without** over-penetrating:
  - Long: candle `low <= range_high + retest_tol` **and** `low >= range_high - max_retest_deviation`.
  - Short: candle `high >= range_low - retest_tol` **and** `high <= range_low + max_retest_deviation`.
  - i.e. the pullback must *touch* within `retest_tol` of the boundary but must
    not pierce deeper than `max_retest_deviation` into the range, and the candle
    must **not** close decisively back inside the range (see invalidation).
- **Failed retest (setup invalidated → no trade).** Any of:
  1. **Over-penetration:** the retest extreme pierces beyond
     `max_retest_deviation` into the range
     (long: `low < range_high - max_retest_deviation`;
     short: `high > range_low + max_retest_deviation`).
  2. **Decisive reclaim:** a completed candle **closes** back inside the range
     past `range_high - reentry_tol` (long) / `range_low + reentry_tol` (short).
- **Timeout (setup expires → no trade).** No valid retest occurs within
  `setup_max_bars` execution-TF bars measured from the breakout candle close.
- **Maximum retest deviation (configurable):** `max_retest_deviation =
  max(retest_tol, retest_dev_atr_mult * ATR14)`, default `retest_dev_atr_mult
  = 0.5`. This caps how far the pullback may go before the breakout is treated as
  failed rather than a healthy retest.
- **Retest touch tolerance (configurable):** `retest_tol =
  max(retest_min_pips_in_price, retest_atr_mult * ATR14)`; defaults
  `retest_min_pips = 2`, `retest_atr_mult = 0.15`.
- **Reentry tolerance (configurable):** `reentry_tol` default = `retest_tol`.

**Invalidation rules (consolidated).** A setup is invalidated (→ no trade) on the
first of: over-penetration, decisive reclaim, bias flip to non-permitting (§3),
or timeout. Once invalidated, the setup is discarded — it cannot be revived by a
later touch; a fresh breakout is required.

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
     candle's extreme in the trade direction.
- If not achieved within the remaining `setup_max_bars` window → setup expires →
  no trade.

---

## 7. Entry

- Enter **only after** breakout (§4) **and** valid retest (§5) **and**
  continuation confirmation (§6), in the direction permitted by bias (§3).
- **Long and short rules are symmetrical** (mirror of high/low, above/below,
  close>open / close<open). No asymmetry in this baseline; any future asymmetry
  is evidence-justified and version-bumped.
- **Entry reference price:** the **close of the final confirming candle**
  (`entry_price = confirm_close`). Per §1.2 the position is taken on the **next**
  bar; the backtest fill is that next bar's open adjusted by modeled
  spread/slippage.
- On confirmed entry the engine emits a **Trade Instruction** (§8).

### 7.1 Engine-contract mapping (NORMATIVE — ORB state machine onto a per-bar weight)

The backtest engine consumes a **per-bar signal weight in `[-1.0, 1.0]`**, not a
bracket order (audit §E). The multi-step ORB is implemented **inside**
`generate()` as an explicit per-symbol state machine emitting a weight series:

- States: `FLAT → ARMED (post-breakout) → RETESTED → IN_POSITION → FLAT`.
- While `FLAT`/`ARMED`/`RETESTED`: weight = `0.0`.
- On confirmed entry: weight = `+1.0` (long) / `-1.0` (short), held until exit.
- **Stop/target enforced in-`generate()`**: when a completed bar's low/high
  crosses `stop_loss` or `take_profit` (or a §12 time/weekend rule fires), the
  weight returns to `0.0` on the exit bar (shifted per §1.2). The engine models
  no broker-side SL/TP, so the strategy owns exit detection.
- **One position per symbol** is structurally guaranteed: weight is only ever
  `0`, `+1`, or `−1`; the machine never adds to or averages a position (§9).

---

## 8. Trade Instruction Contract v1 (versioned schema)

Every qualified setup emits **one** Trade Instruction — a passive, self-describing
data object (§0.2). The schema is **versioned** (`instruction_schema_version = 1`);
any field change bumps this version and the spec version. All timestamps are
**UTC, ISO-8601**. All prices are in the symbol's quote currency.

| Field | Type | Required | Meaning |
|---|---|---|---|
| `instruction_schema_version` | int | yes | Schema version (=`1`). |
| `signal_id` | string | yes | **Deterministic** id (see below) — no randomness. |
| `strategy_version` | string | yes | `swing_orb.v1.1.0`. |
| `symbol` | string | yes | Canonical `EURUSD.FX` (§13). |
| `direction` | enum | yes | `LONG` / `SHORT`. |
| `entry_price` | float | yes | Reference entry (§7) = final confirming close. |
| `stop_loss` | float | yes | Structural stop (§10). |
| `take_profit` | float | yes | Fixed-2R target (§11). |
| `generated_timestamp` | string (UTC ISO-8601) | yes | Confirming-bar close time. |
| `expiration_timestamp` | string (UTC ISO-8601) | yes | Validity horizon (see §8.2). |
| `evidence_summary` | object | yes | Structured decision trail (§8.1). |
| `confidence` | float in [0,1] | optional | See §8.3. |

- **`signal_id` (deterministic):**
  `signal_id = sha256("{strategy_version}|{symbol}|{direction}|{generated_timestamp}|{entry_price}|{stop_loss}|{take_profit}")[:16]`.
  It is a pure function of the instruction contents — **no UUIDs, no clock, no
  randomness** — so identical inputs reproduce identical ids (supports §16
  repeatability).

### 8.1 `evidence_summary` (required contents)

A structured object (not free text) with at least: `range_high`, `range_low`,
`or_window_utc` (start/end), `session_date`, `bias_d1`, `bias_h4`,
`breakout_bar_ts`, `breakout_close`, `buffer`, `atr14`, `retest_bar_ts`,
`retest_extreme`, `max_retest_deviation`, `confirm_bar_ts` (list),
`confirm_closes` (list), `stop_basis`, `rr_planned`, `filters_passed`
(session/news/spread/stale flags).

### 8.2 Expiration

`expiration_timestamp = generated_timestamp + entry_valid_bars * tf_minutes`
(`entry_valid_bars` default 1 — valid only for the immediately following bar,
matching the §1.2 next-bar fill). An instruction consumed after
`expiration_timestamp`, or whose geometry no longer holds, is **stale → no
trade** (§13).

### 8.3 `confidence`

The v1 baseline is a **deterministic, rule-based** qualifier: a setup either
passes every gate or is not emitted. There is **no graded/probabilistic score**
in v1. For forward compatibility the field is emitted as a fixed
`confidence = 1.0` for any instruction that clears all gates (equivalently it may
be omitted). A graded confidence model is explicitly **deferred**; introducing
one is a schema/version change.

---

## 9. Risk — Frozen Version-1 policy

The following are **frozen invariants** for v1 (changing any is a version bump):

- **Risk per trade:** **0.25% of account equity** (`risk_pct = 0.0025`).
- **One open position per symbol** (hard rule; enforced by §7.1).
- **Fixed reward-to-risk target:** **2.0R** (`rr_target = 2.0`, `min_rr = 2.0`);
  a setup that cannot meet 2.0R is **not** traded.
- **No scaling** (no partial entries, no partial exits in v1).
- **No pyramiding** (never add to a winner).
- **No averaging down** (never add to a loser).
- **No martingale / no grid** (size never increases after a loss).
- **Advanced exits are explicitly deferred:** no trailing stop, no break-even
  move, no structure/HTF target, no time-based scale-out in v1. Exit is strictly
  **stop_loss or take_profit** (or a §12 time/weekend/failure force-exit).
- **Correlated exposure bound:** `max_correlated_risk_pct` (baseline `0.50%`).
  Not exercised by the single-symbol EURUSD baseline, but the control must exist
  and be enforced once a second correlated pair is added.
- **Daily and total loss controls (fail-closed):** `daily_max_loss_pct` (`1.0%`)
  halts new trades for the rest of the UTC day; `total_max_loss_pct` (`6.0%`)
  halts new signals until manual reset. If equity/PnL state cannot be read
  reliably → treat as breached → no trade.

Position size is fixed-fractional off the structural stop only:
`units = (equity * risk_pct) / (stop_distance_price * pip_value)`.

---

## 10. Stop loss

- **Structural stop** beyond the retest invalidation point:
  - Long: `stop_loss = min(retest_low, range_high) - stop_pad`.
  - Short: `stop_loss = max(retest_high, range_low) + stop_pad`.
  - `stop_pad = max(stop_min_pips_in_price, stop_atr_mult * ATR14)`; defaults
    `stop_min_pips = 2`, `stop_atr_mult = 0.25`.
- **Maximum stop-distance protection:** `max_stop_pips` (baseline 60 for EURUSD).
  If the structural stop distance exceeds it → setup **rejected** (no nearer,
  non-structural stop is fabricated).
- **No valid structural stop ⇒ no trade.**

---

## 11. Profit management (frozen: fixed multiple)

- `take_profit = entry_price ± rr_target * stop_distance`, `rr_target` **2.0**.
  Long adds, short subtracts.
- **Rationale:** most deterministic, cleanest baseline before optimization.
  Alternatives **(b) higher-TF structure target** and **(c) partial-profit +
  structure trail** are documented as intended *later* options and are
  **explicitly deferred** (see §9 advanced exits).

---

## 12. Time / news / data filters

- **Session eligibility:** setups armed only during the configured
  London-anchored window. Outside eligible hours, no new setup is armed.
- **Friday / weekend holding policy:** **no position held over the weekend.** Any
  open position is closed before Friday session end (`friday_close_utc`); no new
  entries after `friday_no_new_entry_utc`. The signal layer must not emit entries
  that would necessarily straddle the weekend. In backtest, the state machine
  (§7.1) force-exits at `friday_close_utc`.
- **High-impact-news lockout:** entries blocked within `news_lockout_min`
  (baseline ±30 min) of a configured high-impact event for the traded
  currencies. **Fail-closed:** if the calendar is unavailable/stale, treat the
  window as locked out. In backtest, absent a supplied event dataset the run
  must **record the news filter as inactive** (never silently "passed", §14).
- **Spread rejection:** if current spread `> max_spread_pips` (baseline 2.0),
  reject entry.
- **Stale-data rejection:** if the latest completed bar is older than
  `max_data_age` (a small multiple of the bar interval), reject → no trade.

---

## 13. Failure semantics (all fail-closed → NO TRADE)

Return **no trade** (never a guess) in every one of these:
missing data; incomplete/forming candles where a completed candle is required;
ambiguous session/timezone (incl. DST-transition); insufficient history
(EMA/ATR warmup, `< or_min_bars` in the range, or an incomplete higher-TF bucket
per §1.1); neutral/conflicting H4/D1 bias; failed/timed-out retest (§5); no valid
structural stop (§10); RR below 2.0 (§11); any filter failure (§12); invalid or
stale instruction (expired `expiration_timestamp` or broken geometry).

> **Platform hazard (audit §F):** the backtest classifier recognizes forex only
> as `EUR/USD` or `EURUSD.FX`, but artifact CSV writing breaks on the `/` in
> `EUR/USD`. **Canonical for run configs is `EURUSD.FX`** (verified working). Any
> unrecognized/misrouted symbol → no trade.

---

## 14. Validation plan (design-only; executed in a later phase)

- **In-sample / out-of-sample separation** with a held-out final period that is
  **never** used for parameter selection.
- **Walk-forward** testing. *Caveat (audit §D/§F):* the platform's built-in
  `walk_forward_analysis` is a **consistency-across-windows** check, not true
  anchored/rolling WFO. Genuine walk-forward is **orchestrated externally**.
- **Monte Carlo.** *Caveat:* built-in `monte_carlo_test` is a **trade-order
  permutation** test, not synthetic price paths.
- **Bootstrap** CIs. *Caveat:* built-in is **IID** (no block bootstrap).
- **Costs included:** spread (modeled per-pair), swap (incl. Wednesday triple),
  slippage. **Commission is hard-zero in the FX engine** — state in every result.
- **Breakdowns required:** regime, pair-by-pair, long-vs-short, session, and
  day-of-week.
- **No parameter selection using final holdout data.**
- **Reproducibility:** fixed seeds; record whether the news filter had an event
  dataset (else reported inactive, not silently "passed").

---

## 15. Configurable parameters (summary)

| Param | Default | Meaning |
|---|---|---|
| `execution_tf` | `15m` | OR/breakout/retest/confirm TF (must divide H4) |
| `bias_tfs` | `H4,D1` | Bias timeframes (both must align) |
| `bias_ema_fast/slow` | `20 / 50` | Bias EMAs |
| `session_anchor` / `session_tz` | `London` / `Europe/London` | DST-aware anchor |
| `or_start_local` / `or_window` | `08:00` / `60m` | Opening-range start & duration |
| `or_min_bars` | window-derived | Min closed bars to form a range |
| `buffer` | `max(2 pip, 0.25·ATR14)` | Min breakout distance |
| `setup_max_bars` | `12` | Bars allowed breakout→entry |
| `retest_tol` | `max(2 pip, 0.15·ATR14)` | Retest touch tolerance |
| `max_retest_deviation` | `max(retest_tol, 0.5·ATR14)` | Max pullback penetration |
| `reentry_tol` | `= retest_tol` | Range-reclaim invalidation band |
| `confirm_bars` | `1` | Continuation confirmation count |
| `body_min_frac` | `0.5` | Min body fraction of confirming candle |
| `risk_pct` | `0.0025` | Risk per trade (0.25%) |
| `min_rr` / `rr_target` | `2.0 / 2.0` | Min and target reward-to-risk |
| `max_correlated_risk_pct` | `0.005` | Correlated exposure cap |
| `daily_max_loss_pct` / `total_max_loss_pct` | `0.01 / 0.06` | Loss kills |
| `stop_pad` | `max(2 pip, 0.25·ATR14)` | Structural stop padding |
| `max_stop_pips` | `60` | Max stop distance (else no trade) |
| `entry_valid_bars` | `1` | Instruction validity horizon (→ expiration) |
| `news_lockout_min` | `30` | High-impact news lockout (± min) |
| `max_spread_pips` | `2.0` | Max spread to allow entry |
| `max_data_age` | `1.5×` bar | Stale-data cutoff |
| `friday_no_new_entry_utc` / `friday_close_utc` | configurable | Weekend policy |

`pip` = 0.0001 for non-JPY pairs (0.01 for JPY quote); `*_in_price` denotes the
pip value converted to price units. All defaults are **provisional baseline
values**, deterministic and **not** optimized.

---

## 16. Phase 1 acceptance criteria (definition of done)

Phase 1 is complete when **all** hold:

1. **Deterministic outputs.** Identical inputs → identical signals, instructions,
   and trades. No wall-clock, RNG, or environment dependence in strategy logic;
   `signal_id` is content-derived (§8).
2. **No look-ahead bias.** A test proves a signal at bar *t* depends only on data
   ≤ *t* and takes effect at *t+1* (§1.2).
3. **Repeatable results.** Re-running the same config on the same data (same
   machine or another) yields byte-identical signals/metrics (fixed seeds; no
   nondeterministic ordering).
4. **Fail-closed behavior.** Every §13 failure path returns **no trade**, covered
   by unit tests.
5. **Complete audit trail.** Every emitted instruction carries all §8 fields with
   a valid §8.1 `evidence_summary`; every *rejected* setup records a structured
   reason (which gate failed) so a run's decisions are fully reconstructable.
6. **No changes to Vibe-Trading core subsystems.** The `SignalEngine` is added
   via the file/run-dir extension point (audit §E) with **zero** modifications to
   Vibe-Trading's engine, loaders, validation, export, swarm, agent, or memory
   subsystems; **Phantom and Titan untouched**; the §0.2 execution boundary is
   never crossed. The repo's official validation (safety gates, syntax check,
   full pytest suite) stays green.
7. A minimal **EURUSD** backtest runs end-to-end through the existing `ForexEngine`
   (symbol `EURUSD.FX`) producing metrics + platform validation artifacts, with
   spread/swap/slippage modeled and commission noted as zero.
8. Unit tests cover: opening-range determinism, DST/session eligibility, bias
   truth table (incl. fail-closed neutral/conflict), wick-vs-close breakout,
   the §5 retest contract (valid / failed / timeout / over-penetration /
   reclaim), continuation criteria, structural stop & max-stop rejection,
   RR≥2.0 gating, instruction-schema completeness + deterministic `signal_id`,
   and the state machine's single-position / no-averaging guarantee.

Full validation *analysis* (walk-forward/MC/bootstrap/breakdowns, §14) is planned
but its external orchestration may extend into a Phase 1.x task; the minimal
end-to-end run plus the unit-test suite above are the hard gate.

---

## 17. Change log

- **v1.1.0** — Design revision requested pre-Phase-1 approval. Froze the exact
  London opening-range window (08:00–09:00 `Europe/London`, explicit GMT/BST UTC
  mapping, §2). Added the versioned **Trade Instruction Contract v1** with
  `signal_id`/`confidence`/`generated_`+`expiration_timestamp`/`evidence_summary`
  and a deterministic `signal_id` rule (§8). Expanded the **Retest contract**
  (valid/failed/timeout/max deviation/invalidation, §5). Consolidated the frozen
  **Version-1 risk policy** incl. no-scaling/pyramiding/averaging/martingale and
  deferred advanced exits (§9). Added the explicit **Execution boundary** (§0.2).
  Strengthened **Phase 1 acceptance criteria** (deterministic, no-lookahead,
  repeatable, fail-closed, complete audit trail, no core changes, §16).
- **v1.0.0** — Frozen baseline. Added platform-fit rules: single-interval
  backtest constraint & multi-TF derivation (§1.1), no-lookahead (§1.2),
  engine-contract/state-machine mapping (§7.1), evidence schema, expiration rule,
  Phase 1 acceptance criteria. Canonical symbol set to `EURUSD.FX`. Superseded
  the pre-freeze `v0.1.0-draft`.
