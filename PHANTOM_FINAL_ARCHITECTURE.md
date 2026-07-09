# Phantom Final Architecture — Frozen for Approval

Status: **proposed for approval, not yet approved.** No code was
written to produce this document. No ADR was created (per explicit
instruction). `mt5/PhantomBridgeEA.mq5` and `phantom/bridge/` were not
modified — Phase 1 remains frozen pending real MT5 validation
(`PHANTOM_BRIDGE_EA_PHASE1_VALIDATION_PACKAGE.md`). No Phase 2
implementation was begun.

This document supersedes, for all *new* design work, the naming and
component boundaries implied by the historical `ADR-002`–`ADR-023`
pipeline and by `phantom_pipeline/`. Per this session's own prior,
explicit direction — "starting Phantom completely from scratch... do
not preserve packages, files, ADRs, or implementations unless they
earn their place through this design process" — those artifacts remain
on disk as reference material only, exactly as `phantom/` (legacy) and
`phantom_institutional.py` already are. Nothing in this document
deletes or modifies them; that is a separate, future decision, not
made here.

---

## 0. Scope of this freeze

Nine components, eight live and one offline-only, per the brief:

1. PhantomBridgeEA (live — already built, Phase 1, frozen)
2. Evidence Engine (live)
3. Strategy Engine (live)
4. Portfolio Statistical Risk Engine (live)
5. Market Intelligence Engine (live)
6. Prop Firm Compliance Engine (live)
7. Research & Learning Engine (live, advisory-only, never writes to
   live trading)
8. System Reliability Engine (live)
9. Validation (offline only — backtesting, replay, forward testing,
   reports, strategy comparison)

---

## 1. Final folder structure

```
phantom/                         # Python package root (already exists — Phase 1)
├── bridge/                      # Component 1 (Python side) -- FROZEN, built, no changes
├── evidence/                    # Component 2
├── strategy/                    # Component 3
├── risk/                        # Component 4
├── intelligence/                # Component 5
├── compliance/                  # Component 6
├── research/                    # Component 7
├── reliability/                 # Component 8
├── validation/                  # Component 9 -- offline only
└── shared/                      # Recommended, not yet approved -- see §14

mt5/
├── PhantomBridgeEA.mq5          # Component 1 (MQL5 side) -- FROZEN
└── PhantomBridgeEA.set          # Component 1 config template -- FROZEN

tests/phantom/
├── bridge/                      # already exists (85 tests, Phase 1)
├── evidence/
├── strategy/
├── risk/
├── intelligence/
├── compliance/
├── research/
├── reliability/
└── validation/

docs/
├── research/                    # this session's research artifacts (unchanged pattern)
├── architecture/                # existing diagrams (unchanged)
└── mt5_validation/              # Phase 1 validation package (unchanged)
```

No top-level Python package outside `phantom/` is introduced. `mt5/`
stays the sole home for MQL5 source, matching Phase 1's existing
layout.

---

## 2. Final file list and 3. responsibility of every file

### Component 1 — PhantomBridgeEA (frozen, listed for completeness only)

| File | Responsibility |
|---|---|
| `phantom/bridge/models.py` | Wire-message types: `CommandKind`, `ErrorCode`, `TradeCommand`, `ExecutionReport`, `TradeTransactionReport`, etc. |
| `phantom/bridge/config.py` | `BridgeConfig` — API key, allowed symbols, magic number, lot/slippage caps, timeouts |
| `phantom/bridge/validation.py` | Transport-integrity checks run before any state change |
| `phantom/bridge/connection_health.py` | Liveness tracking, independent of command authorization |
| `phantom/bridge/command_queue.py` | Single relay chokepoint; idempotency, TTL, emergency-stop gating |
| `phantom/bridge/engine.py` | Orchestrates the above; the only object with command-submission authority |
| `phantom/bridge/server.py` | 9-route HTTP surface |
| `phantom/bridge/logging_sink.py`, `metrics.py` | Structured logs / counters for this component only |
| `mt5/PhantomBridgeEA.mq5`, `.set` | MT5-side execution, position management, secure communication, execution quality, fail-closed safety |

