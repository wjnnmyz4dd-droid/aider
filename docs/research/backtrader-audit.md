# Repository Research — 3 of 5: mementum/backtrader

Status: **Complete.** Per your framing, backtrader is scoped to
strategy validation/backtesting ideas only — it does not change the
approved 7-component EA runtime architecture. No code was written or
copied.

License: **GPLv3** (full copyleft) — governs the *code*; the ideas
below (Sharpe/SQN/Calmar/VWR formulas, the analyzer-pattern shape, the
broker-interface-abstraction concept) are generic quantitative-finance
and software-architecture concepts, not copyrightable expression, and
are reimplemented from scratch, never copied.

---

## 1. Complete audit

### 1.1 Architecture

One orchestrator, `Cerebro`, wires together six collaborator kinds:
Feeds (historical/live data), Strategy (user logic), Indicator, Sizer
(pluggable position sizing, decoupled from strategy logic), Broker
(`BackBroker` for simulation; `IBBroker`/`OandaBroker`/`VCBroker` for
live — **all sharing the same `buy`/`sell`/`getcash`/`getvalue`/
`getposition` interface**), and Analyzer (read-only performance
measurement). `Cerebro.run()` decides vectorized (`runonce`, indicators
computed in one pass over preloaded data) vs. event-driven (`runnext`,
forced for live/replay data) execution, but strategy logic and order
matching are *always* bar-by-bar regardless of mode — vectorization
only accelerates indicator math.

**The single most important architectural fact:** the same `Strategy`
subclass runs unmodified whether the broker underneath it is a
historical-fill simulator or a live broker — swapping `cerebro.broker`
is the only change needed to go from backtest to live.

### 1.2 Internal component wiring

Not a networked system. Cerebro constructs the strategy with data feeds
as constructor args, then attaches analyzers/observers/sizers post-
construction. Strategy → Broker is direct, synchronous (`buy()`/`sell()`
calls). Broker → Strategy is a per-bar notification queue drained once
per loop iteration. **Analyzers are structurally read-only** — they
receive one-way notifications (`notify_order`, `notify_trade`,
`notify_cashvalue`, `next`) and expose results only via `get_analysis()`;
there is no method by which an analyzer can submit an order or mutate
broker/strategy state. This is real, enforced separation, not just a
convention.

### 1.3 Security

N/A — no network exposure, no untrusted-input boundary beyond ordinary
file parsing. No finding forced here.

### 1.4 Error handling / look-ahead-bias prevention

Minimal exception vocabulary (two real exception subclasses total);
most failure modes (insufficient margin, order rejection) are status
codes, not exceptions. **Look-ahead-bias prevention is structural, not
a runtime check**, via two independent mechanisms: (1) every data line
is indexed relative to "now" with no forward-index ever exposed to
strategy code, and (2) orders created inside `next()` are matched
against the *next* bar's price, with broker order-matching running
before the strategy sees the new bar each loop iteration. Two explicit,
off-by-default, clearly-labeled "cheat" modes (`coc`/`coo`) exist as
escape hatches — never adopt these, see §2 below. Missing/bad data is
handled by a gap-filling wrapper, not exceptions. Insufficient
cash/margin surfaces as an `Order.Margin` status transition. **Full-size
fills are the default with no volume-awareness unless a filler is
explicitly configured** — optimistic for illiquid instruments.

### 1.5 Performance

Vectorized indicator computation (default) vs. forced event-driven mode
for live/replay data — a real, explicitly documented tradeoff. A
documented memory-saving mode trades preloading/plotting for bounded
RAM on very large datasets. Parameter-sweep optimization runs
parallelize via `multiprocessing.Pool`, with the library's own authors
claiming concrete speedups (~20-32%) from preloading data once and
returning lightweight result objects instead of full strategy trees.
Community performance complaints about per-bar Python object overhead
at scale are real but externally sourced (not verifiable from the
shallow clone).

### 1.6 Strengths

- The Analyzer pattern is a genuinely clean, structurally-enforced
  read-only boundary — directly matches Phantom's own "intelligence is
  advisory-only" principle and gives it a concrete implementation shape.
- Composable analyzers built from one shared computation (Sharpe,
  Calmar, and VWR all wrap the same underlying return-series
  calculation) — a real no-duplicate-computation pattern.
