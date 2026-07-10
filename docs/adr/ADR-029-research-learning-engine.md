# ADR-029 — Research & Learning Engine

Status: **Accepted**

Owner: Quant Validation Engineer (per `.claude/agents/TEAM.md`'s own
charter — "statistical strategy-edge validation... advisory only,
never modifies strategy" is exactly this engine's mandate)

Accepted By: User direction, this session (explicit, full
specification: mission, the 8 named inputs, the full "track everything"
field list, 13-dimension performance attribution, pair/strategy/session
intelligence, execution quality monitoring, market-intelligence and
risk effectiveness review, a deterministic recommendation engine,
5-period reporting, architecture rules, performance targets, and a
9-category testing mandate) — the same in-session approving authority
already used to accept `ADR-024` through `ADR-028`.

Reviewed by: (post-hoc, this session) — checked against `ADR-010`
(Analytics & Decision Provenance), `ADR-019` (Self-Evolving Market
Structure Research Agent), and `ADR-021` (AI Research Desk) before
acceptance; see §0.

Date: 2026-07-10

Depends on: `ADR-024`–`ADR-028` (all Accepted — consumes
`EvidenceSnapshot`, `MarketIntelligenceSnapshot`, `StrategySnapshot`,
`RiskSnapshot`, `ComplianceSnapshot`, `PortfolioState`, `AccountState`
read-only), and reuses `phantom.risk_engine.statistics`'s existing pure
statistical functions rather than a second implementation (§4).

---

# 0. Relationship to existing architecture

Three existing packages sit in adjacent territory, disclosed rather
than hidden:

- **`ADR-010` Analytics & Decision Provenance (`phantom_pipeline/analytics/`)**
  — the closest conceptual relative: `TradeProvenanceRecord` and
  `PerformanceStatistics` are exactly a "track everything per trade,
  then compute statistics" package.
- **`ADR-021` AI Research Desk (`phantom_pipeline/research_desk/`)** —
  AI-agent-driven (`MarketResearchAgent`, `BullBearDebateAgent`,
  `TradeThesisGenerator`, `AITradeJournal`, etc.). This ADR's Research &
  Learning Engine is the explicit opposite: **no ML, no LLM decision
  making** (Hard Rule, §5) — every ranking, attribution, and
  recommendation here is a deterministic statistical computation, never
  a generated narrative or model inference.
- **`ADR-019` Self-Evolving Market Structure Research Agent** — also
  AI/agent-shaped; same distinction applies.

Per the now-five-times-established `phantom/` track precedent
(`ADR-024`–`ADR-028` §0, each disclosing the same class of overlap and
resolving it identically): **fresh, independent, no reuse.**
`phantom/research_engine/` is built clean-room, imports nothing from
`phantom_pipeline/`, and does not share a record type, statistics
implementation, or recommendation mechanism with any of the three.

The one exception, by design: this engine **does** import
`phantom.risk_engine.statistics.compute_statistical_metrics` and its
`TradeResult`/`TradeHistory` types directly, converting its own richer
`ClosedTrade` records into `risk_engine`'s simpler shape purely to reuse
its already-implemented Sharpe/Sortino/VaR/CVaR/drawdown/Kelly formulas
per pair/strategy/session bucket, rather than a third implementation of
the same statistics. This is the identical reuse move `ADR-028` made
for `phantom.risk_engine.exposure` — reusing a sibling `phantom/`
package's already-accepted pure functions is not a duplicate
calculation, it is the alternative to one (Hard Rule, §5).

---

# Pipeline position

Per `ADR-001`'s spirit, this is **not** a numbered pipeline stage — like
`ADR-010`/`ADR-021`/`ADR-022` before it, it is a cross-cutting, entirely
advisory observer that reads already-produced records after the fact.
Nothing in the deterministic pipeline calls into this package, and it
never calls into a pipeline stage's decision method. Per the user's
stated sequence, this is Phase 2F; Validation remains unimplemented and
out of scope here.

---

# 1. Mission

**The Research & Learning Engine is the ONLY authority responsible for
measuring, analyzing, and recommending improvements based on historical
system performance.** It never places trades, rejects trades, sizes
positions, changes strategies, changes parameters, modifies live
behavior, or communicates with MT5. It is completely advisory —
recommendations require explicit operator approval before any
configuration change (Hard Rule, §5).

---

# 2. Inputs

Consume ONLY: `EvidenceSnapshot` (`ADR-024`), `MarketIntelligenceSnapshot`
(`ADR-025`), `StrategySnapshot` (`ADR-026`), `RiskSnapshot` (`ADR-027`),
`ComplianceSnapshot` (`ADR-028`), `PortfolioState` (`ADR-027` type),
`AccountState` (`ADR-028` type) — all read-only, all reused directly,
never redefined — plus one genuinely new type this ADR defines:
**`ClosedTradeHistory`** (§3).

## 3. `ClosedTradeHistory` / `ClosedTrade` — design decision

None of the seven named snapshot/state types carry a *closed trade's*
full lifecycle: entry/exit prices, stop-loss/take-profit, holding time,
execution-quality facts (slippage, requotes, fill time), or the tags
this phase's own "track everything" list requires (session, news
category, volatility bucket, candlestick pattern, S/R interaction,
liquidity sweep, BOS/FVG). This is exactly the same gap `ADR-027`
(`PortfolioState`/`TradeHistory`) and `ADR-028` (`AccountState`) each
resolved the same way: **a new, caller-supplied, pre-aggregated record
type**, defined here since this is the first stage that needs it.
`ClosedTrade` is deliberately richer than `phantom.risk_engine.models.TradeResult`
(which only carries `pair`/`strategy_id`/`risk_r`/`r_multiple`/
`opened_at`/`closed_at`/`won`) — this engine converts the subset it
needs into that simpler shape purely to reuse Risk Engine's statistics
functions (§0), never the reverse.