No new files. This component's only remaining gate is the real-MT5
validation package already produced.

### Component 2 — Evidence Engine (`phantom/evidence/`)

| File | Responsibility |
|---|---|
| `models.py` | `MarketStructureFinding`, `Regime`, `PairScore` (0-100), `PairConfidence` types |
| `config.py` | Per-pair enablement list, indicator/lookback parameters, score-weighting config |
| `market_data_source.py` | The Evidence Engine's own narrow market-data (candle/tick history) ingestion — see §13 for why this lives here and not in a shared component |
| `market_structure.py` | BOS/CHoCH/FVG/order-block/support-resistance detection |
| `regime.py` | Trend/range/volatility regime classification, for strategy selection — distinct from Market Intelligence Engine's session/liquidity/spread quality (see §13) |
| `indicators.py` | The one deterministic indicator library Phantom uses — no second indicator implementation exists anywhere else in the system |
| `scorer.py` | Combines structure + regime + indicators into one 0-100 score per enabled pair |
| `confidence.py` | Produces the human-readable confidence explanation accompanying each score — the *why*, kept separate from the *number* so neither can silently drift from the other |
| `evidence_engine.py` | Orchestrator; the single authority for "what does the market currently look like, per pair" |
| `logging_sink.py`, `metrics.py` | This component's own structured logs/counters |

### Component 3 — Strategy Engine (`phantom/strategy/`)

| File | Responsibility |
|---|---|
| `models.py` | `StrategyKind` (LIQUIDITY_SWEEP, BOS_FVG, TREND_CONTINUATION, SESSION_BREAKOUT, RANGE_REVERSAL), `TradeIdea` |
| `config.py` | Per-strategy enablement/thresholds |
| `playbook.py` | The common playbook interface every strategy implements |
| `playbooks/liquidity_sweep.py` | Liquidity Sweep confirmation logic |
| `playbooks/bos_fvg.py` | BOS + FVG confirmation logic |
| `playbooks/trend_continuation.py` | Trend Continuation confirmation logic |
| `playbooks/session_breakout.py` | Session Breakout confirmation logic |
| `playbooks/range_reversal.py` | Range Reversal confirmation logic |
| `registry.py` | Auto-discovers installed playbooks — deliberately no hand-maintained playbook name list, matching the drift-risk lesson already recorded for this exact anti-pattern |
| `selector.py` | Given Evidence Engine's output, decides which playbook(s), if any, apply right now |
| `strategy_engine.py` | Orchestrator; produces a `TradeIdea` — never a sized, never an executed trade |
| `logging_sink.py`, `metrics.py` | This component's own structured logs/counters |

Every playbook is a confirmation layer only — none decides size or
executes, per the Charter's Strategy philosophy.

### Component 4 — Portfolio Statistical Risk Engine (`phantom/risk/`)

| File | Responsibility |
|---|---|
| `models.py` | `RiskDecision`, `PortfolioSnapshot`, `SizingRecommendation` types |
| `config.py` | Risk limits, Monte Carlo iteration count, correlation lookback, Kelly fraction cap |
| `monte_carlo.py` | Monte Carlo simulation over trade-outcome distributions |
| `var_cvar.py` | Value-at-Risk / Conditional VaR |
| `risk_of_ruin.py` | Risk-of-ruin calculation |
| `kelly.py` | Kelly-criterion sizing — **advisory only**, never auto-applied without passing through `position_sizing.py`'s own cap logic |
| `expectancy.py` | Rolling expectancy |
| `sharpe_sortino.py` | Rolling Sharpe / Sortino — the **one** place these are computed forward-looking for sizing purposes (see §13 re: Research & Learning Engine reuse) |
| `correlation.py` | Correlation matrix across open + candidate positions |
| `exposure.py` | Currency exposure aggregation |
| `portfolio_heat.py` | Aggregate open-risk heat metric |
| `position_sizing.py` | The single sizing authority — converts a `TradeIdea` + all of the above into a concrete size, or a veto |
| `confidence_scaling.py` | Applies Evidence Engine's confidence score as a scaling input to sizing — the only place confidence affects size |
| `drawdown_probability.py` | Probability-of-drawdown-breach estimation |
| `risk_engine.py` | Orchestrator; the single statistical-risk decision authority |
| `logging_sink.py`, `metrics.py` | This component's own structured logs/counters |

