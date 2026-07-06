# Changelog

Format loosely follows [Keep a Changelog](https://keepachangelog.com/).
Dates are UTC. This file starts 2026-07-05 forward — it is not a
retroactive record of everything before it. For the full history of
ADR-002 through ADR-013's implementation, the git log (every commit
carries an explicit message and `Co-Authored-By` line, per
`docs/adr/ADR-014-multi-agent-governance.md` §8/§11) remains the
authoritative record; this file does not attempt to reconstruct it.

Update convention: add a dated entry here as part of the "Implement"
phase of `.claude/agents/TEAM.md` §9's RPI workflow (or, for changes not
gated by that workflow, as part of `CLAUDE.md` §4's existing
"produce a change report" requirement).

## [Unreleased]

## 2026-07-06 (Phase 5 — production deployment & operations infrastructure)

### Added
- `phantom_pipeline/deployment/` — a new, 14th package: VPS/process
  supervision infrastructure for running Phantom on a Windows VPS, no new
  ADR (mirrors `orchestrator.py`, the Phase 3 adapters, and
  `paper_trading`'s own "tooling built around the pipeline, not a stage"
  framing — this phase sits one layer further out still: whole-process
  supervision, not trading-pipeline integration).
  - `models.py` — shared types: `ServiceState`, `DeploymentProfile`
    (DEV/PAPER/LIVE), `ServiceDefinition`, `ServiceStatus`,
    `RestartReason`/`RestartRecord`, `ConfigValidationIssue`/`Result`,
    `ResourceSample`, `MonitoringSnapshot`,
    `BackupRecord`/`BackupManifest`/`RestoreResult`,
    `DeploymentCheckResult`/`DeploymentReadinessReport`.
  - `config_manager.py` — `ConfigurationManager`: DEV/PAPER/LIVE profile
    loading from an injected mapping (never reads `os.environ` directly),
    pre-startup validation (missing secrets, invalid MT5 account, wrong
    broker profile, LIVE-must-not-paper-trade).
  - `service_manager.py` — `WindowsServiceManager`: auto-start after
    reboot, crash/hang detection and restart with a logged
    `RestartRecord`, and the hard rule "never restart MT5 while a trade
    is actively executing" via an injected `trade_in_progress` probe —
    a distinct layer above `watchdog.real_recovery_executor`'s own
    in-pipeline component recovery, never a duplicate of it.
  - `deployment_manager.py` — `ProductionDeploymentManager`: one-command
    `start_all`/`stop_all` over a dependency-ordered
    `Sequence[ServiceDefinition]` (topological sort on `depends_on`),
    pre-launch dependency verification, post-start health verification,
    graceful reverse-order shutdown.
  - `logging_manager.py` — rotating + JSON-structured logging, daily
    archive, crash-dump generation, retention-policy enforcement; pure
    stdlib, no new dependency.
  - `monitoring.py` — `ProductionMonitoring`: injected samplers for
    CPU/RAM/disk/network latency/MT5 connection quality/Python process
    health/Dashboard health, feeding `dashboard.config.DashboardConfig`'s
    already-declared `infrastructure_components` — a previously-unfilled
    gap, not a duplicate.
  - `backup_manager.py` — `BackupManager`: checksummed backup/restore for
    configuration, SQLite databases (via `sqlite3`'s online backup API,
    never a raw copy of a live DB file), analytics, and trade history;
    `verify_integrity` independently re-checksums the backup file itself.
  - `deployment_validator.py` — `DeploymentValidator`: the 10 named
    go-live checks as injected probes; `emergency_stop_functional` is
    documented and tested to be backed by `PositionManager`'s own,
    already-implemented `EMERGENCY_CLOSE` mechanism
    (`compliance_kill_switch_active`) — never a second, invented kill
    switch.
- `tests/phantom_pipeline/deployment/` — 49 tests covering every module,
  including the MT5-never-restarted-during-an-active-trade rule, the
  LIVE-profile validation rules, checksummed backup/restore round-trips,
  topological startup/shutdown ordering, and `emergency_stop_functional`
  driving the real `PositionManager.EMERGENCY_CLOSE` path end-to-end via
  the existing orchestrator fixtures.
- `LIVE_DEPLOYMENT_GUIDE.md`, `VPS_SETUP_GUIDE.md`,
  `DISASTER_RECOVERY.md`, `OPERATOR_CHECKLIST.md` — operator
  documentation for wiring and running the deployment package in
  production.
- `docs/plans/phase5-production-deployment.md` — the RPI Research/Plan/
  Validation artifact for this change.

### Changed
- Nothing in any existing `phantom_pipeline` file, ADR, or trading-logic
  module — confirmed via `git diff --stat` showing zero output against
  every tracked file; this change is 100% new files. Full suite re-run:
  1264/1264 tests (was 1215), `validate.py` 13/13,
  `scripts/check_architecture.py` clean (14 packages, no new cycle, no
  new cross-package private-state access).

## 2026-07-06 (Phase 4 — paper trading & forward validation)

