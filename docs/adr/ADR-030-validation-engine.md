# ADR-030 — Validation Engine

Status: Accepted

Acceptance Date: 2026-07-10

Accepted By: Software Architect / Titan Protocol Engineering Council (full spec
supplied in one message, per the same "complete spec accepted in one
pass" precedent `ADR-029` established for the Research & Learning
Engine — no Proposed→Accepted rewrite cycle was needed).

Owner: Quant Validation Engineer (per `.claude/agents/TEAM.md` — the
role already scoped to "walk-forward analysis, Monte Carlo simulation,
overfitting detection, parameter robustness, risk-adjusted performance
... advisory only; never modifies strategy logic directly," an exact
match for this ADR's mission)

Reviewed by: Software Architect (mandatory cross-cutting reviewer, same
as every prior stage this session), Test Results Analyzer (Consulted —
owns `ADR-018`'s adjacent Replay & Certification Engine; §0 below
depends on that ADR's scope staying distinct from this one)

Date: 2026-07-10

Depends on: `ADR-001-single-authority-architecture.md` (Accepted),
`ADR-024-evidence-engine.md` (Accepted — read-only consumer of
`EvidenceSnapshot`), `ADR-025-market-intelligence-engine.md` (Accepted
— read-only consumer of `MarketIntelligenceSnapshot`),
`ADR-026-strategy-engine.md` (Accepted — read-only consumer of
`StrategySnapshot`), `ADR-027-portfolio-statistical-risk-engine.md`
(Accepted — read-only consumer of `RiskSnapshot`, and direct reuse of
`risk_engine.statistics`/`risk_engine.monte_carlo`, §0 below),
`ADR-028-compliance-engine.md` (Accepted — read-only consumer of
`ComplianceSnapshot`), `ADR-029-research-learning-engine.md` (Accepted
— direct reuse of `research_engine.ranking`/`.attribution`/
`.effectiveness`/`.execution_quality` and its `ClosedTrade`/
`ClosedTradeHistory`/`ResearchSnapshot` types, §0 below)

---

# Pipeline position

**Cross-cutting, like Watchdog (`ADR-011`), Dashboard (`ADR-012`), and
the Research & Learning Engine (`ADR-029`) — not part of the live
trading pipeline.** It sits alongside the six `titan_protocol/` engines built
this session (Evidence, Market Intelligence, Strategy, Risk,
Compliance, Research & Learning) and verifies them; it never sits
between them.

---

# 0. Relationship to prior work (disclosure, not duplication)

- **`ADR-018` Replay & Certification Engine (Accepted, `phantom_pipeline`
  lineage)** already owns historical replay, determinism verification,
  walk-forward testing, Monte Carlo testing, bootstrap analysis, and
  shadow trading — as vocabulary, this looks identical to several items
  in this ADR's own mission. **The scope is not the same system:**
  `ADR-018` evaluates whether a *candidate strategy or architectural
  change* (submitted by `ADR-019`'s research agent or a human) has
  earned promotion through `phantom_pipeline`'s own Analytics
  (`ADR-010`) / Data Pipeline (`ADR-013`) replay data. This ADR
  validates whether the **six engines actually built this session**
  (Evidence through Research & Learning) are behaving correctly against
  already-recorded historical scenarios — it has no certification-level
  state machine, no promotion workflow, and no relationship to
  `ADR-019`'s research agent. Both may reuse the same statistical
  vocabulary (Sharpe, Sortino, walk-forward, Monte Carlo) because both
  ultimately answer "is this evidence statistically sound," but neither
  consumes the other's inputs or outputs. A future ADR could merge them
  if the Council decides `phantom_pipeline`'s certification workflow
  should adopt this engine's per-stage verification — not assumed here.
- **`ADR-027` (`risk_engine.statistics.compute_statistical_metrics`,
  `risk_engine.monte_carlo.run_monte_carlo`)** — reused directly, not
  reimplemented, for every statistic this ADR's tournaments and Monte
  Carlo validation need (win rate, profit factor, Sharpe, Sortino,
  drawdown, expectancy, recovery factor, risk of ruin). The same
  `ClosedTrade -> TradeResult` adapter pattern `ADR-029` §0 established
  is reused here (§3).
- **`ADR-029` (`research_engine.ranking.build_rankings`,
  `.strategy_intelligence.rank_strategies`, `.pair_intelligence.
  rank_pairs`, `.session_intelligence.rank_sessions`,
  `.attribution.compute_bucket_statistics`, `.effectiveness.
  compare_buckets`/`.bucket_by_score_tertiles`, `.execution_quality.
  summarize_execution_quality`)** — reused directly for every tournament
  and drift-detection computation. This ADR's Strategy/Pair/Session
  Tournaments are, mechanically, the exact same ranking builder
  `ADR-029` already wrote, called on a caller-supplied
  `ClosedTradeHistory` (`ADR-029`'s own type, imported here, never
  redefined) — the only new code is the thin `TournamentEntry` wrapper
  adding `recovery_factor` (already a `StatisticalMetrics` field,
  `ADR-027`) that `Ranking` doesn't itself surface.
- **No legacy validation/replay/tournament engine exists in `titan_protocol/`.**
  `phantom_institutional.py` has no equivalent. This stage is designed
  from first principles for the six engines it validates, reusing their
  neighbors' already-accepted pure functions rather than inventing a
  seventh statistics implementation.

---

# 1. Mission

**The Validation Engine is Titan Protocol's independent verification authority
for the six engines built this session.** It answers exactly one
question per capability: "does the recorded evidence show these engines
behaving correctly, consistently, and explainably?" It never trades,
sizes positions, changes parameters, optimizes live systems, changes
configurations, or executes orders. It only validates.

---

# 2. Hard Rules

These override any other requirement in this document if they ever
appear to conflict:

1. **No execution.** No order-placement capability, no broker
   credentials, ever.
2. **No optimization, no parameter mutation, no configuration change.**
   Every tournament, drift finding, and calibration result is a
   `Recommendation`-shaped string, never an applied change — the exact
   same advisory-only discipline `ADR-029` Hard Rule 3 established, and
   the same "operator approval required" gate.
3. **No strategy selection.** Tournaments rank; they never choose.
4. **No evidence calculations. No compliance decisions.** The Validation
   Engine never re-invokes `EvidenceEngine`/`MarketIntelligenceEngine`/
   `StrategyEngine`/`RiskEngine`/`ComplianceEngine`'s compute logic. It
   consumes their already-produced, frozen `*Snapshot` dataclasses
   (caller-supplied, exactly as every downstream stage in this pipeline
   already consumes its upstream's snapshot rather than recomputing it)
   and verifies structural, cross-stage, and explainability invariants
   over them. "Historical Replay" in this ADR means *replaying and
   re-verifying already-recorded pipeline outputs*, never recomputing a
   new evidence/compliance decision from raw market data — see §3 for
   why this is the safer reading of the task's own "Evidence ↓ ... ↓
   Compliance ↓ Bridge. Verify every output" language.
5. **No duplicate calculations from other engines.** Every statistic
   this engine reports is computed by `risk_engine.statistics`/
   `.monte_carlo` or `research_engine.ranking`/`.attribution`/
   `.effectiveness`/`.execution_quality` (§0) — never a second,
   divergent formula.
6. **Read-only. Deterministic. Thread safe.** Same statelessness
   discipline as every prior engine (`self.config`/`self.metrics` only,
   verified by the same AST test `ADR-029` §"Testing" introduced).

---

# 3. Why "consume recorded snapshots," not "re-invoke the five engines"

The task's own text draws the replay chain as "Evidence ↓ Market
Intelligence ↓ Strategy ↓ Risk ↓ Compliance ↓ Bridge. Verify every
output." Two readings are possible:

- **(a) Re-invoke:** construct fresh `EvidenceEngine`/
  `MarketIntelligenceEngine`/etc. instances and call their `evaluate()`
  methods against raw historical bars/events, then compare the freshly
  computed outputs to what was recorded live.
- **(b) Verify recorded outputs:** treat a `HistoricalScenario` as
  already carrying the five engines' recorded `*Snapshot` outputs for
  one pair/timestamp (produced during a live or paper run, entirely
  outside this package), and check that they satisfy the invariants
  those engines' own Hard Rules already promise (compliance never
  increases risk versus Risk Engine's recommendation, a rejected
  Strategy Engine snapshot implies no Risk/Compliance approval, every
  explanation field is populated, etc.).

**(b) is adopted.** Reading (a) requires this package to hold live
instances of, and call directly into, five other stages' compute
logic — in direct tension with Hard Rule 4's "no evidence calculations,
no compliance decisions," and with the "caller-supplied, pre-aggregated,
never derived by this engine" input discipline `ADR-027` (`PortfolioState`/
`TradeHistory`), `ADR-028` (`AccountState`), and `ADR-029`
(`ClosedTradeHistory`) all already established for exactly this reason.
Reading (b) keeps the Validation Engine a pure downstream verifier —
identical in spirit to how Compliance Engine consumes `RiskSnapshot`
without ever recomputing risk. "Historical Replay" therefore means: load
an ordered sequence of already-recorded per-scenario snapshots
(`HistoricalRun`) and re-run this package's own (pure, deterministic)
verification logic against them — repeatedly, for Determinism Validation
(§5) — never re-run the five upstream engines' own logic.

---

# 4. Inputs — consume only

- `EvidenceSnapshot` (`evidence_engine`), `MarketIntelligenceSnapshot`
  (`market_intelligence`), `StrategySnapshot` (`strategy_engine`),
  `RiskSnapshot` (`risk_engine`), `ComplianceSnapshot`
  (`compliance_engine`) — bundled per scenario into a new
  `HistoricalScenario` (§6), one per historical pair/timestamp instance,
  mirroring every prior "new caller-supplied bundle type" precedent.
- `ClosedTrade`/`ClosedTradeHistory` (`research_engine`, unmodified,
  imported) — the substrate for every tournament, walk-forward, Monte
  Carlo, and drift computation (§0).
- `ResearchSnapshot` (`research_engine`, optional, per `HistoricalRun`)
  — for the Explainability Validation's "Research" leg (§7).
- A new `BridgeExecutionRecord` (this package, §6) — the recorded,
  already-happened fill/rejection facts for one scenario's order, for
  Execution Validation (§11) and the Explainability Validation's
  "Bridge" leg. This package never talks to MT5 or holds broker
  credentials (Hard Rule 1); it only reads what already happened.

---

# 5. Responsibilities

1. **Historical Replay** (§3) — structural/cross-stage verification over
   an ordered `HistoricalRun` of `HistoricalScenario`s.
2. **Determinism Validation** — re-running this package's own
   verification against the same `HistoricalScenario` N times must
   produce identical results (protects against non-determinism in this
   package's own aggregation/grouping code — dict-ordering, floating-
   point summation order, wall-clock reads — never a claim about the
   five upstream engines' own internal state, which this package never
   touches, Hard Rule 4).
3. **Explainability Validation** — Evidence, Strategy, Risk, Compliance,
   Bridge, Research each carry a non-empty explanation (the task's own
   list; Market Intelligence is deliberately not in it, even though it
   has its own `MarketIntelligenceExplanation` type — not an oversight).
4. **Strategy / Pair / Session Tournament** — thin wrappers over
   `research_engine.strategy_intelligence.rank_strategies`/
   `.pair_intelligence.rank_pairs`/`.session_intelligence.rank_sessions`
   (§0), each `Ranking` widened into a `TournamentEntry` carrying
   `recovery_factor`.
5. **Configuration Tournament** — ranks a caller-supplied
   `Mapping`-shaped `Tuple[ConfigurationRun, ...]` (one `ClosedTradeHistory`
   per named `ConfigurationProfile`: Conservative/Balanced/Aggressive/
   London Focus/New York Focus/Trend Focus/Range Focus/Custom) by
   `research_engine.attribution.compute_bucket_statistics` expectancy.
   Recommendations only — no configuration is ever changed by this
   package (Hard Rule 2).
6. **Shadow Trading** — a 2-way Configuration Tournament restricted to
   exactly "production" vs. "candidate," produced via
   `research_engine.effectiveness.compare_buckets`. No capital, no
   execution — pure data comparison over two already-recorded
   `ClosedTradeHistory`s from the same historical window.
7. **Stress Testing** — replays `HistoricalScenario`s tagged with a
   `StressScenarioTag` (high spread, low liquidity, gap open, flash
   crash, COVID, Brexit, central bank intervention, NFP, FOMC, holiday
   trading, weekend gap) through the same verification path as §3,
   confirming it never raises and that Compliance/Risk's recorded
   decisions correctly reflect the stressed condition (e.g. a
   `market_closed`/`trading_halted` scenario's recorded `ComplianceSnapshot`
   must not be `ready_for_bridge`).
8. **Walk-Forward Testing** — splits a `ClosedTradeHistory` into
   train/validation/out-of-sample buckets by `evaluated_at`, computing
   `research_engine.attribution.compute_bucket_statistics` per bucket
   and flagging degradation via the same expectancy-delta comparison
   `research_engine.effectiveness.compare_buckets` already implements.
9. **Monte Carlo Validation** — converts `ClosedTradeHistory` to
   `risk_engine.models.TradeHistory` (same adapter pattern `ADR-029`
   §0 established) and calls `risk_engine.monte_carlo.run_monte_carlo`
   directly — zero new simulation code.
10. **Drift Detection** — current-period vs. historical-baseline-period
    comparison, per strategy/pair/session/regime (via
    `research_engine.effectiveness.compare_buckets` over each
    dimension's grouped trades) and per execution quality (via
    `research_engine.execution_quality.summarize_execution_quality`'s
    composite score, compared).
11. **Confidence Calibration** — groups executed `ClosedTrade`s by their
    existing `risk_confidence_tier` field and verifies higher tiers do
    not show materially worse expectancy than lower tiers (a monotonicity
    check, not a new statistic — `compute_bucket_statistics` again).
12. **Execution Validation** — static consistency checks over recorded
    `BridgeExecutionRecord`s (executed size never exceeds Compliance's
    approved size; an executed record never accompanies a REJECT
    decision; slippage is within a configured sanity bound).
13. **Independent Audit Report** — a human-readable narrative built
    purely from an already-produced `ValidationSnapshot` (§6) — no new
    computation, pure text assembly, mirroring `research_engine.
    explainability.build_research_snapshot`'s "pure assembly" pattern.

---

# 6. Output — `ValidationSnapshot`

One record per validation run:

- `pass_` (overall pass/fail — the AND of every component check that
  ran), `warnings: Tuple[str, ...]`, `recommendations: Tuple[str, ...]`
  (advisory only, Hard Rule 2).
- `replay_verifications: Tuple[ScenarioVerification, ...]`,
  `determinism_report: DeterminismReport`,
  `explainability_report: ExplainabilityReport`.
- `strategy_tournament`, `pair_tournament`, `session_tournament`:
  `Tuple[TournamentEntry, ...]` each.
- `configuration_tournament: ConfigurationTournamentResult`,
  `shadow_comparison: Optional[ShadowComparisonResult]`.
- `stress_test_results: Tuple[StressTestResult, ...]`.
- `walk_forward_result: Optional[WalkForwardResult]`.
- `monte_carlo_validation: Optional[MonteCarloValidationResult]`.
- `drift_analysis: DriftAnalysis`.
- `confidence_calibration: ConfidenceCalibrationResult`.
- `execution_validation: ExecutionValidationResult`.

**Type-level guarantee:** none of these types is structurally capable
of holding a trade instruction, a parameter mutation, or a config
change — verified by a dedicated architecture test, per every prior
stage's own precedent.

---

# 7. Testing

Unit, Replay, Tournament, Concurrency, Regression, Architecture, Stress,
Performance, Determinism, Explainability — the task's own 10 categories.

---

# 8. Acceptance criteria

- ✓ Never re-invokes the five upstream engines' compute logic (§3, §2.4).
- ✓ Every statistic traces to `risk_engine`/`research_engine`'s own
  already-accepted pure functions (§0, §2.5).
- ✓ Every tournament/drift/calibration finding is advisory text only,
  never applied (§2.2).
- ✓ Read-only, deterministic, stateless (§2.6, verified by AST test).

Per `ADR-001` and `CLAUDE.md` §1.10, no implementation begins until this
ADR's Status changes from Proposed to Accepted — it is accepted above,
in the same single pass `ADR-029` used, since the full spec arrived in
one message.