### Component 5 — Market Intelligence Engine (`phantom/intelligence/`)

| File | Responsibility |
|---|---|
| `models.py` | `NewsScore`, `EconomicEvent`, `PairSafetyScore` types |
| `config.py` | Calendar source config, blackout-window widths, per-event-type impact weighting |
| `calendar_source.py` | The Market Intelligence Engine's own narrow news/economic-calendar ingestion — see §13 |
| `economic_calendar.py` | Calendar normalization/query surface |
| `event_classifier.py` | Classifies events: high-impact, central bank, CPI, PPI, GDP, NFP, rate decisions, speeches |
| `session_quality.py` | Session-quality scoring (is this a liquid trading session right now) |
| `liquidity_quality.py` | Liquidity-quality scoring |
| `spread_quality.py` | Spread-quality scoring |
| `volatility_forecast.py` | Short-horizon volatility forecast |
| `peg_policy_protection.py` | Currency-peg / policy-event protection (e.g. central-bank-defended pegs) |
| `news_blackout.py` | Computes blackout windows around high-impact events |
| `pair_safety_score.py` | Aggregates the above into one per-pair Pair Safety Score |
| `news_score.py` | The individual news score (0-100) per enabled pair |
| `intelligence_engine.py` | Orchestrator; advisory-only, never trades (Charter §2 Intelligence philosophy) |
| `logging_sink.py`, `metrics.py` | This component's own structured logs/counters |

### Component 6 — Prop Firm Compliance Engine (`phantom/compliance/`)

| File | Responsibility |
|---|---|
| `models.py` | `ComplianceRuleSet`, `ComplianceDecision` types |
| `config.py` | Per-prop-firm rule sets (FTMO named explicitly by this design's brief; built as a pluggable rule set so a second prop firm's rules are additive configuration, never a duplicate compliance engine — see §12) |
| `daily_drawdown.py` | Daily drawdown rule |
| `total_drawdown.py` | Total/maximum drawdown rule |
| `trading_day_rules.py` | Minimum trading days / trading-day counting rules |
| `position_limits.py` | Maximum concurrent position count/exposure |
| `daily_trade_limits.py` | Maximum trades per day |
| `emergency_lockout.py` | Hard lockout trigger and state |
| `compliance_engine.py` | Orchestrator; the single hard-gate authority — can only reduce or reject what Risk Engine proposed, never increase it (see §13) |
| `logging_sink.py`, `metrics.py` | This component's own structured logs/counters |

### Component 7 — Research & Learning Engine (`phantom/research/`)

| File | Responsibility |
|---|---|
| `models.py` | `TradeMemoryEntry`, `AttributionResult`, `Recommendation` types |
| `config.py` | Review cadence, RAG retrieval parameters |
| `trade_memory.py` | Durable record of every completed trade and its full decision chain |
| `rag.py` | Retrieval-augmented generation over trade memory for natural-language queries |
| `pattern_discovery.py` | Discovers recurring patterns in trade memory |
| `performance_attribution.py` | Attributes outcomes to strategy/pair/session — **reads** Risk Engine's stored rolling stats rather than recomputing Sharpe/Sortino/expectancy independently (see §13) |
| `trade_explainer.py` | Produces a human-readable explanation for every trade, from the full Evidence -> Strategy -> Intelligence -> Risk -> Compliance chain that produced it |
| `weekly_review.py`, `monthly_review.py` | Periodic institutional-style review generation |
| `strategy_ranking.py` | Ranks strategies by realized performance |
| `recommendations.py` | Emits recommendations only — structurally unable to write back into live trading (see §14 for how this boundary is enforced) |
| `research_engine.py` | Orchestrator |
| `logging_sink.py`, `metrics.py` | This component's own structured logs/counters |

### Component 8 — System Reliability Engine (`phantom/reliability/`)