Day-of-week is deliberately **not** a stored field — it's derived from
`opened_at.weekday()` at attribution time, so there is exactly one
source of truth for it, never two that could drift.

---

# 4. Hard Rules (Architecture)

1. **No ML. No LLM decision making. No automatic optimization. No
   parameter mutation. No execution.** Every ranking, attribution
   bucket, and recommendation is a plain deterministic computation over
   `ClosedTradeHistory` plus the six read-only snapshot/state types —
   verified by `test_architecture.py` (no ML-library import, no
   randomness, no mutation method on any config/state type).
2. **Read-only, deterministic, thread safe.** `ResearchEngine.evaluate()`
   holds no mutable state, mirroring `ADR-028`'s `ComplianceEngine`
   precedent — a stateless function of its inputs is trivially
   thread-safe.
3. **No duplicate calculations from other engines.** Evidence, market
   intelligence, strategy, risk, and compliance facts are read from
   their own snapshot types exactly as computed upstream. Statistical
   formulas (Sharpe, Sortino, VaR, CVaR, drawdown, Kelly fraction,
   profit factor, expectancy) are never reimplemented — `phantom.risk_engine.statistics`'s
   existing pure functions are reused per bucket (§0).
4. **Recommendations are advisory only, never applied automatically.**
   `Recommendation` is a plain, inert data record (text, supporting
   dimension, supporting data, confidence tag) — nothing in this
   package writes to any other engine's configuration. Operator
   approval for any resulting configuration change happens entirely
   outside this engine's scope.

---

# 5. Scope of each required capability

- **Track Everything** → `ClosedTrade`'s field list (§3) covers every
  named item in the task; execution-quality fields (requested entry,
  actual fill, slippage, spread at entry/exit, time to fill, partial
  fills, requotes) are part of the same record, since they are
  per-trade facts a caller must supply (this engine cannot observe
  broker fills itself — no MT5/Bridge communication, Hard Rule 1).
- **Performance Attribution** → `attribution.py`'s single generic
  `attribute_by()` grouping function, reused for all 13 named
  dimensions (not 13 near-duplicate functions per CLAUDE.md §6) — every
  bucket's statistics come from the reused `risk_engine.statistics`
  call (§0).
