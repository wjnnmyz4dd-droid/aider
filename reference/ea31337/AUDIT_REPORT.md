# EA31337 Architecture Audit — vs. Phantom

Scope: `EA31337`, `EA31337-classes`, `EA31337-strategies` (vendored under
`reference/ea31337/`), compared against Phantom's current implementation
in `phantom_pipeline/`. Research-only — no code was written or changed as
part of this audit.

**Legend:** KEEP = concept worth adopting largely as-is (reimplemented
clean-room, never copy-pasted — see the license note below). IMPROVE =
worth adapting into something better for Phantom. REPLACE = Phantom
already has an equivalent that is architecturally superior; if this
capability is ever revisited, replace the EA31337 approach rather than
port it. REMOVE = present in EA31337 and should be actively avoided —
don't copy, don't resurrect, don't take as inspiration. IGNORE = not
relevant to Phantom, no action needed either way.

---

## 0. Critical caveats (read first)

1. **All three repos are GPLv3** (one embedded BSD-licensed file,
   `EA31337-classes/MD5.mqh`). GPLv3 is copyleft — copying or adapting
   this source into Phantom's proprietary codebase creates a real
   copyleft-infection risk. **Nothing in this report should be read as
   "copy this code."** Every KEEP/IMPROVE verdict below means
   *reimplement the concept from scratch*, never adapt the EA31337
   source text directly. This is a legal constraint, not a style
   preference — treat it as a hard blocker on literal reuse.

2. **The vendored `reference/ea31337/EA31337-strategies` and
   `reference/ea31337/EA31337` trees are scaffolding-only.** Both
   upstream repos use git submodules for their real content (68
   per-strategy repos; `EA31337-classes`/strategies/indicators
   respectively), and those submodules were never initialized when this
   material was vendored into the repo. To produce items 1 and parts of
   13–17 below, I separately shallow-cloned all 68 real
   `EA31337/Strategy-*` repos into this session's scratchpad (not
   committed to the repo) so the strategy catalog below reflects actual
   signal logic, not guesses from directory names. **The committed
   `reference/ea31337/EA31337-strategies/` tree in git still contains
   only the empty scaffolding** — if you want the 68 real strategy
   repos permanently vendored (another ~9 MB), say so and I'll add them
   in a follow-up commit; they were not added automatically since it
   wasn't part of the original request.

3. `EA31337-classes` (the one repo with substantial real code already
   vendored) is architecturally patchy: no dedicated Risk or Money
   management class, no trailing-stop or break-even implementation at
   all, two dead/unused code hierarchies left in the tree, and several
   methods that are commented-out stubs disguised as real methods. This
   materially lowers how much is actually minable from it — see §3–§8.

---

## 1. Every trading strategy (68, from the `EA31337/Strategy-*` repos)

Every `Stg_<Name>.mqh` subclasses a common `Strategy` base and expresses
entry logic as `SignalOpen()`. **64/68 delegate SL/TP and lot sizing
entirely to the framework** (only `BearsPower`, `MA_Trend`,
`Oscillator_Trend`, `Retracement` define custom `PriceStop()`); only one
(`Envelopes`) overrides `SignalClose`, and that override is functionally
a no-op. None embed independent money-management logic — this is a
uniform, framework-delegated design across the whole set.

Phantom's Strategy Engine playbooks (`liquidity_reversal`, `orb`,
`range_reversal`, `session_breakout`, `trend_continuation`) are
**structural/price-action** confirmation layers (BOS/CHoCH/FVG/order
blocks/support-resistance), not single-indicator threshold-cross
systems. That's the lens for every verdict below: EA31337's strategies
don't map onto Phantom's playbook model directly; the question is
whether an individual signal *idea* is worth mining as a new,
independent **scoring_engine rule** instead (Phantom's scoring engine
currently has zero technical-indicator-based rules — only generic
meta-rules: `directional_clarity`, `evidence_count`,
`reason_code_presence`, `supporting_observation_count`).