| File | Responsibility |
|---|---|
| `models.py` | `HealthStatus`, `AlertEvent` types |
| `config.py` | Health-check intervals, latency thresholds, kill-switch triggers |
| `watchdog.py` | Periodic health checks across every other component |
| `auto_recovery.py` | Automated recovery actions for known-recoverable failure modes |
| `health_monitor.py` | Aggregate system health surface |
| `broker_connectivity.py` | Monitors PhantomBridgeEA's own reported connection health (reads, never duplicates, the bridge's `ConnectionHealth`) |
| `latency_monitor.py` | End-to-end latency tracking across the command/report round trip |
| `kill_switch.py` | The one system-wide emergency-stop authority above PhantomBridgeEA's own transport-level halt — a distinct, higher authority, never merged with it (matching the Charter's note that the bridge's `EmergencyStopState` is transport-level only, not this component's future authority) |
| `logging.py` | The underlying structured-log sink/rotation/retention layer every other component's own `logging_sink.py` writes through — one logging infrastructure, not eight |
| `reliability_engine.py` | Orchestrator |
| `metrics.py` | This component's own counters |

### Component 9 — Validation (`phantom/validation/`, offline only)

| File | Responsibility |
|---|---|
| `models.py` | `BacktestResult`, `ReplaySession`, `ComparisonReport` types — deliberately reuses each live component's own `models.py` types for inputs/outputs rather than inventing parallel ones |
| `config.py` | Backtest/replay parameters |
| `backtest_engine.py` | Historical strategy backtesting |
| `replay_engine.py` | Tick/bar replay of a historical window |
| `forward_test.py` | Forward-test (paper) session runner |
| `performance_reports.py` | Report generation |
| `strategy_comparison.py` | Side-by-side strategy comparison |
| `runner.py` | CLI/entry point tying the above together |

Validation never imports any live component's `engine.py`/orchestrator
directly — only their `models.py` types plus its own historical data —
so the offline/online boundary is structurally checkable the same way
`tests/phantom/bridge/test_structural_boundary.py` already checks
Phase 1's boundary.

---

## 4. Data flow

```
                     MT5 terminal (account/position/order state)
                              |
                    PhantomBridgeEA (mt5/*.mq5)
                              |  heartbeat / account / positions / orders /
                              |  execution reports / trade-transaction mirror
                              v
                     phantom/bridge (Component 1)
                              |
        (execution telemetry only -- not OHLC market data, not news)
                              |
              -----------------------------------
              |                                 |
   phantom/evidence (Component 2)     phantom/intelligence (Component 5)
   owns its OWN market-data           owns its OWN news/economic-
   ingestion (candles/ticks) via      calendar ingestion via
   market_data_source.py              calendar_source.py
```

Two, and only two, ingestion points exist, deliberately scoped to
different data domains (price history vs. news/calendar) so neither
duplicates the other. See §13 for why a third, shared ingestion
component was considered and not adopted.

## 5. Trading flow

```
Evidence Engine (score + confidence, every enabled pair, continuously)
        -> Strategy Engine (selector picks a playbook, produces a TradeIdea)
                -> Market Intelligence Engine (Pair Safety Score can suppress the idea)
                        -> Portfolio Statistical Risk Engine (sizes or vetoes)
                                -> Prop Firm Compliance Engine (hard gate: reduce or reject only)
                                        -> PhantomBridgeEA (executes exactly the resulting command)
```

## 6. Risk flow

```
Portfolio Statistical Risk Engine consumes:
  - PhantomBridgeEA's reported open positions (current exposure)
  - Strategy Engine's TradeIdea (candidate)
  - Evidence Engine's confidence score (scaling input)
  - Market Intelligence Engine's Pair Safety Score (scaling/veto input)
  - its own rolling stats (expectancy, Sharpe, Sortino, VaR/CVaR, risk of ruin)
        -> produces a SizingRecommendation or a veto
        -> handed to Prop Firm Compliance Engine, which may only shrink or reject it,
           never enlarge it (single authority split -- see §13)
```

## 7. News flow