- One shared timeframe-boundary detector reused by every time-bucketed
  analyzer instead of five separate reimplementations.
- Fund-mode vs. total-equity accounting distinction — a real-world
  nuance (capital additions/withdrawals) most hobby backtesters skip,
  directly relevant to a prop-firm context.
- Same strategy code runs backtest or live via a shared broker
  interface — the single highest-value idea here.
- A small, explicit, named set of fill/slippage/commission knobs
  (percentage-or-fixed slippage capped at bar high/low, volume-based
  partial fills via a pluggable function, explicitly-labeled cheat
  modes that are off by default) rather than an implicit "instant full
  fill at any price."

### 1.7 Weaknesses

- De facto unmaintained (last commit 2023-04-19; community maintains a
  bugfix-only fork with no feature roadmap) — mine it, never depend on
  it as a library.
- Minimal error taxonomy — most failures are status codes, not
  exceptions, giving no structured way to distinguish an expected
  trading outcome from a bug or data corruption.
- No first-class walk-forward/out-of-sample split, Monte Carlo, or
  parameter-robustness tooling in core — its parameter-sweep
  optimization is a brute-force grid search that says nothing about
  robustness or overfitting on its own.
- Full-size fills by default, no volume-awareness unless configured.
- Cheat-on-close/cheat-on-open exist as reachable settings in the base
  broker — a temptation, even though off by default.
- Four parallel "run the loop" implementations for one concept
  (vectorized/event-driven × current/legacy-compat variants) — real
  internal duplication risk, exactly the kind of thing Phantom's
  charter flags as a defect.
- A global mutable object cache that the library's own docs admit
  "breaks things... corner cases" and is disabled by default — a
  shared-mutable-state smell.

### 1.8 Maintenance status

Last commit 2023-04-19. ~22.4k stars / ~5.2k forks (historical
adoption, not current maintenance activity). Community fork exists
purely to keep bugfixes flowing, no new-feature roadmap. GPLv3.

---

## 2. KEEP / IMPROVE / REMOVE / IGNORE