- **Pair / Strategy / Session Intelligence** → three thin ranking
  builders over the same reused statistics, differing only in their
  grouping key; ranked by expectancy (ties broken by sample size, never
  randomized — the same discipline `ADR-026`'s selection cascade and
  `ADR-027`'s sizing established).
- **Execution Quality** → a new, this-package-owned deterministic
  0–100 score per trade (slippage magnitude, fill time, requote count,
  stop/TP execution accuracy), aggregated per pair/strategy — genuinely
  new territory, not a duplicate of anything upstream.
- **Market Intelligence Review / Risk Review / Compliance
  Effectiveness** → one shared "compare two outcome buckets, describe
  the delta" helper (`effectiveness.py`), reused by `reviews.py`'s three
  named review functions — never three divergent comparison
  implementations.
- **Learning / Recommendation Engine** → `recommendations.py` scans
  attribution buckets for a configured minimum-sample-size, statistically
  notable expectancy/win-rate delta, and emits a plain-text
  `Recommendation` — deterministic threshold logic, not language
  generation (Hard Rule 1). Matches the task's own worked examples
  ("EURUSD Trend Continuation performs better in London than NY," etc.)
  as literal, mechanically-generated sentences from real bucket deltas.
- **Reporting** → `reporting.py` filters `ClosedTradeHistory` by a
  `ReportPeriod` (`DAILY`/`WEEKLY`/`MONTHLY`/`QUARTERLY`/`CUSTOM`) before
  every other computation runs — one period, one full `ResearchSnapshot`
  per `evaluate()` call.

---

# 6. Output — `ResearchSnapshot`

Pair rankings, strategy rankings, session rankings, the full 13-dimension
attribution set, execution quality summary, market-intelligence review,
risk review, compliance effectiveness, recommendations, warnings, the
period evaluated, and the sample size behind it. No trade decision,
ever.

---

# 7. Architecture

```
phantom/research_engine/
    __init__.py
    models.py                  ClosedTrade, ClosedTradeHistory, AttributionDimension,
                              AttributionBucket, PerformanceAttribution,
                              PairRanking/StrategyRanking/SessionRanking,
                              ExecutionQualityRecord/Summary, EffectivenessComparison,
                              MarketIntelligenceReview, RiskReview, ComplianceEffectiveness,
                              Recommendation, ReportPeriod, ResearchSnapshot
    config.py                   ResearchEngineConfig -- every threshold named
    attribution.py               generic attribute_by() + the 13 named dimension groupers
    pair_intelligence.py          per-pair ranking (reuses risk_engine.statistics)
    strategy_intelligence.py      per-strategy ranking
    session_intelligence.py       per-session ranking
    execution_quality.py          the Execution Quality Score
    effectiveness.py              shared bucket-comparison helper
    reviews.py                    market intelligence review + risk review + compliance effectiveness
    recommendations.py            deterministic threshold-based recommendation generator
    reporting.py                  period filtering (daily/weekly/monthly/quarterly/custom)
    explainability.py             ResearchSnapshot assembly
    engine.py                     ResearchEngine.evaluate() (pure, stateless, read-only)
    logging_sink.py, metrics.py

tests/phantom/research_engine/
    _fixtures.py, test_attribution.py, test_pair_intelligence.py,
    test_strategy_intelligence.py, test_session_intelligence.py,
    test_execution_quality.py, test_reviews.py, test_recommendations.py,
    test_reporting.py, test_engine.py, test_regression.py,
    test_performance.py, test_concurrency.py, test_determinism.py,
    test_architecture.py, test_stress.py, test_explainability.py

docs/adr/ADR-029-research-learning-engine.md
```

# 8. Testing mandate

Unit, regression, attribution, performance, concurrency, determinism,
architecture, stress, explainability — 9 categories, exactly as
specified.

# 9. Performance

28+ pairs' worth of closed-trade history, concurrent evaluation, thread
safe (trivially, via statelessness — the same proof `ADR-028`
established), deterministic, no duplicate statistical calculations.