```
Market Intelligence Engine:
  calendar_source.py (ingestion)
    -> economic_calendar.py (normalize/query)
      -> event_classifier.py (CPI/PPI/GDP/NFP/rate-decision/speech/central-bank)
        -> news_blackout.py + session_quality.py + liquidity_quality.py +
           spread_quality.py + volatility_forecast.py + peg_policy_protection.py
          -> pair_safety_score.py + news_score.py (per-pair outputs)
            -> consumed by Strategy Engine (suppression) and Risk Engine (scaling)
```

## 8. Intelligence flow

*(Read as the Research & Learning Engine's own pipeline — see the note
in §11 on why "News flow" and "Intelligence flow" are two distinct
items even though both components have "Intelligence" in their name.)*

```
Every completed trade's full decision chain (Evidence + Strategy +
Intelligence + Risk + Compliance snapshots at decision time, plus
PhantomBridgeEA's actual execution outcome)
        -> trade_memory.py (durable record)
            -> rag.py + pattern_discovery.py (retrieval / recurring-pattern mining)
            -> performance_attribution.py (reads Risk Engine's stored rolling stats)
            -> trade_explainer.py (human-readable per-trade explanation)
            -> weekly_review.py / monthly_review.py / strategy_ranking.py
                -> recommendations.py (recommendations only, to a human -- never
                   back into Strategy Engine's selector or Risk Engine's sizing
                   automatically)
```

## 9. Execution flow

```
Prop Firm Compliance Engine's approved (possibly reduced) command
        -> submitted to PhantomBridgeEA (phantom/bridge engine.submit_command)
            -> validated (fail-closed if bridge unreachable/stale)
            -> queued -> polled by mt5/PhantomBridgeEA.mq5
                -> pre-flight checks (terminal/account/symbol/volume/stops)
                -> CTrade execution, bounded requote retry only
                -> ExecutionReport (real filled price/volume) sent back exactly once
                -> OnTradeTransaction mirror sent independently, for drift detection only
```

## 10. Decision flow

The master sequence tying every component together end to end:

1. Evidence Engine continuously scores/explains every enabled pair.
2. Strategy Engine's selector produces a `TradeIdea` where evidence
   crosses its own threshold.
3. Market Intelligence Engine's Pair Safety Score can suppress the idea
   before it reaches sizing (e.g. inside a news blackout window).
4. Portfolio Statistical Risk Engine sizes the surviving idea, or
   vetoes it on statistical grounds (correlation, portfolio heat, risk
   of ruin).
5. Prop Firm Compliance Engine performs the final hard gate — it may
   only shrink or reject, never enlarge, what Risk Engine proposed.
6. PhantomBridgeEA executes exactly the resulting command and nothing
   else.
7. System Reliability Engine watches every step above for health,
   latency, and connectivity, and can kill-switch the entire chain at
   any point, independent of what any other component decided.
8. Research & Learning Engine observes completed trades afterward,
   producing explanations and recommendations for a human — never
   feeding anything back into steps 1–6 automatically.
9. Validation is a fully separate, offline, non-realtime path: it only
   ever consumes historical data to backtest/replay/forward-test a
   *candidate* change before that change is proposed for the live
   Strategy Engine (step 2) — it never runs against, or is invoked by,
   the live decision chain.

---

## 11. Why every component exists

