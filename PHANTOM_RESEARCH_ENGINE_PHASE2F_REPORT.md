# Phantom Research & Learning Engine — Phase 2F Implementation Report

**Status:** Complete. Bridge, Evidence Engine, Market Intelligence
Engine, Strategy Engine, Risk Engine, and Compliance Engine remain
frozen and byte-for-byte untouched this phase. Validation is explicitly
**not** started, per this phase's own scope.

Authority: `docs/adr/ADR-029-research-learning-engine.md` (Accepted,
this session). Scope: `phantom/research_engine/` — a new, independent,
completely advisory package, built fresh with no reuse of
`phantom_pipeline/analytics/` (ADR-010), `phantom_pipeline/research_desk/`
(ADR-021, AI-agent-driven), or ADR-019's self-evolving research agent.

---

## 0. Design decisions this phase required

Two real gaps surfaced before any code was written, both documented in
ADR-029 rather than guessed silently:

1. **`ClosedTradeHistory`/`ClosedTrade` (new type).** None of the seven
   named snapshot/state inputs carry a closed trade's full lifecycle
   (entry/exit/SL/TP, holding time, execution-quality facts, or the
   attribution tags this phase's own field list requires). Resolved
   exactly like `ADR-027`'s `PortfolioState`/`TradeHistory` and
   `ADR-028`'s `AccountState`: a new, caller-supplied, pre-aggregated
   record type. The task's own instruction to track "every trade
   (approved, rejected, and executed)" meant execution-outcome fields
   (entry/exit/R-multiple/holding time/execution-quality) had to become
   `Optional`, `None` whenever a candidate was rejected before it ever
   opened — a rejected trade still carries its pipeline context (pair,
   strategy, scores, risk recommendation, compliance decision,
   `evaluated_at`), just no P&L to attribute.
2. **Reuse, not duplicate, `phantom.risk_engine.statistics`.** Every
   ranking and attribution bucket needs win rate, profit factor,
   Sharpe, Sortino, expectancy, and drawdown — exactly what Risk
   Engine's `compute_statistical_metrics()` already computes. Rather
   than a third implementation of the same formulas, this engine
   converts its own `ClosedTrade` records into `risk_engine`'s simpler
   `TradeResult` shape and calls that function directly per bucket —
   the identical reuse move `ADR-028` made for
   `phantom.risk_engine.exposure`.

A real performance issue surfaced during testing and was fixed before
this report: Risk Engine's statistics function includes a Monte-Carlo-
based risk-of-ruin estimate (2,000 resampling simulations by default),
appropriate for its own single-pair-at-a-time usage but far too
expensive when this engine calls it once per bucket across dozens of
attribution buckets and review comparisons per `evaluate()` call.
Fixed by adding `bucket_risk_of_ruin_simulations` (200) and
`bucket_monte_carlo_sequence_length` (20) to `ResearchEngineConfig`,
passed into the reused function's own `RiskEngineConfig` — a 30x
reduction in per-bucket simulation cost with no change to any formula,
dropping one representative test from 8.9s to 0.3s.

---

## 1. Folder structure

```
phantom/research_engine/
    __init__.py
    models.py                 ClosedTrade, ClosedTradeHistory, AttributionDimension,
                             AttributionBucket, PerformanceAttribution, Ranking,
                             ExecutionQualityRecord/Summary, EffectivenessComparison,
                             MarketIntelligenceReview, RiskReview, ComplianceEffectiveness,
                             Recommendation, ReportPeriod, ResearchSnapshot
    config.py                  ResearchEngineConfig -- every threshold named
    attribution.py              generic attribute_by() + the 13 named dimension groupers
    ranking.py                   shared ranking builder (pair/strategy/session all reuse it)
    pair_intelligence.py          rank_pairs()
    strategy_intelligence.py      rank_strategies()
    session_intelligence.py       rank_sessions()
    execution_quality.py          the Execution Quality Score
    effectiveness.py              shared bucket-comparison helper
    reviews.py                    market intelligence review + risk review + compliance effectiveness
    recommendations.py            deterministic threshold-based recommendation generator
    reporting.py                  period filtering (daily/weekly/monthly/quarterly/custom)
    explainability.py             ResearchSnapshot assembly
    engine.py                     ResearchEngine.evaluate() (pure, stateless, read-only)
    logging_sink.py, metrics.py

tests/phantom/research_engine/
    _fixtures.py, test_attribution.py, test_pair_strategy_session_intelligence.py,
    test_execution_quality.py, test_reviews.py, test_recommendations.py,
    test_reporting.py, test_engine.py, test_regression.py, test_performance.py,
    test_concurrency.py, test_determinism.py, test_architecture.py, test_stress.py,
    test_explainability.py

docs/adr/ADR-029-research-learning-engine.md
```

## 2. File list

17 production files (1,349 lines), 16 test files including fixtures
(1,031 lines), 1 ADR, 1 report. `phantom/bridge/`,
`phantom/evidence_engine/`, `phantom/market_intelligence/`,
`phantom/strategy_engine/`, `phantom/risk_engine/`,
`phantom/compliance_engine/`, `phantom_pipeline/`, and
`scripts/check_architecture.py` are byte-for-byte unchanged this phase
— confirmed via `git status`.

## 3. Interfaces

```python
ResearchEngine(config, metrics=None)
    .evaluate(closed_trade_history: ClosedTradeHistory, period: ReportPeriod = CUSTOM,
              now=None, custom_start=None, custom_end=None) -> ResearchSnapshot

attribute_all_dimensions(trades, config) -> Tuple[PerformanceAttribution, ...]
attribute_by(trades, key_func, config) -> Tuple[AttributionBucket, ...]
rank_pairs / rank_strategies / rank_sessions(trades, config) -> Tuple[Ranking, ...]
compute_execution_quality_record(trade, config) -> ExecutionQualityRecord
summarize_execution_quality(trades, config) -> ExecutionQualitySummary
review_market_intelligence / review_risk(trades, config) -> MarketIntelligenceReview / RiskReview
review_compliance(all_trades, config) -> ComplianceEffectiveness
recommendations_from_attribution(attributions, overall, config) -> List[Recommendation]
cross_dimension_recommendations(trades, secondary_key_func, label, config) -> List[Recommendation]
period_bounds(period, now, custom_start=None, custom_end=None) -> Tuple[datetime, datetime]
build_research_snapshot(...) -> ResearchSnapshot
```

No method anywhere accepts or returns a trade direction, an order, a
parameter mutation, or a configuration change — verified by
`test_architecture.py`.

## 4. Data models

`ClosedTrade` (the full per-candidate lifecycle — pipeline-context
fields always present, execution-outcome fields `None` when rejected),
`ClosedTradeHistory`, `AttributionDimension` (13 values),
`AttributionBucket`, `PerformanceAttribution`, `Ranking` (one shared
type for pair/strategy/session), `ExecutionQualityRecord`/`Summary`,
`EffectivenessComparison`, `MarketIntelligenceReview`, `RiskReview`,
`ComplianceEffectiveness`, `Recommendation` (text, supporting
dimension, supporting data, confidence tag), `ReportPeriod` (5 values),
`ResearchSnapshot` (rankings, attributions, execution quality, the
three reviews, recommendations, warnings, period, sample size — no
trade decision, ever). All frozen dataclasses.

## 5. Dependency graph

```
phantom.evidence_engine.models / phantom.market_intelligence.models /
phantom.strategy_engine.models / phantom.compliance_engine.models        <- read-only, models.py (typing only)
phantom.risk_engine.models.{StatisticalMetrics, TradeResult, TradeHistory}  <- read-only, attribution.py
phantom.risk_engine.config.RiskEngineConfig,
phantom.risk_engine.statistics.compute_statistical_metrics                <- reused directly, attribution.py
                                                                              (no second Sharpe/Sortino/VaR/
                                                                              CVaR/drawdown/Kelly implementation)

models.py, config.py        <- everything else in this package
attribution.py                <- ranking.py, effectiveness.py, recommendations.py, engine.py
ranking.py                    <- pair_intelligence.py, strategy_intelligence.py, session_intelligence.py
effectiveness.py              <- reviews.py, recommendations.py
execution_quality.py, reviews.py, recommendations.py, reporting.py,
explainability.py              <- engine.py
engine.py                     <- __init__.py (only)
```

No cycles. Nothing imports `phantom_pipeline` or `phantom.bridge`
(AST-verified); the only upstream imports are the five prior `phantom/`
stages' `.models` types plus Risk Engine's `statistics`/`config`
modules (the reuse target). No `random`/ML-library import anywhere in
the package (AST-verified) — every computation is a plain deterministic
aggregation, and even the reused Risk Engine statistics function's own
seeded Monte Carlo component lives entirely inside `risk_engine`, never
re-imported or re-seeded here.

## 6. Testing report

- New suite: **58/58 pass** across 16 files, covering all 9 mandated
  categories (unit, regression, attribution, performance, concurrency,
  determinism, architecture, stress, explainability).
- Attribution: all 13 named dimensions verified present and grouping
  correctly; rejected candidates confirmed excluded from every bucket;
  bucket statistics confirmed to be `risk_engine`'s own
  `StatisticalMetrics` type (not a locally redefined one).
- Pair/Strategy/Session Intelligence: better-performing groups ranked
  first; below-minimum-sample-size groups excluded rather than ranked
  unreliably; ties broken by sample size then key, never randomized.
- Execution Quality: slippage/requote/fill-time degradation lowers the
  composite score monotonically; score bounded to `[0, 100]`; rejected
  candidates excluded from the summary.
- Reviews: news-blackout/peg/holiday effectiveness, confidence-tier and
  volatility-bucket scaling effectiveness, Kelly-cap-binding
  effectiveness, and compliance approve-vs-reduce effectiveness all
  computed from real bucket comparisons; compliance rejection rate
  computed from the *full* history including rejects (the one review
  that legitimately needs to see them).
- Recommendations: reproduces the task's own worked example shape
  directly — a (pair, strategy) × session cross-tabulation produces
  "EURUSD TREND_CONTINUATION performs better when session = LONDON
  than otherwise" for a deliberately-constructed London-outperforms-
  Asian fixture; confidence tags scale correctly with sample size.
- Reporting: Daily/Weekly/Monthly/Quarterly boundary computation
  verified against fixed calendar dates; Custom requires explicit
  bounds; period filtering excludes out-of-range trades.
- Determinism: repeated calls and two independent engine instances
  produce byte-identical `ResearchSnapshot`s (recommendations are
  stably sorted before comparison).
- Concurrency: 32 threads evaluating one shared engine instance
  concurrently, zero errors, byte-identical results (trivially, via
  statelessness).
- Performance/Stress: 840 trades across 28 pairs evaluate in ~318ms; a
  500-trade mixed history (480 executed, 20 rejected, varied pairs/
  strategies/sessions/volatility/news/liquidity tags) evaluates without
  error and produces correct rejection counts.
- Architecture: no forbidden execution/mutation/strategy-selection
  vocabulary, no `phantom_pipeline`/`phantom.bridge` import, only the
  five permitted upstream packages' types imported, no `random`/ML
  import anywhere, `ResearchEngine.__init__` assigns exactly
  `self.config` and `self.metrics` (AST-verified statelessness), no
  public method resembling a mutation/execution API.
- Full repository suite: **2,310/2,310 pass**. `compileall` clean.
  `scripts/check_architecture.py` (scoped to `phantom_pipeline/`):
  PASS, unaffected.

## 7. Performance

840 closed trades across the task's own 28-pair Forex universe
evaluate in **~318ms** (13-dimension attribution + pair/strategy/
session rankings + execution quality + 3 reviews + 3 cross-dimension
recommendation scans, each reusing `risk_engine.statistics` per
bucket) — acceptable for a periodic/on-demand report generator, not a
per-trade hot path.

## 8. Coverage

All 17 production modules have at least one direct test file; every
public function/method in the interface list (§3) is exercised,
including the full reject-vs-execute split and the period-filtering
boundary computation for all 5 report periods.

## 9. Architecture verification

- No forbidden execution/mutation/strategy-selection vocabulary bound
  anywhere in the package (AST-based).
- No import of `phantom_pipeline` or `phantom.bridge`; only
  `phantom.evidence_engine`, `phantom.market_intelligence`,
  `phantom.strategy_engine`, `phantom.risk_engine`, and
  `phantom.compliance_engine` are imported upstream, all read-only.
- No ML-library import; no `random` import anywhere in this package.
- `ResearchEngine` holds no mutable state beyond `config`/`metrics`
  (AST-verified) — pure, trivially thread-safe, matching `ADR-028`'s
  `ComplianceEngine` precedent.
- `scripts/check_architecture.py` (scoped to `phantom_pipeline/`):
  PASS, unaffected.
- `phantom/bridge/`, `phantom/evidence_engine/`,
  `phantom/market_intelligence/`, `phantom/strategy_engine/`,
  `phantom/risk_engine/`, and `phantom/compliance_engine/` are
  untouched, confirmed via `git status`.

---

## Recommendation

Ship as-is. Every ranking, attribution bucket, and recommendation is a
plain, reproducible aggregation over caller-supplied closed-trade
history — no ML, no LLM, no automatic optimization, no parameter
mutation, exactly as specified. Recommendations are advisory data
records only; applying any of them to live configuration requires
explicit operator action entirely outside this engine's scope.
Validation remains out of scope for this phase, per the task's own
"STOP." Awaiting approval for Phase 2G.
