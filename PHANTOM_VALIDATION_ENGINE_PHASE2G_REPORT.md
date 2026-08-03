# Phantom Validation Engine — Phase 2G Deliverables Report

**Status:** Complete. Validation Engine implemented per `docs/adr/ADR-030-validation-engine.md`
(Accepted). Per the task's own "STOP" instruction, **Phase 3 is not
started**, awaiting approval.

---

## 0. Design decisions

1. **Consume recorded snapshots, never re-invoke the five upstream
   engines (ADR-030 §3, Hard Rule 4).** The task describes "Historical
   Replay" as "Evidence ↓ Market Intelligence ↓ Strategy ↓ Risk ↓
   Compliance ↓ Bridge. Verify every output." Two readings were
   possible: re-run the five engines' own compute logic against raw
   historical bars, or verify already-recorded `*Snapshot` outputs
   against the structural invariants those engines' own Hard Rules
   already promise. The second reading was adopted — it keeps the
   Validation Engine a pure downstream verifier (mirroring every other
   engine's "consume upstream's snapshot, never recompute it"
   discipline) and avoids any tension with Hard Rule 4's "no evidence
   calculations, no compliance decisions." `HistoricalScenario` therefore
   bundles the five engines' real, frozen `*Snapshot` types directly —
   never a raw `Bar`.
