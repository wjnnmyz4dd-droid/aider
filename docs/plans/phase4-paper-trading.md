# Plan: Phase 4 — Paper trading & forward validation

Status: Validated
Owner (Plan phase): Backend Architect
Touched components: new `phantom_pipeline/paper_trading` package only

---

## Research

- **Affected files and their dependencies**: none of the 12 existing
  pipeline-stage packages are modified. A new 13th package,
  `phantom_pipeline/paper_trading/`, is added — the same posture
  `orchestrator.py` (Phase 2) and the four real adapters (Phase 3)
  already established: integration/observability tooling built *around*
  an already-Accepted, already-implemented pipeline, never a new stage.
- **Duplicate-logic check performed before writing anything** (`CLAUDE.md`
  §1.4):
  - `PerformanceStatistics` (`analytics.models`, via `AnalyticsEngine.
    compute_performance_statistics`) already computes win rate, profit
    factor, expectancy, Sharpe, Sortino, average MAE/MFE, max drawdown —
    `ForwardTestEngine` reads this directly, never recomputes it.
  - `AnalyticsEngine.group_by_pair`/`group_by_session`/`group_by_regime`
    already exist — the daily/weekly/monthly reports' "best/worst
    pair/session/regime" reuse these directly, never a second grouping
    implementation.
  - `ExecutionValidatorMetrics.duplicate_prevention_count`,
    `ComplianceEngineMetrics.blocks_by_check`, `MT5BridgeMetrics.average_*
    _latency_seconds`, `WatchdogMetrics.restart_count`/
    `recovery_success_rate` already exist — read directly, never
    reimplemented.
  - `compliance_engine.config.SessionWindow` and `scanner.config.
    SessionWindow` are two *already-existing, independently-owned*
    private copies of the same trivial 5-field type (each package's own
    docstring says so explicitly) — this is the codebase's own
    established precedent for this exact situation, not an accident. A
    third, `paper_trading`-owned copy (for the Runner's own scheduling —
    daily reset, weekend pause — never for what Scanner attaches to a
    `ScannerObservation`) follows that same precedent rather than
    reaching cross-package into either existing one.
  - No existing config field represents a per-trade prop-firm lot cap —
    a genuine gap, not a duplicate; `PropFirmValidator` reports against
    it (advisory), never enforces it (that would require modifying Risk
    Engine/Compliance Engine, out of scope).
  - No existing field captures observed slippage as a number (only a
    configured *threshold* exists, `ComplianceEngineConfig.
    slippage_thresholds`). `ForwardTestEngine` derives it honestly from
    two already-recorded fields already present on a `TradeProvenanceRecord`
    (`market_snapshots` vs. `fill_reports`' fill price) when both exist for
    a record, and reports `None` — never a fabricated value — when they
    don't, mirroring `DataQualityReport.latency_seconds`'s own "None means
    cannot be honestly measured" precedent.
- **Touched stages' ADR status**: no stage's ADR is touched. `ADR-002`
  through `ADR-014` are all Accepted and read-only inputs to this
  package's design.
- **`python3 scripts/check_architecture.py` result (baseline, before this
  change)**: PASS — 12 packages, no cycles, no private-state access.
  Every cross-package import this new package makes targets only another
  package's own `__init__.py` (e.g. `from ..analytics import
  AnalyticsEngine, TradeProvenanceRecord`) — never a private submodule
  (`.config`, `.engine`, `.checks`, etc.) — so the check's rule extends
  cleanly to a 13th package without modification to the check itself.

## Plan

- **Approach**: one new package, `phantom_pipeline/paper_trading/`,
  containing:
  - `session_manager.py` — `SessionManager`: active-session detection,
    weekend handling, daily-reset/trading-day boundaries, for the
    Runner's own scheduling decisions only.
  - `account_tracker.py` — `AccountTracker`: turns a raw equity reading
    (from `MT5Adapter.query_account_equity()`) into the
    `daily_drawdown_pct`/`total_drawdown_pct` values `RiskEngine.
    AccountState`/`ComplianceEngine.AccountState` already expect as an
    externally-supplied input (their own docstrings document this as an
    assumed upstream computation, never previously implemented anywhere
    in this repository) — closing a real, previously-unfilled gap, not
    duplicating either engine's own constraint-evaluation logic.
  - `forward_test_engine.py` — `ForwardTestEngine`/`ForwardTestReport`:
    pure aggregation over already-computed `PerformanceStatistics` +
    every stage's own `metrics.py` object + `TradeProvenanceRecord`
    fields.
  - `prop_firm_validator.py` — `PropFirmValidator`/`PropFirmProfile`/
    `PropFirmComplianceStatus`: read-only comparison of deployed
    `RiskEngineConfig`/`ComplianceEngineConfig` values against a named
    profile's public thresholds, plus real-time status read from
    already-produced `RiskDecision`/`ComplianceDecision` objects — reports
    a finding, never blocks a trade (that authority remains exclusively
    Risk Engine's/Compliance Engine's).
  - `report_generator.py` — `ReportGenerator`: daily/weekly/monthly
    reports built from `AnalyticsEngine`'s existing grouping methods +
    `ForwardTestEngine` + `PropFirmValidator`.
  - `paper_trading_runner.py` — `PaperTradingRunner`: wraps an
    already-constructed `PipelineOrchestrator` + `MT5Adapter` +
    `MarketDataAdapter` + `SessionManager` + `AccountTracker`, with an
    explicit, checked demo-account guard (never places a live trade).
  - `validation_dashboard.py` — `ValidationDashboardView`/
    `ValidationDashboardBuilder`: a new, paper-trading-scoped read-only
    view type (the existing `dashboard.models.ViewName` is a closed
    10-value enum that Phase 4 has no authorization to extend — a
    separate view type is additive, not a modification).
- **Architectural-compliance confirmation**: no new pipeline stage, no
  new ADR, no new decision object, no change to any existing engine's
  decision logic anywhere. Every one of the six modules above is either
  (a) a pure reader/aggregator of already-produced, immutable objects, or
  (b) new plumbing this architecture always assumed existed externally
  (account-state computation) but never implemented until now.
  `PaperTradingRunner` never submits an order MT5Bridge/ExecutionValidator
  didn't already approve — it only drives the existing orchestrator's
  existing public methods on a schedule, exactly as `orchestrator.py`'s
  own docstring already describes for any caller.
- **Files to be touched** (all new; zero existing `phantom_pipeline` file
  is modified):
  - `phantom_pipeline/paper_trading/__init__.py` + 7 module files above
  - `tests/phantom_pipeline/paper_trading/` — one test file per module +
    one end-to-end integration test file
- **Boundaries (what this change explicitly does NOT do)**:
  - Never places a live trade — `PaperTradingRunner` refuses to run
    unless the injected `MT5Adapter`'s connected account reports a demo
    trade mode (or a caller-supplied `require_demo=True` override for a
    test double that cannot express a real MT5 account object).
  - Never adds a new blocking authority — `PropFirmValidator`'s output is
    a status report; it has no method capable of rejecting a candidate,
    trade, or decision.
  - Never modifies `dashboard.models.ViewName`, any existing engine, or
    any existing config default.
  - Does not implement a persistent report-storage/scheduling daemon —
    `ReportGenerator`/`PaperTradingRunner` are pure, callable components a
    real deployment's own scheduler (cron, systemd timer) would invoke;
    building that scheduler is deployment-specific, out of scope.

## Validation

- `python3 -m compileall phantom_pipeline tests scripts`: clean.
- `python3 -m unittest discover -s tests/phantom_pipeline`: full suite
  green, no regression against the Phase 3 baseline (1130/1130).
- `python3 validate.py`: 13/13.
- `python3 scripts/check_architecture.py`: PASS — 13 packages, no new
  cycle, no new cross-package private-state access.
- Code Reviewer / Test Results Analyzer / Integration Engineer /
  Quant Validation Engineer sign-off: self-certified in this same session
  per the Council's existing solo-session precedent (Phases 1–3);
  Integration Engineer's checklist applied directly (new package crosses
  every existing package's boundary via read-only imports only); Quant
  Validation Engineer's lane (statistical edge validation) is
  out-of-scope here since Phase 4 adds no new strategy/scoring logic —
  noted for completeness, not invoked.