| Item | Verdict | Why |
|---|---|---|
| Same strategy/risk code runs against historical data or live broker via one shared execution interface | **KEEP as the core design principle** | This is the concrete mechanism that lets Phantom validate a strategy before it goes live without maintaining two parallel implementations |
| Read-only Analyzer contract (one-way notification in, `get_report()`-style output only, no callback that can mutate state) | **KEEP as the shape for any Phantom validation reporting** | Directly matches and reinforces the already-approved `intelligence` component's advisory-only structural isolation |
| Composable metrics built on one shared equity-curve/return-series computation | **KEEP** | Avoids duplicate-computation drift across Sharpe/drawdown/Calmar-equivalent metrics |
| Small, explicit, named fill/slippage/commission parameters | **KEEP** (as a design shape) | Auditable and realistic; the alternative (implicit instant-fill-at-any-price) is not acceptable for a capital-preservation-first system |
| Minimum-period/warm-up gating before a strategy sees real trading logic | **KEEP** | Should be a first-class, testable boundary in Phantom's validator, not an incidental off-by-one |
| Timeframe-boundary detection as one shared utility | **KEEP** (minor) | Reusable pattern for any period-bucketed reporting |
| Fund-mode vs. total-equity accounting distinction | **IMPROVE** (worth considering) | Relevant for a prop-firm context with account resets/top-ups; not urgent, but worth designing for from the start rather than retrofitting |
| Walk-forward / out-of-sample validation, Monte Carlo, parameter-robustness testing | **IMPROVE** (build fresh) | backtrader's core has none of this — it's exactly the gap Phantom's own validation capability needs to fill, informed by this audit's finding that grid-search optimization alone says nothing about robustness |
| Vectorized-vs-event-driven dual execution mode | **IGNORE** | Optimization-only concern; Phantom's validator can start fully event-driven (simpler, matches "no unnecessary abstraction") and revisit only if a real performance need appears |
| Brute-force parameter grid search as the sole optimization tool | **IGNORE** | Not something to adopt as-is; if Phantom ever wants parameter search, it must be paired with the walk-forward/robustness machinery from the IMPROVE row above, never presented alone as validation |
| Cheat-on-close / cheat-on-open | **REMOVE** (never implement, not even as an opt-in toggle) | A validator's entire value proposition is that a passing backtest could plausibly have been achieved live; any cheat mode undermines that guarantee |
| Full-size, volume-blind fills as a default | **REMOVE** (never make this the default) | Overstates achievable execution; conflicts with capital preservation as the top risk-philosophy priority |
| Global mutable object cache for speed | **REMOVE** (anti-pattern) | The library's own docs admit it breaks things in corner cases; not acceptable given Phantom's zero-tolerance stance on race conditions and non-deterministic behavior |
| Four parallel "run the loop" implementations for one concept | **REMOVE** (anti-pattern) | Legacy-compatibility debt; never let a validation engine accumulate multiple parallel execution-loop implementations for the same job |
| Minimal status-code-only error handling (no exceptions for most failure modes) | **REMOVE** (anti-pattern, don't replicate) | Gives no structured way to distinguish an expected trading outcome from a bug; Phantom's validator should prefer explicit, typed failure signals |

## 3. Does this change the 7-component architecture?

**No change to the seven components' core responsibilities.** Per your
own framing, and confirmed by this audit: backtrader has nothing to say
about market structure, strategy signal generation, risk sizing,
advisory intelligence, health monitoring, or configuration — its entire
value is in the "validate before going live" question, which sits
*alongside* the live runtime, not inside it.

**The recommended shape is a separate, offline-only validation
capability — not an 8th live-runtime component — built on one
principle borrowed directly from backtrader's strongest idea:**

- The Strategy Engine and Risk Engine components run **exactly the
  same code** whether their execution target is `bridge/` (live,
  talking to the real EA) or a historical-fill simulator implementing
  the identical execution interface. The only thing that changes is
  which implementation of that interface is wired in — the same shape
  as swapping `BackBroker` for `IBBroker` in Cerebro.
- This means the validation capability's only new code is: (a) a
  historical-data feed reader, (b) a fill simulator implementing the
  same interface `bridge/command_queue.py` exposes to the rest of the
  system, with explicit, named slippage/partial-fill/commission
  parameters and no cheat modes, and (c) a small set of read-only,
  composable performance analyzers (Sharpe/drawdown/Calmar-equivalent
  metrics, all built on one shared equity-curve computation) reporting
  on a completed run.
- This validation capability never runs during live trading, never
  feeds back into any live decision, and is structurally incapable of
  it — it consumes the Strategy/Risk Engine's output, it never becomes
  a second decision authority. This keeps "one authority per decision"
  intact: adding it doesn't introduce a new place that decides
  anything; it introduces a new place that *replays* the same decision
  logic against history and reports on it.

**Proposed minimal addition to the folder structure** (everything else
from the consolidated architecture report unchanged):

```
phantom/
├── validation/
│   ├── __init__.py
│   ├── historical_feed.py      — reads historical bars, feeds them through the same scanner/strategy/risk pipeline
│   ├── fill_simulator.py        — implements the same execution interface as bridge/command_queue.py; explicit slippage/partial-fill/commission params, no cheat modes
│   ├── analyzers.py              — read-only, composable performance metrics built on one shared return-series computation
│   └── report.py                  — produces the final validation report; never callable from any live decision path
```

This is additive and clearly separable — if you'd rather fold it
directly into `risk/` (since a Quant-Validation-style capability is
advisory to risk decisions) instead of a standalone `validation/`
package, that's a legitimate alternative; the substantive design
(shared execution interface, read-only analyzers, no cheat modes) is
the same either way. Flagging both placements for your decision rather
than picking unilaterally, since you asked to decide on any
architecture adjustment before implementation starts.

---

## Repository research status

All three of your approved repositories are now complete:
1. MQL5-JSON-API-2 — `docs/research/mql5-json-api-2-audit.md`
2. darwinex/dwx-zeromq-connector — `docs/research/dwx-zeromq-connector-audit.md`
3. mementum/backtrader — this document

Two remain unapproved and unstarted: TA-Lib and the MetaTrader 5
Standard Library. **Waiting for your direction**: research those two
before implementation, or proceed directly to deciding the
`validation/` placement question above and starting implementation.