| Component | Exists because |
|---|---|
| PhantomBridgeEA | Something must be the one thing that actually talks to MT5. Every other component would otherwise need its own execution path — the exact duplication the Charter forbids. |
| Evidence Engine | Every downstream component (Strategy, Risk, Intelligence's scaling) needs one shared, factual answer to "what does the market look like right now, per pair" — without it, each would compute its own market-structure read, duplicating indicators/structure logic per component. |
| Strategy Engine | Evidence alone is not a trade idea — something must decide *which* pattern, if any, the current evidence matches, without itself sizing or executing. |
| Portfolio Statistical Risk Engine | Sizing and portfolio-level risk (correlation, heat, ruin probability) require account-wide state no single strategy or pair-level component can see; it must be one authority so two strategies can never independently size conflicting exposure. |
| Market Intelligence Engine | News/session/liquidity conditions are a distinct data domain from price structure (Evidence Engine) and from statistical risk (Risk Engine) — a fact about the world, not a decision, that both of those need as an input. |
| Prop Firm Compliance Engine | Regulatory/prop-firm rules are legal/contractual constraints, categorically different from Risk Engine's statistical optimization — conflating them risks a "the math says it's fine" override of a hard rule. |
| Research & Learning Engine | Explaining and improving the system over time requires reading its own history — but must be structurally incapable of writing back into live decisions, or it becomes an ungoverned second decision authority. |
| System Reliability Engine | Every other component can fail independently; something must watch all of them and hold a kill switch that no single component's own internal logic can override. |
| Validation | Any proposed change to Strategy Engine's playbooks or Risk Engine's parameters must be testable against history before it ever reaches the live path — without this, "test in production" becomes the only option. |

## 12. Why every component is not duplicated

- **No duplicate indicators:** `phantom/evidence/indicators.py` is the
  only indicator library in the system; Strategy Engine's playbooks
  consume Evidence Engine's output, they never recompute their own
  indicators.
- **No duplicate scoring:** Evidence Engine's 0-100 score and Market
  Intelligence Engine's news score answer different questions (price
  structure vs. news/session safety) and are never combined into a
  single number by either component — combination, if ever wanted, is
  Risk Engine's job (via `confidence_scaling.py`), not theirs.