| Strategy | Family | Signal (one line) | Verdict |
|---|---|---|---|
| RSI | Oscillator | 50±level threshold cross + rising/falling | IMPROVE — mine as a new scoring rule |
| Stochastic | Oscillator | %K/%D oversold/overbought cross | IMPROVE |
| CCI | Oscillator | ±level threshold cross | IMPROVE |
| WPR | Oscillator | −50±level cross | IMPROVE |
| Momentum | Oscillator | pure slope, no level | IGNORE (too weak alone) |
| MFI | Volume/Oscillator | 50±level cross | IMPROVE |
| DeMarker | Oscillator | 0.5±level cross | IGNORE (redundant with RSI/Stochastic if both added) |
| OsMA | Oscillator | histogram zero-line reversal | IMPROVE |
| MACD | Oscillator | signal/main line cross | IMPROVE — highest-value single addition |
| RVI | Oscillator | cross + oversold/overbought zone | IGNORE (niche) |
| DPO | Oscillator | plain threshold cross | IGNORE |
| AD | Volume | %-change threshold only | IGNORE (weakest signal in the set) |
| OBV | Volume | slope-follow | IGNORE |
| Chaikin | Volume | squared-level threshold | IGNORE |
| BWMFI | Volume | histogram + BW color check (looks bugged — sell branch reuses buy's color check) | REMOVE (don't copy the bug) |
| AC | Bill Williams | saucer-adjacent | IGNORE |
| Awesome (AO) | Bill Williams | 3-bar saucer pattern | IGNORE |
| Force | Volume | sign + slope | IGNORE |
| ASI | Volume | slope-follow | IGNORE |
| Fractals | Structure | raw fractal buffer passthrough | REPLACE (Phantom's scanner already computes swing structure better) |
| BearsPower / BullsPower | Bill Williams | histogram sign + slope; asymmetric custom-SL/TP (Bears has it, Bulls doesn't — an inconsistency) | IGNORE |
| AMA, DEMA, SAR, SuperTrend, TMA_CG, TMA_True | Trend/MA | slope or band-touch + threshold | REPLACE (Phantom's EMA-trend + structure.py already covers this territory) |
| TMAT_SVEBB | Trend/MA | 2-indicator band confluence | IGNORE (interesting idea, low priority) |
| ATR_MA_Trend | Trend | precomputed combo buffers | IGNORE |
| Alligator | Trend | Lips/Teeth/Jaw ordering + bitflag sub-confirmations | REPLACE (Phantom's trend.py) |
| Gator | Trend | histogram-based Alligator derivative | IGNORE |
| Ichimoku | Trend | genuine 3-part confluence (Tenkan/Kijun cross + Chikou + cloud) | IMPROVE — most sophisticated single-indicator logic in the set, worth studying |
| ADX | Trend strength | DI cross + ADX rising (confirmation layer partially disabled in source) | IMPROVE (mine the idea, ignore the broken confirmation call) |
| HeikenAshi | Price-action | synthetic-candle pattern matching | IMPROVE — candle-pattern recognition is a real gap in Phantom's scanner |
| Pattern | Price-action | generic bitmask pattern wrapper, fragile encoding | IGNORE (implementation is fragile; the idea of pattern-flags is fine, see Indi_Candle/Pattern below) |
| Pinbar | Price-action | 4-indicator confluence (Pattern+RSI+CCI+ATR) | IMPROVE — best confluence example in the set |
| ZigZag | Structure | swing-point wait-for-confirmation | REPLACE (Phantom's swing.py) |
| ElliottWave | Price-action | 2-buffer wave dynamics (confirmation partially disabled) | IGNORE (speculative, unverified) |
| Pivot | Structure | zone membership between pivot bands | REPLACE (Phantom's structure.py already computes S/R) |
| Bands, Envelopes, SVE_Bollinger_Bands | Volatility | band-touch mean-reversion | IMPROVE (Bollinger Bands specifically — genuine gap) |
| ATR, StdDev | Volatility | explicitly "not directional, gauges volatility only" per their own source comments | REPLACE (Phantom's volatility.py already does this, and feeds risk sizing — EA31337's doesn't) |
| SAWA | Misc | 2-line comparator, indicator-specific | IGNORE |
| Demo | Template | explicit placeholder/scaffold | IGNORE |
| MA, MA_Breakout, MA_Cross_Pivot, MA_Cross_Shift, MA_Cross_Sup_Res, MA_Cross_Timeframe, MA_Trend, Retracement | Meta/MA | enum-selectable MA-type + one generic signal formula each | IGNORE as trading strategies; IMPROVE the *meta-selectable-indicator* pattern as an architecture idea (see §14) |
| Oscillator, Oscillator_Cross, _Cross_Shift, _Cross_Timeframe, _Cross_Zero, _Divergence, _Multi, _Overlay, _Range, _Trend | Meta/Oscillator | enum-selectable oscillator + one generic formula each | IGNORE as trading strategies; note in §15 that these re-cover the same ~16-24 indicators as the standalone strategies above through a *different* formula — a real double-counting risk if Phantom ever added both a raw-indicator rule and a generic wrapper rule for the same indicator |
| Oscillator_Martingale | Meta/Oscillator | adds averaging-entry logic keyed off adverse price movement from an existing position | **REMOVE** — directly conflicts with CLAUDE.md's "no uncontrolled pyramiding"; do not use even as inspiration |
| Indicator | Meta | raw single-threshold gate on any arbitrary indicator/buffer | IGNORE (too generic/weak to be a real signal on its own) |
| Arrows | Meta | arrow-indicator passthrough (one working mode, one commented out) | IGNORE |

**Family-level takeaway:** none of the 68 strategies are directly
portable to Phantom's structural Strategy Engine. The real value is in
**mining 4-6 specific indicators as new independent scoring rules**
(RSI, MACD, Stochastic, Bollinger Bands, ADX) and **2 confluence
patterns as scanner/scoring ideas** (Ichimoku's 3-part confluence,
Pinbar's 4-indicator candle+oscillator confluence) — never as literal
code, and each gated by its own ADR before implementation (CLAUDE.md
§1.10).

---

## 2. Every indicator (70 classes in `EA31337-classes/Indicators/`)

| Category | Indicators | Verdict |
|---|---|---|
| Trend/MA | MA, DEMA, TEMA, AMA, VIDYA, FrAMA, CustomMovingAverage, Alligator, Gator, Ichimoku, SAR, HeikenAshi, ZigZag, ZigZagColor | REPLACE/IGNORE — Phantom's EMA-trend + structure.py already cover this ground; `ZigZagColor` is a near-duplicate of `ZigZag` |
| Momentum/oscillator | RSI, RS, Stochastic, MACD, OsMA, Momentum, ROC, CCI, WPR, DeMarker, RVI, AO, AC, BearsPower, BullsPower, TRIX, UltimateOscillator, MassIndex, CHO (Chaikin Osc), DetrendedPrice | **IMPROVE** — genuinely new capability; Phantom computes none of these today |
| Volatility | ATR, Bands, StdDev, Envelopes, CHV (Chaikin Volatility), BWZT | REPLACE (ATR) / IMPROVE (Bollinger Bands specifically; the rest are niche) |
| Volume | Volumes, OBV, AD, BWMFI, MFI, PriceVolumeTrend, VROC, WilliamsAD, Force | IMPROVE, with a caveat: real MT5 forex "volume" is tick-count, not true traded volume — flag this limitation before building anything on it |
| Structure/S-R | Pivot, PriceChannel, Fractals, Killzones (8-session) | REPLACE (Pivot/PriceChannel/Fractals — Phantom's structure.py is better) / **IMPROVE** (Killzones — genuinely more granular session model than Phantom's 3-session one) |
| Infra/utility | OHLC, Price, AppliedPrice, PriceFeeder, TickMt, ColorBars, ColorCandlesDaily, ColorLine, Demo | IGNORE (visual/testing scaffolding, not signal-relevant) |
| Custom/proprietary | Indi_Math (generic 2-buffer combinator), Indi_Candle / Indi_Pattern (bitwise multi-candle pattern flags), Indi_Killzones | IMPROVE as **architecture ideas** — the composable-combinator pattern and bitwise pattern-flag encoding are worth studying even though the indicators themselves won't be copied |
| Special/unsafe | Indi_Custom (loads arbitrary external `.ex4`/`.ex5` by path), Indi_Drawer (Redis-backed remote-drawing command channel) | **REMOVE** — arbitrary-binary-loading and unexplained external-service coupling are inappropriate for an institutional system regardless of license |
| Dead/vaporware | INDI_MARKET_FI (enum only, no class — duplicate of INDI_BWMFI), 12 `_ON_PRICE`/`INDI_SVE_BB`/`INDI_TMA_TRUE` enum entries with zero backing code | IGNORE — nothing to import |

---

## 3. Every risk management feature

**Finding: no coherent Risk Engine exists in EA31337-classes.** Risk
logic is a scattered, partly-dead set of account-condition checks:

| Feature | Where | Verdict |
|---|---|---|
| `AccountMt::CheckCondition()` (equity/margin % thresholds) | Account/AccountMt.h | REPLACE — Phantom's `risk_engine/constraints.py` (`per_trade_ceiling`, `daily_budget`, `portfolio_heat`, `currency_exposure`, `correlation_exposure`, `volatility_adjustment`, `loss_streak_adjustment`, `drawdown_scaling`) is already far more comprehensive, tested, and independently composable |
| `GetDrawdownInPct()` (live, working) | AccountMt.h | IGNORE — trivial calc, Phantom already covers this via `drawdown_scaling` + `statistical_risk/drawdown.py` |
| `GetRiskMarginLevel()` — commented-out stub despite being the most "risk engine"-sounding method name in the whole library | AccountMt.h | **REMOVE** — a documentation/reality mismatch; exactly the kind of drift CLAUDE.md's ADR-gating discipline exists to prevent |
| Balance-vs-yearly/monthly/weekly-average conditions, margin-call detection | AccountMt.h (commented out, never compiles) | REMOVE |

**Verdict overall: nothing here is worth importing.** Phantom's own
risk_engine + statistical_risk (Monte Carlo, VaR/CVaR, Risk of Ruin,
real Kelly criterion) are architecturally superior to everything found
in this reference material.

---

## 4. Every order management feature

| Feature | Where | Verdict |
|---|---|---|
| `Order.mqh` (OrderSend/Close/Modify, dummy-mode for backtesting, dual MQL4/MQL5 API abstraction) | EA31337-classes | IGNORE — Phantom's EA bridge is MQL5-only; the dual-API abstraction doesn't apply |
| `OrderQuery.h` (generic query/aggregation over an order collection) | EA31337-classes | IMPROVE (minor) — clean generic-aggregation pattern, could loosely inform future `position_manager`/analytics helpers, low priority |
| `Orders.mqh` (pool-level ops: `TotalSL`/`TotalTP`/`GetOpenLots`/etc.) | EA31337-classes | IGNORE — Phantom's `position_manager` already covers this territory with a tested, ADR-gated design |
| `BasicTrade.mqh` (legacy MT4-era class, blocking `Sleep()`-based retry loops, not included anywhere in the codebase) | EA31337-classes | **REMOVE** — dead code with a real anti-pattern (blocking sleeps on the trading thread); do not emulate even as a quick pattern for the new MQL5 EA bridge |
| EA-level Task system (declarative condition→action rules, e.g. "close all on equity drop") | EA31337 core (`ea.h::GetTaskEntry`) | IMPROVE (low priority) — Phantom's compliance_engine kill-switch + Watchdog already cover the emergency-close case; the declarative condition→action framing could inform a future Watchdog extension, but nothing urgent |
| `EATasks` — a second, unused, duplicate implementation of the exact same condition/action wiring | EA31337 core (`tasks.h`) | **REMOVE-flagged** as a cautionary example, not something to import — a live lesson in why Phantom's "no duplicate logic" rule (CLAUDE.md §1.3) matters |

---

## 5. Every trailing stop implementation

**None exist.** Full-text search across all of `EA31337-classes` found
zero files or classes named or related to "trailing." The only
trailing-adjacent mechanism is `StrategyPriceStop::GetValue()` — a
single generic, bitflag-driven stop-price formula (peak/pivot/range-add
variants) used by the 4 strategies with custom SL/TP, not a distinct
trailing-stop algorithm.

**Verdict: IGNORE.** Phantom's `position_manager/checks.py` already has
a real, tested `trailing_stop()` function — there is nothing to mine
here. The generic bitflag stop-price-formula *idea* (pivot-based or
range-based stop variants) is a minor IMPROVE candidate for
`stop_loss_adjustment()` if Phantom ever wants more stop-placement
modes, but it's low priority.

---

## 6. Every break-even implementation

**None exist**, anywhere in any of the three repos — confirmed by a
case-insensitive search for "break even"/"breakeven"/"BreakEven" across
every file. Phantom's `position_manager/checks.py::break_even()` is
already implemented and tested.

**Verdict: IGNORE.** Nothing to compare against or mine.

---

## 7 & 8. Every money management method / position sizing algorithm

(EA31337 has no separate Money class — all sizing logic lives inside
`Trade.mqh`, so these two categories are one finding set.)

| Method | Description | Verdict |
|---|---|---|
| `GetMaxLotSize()` | classic percent-risk sizing (balance × risk% ÷ SL distance) | REPLACE — Phantom's `risk_engine` does this with better separation and independent, testable constraints |
| `OptimizeLotSize()` | scales lot size up based on consecutive win/loss streak length | **REMOVE** — a mild martingale/anti-martingale hybrid; scaling size *up* off streak momentum is a well-known ruin-risk anti-pattern and conflicts with Phantom's risk philosophy (which scales size *down* after losses via `loss_streak_adjustment`) |
| `CalcLotSize()` | 4-method margin/balance-based sizing, marked in its own source as "@todo: Improves calculation logic" (i.e. the author's own admission it's unrefined) | IGNORE |
| `CalcMaxLotSize()` | commented-out dead stub | REMOVE |
| `CalcMaxOrders()` | margin-based concurrent-order cap, with optional gradual smoothing of the limit | IMPROVE (low priority) — the smoothing idea is mildly interesting, but Phantom's `portfolio_heat`/`correlation_exposure` already govern concurrent exposure more rigorously |
| **No Kelly criterion anywhere** (`kelly` search returns zero hits) | — | N/A — Phantom's `statistical_risk` module already has a real, tested Kelly-criterion implementation (`kelly_recommendation()`), which is strictly superior to anything in this reference material |
| Three near-duplicate "available risk amount" formulas inside `Trade.mqh` (`GetMaxLotSize`, `CalcLotSize`, `GetMaxSLTP` each recompute it slightly differently) | — | REMOVE-flagged as an anti-pattern lesson, not something to replicate |

**Verdict overall:** Phantom's existing risk_engine + statistical_risk
combination (independent constraint functions + Monte Carlo + VaR/CVaR
+ real Kelly) is strictly better than everything found here. This is a
clean REPLACE/IGNORE category across the board.

---

## 9. Every market filter

| Filter | Description | Verdict |
|---|---|---|
| `EA_MaxSpread` | hard spread-in-pips ceiling, checked at init and per strategy | IGNORE/REPLACE — Phantom's `compliance_engine`/`execution_validator` already have per-symbol configurable spread thresholds |
| Trade-allowed/market-open gate | checked once at `OnInit()` | IGNORE — trivial; Phantom's `MT5Adapter.connect()`/heartbeat already gates on this |
| `Meta_Spread` (routes to a different confirmation strategy based on current spread band) | implementation absent from the vendored snapshot — could not be verified | IMPROVE (speculative/low priority) — interesting idea, unverified, not worth pursuing without seeing real code |

---

## 10. Every session filter

| Filter | Description | Verdict |
|---|---|---|
| `EA_SignalOpenFilterTime` (8-session bitmask: Chicago/Frankfurt/HongKong/London/NewYork/Sydney/Tokyo/Wellington) | user-configurable session gate | **IMPROVE** — genuinely more granular than Phantom's current 3-session (Asian/London/NY) model in `scanner/session.py`; worth considering if finer session sub-structure is ever wanted |
| `Indi_Killzones` (8-session per-session high/low tracker) | same 8-session granularity, applied to indicator computation rather than gating | IMPROVE — same note as above |
| `Meta_Timezone`/`Meta_Weekday` | day/week-of-year gating strategies | IMPROVE (low priority, unverified — implementation absent from snapshot) |
| EA task day/month boundary conditions (`EA_ADV_COND_EA_ON_NEW_DAY/MONTH`) | schedule an action at calendar boundaries | IGNORE — overlaps more with `compliance_engine`'s `NewsCalendarState` territory than session filtering; low value as-is |

---

## 11. Every volatility filter

| Filter | Description | Verdict |
|---|---|---|
| `Meta_Volatility` (routes to a different confirmation strategy based on volatility band) | implementation absent from vendored snapshot, unverified | REPLACE/IGNORE — Phantom's `scanner/volatility.py` (ATR-bucketed HIGH/NORMAL/LOW/EXTREME) is already wired into both scanning *and* risk sizing *and* statistical stress-testing; EA31337's version, even if real, only routes strategy selection, doing strictly less |

---

## 12. Every trend filter

| Filter | Description | Verdict |
|---|---|---|
| `Meta_Trend` (heavily reused default trend-confirmation layer across build variants) | implementation absent from vendored snapshot, unverified | REPLACE/IGNORE — Phantom's `scanner/trend.py` (EMA-based) is already wired end-to-end through `strategy_engine`'s `trend_continuation` playbook and `risk_engine` |
| `EA_SignalOpenFilterMethod` trend-alignment bit | one of several composable open/close filter bits | IGNORE — folded into the point above |

---

## 13. Every optimization worth keeping

| Item | Description | Verdict |
|---|---|---|
| CI-driven MT5 Strategy Tester optimization (`mql-tester-action`, `.set` file start/step/stop/optimize-flag convention) | genetic/grid parameter optimization wired into GitHub Actions | **IMPROVE** — genuinely reusable operational pattern for the newly-built `mt5/PhantomBridgeEA.mq5` if/when parameter optimization is wanted; would need its own ADR since it touches CI/testing infra |
| Docker-based yearly backtest regression snapshots (pre-recorded 2017-2021 results per build variant) | a "golden" historical regression artifact per year | IMPROVE (low-medium priority) — Phantom's `paper_trading` could adopt a similar year-over-year regression-snapshot discipline |
| `__optimize__` compile-time flag suppressing logging overhead during optimization runs | build-time log-level switch | IGNORE — Python doesn't need a compile-time equivalent; Phantom's config-driven `log_level` fields already solve this |

---

## 14. Every reusable architecture component

| Component | Description | Verdict |
|---|---|---|
| Strategy factory + cache (`StrategiesManager`/`StrategiesMetaManager`, flyweight keyed by `sid@tf`) | avoids reallocating repeated strategy/timeframe instances | IGNORE — Phantom's `strategy_engine/registry.py` already solves discovery differently (auto-discovery registration) and adequately for its stateless-per-evaluation playbook model |
| Magic-number-per-(strategy,timeframe) with hard-fail on collision | structural duplicate-prevention baked into the wiring layer | **IMPROVE** (medium priority) — a nice discipline worth considering if Phantom ever runs multiple playbooks per symbol/timeframe through the same MT5 terminal and needs guaranteed non-colliding magic numbers |
| Meta-strategy chaining (confirmation layers wrapping other confirmation layers) | e.g. Trend → Spread → {indicator selection} | IGNORE — mostly validates Phantom's own existing "playbooks confirm each other, never decide/size/execute" philosophy (CLAUDE.md §2) rather than introducing something new |
| Config/inputs tiering (Lite/Advanced/Rider/Elite via compile-time flags) | four build variants from one source tree | IGNORE — not applicable to Python; Phantom's config dataclasses with sane defaults already give equivalent flexibility more cleanly |
| Generic indicator combinator (`Indi_Math`: apply a math op across two indicator buffers) | composable derived-indicator pattern | IMPROVE (architecture inspiration only) — could inform a future generic "derived scoring rule" pattern in `scoring_engine/rules` if indicator-based rules are added |
| Bitwise multi-candle pattern encoding (`Indi_Candle`/`Indi_Pattern`) | packs boolean pattern flags into one integer instead of one buffer per pattern | IMPROVE — space-efficient pattern-encoding idea, relevant if candlestick-pattern recognition is ever added to the scanner |
| Serialization-for-diagnostics (JSON dump of EA/strategy state to chart comment) | on-chart debug visibility | **IMPROVE** — directly applicable to the just-built `mt5/PhantomBridgeEA.mq5`; a similar on-chart diagnostic dump would help operators troubleshoot the EA bridge in the field |
| Resource-embedding for Strategy Tester (`#resource` bundling compiled indicators/news CSVs into the `.ex5`) | self-contained backtestable binary | IGNORE — not relevant to Phantom's transport-only EA bridge |

---

## 15. Every duplicate feature

| Duplicate | Verdict |
|---|---|
| `AccountMt` (real, used) vs. `AccountBase`/`Account<AS,AE>`/`AccountForex` (empty scaffolding, unused anywhere) | REMOVE-flagged — don't copy the dead hierarchy |
| `Trade.mqh` (real, used) vs. `BasicTrade.mqh` (legacy, unincluded anywhere) | REMOVE-flagged |
| Three near-duplicate "risk amount" formulas inside `Trade.mqh` | REMOVE-flagged (anti-pattern) |
| `EATasks` (dead) vs. `ea.h::GetTaskEntry` (live) — duplicate task-wiring implementations | REMOVE-flagged |
| `ZigZag` vs. `ZigZagColor` | IGNORE — trivial, coloring-only difference |
| `ADX` vs. `ADXW` | IGNORE — legitimate Wilder-formula variant, not an accidental duplicate |
| Meta-family (`Oscillator_*`, `MA_*`) re-covering the same 16-24 indicators already implemented as standalone strategies, via a different generic formula | IGNORE architecturally intentional, but **flag directly against CLAUDE.md's "no indicator counted twice" rule** — if Phantom ever adds both a raw-indicator scoring rule and a generic-wrapper rule for the same indicator, that would double-count a single confirmation source |
| `INDI_BWMFI` vs. `INDI_MARKET_FI` (latter is a dead enum entry with no implementing class) | REMOVE-flagged |
| `ColorBars`/`ColorCandlesDaily`/`ColorLine` (near-identical boilerplate, visual-only) | IGNORE |

---

## 16. Every outdated implementation

- `BasicTrade.mqh` — legacy MT4-era class with blocking `Sleep()`-based
  retry loops. **REMOVE-flagged.**
- `AccountMt::CheckCondition()` dead branches (balance-vs-yearly/monthly/
  weekly-average, margin-call detection) — commented out, never
  compiles. **REMOVE-flagged.**
- `AccountMt::GetRiskMarginLevel()` — commented-out stub despite being
  the most "risk engine"-sounding method name in the library.
  **REMOVE-flagged.**
- `Trade::CalcMaxLotSize()` — dead stub. **REMOVE-flagged.**
- 12 indicator enum entries with zero implementing code. IGNORE.
- `Strategy-ADX`/`Strategy-ElliottWave`'s disabled `CheckSignals()`
  confirmation calls — partially-disabled logic. IGNORE.
- `Strategy-Arrows`' commented-out `ATR_MA_Slope` option. IGNORE.

---

## 17. Everything that should NOT be copied

1. **GPLv3 license on all three repos** — the single most important
   finding. Hard legal blocker on literal code reuse; every idea above
   must be reimplemented clean-room, never adapted from the source text.
2. **`BasicTrade.mqh`'s blocking `Sleep()`-based retry loops** — a real
   anti-pattern for a live trading terminal thread. Do not emulate even
   as a "quick win" for the MQL5 EA bridge.
3. **`Oscillator_Martingale`'s live-position-aware averaging-entry
   logic** — directly conflicts with CLAUDE.md's "no uncontrolled
   pyramiding" rule. Do not adopt even as inspiration.
4. **`Indi_Custom`'s arbitrary external `.ex4`/`.ex5` binary loading by
   file path** — an arbitrary-code-loading mechanism inappropriate for
   an institutional system regardless of licensing.
5. **`Indi_Drawer`'s Redis-backed remote-drawing/command channel** —
   unrelated infra with unclear provenance/security posture, out of
   scope entirely.
6. **The two dead/unused code hierarchies** (`AccountBase` family,
   `BasicTrade.mqh`, `EATasks`) — don't copy dead scaffolding just
   because it's present in the tree; verify any candidate is actually
   live/compiled before treating it as a "proven algorithm," per the
   Engineering Charter's own instruction (`.claude/agents/TEAM.md` §8
   concern about drift risk).
7. **The three-times-duplicated risk-amount-calculation formula** —
   don't replicate this specific duplication anti-pattern in Phantom's
   own code.
8. **Product-tier (Lite/Elite/Rider/Advanced) compile-time-flag
   architecture** — not applicable to Python, adds complexity Phantom
   doesn't need.

---

## Summary / suggested next steps

Every genuine capability gap identified (new scoring rules, candlestick
patterns, 8-session model, EA-bridge diagnostics) requires **its own
Accepted ADR before any implementation begins** (CLAUDE.md §1.10) — this
report is research only and authorizes nothing.

If asked to prioritize, in descending order of value-to-effort:

1. **New independent scoring_engine rules** for RSI, MACD, Stochastic,
   Bollinger Bands, ADX — genuine gap, moderate effort, directly
   compatible with the charter's "more independent confirmations"
   philosophy. Must be built clean, not adapted from the (partially
   broken) EA31337 versions.
2. **Candlestick-pattern recognition** in the scanner, inspired by
   `Pinbar`'s 4-indicator confluence and `HeikenAshi`'s synthetic-candle
   approach — a real gap today.
3. **Extended 8-session model** in `scanner/session.py`, inspired by
   `Indi_Killzones` — straightforward, low-risk extension of an
   existing module.
4. **On-chart diagnostic JSON dump** for `mt5/PhantomBridgeEA.mq5`,
   inspired by EA31337's serialization-for-diagnostics pattern — directly
   useful for operating the EA bridge already built this session.
5. **CI-driven MT5 Strategy Tester optimization workflow** for the EA
   bridge, if/when parameter tuning is needed.

Everything else catalogued above is REPLACE, IGNORE, or REMOVE — Phantom's
existing risk_engine, statistical_risk, position_manager, and scanner
modules are already more rigorous than what this reference material
offers in those areas.
