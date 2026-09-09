# Forex Swing Opening-Range-Breakout (Swing-ORB) — Strategy Specification

**Product name:** **Session Edge Swing-ORB** (implementation lives in
`forex_swing_orb/`, the single source of truth for this strategy — no parallel
implementation exists or is authorized).
**Status:** **FROZEN v1.4.0 — Phase 1 (implemented; corrected in-place after
acceptance review).** This document is design-authoritative; Phase 1 implements
exactly it. No live execution, no MT5, no filesystem bridge, no networking.
**Strategy version anchor:** `swing_orb.v1.4.0` (stamped into every emitted
signal's `strategy_version`).
**Trade-instruction schema version:** `1` (see §8).
**Audited platform baseline:** Vibe-Trading `v0.1.12` @ commit `e0b236c` (see
`docs/VIBE_TRADING_PHASE0_AUDIT.md`).

This document defines the *first candidate* strategy. It fixes a single,
deterministic baseline so a clean, unoptimized result can be produced before any
parameter tuning. Every rule is reducible to code with **no discretionary,
visual, natural-language, or LLM-interpreted qualification**.

---

## 0. Purpose and scope

- Market: **Forex only**. Initial validation symbol: **EURUSD** (canonical
  internal format `EURUSD.FX`; see §15 on the symbol-format hazard).
- Style: **Swing trading.** Holding period **several hours to several days**.
  Explicitly **not** scalping.
- The strategy produces a **signal / trade instruction** only (see §0.2).

### 0.1 Freeze status & change control

- This spec is **frozen at v1.2.0** and is the authoritative reference for Phase 1.
- Any change to a **rule or default value** requires a version bump (patch
  `v1.2.x` for clarifications/fixes; minor `v1.y.0` for a rule/schema change),
  recorded in §19, and the code's `strategy_version` must track it.
- Phase 1 implements **exactly** this baseline — no optimization, no rule
  additions beyond what is written here. Anything requiring a rule change is
  raised as a spec change, not silently coded.

### 0.2 Execution boundary (NORMATIVE)

- The Swing-ORB `SignalEngine` **generates trade instructions only** (§8). It
  performs research, qualification, and signal formation and nothing else.
- It **does not** connect to, authenticate with, send/modify orders on, or read
  live account state from **MT5 or any broker**, and performs **no** network I/O
  to any execution venue.
- The emitted instruction is a **passive data object**. Whether/when/how it is
  executed is the sole responsibility of a **separate, later execution layer**
  (the future Titan MT5 EA), out of scope here and for Phase 1.
- This boundary is a **frozen invariant**: no Phase 1 code may cross it.

---

## 1. Timeframes and anchoring

| Purpose | Timeframe | Notes |
|---|---|---|
| Directional trend (market structure) | **D1** and **H4** | Both must agree (§2). |
| Opening range, breakout, retest, confirmation | **M15** (execution TF) | Configurable; must divide H4 (`5m/15m/30m/1H`). |

All decisions use **closed/completed bars only**. A forming bar is never used.

### 1.1 Single-interval backtest constraint → deterministic multi-TF derivation (NORMATIVE)

The backtest `SignalEngine.generate(data_map)` receives OHLCV at **one** interval
only (audit §E). Therefore the strategy runs at `execution_tf` (default `15m`) and
**derives H4/D1 by resampling the execution-TF closed bars** (`open=first,
high=max, low=min, close=last`, right-closed/right-labeled buckets), using **only
fully-closed higher-TF buckets** (a partial H4/D1 bucket is excluded — fail-closed,
§14). `execution_tf` must divide H4; the config validator rejects one that does
not. The live path MAY use native H4/D1 bars only if it yields identical structure
results (§2); any divergence is a spec change.

### 1.2 No-lookahead rule (NORMATIVE)

A decision from a bar closing at *t* may only affect positions from bar *t+1*.
The returned signal series is computed on closed bars ≤ *t* and **shifted forward
one bar** before return (the engine fills at the next bar's open). No indicator,
pivot, range, breakout, retest, or confirmation may read a bar not yet closed.
See §2.2 for how this applies to pivot confirmation latency.

---

## 2. Market structure & directional trend (FROZEN)

Trend is defined by **deterministic swing structure** on H4 and D1 (derived per
§1.1). This supersedes the v1.1.0 EMA-alignment bias (see §19).

### 2.1 Frozen pivot / swing algorithm

- **Fractal pivot of strength `pivot_k`** (default **2**, i.e. a 5-bar fractal):
  - **Swing high** confirmed at bar index *i* iff
    `high[i] > high[j]` for all *j* ∈ `[i-pivot_k, i-1]` **and**
    `high[i] > high[j]` for all *j* ∈ `[i+1, i+pivot_k]` (strict `>`).
  - **Swing low** confirmed at bar index *i* iff
    `low[i] < low[j]` for all *j* ∈ `[i-pivot_k, i-1]` **and**
    `low[i] < low[j]` for all *j* ∈ `[i+1, i+pivot_k]` (strict `<`).
  - Strict inequalities mean **equal highs/lows are not pivots** (deterministic).
- **Alternation (frozen):** the confirmed pivot list is kept in strict
  chronological **alternation** of high/low. If two consecutive same-type pivots
  occur, keep the more extreme one (the higher high / the lower low); discard the
  other. This yields one deterministic alternating swing sequence.

### 2.2 No-lookahead for pivots (NORMATIVE)

A pivot at index *i* needs `pivot_k` bars to its right to be confirmed, so it is
**confirmed only once bar `i+pivot_k` has closed**. At decision time *t* (latest
closed bar) only pivots with `i ≤ t - pivot_k` are usable. No pivot is ever
inferred from bars unavailable at decision time.

**Higher-timeframe causal timestamp (clarified v1.4.0):** an H4/D1 pivot's
confirmation timestamp is the **close of the confirming higher-timeframe bar**
(`confirming_bar_open + htf_span`), never its open. Higher-timeframe trend and
Trend Health states therefore become visible to an execution-timeframe decision
**only at or after the confirming HTF candle has closed** — H4 state not before
the confirming H4 close, D1 state not before the confirming D1 close. Any
as-of mapping onto execution bars must use this close-based timestamp so no HTF
information is exposed before it was knowable. Execution-timeframe (minor) pivots
remain causally correct under §2.2 at their own granularity.

### 2.3 Frozen trend definition (required swing count)

Using the most recent **confirmed** alternating pivots on a timeframe, with
equality tolerance `swing_eq_tol = max(eq_min_pips_in_price, eq_atr_mult·ATR14)`
(default `eq_atr_mult = 0.1`):

- **Bullish** iff there are ≥ `min_confirmed_highs` (default **2**) confirmed
  swing highs and ≥ `min_confirmed_lows` (default **2**) confirmed swing lows, and
  the two most recent confirmed highs are ascending
  (`SH_n > SH_{n-1} + swing_eq_tol`) **and** the two most recent confirmed lows
  are ascending (`SL_n > SL_{n-1} + swing_eq_tol`) — i.e. a confirmed sequence of
  **higher highs and higher lows**.
- **Bearish** iff the mirror holds: ≥2 confirmed highs and lows, the two most
  recent highs descending (`SH_n < SH_{n-1} - swing_eq_tol`) **and** the two most
  recent lows descending (`SL_n < SL_{n-1} - swing_eq_tol`) — **lower highs and
  lower lows**.
- **Neutral / ambiguous → no trade** in every other case, explicitly including:
  mixed structure (high/low comparisons disagree); insufficient confirmed swings
  (fewer than the minimum of either type); equal or overlapping structure — any
  required comparison falling **within** `swing_eq_tol`; or **disagreement
  between H4 and D1**.

### 2.4 Multi-timeframe agreement (frozen)

Compute the trend independently on **H4** and **D1**. Combined trend is
**BULLISH** iff both are bullish, **BEARISH** iff both are bearish, else
**NEUTRAL → no trade**. **Long setups require BULLISH; short setups require
BEARISH; ambiguous or ranging structure means no trade.**

### 2.5 Trend Health Gate (FROZEN — new in v1.3.0)

A deterministic gate that runs **after** a directional trend is established
(§2.4) and **before** breakout evaluation. Its purpose is **to reject weak
continuation trades — NOT to predict reversals.** There is **no forecasting, no
probability, no AI/LLM opinion, no reversal model**; every check is a closed-form
function of the already-confirmed swing structure and ATR available at decision
time (no look-ahead, §2.2).

The gate is evaluated **independently on H4 and D1** using each timeframe's
confirmed alternating pivots; **both must pass** (consistent with §2.4). For a
BULLISH trend (bearish is the exact mirror), with `ATR` the bias-timeframe ATR14
at the confirmation instant and legs measured on the confirmed alternating pivot
sequence `P` (…, `P[-3]`, `P[-2]`, `P[-1]`):

1. **Structure integrity** — there are ≥ `health_min_confirmed` (default **3**)
   confirmed swing highs **and** ≥ `health_min_confirmed` confirmed swing lows in
   the monotonic HH/HL sequence (stricter than the trend minimum of 2). Fewer →
   deteriorating/insufficient structure → fail.
2. **Progress margin** — the most recent higher-high and higher-low each advance
   by a real margin: `SH_n − SH_{n−1} ≥ health_progress_atr·ATR` **and**
   `SL_n − SL_{n−1} ≥ health_progress_atr·ATR` (default `health_progress_atr =
   0.10`). Marginal (barely-higher) swings → fail.
3. **Continuation quality** — the latest leg has real size:
   `last_leg = |P[-1] − P[-2]| ≥ health_min_leg_atr·ATR` (default 0.5).
4. **Not weakening** — the latest leg is not collapsing versus the prior leg:
   `last_leg ≥ health_leg_ratio · prior_leg` where `prior_leg = |P[-2] − P[-3]|`
   (default `health_leg_ratio = 0.5`).

If **any** check fails on **either** required timeframe → **NO TRADE** with reason
`TREND_HEALTH_WEAK`. The gate never changes trade **direction** (that is fixed by
§2/§2.4); it only permits or blocks continuation.

---

## 3. Range & ORB breakout contract

### 3.1 London opening range (PRIMARY, FROZEN)

- **Session anchor:** London session open at **08:00 local**.
- **Timezone:** **`Europe/London`** (IANA tz), resolved with `zoneinfo`; no fixed
  offset is hard-coded.
- **Window (frozen default):** first **60 minutes**, local `[08:00, 09:00)`
  (`or_start_local`/`or_window` configurable; baseline frozen at 08:00–09:00).
- **DST (frozen, explicit):** convert the local window to UTC **per date** via
  `zoneinfo`:

  | Period | London offset | Range window in **UTC** |
  |---|---|---|
  | Winter (GMT) | UTC+0 | **08:00–09:00 UTC** |
  | Summer (BST) | UTC+1 | **07:00–08:00 UTC** |

  DST-transition ambiguity/nonexistence → day ineligible → no trade (§14).
- **Construction (closed bars only):** `range_high = max(high)`,
  `range_low = min(low)` over closed bars whose **open timestamp** is in the UTC
  window; **frozen** at the first bar close after the window; never modified later.
  Fewer than `or_min_bars` (default = `or_window/tf`) closed bars → ineligible.

### 3.2 Generic consolidation range contract (FROZEN, DEFINED; v1 use deferred)

A deterministic consolidation range, defined for completeness and future use.
**For v1 the London OR (§3.1) is the sole trade trigger; the generic range is a
frozen, defined structure but is NOT an independent v1 entry trigger** (deferred
to keep one deterministic baseline — see §0.1 / ambiguity note in the return).

- **Duration:** `min_range_bars` (default 6) ≤ closed-bar count ≤ `max_range_bars`
  (default 48); equivalently `min_range_duration`/`max_range_duration`.
- **Boundaries:** `range_high = max(high)`, `range_low = min(low)` over the window.
- **Maximum boundary variation:** the top must be tested by ≥ `min_boundary_touches`
  (default 2) closed bars whose `high` is within `boundary_touch_tol`
  (default `max(2 pip, 0.1·ATR14)`) of `range_high`, and symmetrically for the
  bottom; any bar exceeding a boundary by more than `boundary_touch_tol`
  invalidates the range (that is a breakout, not consolidation).
- **Width:** `min_range_width` ≤ `range_high − range_low` ≤ `max_range_width`.
- **Volatility-normalized width (used):** `min_width_atr` ≤
  `(range_high − range_low)/ATR14` ≤ `max_width_atr` (defaults 0.5 and 5.0).
- **Range invalid if:** too few/many bars, width or normalized width out of
  bounds, boundary variation exceeded, insufficient boundary touches, or price
  already broke out during formation.

### 3.3 Valid breakout (FROZEN)

A valid breakout requires **all** of:
- a **completed candle close** beyond the relevant boundary — long:
  `close > range_high + buffer`; short: `close < range_low − buffer`
  (**a wick beyond the boundary alone is not a breakout**);
- a **minimum breakout buffer**: `buffer = max(breakout_min_pips_in_price,
  atr_mult·ATR14)`, defaults `breakout_min_pips = 2`, `atr_mult = 0.25`;
- **alignment with higher-timeframe trend** (§2): long only when BULLISH, short
  only when BEARISH; against-trend breakouts are ignored;
- **no breakout chasing / no immediate entry**: the breakout only *arms* the
  setup; entry is never taken on the breakout candle (§4/§6/§7).
- **Setup expiry:** breakout must reach retest + confirmation within
  `setup_max_bars` (default 12) execution-TF bars, else discarded.

---

## 4. Retest contract

After a valid breakout, price must **revisit the broken boundary and hold it**.
States are deterministic and mutually exclusive; **all retest evidence uses
completed, temporally contiguous bars** (see §4.1).

- **Valid retest.** A completed candle whose retest extreme reaches the boundary
  zone without over-penetrating and without a decisive reclaim:
  - Long: `low ≤ range_high + retest_tol` **and** `low ≥ range_high − max_retest_deviation`.
  - Short: `high ≥ range_low − retest_tol` **and** `high ≤ range_low + max_retest_deviation`.
- **Successful boundary hold:** the retest candle does **not** close decisively
  back inside the range (see reclaim below) and does not over-penetrate.
- **Failed retest (invalidated → no trade):**
  1. **Over-penetration:** extreme pierces beyond `max_retest_deviation`
     (long: `low < range_high − max_retest_deviation`; short: mirror).
  2. **Close-back-inside (decisive reclaim):** a completed candle **closes** past
     `range_high − reentry_tol` (long) / `range_low + reentry_tol` (short).
- **Maximum retest duration / timeout:** no valid retest within `setup_max_bars`
  execution-TF bars from the breakout close → setup expires → no trade.
- **Maximum permitted penetration:** `max_retest_deviation =
  max(retest_tol, retest_dev_atr_mult·ATR14)` (default `retest_dev_atr_mult = 0.5`).
- **Retest tolerance:** `retest_tol = max(retest_min_pips_in_price,
  retest_atr_mult·ATR14)` (defaults `retest_min_pips = 2`, `retest_atr_mult = 0.15`).
- **Reentry tolerance:** `reentry_tol` default = `retest_tol`.

### 4.1 Data contiguity, gaps, and no skip-resume (NORMATIVE)

- Evidence bars must be **temporally contiguous** at `execution_tf`. If the bar
  sequence has a **gap or missing bar** within a live setup window, the setup is
  **invalidated → no trade** (fail-closed); the strategy does **not** stitch
  across the gap.
- **No skipping-and-resuming:** once a setup's evidence is broken or invalid
  (over-penetration, reclaim, gap, timeout, or trend flip), the setup is
  **discarded permanently**. It **cannot** be revived by ignoring the invalid
  evidence and continuing later; a fresh breakout is required.

**Invalidation rules (consolidated):** a setup is invalidated on the first of —
over-penetration, decisive reclaim, data gap/missing bar, trend flip to
non-permitting (§2), or timeout.

---

## 5. Price-action confirmation (FROZEN v1 model)

After a valid retest, require **exactly one deterministic confirmation model**,
**frozen for v1** (no discretionary selection):

**v1 model — minor-swing break (frozen):** confirmation occurs when a **completed
execution-TF candle closes beyond the most recent confirmed minor swing** in the
trend direction:
- Long: a completed candle **closes above** the most recent **confirmed minor
  swing high** formed during/after the retest.
- Short: a completed candle **closes below** the most recent **confirmed minor
  swing low** formed during/after the retest.
- **Minor swing** = a fractal pivot (§2.1) on the execution TF with strength
  `minor_pivot_k` (default **1**, a 3-bar fractal). The minor swing must be
  **confirmed** (needs `minor_pivot_k` right bars closed) before its break counts
  (no-lookahead, §2.2).
- **Confirmation count:** `confirm_bars` (default **1**) qualifying closes.
- If not achieved within the remaining `setup_max_bars` window → setup expires →
  no trade.

**Deferred candidates (NOT in v1):** an engulfing model and a rejection-candle
(pin/wick) model are documented as later candidates. They must **not** be mixed
into v1, and may only be introduced by a version bump with their **exact OHLC
rules frozen**. No natural-language judgment, visual discretion, or LLM
interpretation may qualify a setup (frozen invariant).

---

## 6. (reserved — see §5 for confirmation; §7 for entry)

*Section intentionally left as a numbering anchor after the v1.2.0 restructure;
no rules live here.*

---

## 7. Entry

- Enter **only after** breakout (§3.3) **and** valid retest (§4) **and**
  confirmation (§5), in the direction permitted by trend (§2).
- **Long/short rules symmetrical** (mirror of high/low, above/below). No asymmetry
  in v1; any future asymmetry is evidence-justified and version-bumped.
- **Entry reference price:** the **close of the final confirming candle**
  (`entry_price = confirm_close`). Per §1.2 the position is taken on the **next**
  bar; the backtest fill is that next bar's open adjusted by modeled
  spread/slippage.
- On confirmed entry the engine emits a **Trade Instruction** (§8).

### 7.1 Engine-contract mapping (NORMATIVE — ORB state machine onto a per-bar weight)

The engine consumes a per-bar weight in `[-1.0, 1.0]`, not bracket orders
(audit §E). The ORB is a per-symbol state machine inside `generate()`:
`FLAT → ARMED (post-breakout) → RETESTED → IN_POSITION → FLAT`.
Weight is `0.0` until confirmed entry, then `+1.0` (long) / `−1.0` (short) held
until exit; **stop/target are enforced in-`generate()`** (weight→0 on the exit
bar, shifted per §1.2) since the engine models no broker SL/TP. Weight is only
ever `0`, `+1`, `−1`, so **one position per symbol** and **no averaging** are
structurally guaranteed (§9).

---

## 8. Trade Instruction Contract v1 (versioned schema)

Every qualified setup emits **one** passive Trade Instruction (§0.2). Schema is
versioned (`instruction_schema_version = 1`); any field change bumps it and the
spec version. Timestamps are **UTC, ISO-8601**; prices in the quote currency.

| Field | Type | Required | Meaning |
|---|---|---|---|
| `instruction_schema_version` | int | yes | `1`. |
| `signal_id` | string | yes | **Deterministic** content hash (below). |
| `strategy_version` | string | yes | `swing_orb.v1.2.0`. |
| `symbol` | string | yes | Canonical `EURUSD.FX` (§15). |
| `direction` | enum | yes | `LONG` / `SHORT`. |
| `entry_price` | float | yes | Final confirming close (§7). |
| `stop_loss` | float | yes | Structural stop (§10). |
| `take_profit` | float | yes | Fixed-2R target (§11). |
| `generated_timestamp` | string (UTC ISO-8601) | yes | Confirming-bar close time. |
| `expiration_timestamp` | string (UTC ISO-8601) | yes | Validity horizon (§8.2). |
| `evidence_summary` | object | yes | Structured decision trail (§8.1). |
| `confidence` | float in [0,1] | optional | See §8.3. |

- **`signal_id` (deterministic):**
  `sha256("{strategy_version}|{symbol}|{direction}|{generated_timestamp}|{entry_price}|{stop_loss}|{take_profit}")[:16]`
  — a pure function of contents, **no UUIDs/clock/randomness** (supports §18
  repeatability).

### 8.1 `evidence_summary` (required contents)

Structured object (not free text) with at least: `trend_d1`, `trend_h4`,
`confirmed_swings_d1`, `confirmed_swings_h4` (the pivots used, with indices/prices),
`range_source` (`london_or`), `or_window_utc`, `session_date`, `range_high`,
`range_low`, `breakout_bar_ts`, `breakout_close`, `buffer`, `atr14`,
`retest_bar_ts`, `retest_extreme`, `max_retest_deviation`, `minor_swing_ref`
(price/ts of the broken minor swing), `confirm_bar_ts`, `confirm_close`,
`stop_basis`, `rr_planned`, `news_check` (§12 result), `filters_passed`
(session/spread/stale flags), and `reason_code` (`OK` for an emitted instruction;
§13 codes otherwise).

### 8.2 Expiration horizon (clarified v1.4.0)

An instruction must remain valid **strictly beyond the first effective execution
bar**. Per §1.2 the decision is taken from the bar closing at *t*
(`generated_timestamp`) and the executable weight first applies on the next bar,
whose open is `first_exec_open = generated_timestamp + tf_minutes` (also the
expected fill point). The expiration is therefore set **one or more full bars
after** that bar:

`expiration_timestamp = first_exec_open + entry_valid_bars·tf_minutes`
`                     = generated_timestamp + (entry_valid_bars + 1)·tf_minutes`

with `entry_valid_bars` default **1** (so the instruction is valid across the
execution bar and one further bar). **Expiration comparison is defined
explicitly:** an instruction is expired **iff `evaluation_time >=
expiration_timestamp`**. Consequently `expiration_timestamp > first_exec_open`
always holds — an instruction can never expire at or before the bar where the
shifted executable weight first appears. An instruction consumed at/after
`expiration_timestamp`, or whose geometry no longer holds, is **stale → no
trade** (§14). `generated_timestamp` (hence `signal_id`) is unchanged by this
clarification.

### 8.3 `confidence`

v1 is a deterministic, rule-based qualifier: a setup either passes every gate or
is not emitted. There is **no graded score** in v1; the field is emitted as fixed
`confidence = 1.0` for a fully-qualified setup (or omitted). A graded model is
deferred (schema/version change).

---

## 9. Risk — Frozen Version-1 policy

Frozen invariants for v1 (changing any is a version bump):

- **Risk per trade:** **0.25%** of account equity (`risk_pct = 0.0025`).
- **One open position per symbol** (enforced by §7.1).
- **Fixed reward-to-risk target: 2.0R** (`rr_target = min_rr = 2.0`); a setup that
  cannot meet 2.0R is not traded.
- **No scaling** (no partial entries/exits), **no pyramiding**, **no averaging
  down**, **no martingale / no grid**.
- **Advanced exits explicitly deferred:** no trailing stop, no break-even, no
  structure/HTF target, no time-based scale-out. Exit is strictly `stop_loss` or
  `take_profit` (or a §12 time/weekend/failure force-exit).
- **Correlated exposure bound:** `max_correlated_risk_pct` (baseline 0.50%);
  dormant for the single-symbol EURUSD baseline but must exist.
- **Daily/total loss controls (fail-closed):** `daily_max_loss_pct` (1.0%) halts
  new trades for the rest of the UTC day; `total_max_loss_pct` (6.0%) halts new
  signals until manual reset. Unreadable equity/PnL → treat as breached → no trade.

Size: `units = (equity·risk_pct)/(stop_distance_price·pip_value)`.

---

## 10. Stop loss

- Structural stop beyond the retest invalidation point:
  - Long: `stop_loss = min(retest_low, range_high) − stop_pad`.
  - Short: `stop_loss = max(retest_high, range_low) + stop_pad`.
  - `stop_pad = max(stop_min_pips_in_price, stop_atr_mult·ATR14)` (defaults
    `stop_min_pips = 2`, `stop_atr_mult = 0.25`).
- **Max stop-distance protection:** `max_stop_pips` (baseline 60 EURUSD); exceed →
  setup **rejected** (no fabricated nearer stop).
- **No valid structural stop ⇒ no trade.**

---

## 11. Profit management (frozen: fixed multiple)

`take_profit = entry_price ± rr_target·stop_distance`, `rr_target = 2.0`. Most
deterministic baseline; higher-TF-structure and partial-profit-trail alternatives
are **deferred** (§9).

---

## 12. News Engine Contract

News handling has two parts: (A) the **News Engine** component (continuous
ingestion) and (B) **v1 trade-qualification consumption** (risk filter only).
Both are specified as design contracts; **for backtest, news is a supplied,
timestamped event dataset** — building the live continuous ingestion service may
be a separate component/phase (see the scoping ambiguity in the return).

### 12.1 News Engine (component contract)

Runs **continuously, including when the Forex market is closed**. It must:
- ingest and **timestamp scheduled** economic events;
- ingest and **timestamp material unscheduled** geopolitical or central-bank news;
- retain **source/provenance** for every record;
- identify **affected currencies and pairs**;
- **reject stale or unverified** records;
- remain **operational independently of trading-session state**.

### 12.2 v1 trade-qualification consumption (frozen; fail-closed default — clarified v1.4.0)

- News acts **only as a risk filter**: it **does not generate direction** and
  **does not override** any strategy requirement (§§2–11).
- **Fail-closed is the default and production posture.** A qualified setup may
  **not** emit a trade instruction unless the required news data is **present,
  valid, fresh, and verified** per the configured contract **and** the decision
  time is **outside** the configured high-impact lockout window. Concretely, at
  the confirmation bar:
  - required news **absent / unverifiable freshness** → `NEWS_DATA_UNAVAILABLE`;
  - news **older than `news_max_age_min`** (freshness proven from the supplied
    `news_asof`) → `NEWS_DATA_STALE`;
  - decision within a high-impact **lockout** window (`news_pre_lockout_min` /
    `news_post_lockout_min`, defaults 30/30) for an affected currency →
    `NEWS_LOCKOUT`;
  - a **malformed** news record (missing/invalid `timestamp`, `impact`, or
    `currencies`) → **fail closed** to `NEWS_DATA_UNAVAILABLE`, never an
    exception.
  In all of the above → **no trade**.
- **There is no default mode in which missing news silently becomes eligible.**
- **Research-only disable is explicit and audited.** News filtering may be
  bypassed **only** by explicitly setting `news_research_bypass = true`
  (default `false`). When bypassed, the audit records the news state as
  `RESEARCH_BYPASS` for every affected decision. This is a research-only posture,
  never the production/default.
- **Affected-currency mapping is deterministic:** `EURUSD.FX → {EUR, USD}`.
- **Existing-position behavior (separate):** an open position is **not
  force-closed by news** in v1 (advanced exits deferred, §9); news only blocks
  **new** entries.
- **Auditability:** every news decision (allow, each denial reason, or explicit
  bypass) is recorded in the per-bar audit trail.

---

## 13. Session / weekend / market-data filters

- **Session eligibility:** setups armed only during the configured London-anchored
  window; outside eligible hours no new setup is armed.
- **Friday / weekend policy:** **no position held over the weekend.** Open
  positions closed before `friday_close_utc`; no new entries after
  `friday_no_new_entry_utc`; the signal layer must not emit entries that would
  necessarily straddle the weekend. Backtest state machine force-exits at
  `friday_close_utc`.
- **Spread rejection:** current spread `> max_spread_pips` (baseline 2.0) → reject.
- **Stale-data rejection:** latest completed bar older than `max_data_age` (small
  multiple of the interval) → no trade.
- (High-impact **news** lockout is specified separately in §12.)

---

## 14. Pipeline order & reason codes (FROZEN)

Qualification runs in this **fixed order**; the **first** failing stage produces
**no trade** and an **auditable reason code**, and no later stage can override it:

1. **Closed / contiguous data** — complete, gap-free, non-stale bars (else `E_DATA`).
2. **Session & range validity** — session eligible; London OR well-formed (§3.1)
   (else `E_SESSION`).
3. **Higher-timeframe trend** — H4+D1 structure agree and permit a direction (§2)
   (else `E_TREND`).
3a. **Trend health** — the §2.5 Trend Health Gate passes on both H4 and D1
   (else `E_TREND_HEALTH` / `TREND_HEALTH_WEAK`).
4. **Completed-candle breakout** — close beyond boundary + buffer, trend-aligned,
   not wick-only (§3.3) (else `E_BREAKOUT`).
5. **Retest** — valid retest, not failed/timed-out/gapped (§4) (else `E_RETEST`).
6. **Deterministic price-action confirmation** — minor-swing break (§5)
   (else `E_CONFIRM`).
7. **News eligibility** — no active high-impact lockout; news data present & fresh
   (§12) (else `E_NEWS`).
8. **Risk eligibility** — valid structural stop, RR ≥ 2.0, within max-stop, within
   loss/exposure limits, one-position (§§9–11) (else `E_RISK`).
9. **Versioned trade instruction** — emit (§8) with `reason_code = SIGNAL_GENERATED`.

Every stage's outcome (pass/fail + code) is recorded for a fully reconstructable
audit trail.

### 14.1 Exit reason codes (clarified v1.4.0)

Position exits are audited with **dedicated** reason codes — never by reusing a
setup-qualification code:
- `EXIT_STOP_LOSS` — stop touched on a completed bar.
- `EXIT_TAKE_PROFIT` — target touched on a completed bar.
- `EXIT_TIME` — Friday/weekend time close (§13).
- `EXIT_INVALIDATED` — continuity broken while in position (e.g. a data gap).

**Same-bar stop and target (frozen worst-case):** if a single completed bar
touches **both** `stop_loss` and `take_profit`, resolve **stop first**
(`EXIT_STOP_LOSS`); never assume the target filled first. `RISK_INVALID` and
`SIGNAL_GENERATED` are **not** used for exits.

### 14.2 Ownership of downstream (execution-layer) checks (clarified v1.4.0)

The SignalEngine performs only what is provable from candle data. The following
frozen requirements are **explicitly downstream** (future Titan/execution layer)
and are **not** implemented in, nor falsely reported by, the SignalEngine:
live **spread** checks (§13), broker **stop-distance** checks, **account
equity**, **daily loss limits** and **total drawdown limits** (§9), and the
execution **kill switch**. Reason codes that the SignalEngine cannot emit from
candle data alone are **reserved/annotated** (e.g. `DATA_STALE`,
`DATA_NOT_CLOSED` — live-feed concerns) rather than presented as implemented.
**Data-freshness that is provable from candle timestamps remains the
SignalEngine's responsibility and fails closed** (temporal-gap detection →
`TEMPORAL_GAP`; incomplete higher-TF buckets excluded, §1.1).

---

## 15. Failure semantics (all fail-closed → NO TRADE)

Return **no trade** (never a guess) for: missing/incomplete/forming/non-contiguous
data; ambiguous session/timezone (incl. DST-transition); insufficient history
(pivot/ATR warmup, `< or_min_bars`, incomplete higher-TF bucket §1.1, `<`
required confirmed swings §2.3); neutral/conflicting H4/D1 trend; weak trend
health (§2.5, `TREND_HEALTH_WEAK`); failed/timed-out
retest or data gap (§4); confirmation not met (§5); missing/stale/conflicting news
(§12); no valid structural stop / RR<2.0 / max-stop exceeded / loss-limit breach
(§§9–11); invalid or stale instruction (§8.2). Each maps to a §14 reason code.

> **Platform hazard (audit §F):** the backtest classifier recognizes forex only as
> `EUR/USD` or `EURUSD.FX`, but artifact CSV writing breaks on the `/` in
> `EUR/USD`. **Canonical for run configs is `EURUSD.FX`.** Unrecognized/misrouted
> symbol → no trade.

---

## 16. Validation plan (design-only; later phase)

In-sample/out-of-sample separation with an untouched final holdout; walk-forward
(*caveat:* built-in is a consistency check, not true WFO — orchestrate externally,
audit §D/§F); Monte Carlo (*caveat:* built-in is a trade-order permutation test);
bootstrap CIs (*caveat:* IID, no block bootstrap). Costs: spread + swap (incl.
Wednesday triple) + slippage; **commission is hard-zero in the FX engine** — state
in every result. Breakdowns: regime, pair-by-pair, long-vs-short, session,
day-of-week. **No parameter selection on the final holdout.** Fixed seeds; record
whether the news dataset was present (else news reported inactive).

---

## 17. Configurable parameters (summary of frozen defaults)

| Param | Default | Meaning |
|---|---|---|
| `execution_tf` | `15m` | OR/breakout/retest/confirm TF (must divide H4) |
| `bias_tfs` | `H4,D1` | Trend timeframes (both must agree) |
| `pivot_k` | `2` | HTF fractal pivot strength (§2.1) |
| `min_confirmed_highs` / `min_confirmed_lows` | `2 / 2` | Required confirmed swings (§2.3) |
| `health_min_confirmed` | `3` | Min confirmed highs & lows for trend health (§2.5) |
| `health_progress_atr` | `0.10` | Min HH/HL progress margin, in ATR (§2.5) |
| `health_min_leg_atr` | `0.5` | Min latest-leg size, in ATR (§2.5) |
| `health_leg_ratio` | `0.5` | Min latest/prior leg ratio (§2.5) |
| `swing_eq_tol` | `max(1 pip, 0.1·ATR14)` | Swing equality tolerance (`eq_min_pips=1`, §2.3) |
| `minor_pivot_k` | `1` | Execution-TF minor-swing strength (§5) |
| `confirm_bars` | `1` | Confirmation closes required (§5) |
| `session_anchor`/`session_tz` | `London`/`Europe/London` | DST-aware anchor |
| `or_start_local`/`or_window` | `08:00`/`60m` | London OR start & duration |
| `or_min_bars` | window-derived | Min closed bars to form the OR |
| `min_range_bars`/`max_range_bars` | `6`/`48` | Generic range duration (§3.2, deferred use) |
| `min_boundary_touches` | `2` | Boundary touches for a valid generic range |
| `min_width_atr`/`max_width_atr` | `0.5`/`5.0` | Vol-normalized range width (§3.2) |
| `buffer` | `max(2 pip, 0.25·ATR14)` | Min breakout distance |
| `setup_max_bars` | `12` | Bars allowed breakout→entry |
| `retest_tol` | `max(2 pip, 0.15·ATR14)` | Retest touch tolerance |
| `max_retest_deviation` | `max(retest_tol, 0.5·ATR14)` | Max pullback penetration |
| `reentry_tol` | `= retest_tol` | Reclaim invalidation band |
| `risk_pct` | `0.0025` | Risk per trade (0.25%) |
| `min_rr`/`rr_target` | `2.0/2.0` | Reward-to-risk |
| `max_correlated_risk_pct` | `0.005` | Correlated exposure cap |
| `daily_max_loss_pct`/`total_max_loss_pct` | `0.01/0.06` | Loss kills |
| `stop_pad` | `max(2 pip, 0.25·ATR14)` | Structural stop padding |
| `max_stop_pips` | `60` | Max stop distance (else no trade) |
| `entry_valid_bars` | `1` | Extra bars of validity **beyond** the execution bar (§8.2) |
| `news_pre_lockout_min`/`news_post_lockout_min` | `30/30` | High-impact lockout windows (§12) |
| `news_max_age_min` | `1440` | Max news age before `NEWS_DATA_STALE` (§12) |
| `news_research_bypass` | `false` | Explicit research-only news bypass; audited `RESEARCH_BYPASS` (§12) |
| `max_spread_pips` | `2.0` | Max spread — **downstream** (§14.2), not enforced in the SignalEngine |
| `max_data_age` | `1.5×` bar | Stale-feed cutoff — **downstream** (§14.2); candle gaps handled via `TEMPORAL_GAP` |
| `friday_no_new_entry_utc`/`friday_close_utc` | configurable | Weekend policy |

`pip` = 0.0001 (0.01 for JPY quote); `*_in_price` = pip converted to price units.
All defaults are deterministic and **not** optimized.

---

## 18. Phase 1 acceptance criteria (definition of done)

Global gates (unchanged): **deterministic outputs**; **no look-ahead**;
**repeatable results** (byte-identical signals/metrics on re-run; content-derived
`signal_id`); **fail-closed** on every §15 path; **complete audit trail** (every
emitted instruction carries §8 fields incl. `evidence_summary`; every rejected
setup records its §14 reason code); **no changes to Vibe-Trading core subsystems**
(added via the file/run-dir extension point, audit §E; §0.2 boundary never
crossed; **Phantom and Titan untouched**; official validation stays green); a
minimal **EURUSD** (`EURUSD.FX`) end-to-end backtest through `ForexEngine`.

**Required tests (v1.2.0 — added/expanded):**
1. **Deterministic swing detection** — fixtures yield exact confirmed pivots.
2. **No future-bar/look-ahead dependency** — a pivot/decision at *t* uses only
   bars ≤ *t* (pivot confirmation latency §2.2 enforced).
3. **Trend cases** — bullish, bearish, neutral, and **insufficient-history**
   inputs each classify correctly (incl. H4/D1 disagreement → neutral).
3b. **Trend health** — a healthy continuation passes; weak structure (too few
   confirmed swings, marginal progress, undersized or shrinking latest leg) is
   rejected with `TREND_HEALTH_WEAK` and produces no trade (§2.5).
4. **Completed close vs wick-only breakout** — wick-only does not arm; completed
   close beyond boundary+buffer does.
5. **Valid and failed retests** — valid hold; over-penetration; decisive reclaim;
   **data-gap invalidation**; and **no skip-and-resume**.
6. **Setup expiration** — timeout with no valid retest/confirmation → no trade.
7. **Price-action confirmation pass/fail** — minor-swing break confirmed vs not.
8. **Range validity and invalidity** — well-formed vs each §3.2 invalidation cause.
9. **Missing or stale news fails closed** — absent/stale/conflicting news → no
   new trade with `E_NEWS`.
10. **High-impact news blocks new entries** — active pre/post lockout → `E_NEWS`.
11. **News does not generate direction** — news alone never produces a signal;
    direction always derives from §2 trend + §§3–5.
12. **Identical inputs → identical signal IDs and outputs.**
13. **No MT5/broker/Titan/Phantom dependency** — import/boundary test.
14. **No Vibe-Trading core subsystem changes** — repo official validation green.

Full validation *analysis* (§16) may extend into a Phase 1.x task; the minimal
end-to-end run plus this test suite are the hard gate.

---

## 19. Change log

- **v1.4.0** — Acceptance-review corrections (design-level clarifications only; no
  change to trade direction, structure/breakout/retest/confirmation rules, risk,
  or the instruction schema). (1) **News fail-closed by default** (§12.2): no
  default mode where missing news becomes eligible; missing/unverifiable →
  `NEWS_DATA_UNAVAILABLE`, stale → `NEWS_DATA_STALE`, lockout → `NEWS_LOCKOUT`,
  malformed → fail-closed `NEWS_DATA_UNAVAILABLE`; research-only bypass requires
  explicit `news_research_bypass` and is audited `RESEARCH_BYPASS`. (2)
  **Expiration horizon** (§8.2): `expiration_timestamp = generated + (entry_valid_bars+1)·tf`,
  strictly after the first execution bar; expired iff `evaluation_time >=
  expiration_timestamp`. (3) **HTF causal timestamp** (§2.2): H4/D1 pivot/trend/
  health confirmation uses the confirming HTF bar's **close**, never its open.
  (4) **Exit reason codes** (§14.1): `EXIT_STOP_LOSS`/`EXIT_TAKE_PROFIT`/
  `EXIT_TIME`/`EXIT_INVALIDATED`; same-bar stop+target resolves **stop-first**.
  (5) **Downstream ownership** (§14.2): live spread, broker stop-distance, equity,
  daily/total loss limits, kill switch are downstream; `DATA_STALE`/
  `DATA_NOT_CLOSED` reserved (live-feed), not falsely implemented.
- **v1.3.0** — Added the **Trend Health Gate** (§2.5): a deterministic
  continuation-quality gate (structure integrity, progress margin, leg size,
  non-weakening) evaluated on H4 and D1 after the trend gate and before breakout;
  fails closed to `TREND_HEALTH_WEAK`; no forecasting/probability/reversal logic.
  Inserted into the pipeline order (§14 step 3a), failure semantics (§15),
  parameters (§17), and acceptance tests (§18). Recorded the product name
  **Session Edge Swing-ORB** and the single-source-of-truth rule (the strategy is
  implemented once, in `forex_swing_orb/`; no parallel implementation). No change
  to trade direction, risk, or the instruction schema.
- **v1.2.0** — Approved pre-Phase-1 requirements. **Replaced EMA bias with a
  frozen market-structure trend** (fractal pivot `pivot_k`, alternation rule,
  confirmed HH/HL vs LH/LL with `swing_eq_tol`, H4+D1 agreement, pivot
  no-lookahead latency, §2). Added the **generic consolidation-range contract**
  (duration/boundaries/variation/width/vol-normalized/invalidity) alongside the
  primary London OR, with v1 trade-trigger use deferred (§3.2). Expanded the
  **retest contract** with data-contiguity, gap/missing-data invalidation, and the
  **no-skip-and-resume** rule (§4.1). Froze the **v1 price-action confirmation**
  as the minor-swing break, with engulfing/rejection explicitly deferred (§5).
  Added the **News Engine Contract** (continuous ingestion; v1 risk-filter-only
  consumption with pre/post lockout, separate existing-position behavior,
  fail-closed, auditable, §12). Froze the **pipeline order & reason codes** (§14).
  Expanded **Phase 1 acceptance tests** (§18).
- **v1.1.0** — Froze exact London OR window (08:00–09:00 Europe/London, GMT/BST
  mapping); added versioned Trade Instruction Contract v1 (deterministic
  `signal_id`); expanded retest contract; froze v1 risk (no scaling/pyramiding/
  averaging/martingale; advanced exits deferred); added Execution boundary;
  strengthened acceptance criteria.
- **v1.0.0** — Frozen baseline: single-interval multi-TF derivation, no-lookahead,
  engine-contract/state-machine mapping, evidence schema, expiration, acceptance
  criteria; canonical symbol `EURUSD.FX`.
