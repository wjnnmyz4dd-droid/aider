# ADR-022 — Statistical Risk Management

Status: Accepted

Acceptance Date: 2026-07-07

Accepted By: User direction, this session (explicit, full specification:
module list, 20 named capabilities, `StatisticalRiskAssessment`'s 18
named fields, the 4-value advisory recommendation enum, and the
architecture rules forbidding modification of any existing pipeline-stage
package) — the same in-session approving authority already used to accept
`ADR-020`/`ADR-021` in this repository.

Owner: Quant Validation Engineer (Accountable per `.claude/agents/TEAM.md`
— statistical edge/robustness analysis is this role's explicit mandate,
and the role is already scoped as advisory-only, never modifying strategy
or risk logic directly)

Reviewed by: Integration Engineer (post-hoc interface-compatibility and
circular-import verification, per `TEAM.md`'s RACI — this ADR adds a 17th
package and a new `CROSS_CUTTING_OBSERVER_PACKAGES` member),
Backend Architect (Consulted — Monte Carlo/VaR/CVaR determinism under a
seeded PRNG)

Date: 2026-07-07

Depends on: `ADR-001-single-authority-architecture.md` (Accepted),
`ADR-005-risk-engine.md` (Accepted — read-only input type reuse only,
`RiskDecision`/`AccountState`/`OpenPosition`), `ADR-010-analytics-decision-provenance.md`
(Accepted — `TradeProvenanceRecord`/`PerformanceStatistics` are this
package's primary historical data source), `ADR-013-data-pipeline.md`
(Accepted — `NormalizedBar` is the ATR data source), `ADR-020-knowledge-rag-subsystem.md`,
`ADR-021-ai-research-desk.md` (Accepted — this ADR's cross-cutting-observer
posture and `CROSS_CUTTING_OBSERVER_PACKAGES` enforcement mechanism are
adopted from these two verbatim, not reinvented)

---

# Pipeline position

**Statistical Risk Management is not part of the deterministic trading
pipeline, and it is not a 17th pipeline stage.** Exactly like Knowledge
(`ADR-020`) and the AI Research Desk (`ADR-021`), it is a cross-cutting
observer that reads already-produced, immutable records after the fact
and computes derived statistics about them. Unlike every stage from
Scanner through Analytics, nothing in the deterministic pipeline calls
into this package, and this package never calls into a pipeline stage's
decision method — it only ever reads another package's `.models` types
(`analytics.models.TradeProvenanceRecord`, `risk_engine.models.AccountState`/
`OpenPosition`/`RiskDecision`, `data_pipeline.models.NormalizedBar`,
`scanner.models.ScannerObservation` fields), exactly the same reuse
pattern `knowledge`/`research_desk` already established for themselves.

**The deterministic Risk Engine (`ADR-005`) remains the sole risk
authority, unmodified.** `phantom_pipeline/risk_engine/` is not touched by
this ADR — not its `models.py`, not its `config.py`, not its `engine.py`,
not its `constraints.py`. `RiskEngine.decide()`'s signature, behavior, and
output are identical before and after this package exists. This is
enforced structurally, not just documented: `statistical_risk` is added to
`scripts/check_architecture.py`'s `CROSS_CUTTING_OBSERVER_PACKAGES` set,
which means no pipeline-stage package — `risk_engine` included — may ever
import `statistical_risk`, in either direction. The relationship is
one-way: `statistical_risk` may read `risk_engine.models` (a `.models`
import is always allowed across a package boundary, per the existing
private-state rule), but `risk_engine` can never read `statistical_risk`.

---

# 1. Mission

**Statistical Risk Management answers exactly one question: "What does
Phantom's own historical trade record say, statistically, about the risk
of the current situation?"**

**It never answers:** Should we trade? Should this trade's risk be
approved, reduced, or blocked? Those remain the deterministic Risk
Engine's (`ADR-005`), Compliance Engine's (`ADR-006`), and Execution
Validator's (`ADR-007`) own questions, each already answered by that
stage's own Accepted ADR. This package's entire mandate is descriptive
statistics and simulation over already-recorded historical outcomes — it
observes and estimates; it never decides, never sizes, never scores,
never approves, and never executes.

Its sole exported judgment is `StatisticalRiskAssessment.statistical_recommendation`,
one of four values (`NORMAL_RISK`, `REDUCE_RISK_25`, `REDUCE_RISK_50`,
`SKIP_HIGH_RISK`) — an inert, plain-data suggestion that a future caller
*may* choose to read alongside a `RiskDecision`. This package holds no
mechanism to apply that recommendation itself; nothing here can lower (or
raise) `RiskDecision.approved_risk_percent` or any other stage's output.

---

# Hard Rules

1. **Read-only, structurally.** No class, method, or module in
   `phantom_pipeline/statistical_risk/` accepts a `RiskDecision`,
   `ComplianceDecision`, `ExecutionDecision`, `CandidateTrade`, or
   `ScoreResult` as a *return* value it produces — those types may only
   ever be read as inputs. No `set_*`/`submit_*`/`decide_*`/`approve_*`/
   `reject_*`/`execute_*`/`size_*` method exists anywhere in this package.
2. **Never increases risk.** `statistical_recommendation` is always one
   of the four named values above; `REDUCE_RISK_25`/`REDUCE_RISK_50`/
   `SKIP_HIGH_RISK` only ever *narrow* the deterministic engine's already-
   approved risk, never widen it. There is no fifth value, and no
   numeric field on `StatisticalRiskAssessment` is capable of exceeding
   the `RiskDecision.approved_risk_percent` it was computed alongside —
   enforced by a dedicated test (`test_recommendation_never_increases_risk`),
   not merely documented.
3. **Advisory only — never applied automatically.** Nothing in this
   package writes to, mutates, or calls a method on `risk_engine`,
   `compliance_engine`, `execution_validator`, `position_manager`,
   `mt5_bridge`, `scanner`, or `strategy_engine`. `StatisticalRiskAssessment`
   is a plain, frozen, inert data record — the same "suggest, never
   apply" posture `ADR-020` Hard Rule 3 and `ADR-021` Hard Rule 2 already
   establish for `ResearchSuggestion`/research findings.
4. **`scripts/check_architecture.py` enforced, extended.** `statistical_risk`
   is added to `CROSS_CUTTING_OBSERVER_PACKAGES` alongside `knowledge`/
   `research_desk` — no pipeline-stage package (the 10 in
   `PIPELINE_STAGE_PACKAGES`, `risk_engine` included) may import
   `statistical_risk`, in either direction. No circular import; every
   cross-package import from `statistical_risk/` targets only another
   package's `.models`/`__init__.py`, never a private submodule.
5. **No AI or LLM may generate a statistical value.** Every number in
   `StatisticalRiskAssessment` is computed by plain arithmetic, a seeded
   pseudo-random simulation, or a closed-form statistical formula — never
   a language-model call. This mirrors `ADR-020` Hard Rule 5's
   deterministic-explanation posture, applied here to numeric output
   instead of natural-language text.
6. **100% deterministic given identical historical inputs.** Every Monte
   Carlo simulation seeds its own `random.Random` instance from a caller-
   supplied or `trace_id`-derived seed — never Python's global `random`
   module state. Two `StatisticalRiskEngine` instances given byte-
   identical `TradeProvenanceRecord` sequences and the same seed produce
   byte-identical `StatisticalRiskAssessment` output, verified by a
   dedicated replay-determinism test (mirrors every prior stage's own
   determinism test).
7. **Historical Phantom data only — never fabricated.** Every input is a
   real, already-recorded `TradeProvenanceRecord` (via `AnalyticsEngine`),
   `NormalizedBar` (via `data_pipeline`), or `AccountState`/`OpenPosition`
   (via `risk_engine.models`, caller-supplied the same way `RiskEngine.decide()`
   itself receives them). A capability with no honest data source (e.g.
   confidence intervals when fewer than a configured minimum sample size
   of closed trades exists) reports `None`/an explicit
   `insufficient_sample` reason code, never an invented number — the same
   "`None` means cannot be honestly measured" discipline `data_pipeline.models.DataQualityReport.latency_seconds`
   and `ADR-021`'s `ParameterSensitivityResult.available=False` already
   establish.
8. **No duplicate computation.** Whole-sample win rate, profit factor,
   Sharpe, Sortino, expectancy, and max drawdown are already computed by
   `analytics.performance.compute_performance_statistics` — this package
   never re-derives the whole-sample versions. It computes only what does
   not already exist anywhere in `phantom_pipeline`: **rolling** (trailing-
   window) win rate/profit factor/expectancy/Sharpe/Sortino, Monte Carlo
   simulation, probability of reaching a drawdown limit, VaR/CVaR, Risk of
   Ruin, Kelly Criterion, ATR/realized-volatility-adjusted recommendations,
   correlation/currency/concentration-adjusted portfolio-heat
   recommendations, regime-based statistical confidence, and per-trade
   confidence intervals — all sixteen of which are genuinely new
   statistical computations with no existing implementation to duplicate
   (confirmed by reading `analytics/performance.py`, `analytics/models.py`,
   and `paper_trading/forward_test_engine.py` in full during this ADR's
   Research phase).
9. **Zero modification to any of the 16 existing `phantom_pipeline`
   packages.** `statistical_risk` becomes the 17th package. No existing
   package's file changes except `scripts/check_architecture.py` (Hard
   Rule 4's one-line set addition).

---

# 2. What is read (Responsibilities)

- **`analytics.models.TradeProvenanceRecord`** (via a caller-supplied
  sequence, the same shape `analytics.performance.compute_performance_statistics`
  already consumes) — the sole source of historical trade outcomes for
  every rolling statistic, Monte Carlo simulation, VaR/CVaR, Risk of
  Ruin, Kelly Criterion, and confidence interval.
- **`risk_engine.models.RiskDecision`** — read only to confirm Hard Rule
  2 (never recommend above the already-approved value) and to read
  `approved_risk_percent`/`risk_tier` for context; never mutated, never
  re-decided.
- **`risk_engine.models.AccountState`/`OpenPosition`** — read only, the
  same objects `RiskEngine.decide()` itself receives, for portfolio heat,
  correlation exposure, and currency exposure recommendations. Reusing
  these types (rather than inventing parallel ones) means this package's
  view of "what's open" can never drift from the Risk Engine's own view.
- **`data_pipeline.models.NormalizedBar`** — a bounded historical OHLC
  series (via `HistoricalSeries`), the sole source for ATR (Average True
  Range, Wilder's method) and realized volatility (standard deviation of
  log/simple returns).
- **`scanner.models.ScannerObservation`** fields (`phase: MarketPhase`,
  `range_structure: RangeStructure`, `structure_confidence: StructureConfidence`) —
  read only, for regime-based statistical confidence (i.e. "how much
  historical data exists for trades taken in a similar regime").

Never ingested or read: raw credentials, `.env` files, live broker
connections — this package performs no I/O beyond the plain Python
objects a caller passes to it.

---

# 3. Interfaces (`phantom_pipeline/statistical_risk/`)

`models.py` (types only — `StatisticalRiskAssessment`, `RiskRecommendation`,
`VolatilityState`, `CorrelationState`, `ConfidenceInterval`, `MonteCarloResult`),
`config.py` (tunables — rolling window size, Monte Carlo simulation
count/default seed source, VaR/CVaR confidence level, minimum sample
sizes), `probability.py` (probability of reaching daily/total drawdown
limit, Risk of Ruin), `monte_carlo.py` (seeded Monte Carlo simulation over
historical trade PnL), `volatility.py` (ATR, realized volatility,
volatility-adjusted recommendation), `drawdown.py` (maximum historical
drawdown, expected drawdown), `expectancy.py` (rolling expectancy/win-rate/
profit-factor/Sharpe/Sortino), `correlation.py` (correlation-adjusted
exposure recommendation), `portfolio.py` (portfolio heat, position
concentration, currency exposure), `metrics.py`, `logging_sink.py`,
`engine.py` (`StatisticalRiskEngine` — the top-level orchestrator
composing every module above into one `StatisticalRiskAssessment`, plus
VaR/CVaR, Kelly Criterion, and regime-based confidence, which have no
single-purpose module of their own since each is a short, self-contained
formula), `__init__.py`.

No pipeline-stage package's public interface changes. A caller wanting to
read a `StatisticalRiskAssessment` alongside a `RiskDecision` does so from
outside both packages — e.g. `orchestrator.py` or a future integration
point — exactly as `paper_trading`/`deployment` already call other
packages' existing public methods from outside those packages themselves.

---

# 4. Testing

Per the task's stated target (100% deterministic output, full unit +
integration coverage): determinism (identical `TradeProvenanceRecord`
sequence + seed → byte-identical `StatisticalRiskAssessment`, including
Monte Carlo), the Hard-Rule-2 invariant (recommendation never implies a
risk percent above `RiskDecision.approved_risk_percent`), rolling-window
correctness (hand-computed small examples for expectancy/win-rate/
profit-factor/Sharpe/Sortino), VaR/CVaR/Kelly/Risk-of-Ruin correctness
against hand-computed or textbook reference values, ATR/realized-
volatility correctness against a hand-constructed bar series, insufficient-
sample honesty (`None`/`insufficient_sample` when below the configured
minimum, never a fabricated number), and the structural boundary test (no
pipeline-stage package imports `statistical_risk`, verified via source
scan — mirrors `ADR-020`/`ADR-021`'s own boundary test).

---

# 5. Architectural invariants

- Zero modification to any of the 16 existing `phantom_pipeline`
  packages except the one-line `CROSS_CUTTING_OBSERVER_PACKAGES` addition
  in `scripts/check_architecture.py`.
- `phantom_pipeline/statistical_risk/` becomes the 17th package;
  `scripts/check_architecture.py` must report 17 packages, no cycles, no
  cross-package private-state access, and no pipeline-stage →
  `statistical_risk` import.
- `risk_engine/`, `compliance_engine/`, `execution_validator/`,
  `position_manager/`, `mt5_bridge/`, `scanner/`, `strategy_engine/` are
  byte-for-byte unchanged (verified by `git diff` showing no hunks under
  any of these seven directories).

---

# 6. Acceptance criteria

- All Hard Rules (above) hold, verified by dedicated tests, not merely
  asserted in prose.
- Full existing validation suite (`compileall`, `unittest discover`,
  `validate.py`, `scripts/check_architecture.py`) stays green.
- Full new test suite (unit + integration), all passing.

---

# 7. Explicitly out of scope (this ADR)

- **Wiring `StatisticalRiskAssessment` into `orchestrator.py`, `paper_trading`,
  `knowledge`, `research_desk`, or `dashboard`.** The task's "Integrate
  with" list names these five as intended future consumers of this
  package's output, not packages this ADR modifies. `StatisticalRiskAssessment`
  is a plain, importable, frozen dataclass — structurally ready for any of
  the five to read or wrap it later (the same way `ResearchDeskDashboardSnapshot`
  wraps `KnowledgeDashboardSnapshot`), but no such wiring is implemented
  now, and none of those five packages' files change in this ADR.
- **Any change to the deterministic Risk Engine's behavior.** `RiskEngine.decide()`
  is not modified to read this package's output — a real, deliberately
  deferred future decision the operator/architect makes explicitly,
  never assumed here.
- **A persistent (on-disk) store for historical simulation results** —
  this package is stateless: every call takes its historical input
  explicitly and returns a fresh `StatisticalRiskAssessment`; no
  `InMemory*Store` is needed since there is no incremental ingestion
  step (unlike `knowledge`).

---

# Amendment 1 — Statistical Risk Integration

Status: Accepted

Acceptance Date: 2026-07-07

Accepted By: User direction, this session (explicit, full specification
of 8 named integration points: Orchestrator, Analytics, Paper Trading,
Knowledge, AI Research Desk, Dashboard, Explainable Decisions, Logging/
Metrics) — the same in-session approving authority already used to
accept the base ADR.

This amendment implements §7's deferred wiring ("Wiring `StatisticalRiskAssessment`
into `orchestrator.py`, `paper_trading`, `knowledge`, `research_desk`, or
`dashboard`... no such wiring is implemented now") — this is exactly that
future step, and every constraint the base ADR already established
(advisory-only, no decision authority, structurally incapable of
exceeding the deterministic engine's approved risk, deterministic-only,
no fabricated data) remains unchanged and unweakened by this amendment.

## A1.1 The one classification change: Analytics leaves the restricted set

`scripts/check_architecture.py`'s `PIPELINE_STAGE_PACKAGES` set — used
only to decide which packages may never import a `CROSS_CUTTING_OBSERVER_PACKAGES`
member — previously included `analytics` (mirroring `ADR-001`'s pipeline
diagram, where Analytics is the tenth, terminal stage). This amendment
removes `analytics` from that set, joining `watchdog`/`dashboard`/
`paper_trading`/`deployment`, which were already excluded for the same
reason stated in the script's own comment: **they sit outside the trading
decision chain.**

This is justified, not a loophole, because the restriction's actual
purpose is narrower than "is this package in `ADR-001`'s diagram" — it is
"can this package's decision ever be corrupted by a dependency on an
advisory-only layer." `ADR-010` §1/§3/§11 already establish, as Hard
Rules, that Analytics **holds no decision authority whatsoever** — it
collects, it never decides. Analytics sits at the terminal, recording end
of the pipeline, never the causal end; nothing it stores can feed back
into a live trading decision because Analytics itself never produces one.
Letting Analytics store one more already-produced, read-only record type
(`StatisticalRiskAssessment`, exactly like it already stores `RiskDecision`/
`ComplianceDecision`/every other stage's output) introduces no new risk
the restriction was designed to prevent.

**What does not change:** `PIPELINE_STAGE_PACKAGES`'s other 9 members
(`data_pipeline`, `scanner`, `strategy_engine`, `scoring_engine`,
`risk_engine`, `compliance_engine`, `execution_validator`, `mt5_bridge`,
`position_manager`) are completely unaffected — every one of them remains
structurally forbidden from ever importing `knowledge`, `research_desk`,
or `statistical_risk`. In particular, **`risk_engine` is not touched by
this amendment in any way** — it does not gain the ability to import
`statistical_risk`, and no file under `phantom_pipeline/risk_engine/`
changes. `ADR-001`'s pipeline order and diagram are unaffected — Analytics
still receives every stage's output in exactly the same sequence; only
the import-boundary *enforcement classification* changes.

## A1.2 Integration points (all additive, all read-only)

1. **Orchestrator** (`orchestrator.py`): `PipelineOrchestrator` gains two
   new, `Optional`, default-`None` constructor parameters
   (`statistical_risk: Optional[StatisticalRiskEngine]`, `statistical_risk_records_provider:
   Optional[Callable[[], Sequence[TradeProvenanceRecord]]]`) — omitting
   both preserves every existing caller's behavior byte-for-byte
   (`CLAUDE.md` §1.6). When supplied, `_run_candidate()` computes one
   `StatisticalRiskAssessment` immediately after `risk_decision` is
   produced, using `risk_decision.trace_id` verbatim, and forwards it to
   `Analytics` and onto the returned `CandidateCycleResult` (a new,
   defaulted field) — never altering `risk_decision` itself, never
   gating any subsequent stage call, never changing `run_scan_cycle`'s
   control flow.
2. **Analytics**: `TradeProvenanceRecord` gains two new, defaulted fields
   (`statistical_risk_assessment`, `kelly_recommendation`), both loosely
   typed (`Any`) — mirroring `account_snapshots`' own existing precedent
   — specifically to avoid an analytics ↔ statistical_risk circular
   import (`statistical_risk` already depends on `analytics.models.TradeProvenanceRecord`
   for its own historical input, so the dependency can only run one
   way). `AnalyticsEngine` gains `collect_statistical_risk_assessment`/
   `collect_kelly_recommendation` (mirroring every existing `collect_*`
   method, storing the real object even though the field's static type
   is loose). Historical-trend computation itself
   (`StatisticalRiskEngine.compute_trend()`, `StatisticalRiskTrendReport`/
   `StatisticalRiskTrendPoint`) necessarily lives in `statistical_risk`,
   not `analytics` — it reads the stored records back and reduces them
   to a time-ordered point series, the same "derive from already-recorded
   records, never a second implementation" posture `analytics.performance`
   itself established, just applied from the other side of the (one-way)
   dependency.
3. **Paper Trading**: `PaperTradingRunner` gains an additive
   `preview_statistical_risk()` convenience method (read-only, called
   before submitting a simulated trade, never gating it);
   `PeriodReport` gains a `statistical_risk_summary` field populated from
   `AnalyticsEngine.compute_statistical_risk_trend()`; a new module,
   `statistical_risk_backtest.py`, compares each period's actual
   `realized_pnl` against what a `REDUCE_RISK_25`/`REDUCE_RISK_50`/
   `SKIP_HIGH_RISK` recommendation would have implied, purely as a
   retrospective, informational analysis — never a replay of history,
   never a change to any recorded outcome.
4. **Knowledge**: a new `DocumentKind.STATISTICAL_RISK_ASSESSMENT` value;
   `build_statistical_risk_document()` (`ingestion.py`) renders one
   `StatisticalRiskAssessment` into a deterministic-text `KnowledgeDocument`,
   ingested and embedded exactly like every other document kind — fully
   searchable via the existing `KnowledgeEngine.search()`/`SemanticSearchService`
   path, plus a literal `find_statistical_risk_assessments(recommendation=...)`
   convenience filter (mirrors `find_by_setup_pattern`'s literal-match
   precedent — never a fabricated NLP layer).
5. **AI Research Desk**: `WeeklyInstitutionalReviewGenerator`,
   `MarketResearchAgent`, `TradeThesisGenerator`, `StrategyResearchAgent`,
   and `AITradeJournal` each gain one new, `Optional`, default-`None`
   parameter accepting an already-built `StatisticalRiskAssessment` (or a
   short sequence of them); when supplied, its already-computed fields
   are quoted verbatim into the generated narrative text — no method
   anywhere in `research_desk/` computes a new statistical value; every
   number quoted traces back to `StatisticalRiskAssessment`'s own fields.
6. **Dashboard**: mirrors `ADR-021`'s own `ResearchDeskDashboardBuilder`
   precedent exactly — a new `StatisticalRiskDashboardSnapshot` type
   lives in `statistical_risk/models.py` (not in `dashboard/`), built by a
   new `StatisticalRiskDashboardBuilder` (`statistical_risk/dashboard.py`).
   `dashboard/models.py`'s `ViewName` stays the exhaustive ten values it
   already is (`ADR-012` §5) — this is not an eleventh view, it is a
   wholly separate, additive snapshot type, exactly like
   `KnowledgeDashboardSnapshot` is for `knowledge`. `dashboard/` package
   files are not modified.
7. **Explainable Decisions**: `ExplainableDecisionEngine` gains
   `explain_statistical_risk(question, assessment, history=())`
   answering the 8 named question shapes via deterministic string
   templates built entirely from `StatisticalRiskAssessment`'s own
   already-computed fields (and, for the two comparison questions, a
   plain diff between two supplied assessments) — no new statistic is
   computed here; every answer quotes a field that already exists.
8. **Logging/Metrics**: `statistical_risk/logging_sink.py`/`metrics.py`
   are unchanged (already log/meter every assessment, immutably, since
   the base ADR); `AnalyticsMetrics`' existing generic `record_collected(kind)`
   mechanism already covers the two new collection kinds with zero
   modification needed.

## A1.3 What remains untouched

`risk_engine/`, `compliance_engine/`, `execution_validator/`,
`position_manager/`, `mt5_bridge/`, `scanner/`, `strategy_engine/`,
`dashboard/` — not one file under any of these 8 directories changes.
`statistical_risk`'s own 18-field `StatisticalRiskAssessment` contract
and 4-value `RiskRecommendation` enum are unchanged. No pipeline stage
gains a new import; only `analytics` (already justified above) and the
observer/wrapper packages (`knowledge`, `research_desk`, `paper_trading`,
`orchestrator.py`) gain a new, optional, additive read of
`statistical_risk`'s output.

## A1.4 Acceptance criteria

- All of the base ADR's Hard Rules still hold, unchanged.
- `scripts/check_architecture.py` passes with `analytics` removed from
  `PIPELINE_STAGE_PACKAGES` and `statistical_risk` still in
  `CROSS_CUTTING_OBSERVER_PACKAGES` — 17 packages, no cycles, no private-
  state access, no *actual* pipeline-stage → observer import (the 9
  remaining restricted packages stay clean).
- Every integration point is additive: every new constructor/method
  parameter introduced defaults such that omitting it reproduces prior
  behavior exactly (verified by re-running the full pre-existing test
  suite with zero modification and zero regression).
- New tests cover trace ID continuity, determinism, historical storage,
  dashboard rendering, knowledge ingestion, research desk integration,
  analytics integration, and paper trading integration (§11 of the
  originating task).