### Added
- `phantom_pipeline/paper_trading/` — a new, 13th package: paper-trading
  and observability tooling built around the already-Accepted 12-stage
  pipeline, no new ADR (mirrors `orchestrator.py`'s own Phase 2 framing).
  - `session_manager.py` — `SessionManager`: London/Tokyo/Sydney/New York
    active-session detection, weekend handling, daily-reset/trading-day
    boundaries, for the Runner's own scheduling — never Scanner's own
    per-observation session tagging.
  - `account_tracker.py` — `AccountTracker`: turns a raw equity reading
    into the `daily_drawdown_pct`/`total_drawdown_pct` values
    `RiskEngine`/`ComplianceEngine`'s own `AccountState` types have always
    documented as an externally-supplied input — closing a real,
    previously-unfilled gap.
  - `forward_test_engine.py` — `ForwardTestEngine`/`ForwardTestReport`:
    win rate/profit factor/expectancy/max drawdown attributed directly
    from `AnalyticsEngine.compute_performance_statistics`; average RR,
    slippage, missed/blocked trade counts derived transparently from
    already-recorded `TradeProvenanceRecord` fields; execution latency,
    duplicate prevention, and recovery statistics attributed directly
    from each stage's own existing `*Metrics` object.
  - `prop_firm_validator.py` — `PropFirmValidator`/`PropFirmProfile`
    (FTMO/FundedNext reference presets): read-only config audit plus
    real-time status against already-produced `RiskDecision`/
    `ComplianceDecision` objects — a report, never a second blocking
    authority.
  - `report_generator.py` — `ReportGenerator`: daily/weekly/monthly
    reports (best/worst pair/session/regime, biggest winner/loser, rule
    blocking frequency, compliance/recovery statistics) built entirely
    from `AnalyticsEngine`'s existing grouping methods.
  - `paper_trading_runner.py` — `PaperTradingRunner`: drives
    `PipelineOrchestrator`'s existing public methods on a schedule,
    pulling one live tick per cycle and refusing to run against a
    non-demo account (caller-supplied `confirm_demo_account`, re-checked
    every cycle) — never places a live trade, never modifies any
    engine's decision logic.
  - `validation_dashboard.py` — `ValidationDashboardBuilder`: a new,
    paper-trading-scoped read-only snapshot (system/watchdog health, MT5
    connection, today's open/closed trades, prop-firm status, performance)
    — additive, since `dashboard.models.ViewName` is a closed enum this
    phase has no authorization to extend.
- `docs/plans/phase4-paper-trading.md` — the RPI Research/Plan/Validation
  artifact for this change.

### Changed
- Nothing in any existing `phantom_pipeline` file — confirmed via
  `git diff --stat` showing zero output against every tracked file; this
  change is 100% new files. Full suite re-run: 1215/1215 tests (was
  1130), `validate.py` 13/13, `scripts/check_architecture.py` clean (13
  packages, no new cycle, no new cross-package private-state access).

## 2026-07-06 (Phase 3 — real infrastructure adapters)

### Added
- `phantom_pipeline/mt5_bridge/mt5_adapter.py` — `MT5Adapter`, a real
  `BrokerAdapter` backed by the official `MetaTrader5` package. Translates
  `BrokerRequest` (OPEN/ADJUST/CLOSE) to/from real `order_send` calls;
  the MT5 client is an injectable constructor parameter (lazily imported
  otherwise) since the real package only runs against a live MT5
  terminal. 24 new tests.
- `phantom_pipeline/data_pipeline/market_data_adapter.py` —
  `MarketDataAdapter`, a real MT5-backed live-tick feed / historical
  loader / warm-cache bootstrapper feeding `DataPipeline`'s existing
  public methods only (`process_raw_tick`/`load_historical_bars`/
  `warm_start`) — never a new ingestion path. 12 new tests.
- `phantom_pipeline/dashboard/prometheus_adapter.py` — `PrometheusAdapter`,
  a real, read-only `PrometheusReadPort` querying a live Prometheus
  server's HTTP query API. Documents the info-metric label convention it
  expects from a future per-stage exporter (no such exporter exists yet —
  a flagged, real gap, not closed by this change). 10 new tests.
- `phantom_pipeline/watchdog/real_recovery_executor.py` —
  `RealRecoveryActionExecutor`, a real `RecoveryActionExecutor` performing
  all 8 named `RecoveryActionType` actions via systemctl restart, SIGHUP
  reload, real log rotation, and injectable per-component callbacks for
  the three actions that must reach a specific live dependency this
  package cannot import directly. 18 new tests.
- `docs/plans/phase3-real-adapters.md` — the RPI Research/Plan/Validation
  artifact for this change.

### Changed
- `VALIDATION_MATRIX.md` (Data Pipeline, MT5 Bridge, Watchdog, Dashboard
  sections) and `IMPLEMENTATION_PLAN.md` — a "Phase 3 addition" note per
  affected stage; no stage's status/exit-criteria row changed.
- Nothing in any existing `phantom_pipeline` file — confirmed via
  `git diff --stat` showing zero output against every tracked file; this
  change is 100% new files. `FakeBrokerAdapter`/`FakePrometheusReadPort`/
  `FakeRecoveryActionExecutor` remain unchanged and still back every
  existing test. Full suite re-run: 1130/1130 tests (was 1066), 13/13
  `validate.py`, `scripts/check_architecture.py` clean.

## 2026-07-06

### Added
- `.claude/agents/quant-validation-engineer.md`, `.claude/agents/
  integration-engineer.md`, `.claude/agents/ai-systems-engineer.md` —
  three new Governance Agents extending the Engineering Council from 10
  to 13, per explicit instruction. Quant Validation Engineer (statistical
  edge validation: walk-forward, Monte Carlo, overfitting, parameter
  robustness — advisory only, never edits strategy/scoring/risk code
  directly); Integration Engineer (post-hoc architectural verification:
  interface compatibility, dependency direction, circular-import
  detection, end-to-end pipeline wiring — verifies, does not design);
  AI Systems Engineer (AI-adjacent features only — trade memory, AI
  trade journal, explainable decisions, outcome analytics, NL dashboard,
  research assistant — hard-boundaried against ever generating a trade
  decision or influencing Scanner/Strategy Engine/Risk Engine/Compliance
  Engine/Execution Validator/MT5 Bridge/Position Manager).
- `docs/adr/ADR-014-multi-agent-governance.md` Amendment 2: documents the
  3 new Governance Agents (fills/authority/mandatory-review-trigger/RACI/
  de-duplication per role) and the decision to fold the requested
  "Reliability Engineer (SRE)" into the existing SRE role rather than add
  a 4th, duplicate agent.
- `TEAM.md` §1/§2/§3/§4/§5/§6/§7/§9 updated in place for the 3 new roles;
  SRE's §1/§4 entries extended to cover runtime-reliability review
  (recovery validation, chaos testing, restart validation) the request
  described under "Reliability Engineer (SRE)"; §5 RACI matrix corrected
  to reflect Watchdog/Dashboard's now-Accepted status (was stale "not yet
  drafted" text left over from before this session's earlier work); §6's
  prior "do not add an 11th agent" recommendation explicitly superseded
  for Quant Validation Engineer only, with the reversal's reasoning
  documented inline rather than silently overwritten.

### Changed (Council extension)
- Nothing in `phantom_pipeline/`, `phantom/`, or `tests/` — confirmed via
  `git diff --stat` showing zero output against all three. Full
  validation suite re-run (1066/1066 tests, `validate.py` 13/13,
  `scripts/check_architecture.py` clean) to confirm this documentation/
  governance-only change introduced no regression.

### Added
- `phantom_pipeline/orchestrator.py` — Phase 2 end-to-end Pipeline
  Orchestrator. Integration glue only (not a 13th stage, no new ADR):
  sequences the 12 already-Accepted stages (Data Pipeline through
  Dashboard, `ADR-013`/`ADR-002`-`ADR-012`) in `ADR-001`'s documented
  order via their existing public interfaces only, forwarding every
  output verbatim. `PipelineOrchestrator.run_scan_cycle()`,
  `record_fill()`, `manage_position()`, `evaluate_watchdog_health()`,
  `render_dashboard_snapshot()`.
- `tests/phantom_pipeline/orchestrator/` — 13 end-to-end integration
  tests: successful trade path, blocked trade path, rejected execution,
  MT5 acknowledgement, position management lifecycle, analytics
  recording, watchdog observation, dashboard visibility, replay
  determinism, pipeline restart, duplicate prevention, failure recovery,
  trace continuity.
- `docs/plans/pipeline-orchestrator.md` — the RPI Research/Plan/
  Validation artifact for this change.

### Changed
- Nothing in any of the 12 existing `phantom_pipeline/` stage packages
  or any pre-existing test file — confirmed via `git diff --stat`
  showing zero output against all of them. `scripts/check_architecture.py`
  passes clean (12 packages, no cycles, no private-state access).

## 2026-07-05

### Added
- `docs/adr/ADR-014-multi-agent-governance.md` Amendment 1: a Research →
  Plan → Implement (RPI) gated workflow, mapped entirely onto the
  existing 10 `TEAM.md` Council agents — no new agent, no new authority.
- `TEAM.md` §9: the RPI workflow's practical detail (phase-to-agent
  mapping, when it's mandatory vs. optional, artifact location).
- `docs/plans/` — the RPI Research/Plan/Validation artifact convention
  (`README.md`, `TEMPLATE.md`).
- `scripts/check_architecture.py` — a repeatable circular-import and
  cross-package private-state-access checker, formalizing the manual
  checks performed during the Phase 1 Certification Audit.
- `.claude/commands/rpi/research.md`, `plan.md`, `implement.md` — slash
  commands driving the three RPI phases via the existing Council agents.
- This file.

### Changed
- Nothing in `phantom_pipeline/` or `phantom/` — this entry is
  governance/tooling only; no trading logic, interface, or test was
  modified.