2. **Disclosed overlap with `ADR-018` Replay & Certification Engine.**
   `ADR-018` (Accepted, `phantom_pipeline` lineage) already owns replay,
   determinism, walk-forward, Monte Carlo, and shadow trading vocabulary
   — for a different purpose (certifying a *candidate strategy/change*
   for promotion via `phantom_pipeline`'s Analytics/Data Pipeline). This
   ADR validates the *six engines actually built this session* against
   already-recorded scenarios. Neither consumes the other's inputs or
   outputs; ADR-030 §0 documents this explicitly rather than silently
   duplicating.
3. **Zero new statistics formulas.** Every number in every tournament,
   walk-forward split, Monte Carlo validation, drift finding, and
   confidence-calibration check traces to `risk_engine.statistics.
   compute_statistical_metrics`, `risk_engine.monte_carlo.run_monte_carlo`,
   or `research_engine.ranking`/`.attribution`/`.effectiveness`/
   `.execution_quality` — all imported, none reimplemented. The Strategy/
   Pair/Session Tournament is, mechanically, `research_engine.
   strategy_intelligence.rank_strategies`/`.pair_intelligence.rank_pairs`/
   `.session_intelligence.rank_sessions` called directly, widened into a
   `TournamentEntry` that additionally surfaces `recovery_factor`
   (already a `StatisticalMetrics` field).
4. **Confidence-tier ordering reuses `risk_engine.config.
   DEFAULT_CONFIDENCE_SCHEDULE`'s own `min_score`** rather than inventing
   a second ranking for the same tiers.

---

## 1. Folder structure

```
phantom/validation_engine/
    __init__.py
    models.py
    config.py
    replay.py
    determinism.py
    explainability.py
    tournament.py
    configuration_tournament.py
    shadow_trading.py
    stress_testing.py
    walk_forward.py
    monte_carlo_validation.py
    drift_detection.py
    confidence_calibration.py
    execution_validation.py
    audit.py
    engine.py
    logging_sink.py
    metrics.py

tests/phantom/validation_engine/
    _fixtures.py
    test_replay.py            (Replay)
    test_determinism.py       (Determinism)
    test_explainability.py    (Explainability)
    test_tournament.py        (Tournament)
    test_stress.py            (Stress)
    test_walk_forward.py                (Unit)
    test_monte_carlo_validation.py       (Unit)
    test_drift_detection.py             (Unit)
    test_confidence_calibration.py      (Unit)
    test_execution_validation.py        (Unit)
    test_engine.py            (Unit + Regression)
    test_concurrency.py       (Concurrency)
    test_architecture.py      (Architecture)
    test_performance.py       (Performance)
```

## 2. File list

19 production files, 1,639 lines. 16 test files, 952 lines. 58 tests.

## 3. Interfaces

- `ValidationEngine(config, metrics=None).evaluate(run: HistoricalRun, closed_trades: ClosedTradeHistory, configuration_runs=(), shadow_production=None, shadow_candidate=None, walk_forward_train_end=None, walk_forward_validation_end=None, drift_baseline=None, drift_current=None, now=None) -> ValidationSnapshot`
- `ValidationEngine.build_audit_report(snapshot) -> str`
- Component functions, each independently callable and reused by `engine.py`: `verify_scenario`/`verify_run`, `check_determinism`/`check_determinism_for_run`, `build_explainability_report`, `run_strategy_tournament`/`run_pair_tournament`/`run_session_tournament`, `run_configuration_tournament`, `run_shadow_comparison`, `run_stress_test`/`run_stress_tests`, `run_walk_forward`, `run_monte_carlo_validation`, `detect_drift`, `run_confidence_calibration`, `validate_execution`, `build_independent_audit_report`.

## 4. Data models

`HistoricalScenario` (bundles the five engines' recorded `*Snapshot` types + optional `BridgeExecutionRecord` + optional `StressScenarioTag`), `HistoricalRun`, `ConfigurationRun`, `BridgeExecutionRecord`, `ScenarioVerification`/`OutputVerification`, `DeterminismReport`/`DeterminismCheck`, `ExplainabilityReport`/`ExplainabilityCheck`, `TournamentEntry`, `ConfigurationTournamentResult`, `ShadowComparisonResult`, `StressTestResult`, `WalkForwardResult`, `MonteCarloValidationResult`, `DriftAnalysis`/`DriftFinding`, `ConfidenceCalibrationResult`/`ConfidenceTierStatistics`, `ExecutionValidationResult`, `ValidationSnapshot`. All frozen dataclasses.

## 5. Dependency graph

`validation_engine` → `evidence_engine.models`, `market_intelligence.models`, `strategy_engine.models`, `risk_engine.{models,config,statistics,monte_carlo}`, `compliance_engine.{models,explainability}` (test fixtures only), `research_engine.{models,config,attribution,ranking,effectiveness,execution_quality,pair_intelligence,strategy_intelligence,session_intelligence}`. No package imports `validation_engine` back (verified — it is the newest, topmost cross-cutting observer). Zero import of `phantom_pipeline` or `phantom.bridge`.

## 6. Testing report

58 new tests across the task's own 10 categories (Unit, Replay, Tournament, Concurrency, Regression, Architecture, Stress, Performance, Determinism, Explainability). Full repo suite: **2,368/2,368 passing** (up from 2,310 before this phase). `scripts/check_architecture.py`: PASS (17 `phantom_pipeline/` packages, unaffected — that script is scoped to the legacy pipeline only).

## 7. Performance

50-scenario historical run + 210 closed trades across 7 pairs: full `evaluate()` well under the 10s test budget (sub-second in practice).

## 8. Architecture verification

- No forbidden vocabulary (BUY/SELL/place_order/select_strategy/mutate_parameter/etc.) anywhere in package source.
- No import of `phantom_pipeline` or `phantom.bridge`.
- Only the six permitted upstream `phantom/` packages imported.
- No ML/LLM/`random` import.
- `ValidationEngine.__init__` assigns only `self.config`/`self.metrics` (AST-verified).
- No public method resembles a mutation/execution/selection API.

## 9. Confirmation

`git status --short` on `phantom/bridge`, `phantom/evidence_engine`, `phantom/market_intelligence`, `phantom/strategy_engine`, `phantom/risk_engine`, `phantom/compliance_engine`, `phantom/research_engine`, their test directories, `scripts/check_architecture.py`, and `phantom_pipeline/` shows **zero changes** — all six prior engines and the Bridge/Runtime remain frozen.

## Recommendation

Ship as-is. Per the task's own "STOP" instruction, Phase 3 is out of scope for this phase. Awaiting approval to proceed.