- **No duplicate risk calculations:** all statistical risk math lives
  in `phantom/risk/`; Research & Learning Engine's
  `performance_attribution.py` reads Risk Engine's stored rolling
  stats rather than recomputing Sharpe/Sortino/expectancy itself (see
  §13 — this is the one place duplication was a real risk, and the
  contract above is how it's avoided).
- **No duplicate execution paths:** PhantomBridgeEA is the only
  component that ever calls into MT5; no other component holds a
  broker connection.
- **No duplicate news processing:** all calendar/news ingestion and
  classification lives in `phantom/intelligence/`; no other component
  parses an economic calendar independently.
- **No duplicate AI:** Research & Learning Engine is the only
  component using RAG/generative techniques; Market Intelligence
  Engine's event classification is deterministic rule-based
  classification, not a second AI system, and PhantomBridgeEA has none
  at all (Charter §1/§2: "No AI. No intelligence" in the execution
  layer).
- **No duplicate compliance:** Prop Firm Compliance Engine is the only
  component that can hard-reject a trade for rule reasons; Risk Engine
  can veto on statistical grounds, but that is a different authority
  answering a different question (see §13's explicit split).

## 13. Remaining overlap or unnecessary complexity identified

Named plainly, per the instruction to identify — not hide — anything
that isn't already clean:

1. **Risk Engine vs. Compliance Engine both touch "position
   limits"/"exposure."** Without an explicit authority order, both
   could plausibly reject or resize the same trade for overlapping
   reasons, and it would be ambiguous which decision wins. **Resolved
   in this design** by a strict rule stated in §6/§11: Risk Engine
   proposes a size (or vetoes on statistical grounds); Compliance
   Engine may only shrink or reject what Risk Engine proposed, never
   enlarge it, and its rejections are for rule reasons only (drawdown/
   trading-day/position-count/trade-count limits), never statistical
   ones. This must be enforced structurally when built (e.g. Risk
   Engine's output type has no setter Compliance Engine could use to
   increase it), not merely by convention.
2. **Evidence Engine's `regime.py` vs. Market Intelligence Engine's
   `session_quality.py`/`liquidity_quality.py`/`spread_quality.py`.**
   Both describe "market conditions" and a careless implementation
   could grow into two overlapping "is now a good time to trade"
   scores. **Resolved** by an explicit question-boundary: Evidence
   Engine's regime answers "what kind of price structure is this, for
   strategy selection" (trending/ranging/volatile); Market
   Intelligence Engine's quality scores answer "is it safe/liquid to
   execute right now, for risk/compliance gating." Different
   questions, different consumers downstream — but this boundary is a
   design decision that must be documented in each component's own
   docstrings when built, not left implicit.
3. **Research & Learning Engine's `performance_attribution.py` vs. Risk
   Engine's `expectancy.py`/`sharpe_sortino.py`.** Both are performance
   statistics; a naive build would compute Sharpe/Sortino/expectancy
   twice, once forward-looking (for sizing) and once backward-looking
   (for review), with no guarantee the two ever agree. **Resolved** by
   the explicit reuse contract in §11/§12: Research & Learning Engine
   reads Risk Engine's stored historical values rather than
   recomputing them.
4. **No dedicated Data Pipeline component.** The brief's 8-component
   list has no ingestion component, unlike the historical
   `phantom_pipeline`'s `ADR-013 Data Pipeline`. This design resolves
   it by giving Evidence Engine and Market Intelligence Engine each
   their own narrow, non-overlapping ingestion module (§4) rather than
   inventing a 9th live component the brief didn't ask for. This is a
   deliberate simplification, not an oversight — flagged here so it
   can be revisited if a third component ever needs raw market data or
   news data (at which point extracting a shared ingestion module
   would become justified, not before).
5. **System Reliability Engine's `kill_switch.py` vs. PhantomBridgeEA's
   existing `EmergencyStopState`/`EmergencyDisable`.** These are two
   different authorities at two different layers (bridge = transport-
   level halt of command issuance; System Reliability Engine =
   system-wide halt of the *entire* decision chain, including
   components that never touch the bridge directly, like Strategy
   Engine's idea generation). This is intentional per the Charter's
   own note that the bridge's emergency stop is "the transport-level
   halt for this component only... not the future Risk Engine's
   trading-decision kill-switch, nor the future Watchdog's
   infrastructure emergency stop." Named here so it is not later
   mistaken for accidental duplication.

## 14. Recommended final simplifications

1. **Add one small `phantom/shared/` module** (not yet approved — a
   recommendation, not a decision made unilaterally here) holding only
   genuinely common, stable primitives: a `Pair`/`Symbol` value type, a
   `Direction` enum, a `Clock` protocol, and the `SCHEMA_VERSION`
   convention already established in `phantom/bridge/models.py`. Every
   one of the 8 live components currently needs at least one of these;
   without a shared home, each would independently reinvent the same
   basic type, which is itself a form of duplication the "no duplicate
   logic" principle argues against. Keep this module deliberately
   tiny — value types and protocols only, never behavior, never a
   dumping ground.
2. **Enforce the Risk-Engine-reuse contract in §13 item 3
   structurally**, the same way Phase 1 enforces its own boundaries —
   a `test_structural_boundary.py`-style test in
   `tests/phantom/research/` asserting `phantom/research/*.py` never
   reimplements a Sharpe/Sortino/expectancy calculation, only imports
   `phantom/risk`'s.
3. **Enforce the Compliance-Engine-only-shrinks contract in §13 item 1
   structurally** — Risk Engine's `SizingRecommendation` type should
   make "increase this size" structurally unrepresentable from
   Compliance Engine's code path (e.g. Compliance Engine's function
   signature only ever takes a size and returns a size `<=` it, never
   receiving anything it could use to compute a larger one).
4. **Enforce the Validation offline boundary the same way Phase 1's own
   `test_structural_boundary.py` does** — a test asserting no file
   under `phantom/validation/` imports any other live component's
   `engine.py`/orchestrator module, only `models.py` types.
5. **No other simplification is recommended.** Eight live components
   plus one offline component, each with a single, named
   responsibility and an explicit non-duplication contract with its
   nearest neighbors, is not excess for a system whose stated mission
   is institutional-grade capital preservation across execution,
   statistical risk, regulatory compliance, and market/news awareness
   — collapsing any two of the eight would reintroduce exactly the
   "one authority per responsibility" violation this design was built
   to avoid.

---

## Stop condition

This document is the complete architecture freeze requested. No code
was written, no ADR was created, `PhantomBridgeEA` was not touched, and
no Phase 2 implementation was begun. This is submitted for approval;
implementation of any component above should not begin until that
approval is given, and — per the existing Phase 1 gate — real MT5
validation of PhantomBridgeEA should still be treated as outstanding
regardless of this document's approval status.
