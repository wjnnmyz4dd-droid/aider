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

## 2026-07-24 (Compliance day-one bootstrap verification — KNOWN_GAPS.md #9)

### Added
- `titan_protocol/compliance_state_store/bootstrap.py` --
  `is_account_verified_flat()`/`resolve_bootstrap_balance()`, pure
  functions deciding whether a fresh install's first-ever reported
  balance may be trusted as `daily_starting_balance`. Verified flat
  means no open positions and `balance == equity` within
  `flat_account_equity_tolerance` (default 0.01) -- the strongest signal
  wire data alone can give that the balance wasn't already contaminated
  by trading activity in progress.
- `ComplianceStateStoreConfig.day_start_balance_override` (optional) --
  an operator-confirmed day-start balance that bypasses verification
  entirely and is used immediately. `ComplianceStateStoreConfig.
  flat_account_equity_tolerance` (default 0.01) -- the balance/equity
  comparison tolerance.
- `compliance.day_start_balance_override` /
  `compliance.flat_account_equity_tolerance` in
  `deployment_windows/config_loader.py` and the shipped example config,
  both fail-closed at startup for a non-positive value.
- Tests: `tests/titan_protocol/compliance_state_store/
  test_bootstrap_verification.py` (20 tests -- pure functions plus
  `ComplianceStateStore.load_or_bootstrap()` integration: flat bootstrap,
  open-positions/floating-P&L blocks bootstrap, override bypass, config
  validation), plus new cases in `tests/deployment_windows/
  test_config_loader.py` and `tests/deployment_windows/
  test_compliance_state_persistence.py` covering the real `start.py`
  wiring.

### Changed
- `ComplianceStateStore.load_or_bootstrap()` now takes optional
  `current_equity`/`has_open_positions` (defaulting to "flat", so every
  pre-existing caller is unaffected) and returns `Optional[
  PersistedComplianceState]` -- `None` when a fresh install's account
  isn't yet verified flat and no override is configured, meaning the
  caller must skip the cycle rather than bootstrap from a possibly-
  contaminated balance.
- `deployment_windows/start.py`'s `_build_compliance_account_state()`
  now passes the EA-reported `equity` and `bridge_engine.latest_positions`
  through to the gate above, and returns `(None, None)` (same fail-closed
  convention as "no account state reported yet") while bootstrap
  verification is pending.
- `KNOWN_GAPS.md` section 9: OPEN -> CLOSED, with the fix documented and
  the one residual limitation this can't close (a trade opened and
  closed the same day, before Titan ever received a report, still
  contaminates `balance` in a way no wire field reveals -- the
  override exists for that case).

### Validation
- Full repository suite: 3038 tests; only the three pre-existing,
  environment-only `flask`-import failures (unrelated).
- `compileall` clean across `titan_protocol/`, `tests/`,
  `deployment_windows/`, `scripts/`.
- Zero regression: every pre-existing `compliance_state_store`/
  `config_loader`/`start.py` test continued passing unchanged, since the
  new parameters default to the exact behavior those tests already
  relied on.

## 2026-07-24 (Phase 3C end-to-end ingestion integration tests — ADR-033)

### Added
- `tests/titan_protocol/runtime/test_phase_3c_ingestion_integration.py` —
  the ADR-033 SS7 end-to-end suite that had not yet been written: every
  other Phase 3C test proves `market_data_ingestion`/`news_ingestion` in
  isolation, but none drove a real `RuntimeOrchestrator.run_cycle_for_pair()`
  call with data that actually passed through both ingestion engines.
  Four tests: (1) bars fed through `MarketDataIngestionEngine.ingest_bar()`
  (validation, ordering, warmup, retention buffer) reach the real
  Evidence -> Strategy -> Risk -> Compliance -> Bridge chain and produce
  a genuine `SUBMITTED` `TrendContinuation` trade, not just a "didn't
  crash" smoke test; (2) a high-impact event produced by
  `NewsIngestionEngine.fetch_events()` (through the real failover engine
  and `adapter.to_market_intelligence_event()`) reaches
  `MarketIntelligenceEngine`'s real blackout logic inside that same
  cycle, observed via a thin recording spy since `RuntimeAuditRecord`
  only carries a rendered summary string, not the structured snapshot;
  (3) both news providers failing closed still yields
  `(events=(), trusted=False)` through the real seam, documenting the
  caller-side gate contract ADR-033 SS4.2 requires (Runtime itself has
  no `news_feed_trusted` passthrough); (4) the distinct `backfill()`
  startup code path also produces pipeline-compatible output, not just
  the live `ingest_bar()` loop.

### Verified
- `market_data_ingestion` (44 tests) and `news_ingestion` (52 tests) test
  suites, already present from earlier Phase 3C work, both still pass in
  full — closing tasks #275/#277 which the task tracker had left marked
  in-progress/pending despite the suites already existing and passing.
- Full repository suite: 3007 tests, only the three pre-existing,
  environment-only `flask`-import failures (unrelated to this or any
  prior phase, per ADR-033 SS8's own stated exclusion).
- `git diff --stat` against `titan_protocol/evidence_engine/`,
  `market_intelligence/`, `strategy_engine/`, `risk_engine/`,
  `compliance_engine/`, `runtime/`, `bridge/`, `reliability/` — zero
  output. This change is a new test file only; no frozen package was
  touched (ADR-033 SS8 acceptance criterion).
- `deployment_windows/start.py` was already wiring both ingestion engines
  into the live-cycle loop (confirmed by direct read, not assumed) —
  ADR-033 SS0's own forward reference to "SS9" for this wiring points at
  a section that does not exist in the ADR document; the wiring itself
  is real and tested, only the ADR's internal cross-reference is stale.
  Left as-is (a documentation-only inconsistency, out of scope for a
  test-only change per the Minimal Change Engineer philosophy).

## 2026-07-22 (WinINet proxy/WPAD diagnostic for `WebRequest()` failures)

### Added
- `deployment_windows/diagnose_wininet.py` — diagnoses the WinINet-layer
  `WebRequest()` instability documented as still-open in `KNOWN_GAPS.md`
  section 11 (and now section 12). Reads the operator's proxy registry
  state (`ProxyEnable`/`ProxyServer`/`ProxyOverride`/`AutoConfigURL`) and
  times a request to the Bridge's `/bridge/heartbeat` twice — once
  proxy-aware, once with the proxy explicitly bypassed — to give the
  operator a measured timing delta as evidence rather than a guess.
  `--fix` adds `127.0.0.1`/`<local>` to `ProxyOverride` so loopback
  traffic skips proxy resolution, then re-times the request to prove the
  change helped; it never touches `ProxyEnable`/`ProxyServer` since the
  deployment may still need the real proxy for external news-provider
  calls. Explicitly documents its one limitation: it cannot evaluate a
  PAC script the way WinINet does, since `urllib` does not execute
  JScript.

### Changed
- `WINDOWS_OPERATOR_GUIDE.md` — added "7. If `WebRequest()` still fails
  after the allow-list is confirmed", documenting how to run the new
  diagnostic and what `--fix` will and will not change.
- `KNOWN_GAPS.md` — added section 12 describing the new tool and its
  scope; the underlying WinINet instability itself remains OPEN, as an
  environment property of the operator's VPS, not a code defect.

## 2026-07-22 (Native socket transport removed entirely — HTTP-only — ADR-034 Amendment 10)

### Removed
- `titan_protocol/bridge/socket_transport.py` — the entire native MQL5
  socket server module, deleted outright.
- `BridgeConfig.transport`, `VALID_TRANSPORTS`, `socket_port`,
  `socket_max_message_bytes`, `socket_idle_timeout_seconds`,
  `socket_max_connections` — removed from `titan_protocol/bridge/config.py`.
- `BridgeMetrics`'s ten `socket_*` counters and `socket_health_snapshot()`.
- `server.py`'s socket-frame-only rejection labels
  (`invalid_json_frame`, `missing_or_invalid_seq`,
  `missing_or_invalid_route`, `missing_or_invalid_body`,
  `duplicate_or_replayed_seq`).
- `TitanProtocolEA.mq5`'s entire socket-transport section: the
  `ENUM_TRANSPORT_MODE` enum, `Transport`/`Socket*` inputs, the
  runtime-fallback globals, and every socket-transport function
  (`EnsureSocketConnected()`, `SocketSendFrame()`, `SocketReadFrame()`,
  `SocketRequest()`, etc). `BridgeRequest()`/`BridgePollCommands()` are
  now thin HTTP-only wrappers.
- `deployment_windows/start.py`'s dual-listen (socket primary + HTTP
  fallback) logic — collapsed to a single `bridge_serve()` call.
- `deployment_windows/verify_transport_configuration.py` and its test —
  this tool only ever diagnosed a socket-vs-HTTP mismatch, a condition
  that cannot occur with one transport.
- Socket-specific log parsing in `diagnose_communication.py`
  (`_parse_bridge_rotating_log`, the rotating-log discovery step).

### Changed
- `deployment_windows/config_loader.py`, `install.py`,
  `install_mt5_files.py`, `health_check.py` — all transport-selection
  and socket-specific personalization/verification logic removed; HTTP
  is now the sole, unconditional path.
- `WINDOWS_OPERATOR_GUIDE.md` — allow-list instructions simplified to
  WebRequest-only; socket allow-list steps removed.
- `docs/adr/ADR-034-mt5-bridge-transport-hardening.md` — Amendment 10
  documents the full rationale, including this deployment's own
  evidence that HTTP independently fails on this VPS (WinINet-layer
  `pseudoStatus=1001`/`5203`), and that this was the operator's explicit
  decision made with full knowledge of that evidence, not a code fix for
  the underlying WinINet problem.

### Preserved (unaffected by this change)
- HTTP poll-level exponential backoff, the atomic Delivered/Abandoned
  in-flight command lifecycle, position-confirmation timeout and
  restart-safe persistence (Amendments 8/9), replay protection, health
  monitoring — none of these were transport-specific.
- All trading logic, Compliance Engine, AI/research packages, and risk
  management — untouched.

## 2026-07-21 (Position-confirmation timeout + restart-safe in-flight persistence — ADR-034 Amendments 8/9)

### Added
- `RuntimeConfig.position_confirmation_timeout_seconds` (default 120.0,
  configurable via `runtime.position_confirmation_timeout_seconds` in
  the JSON config) — bounds how long `InFlightCommandRegistry` lets a
  resolved (executed/rejected) pair wait for a confirming
  `/bridge/positions` snapshot before releasing it fail-safe.
- `InFlightCommandRegistry.expire_stale_position_confirmations()` and
  `.position_confirmation_timeout_count()` — releases a pair once it
  exceeds the new timeout, logs a clear warning, and exposes a
  cumulative counter through `run_status`/`health_check.py` alongside
  the existing `awaiting_position_confirmation_count()`.
- `titan_protocol/runtime/in_flight_store.py` (`InFlightCommandStore`/
  `InFlightStoreConfig`) — restart-safe persistence of
  `InFlightCommandRegistry`'s minimal pair-level state (correlation_id,
  pair, state, original timestamp only), using the same atomic-write
  technique as `titan_protocol.compliance_state_store`. Loaded and
  restored once at Bridge startup (`InFlightCommandRegistry.restore()`)
  before the first live cycle, and saved once per cycle after that
  cycle's reconciliation, so an abandoned/resolved-and-confirmed pair
  can never be persisted, let alone restored.
- `tests/titan_protocol/runtime/test_in_flight_store.py`,
  `tests/titan_protocol/runtime/test_bridge_restart_integration.py`, and
  an expanded `tests/titan_protocol/runtime/test_in_flight_commands.py`
  (new `TestExpireStalePositionConfirmations` and
  `TestSnapshotForPersistenceAndRestore` classes) — round-trip,
  corruption, and simulated-restart coverage for both hardening items.

### Changed
- `deployment_windows/config_loader.py`/
  `deployment_windows/config/titan_protocol_config.example.json` — the
  new `position_confirmation_timeout_seconds` field wired through the
  existing config-loading pattern.
- `deployment_windows/start.py` — constructs and threads
  `InFlightCommandStore` through `_live_cycle_loop()` (same pattern as
  the existing `compliance_state_store` parameter); the per-cycle
  reconcile block now also calls `expire_stale_position_confirmations()`
  and persists the reconciled snapshot.

### Documented (no code change)
- `docs/adr/ADR-034-mt5-bridge-transport-hardening.md` — Amendments 8
  and 9, including the accepted limitation that a restored entry can
  only ever be released by its own TTL/timeout, never by a late-arriving
  `ExecutionReport` for a correlation_id the restarted `CommandQueue` no
  longer remembers (deliberate, given `ComplianceEngine`'s independent
  `max_positions_per_pair` check already covers the actual
  duplicate-position outcome once positions reporting resumes).

## 2026-07-08 (Hybrid MT5 MQL5 EA Bridge — ADR-023)

### Added
- `docs/adr/ADR-023-mql5-ea-bridge.md` — a transport-only MQL5 EA bridge:
  the EA attaches to an MT5 chart, relays telemetry (heartbeat, account
  state, ticks, bars, positions) to Phantom, and executes only commands
  Phantom has already approved. Python remains the sole decision
  authority; no pipeline-stage package changes as a result of this work.
- `phantom_pipeline/ea_bridge/` — `EABridgeConfig`, transport models
  (`HeartbeatMessage`/`EAAccountState`/`TickMessage`/`BarMessage`/
  `PositionReport`/`ExecutionCommand`/`ExecutionReport`/`ErrorReport`/
  `EmergencyStopState`), `validation.py` (API key/magic number/symbol
  allowlist/volume/SL-TP/timestamp checks), `CommandQueue` (idempotent,
  fail-closed command relay keyed by `execution_id`), `EABrokerAdapter`
  (implements the existing `mt5_bridge.BrokerAdapter` ABC exactly — zero
  `mt5_bridge` code change required), `EABridgeEngine` (orchestrates
  `DataPipeline`/`CommandQueue`/`EABrokerAdapter`), a stdlib-only HTTP
  server exposing 9 routes (`/ea/heartbeat`, `/ea/account`, `/ea/tick`,
  `/ea/bars`, `/ea/positions`, `/ea/commands/poll`,
  `/ea/execution/report`, `/ea/error/report`, `/ea/emergency-stop`),
  plus `logging_sink.py`/`metrics.py`/`__init__.py`.
- `mt5/PhantomBridgeEA.mq5` + `mt5/PhantomBridgeEA.set` — the MQL5 EA
  itself: configurable backend URL/API key/heartbeat/bar-sync intervals,
  symbol allowlist, magic number isolation, fail-closed timeout, an
  emergency-disable switch, and `CTrade`-backed execution of
  Phantom-approved commands only.
- `tests/phantom_pipeline/ea_bridge/` — 104 tests covering validation,
  command-queue idempotency/staleness/fail-closed behavior, the broker
  adapter, the engine, all 9 HTTP endpoints end to end, and a structural
  boundary suite confirming `EABrokerAdapter` is the only new
  `BrokerAdapter` subclass and that no protected pipeline-stage package
  changed.
- `MT5_EA_BRIDGE_GUIDE.md` — deployment guide covering EA installation,
  `WebRequest` allowlisting, wiring `EABrokerAdapter` into `MT5Bridge`,
  the security checklist, fail-closed behavior, and the Phase-1
  hand-rolled-JSON limitation.

### Scope
- `ea_bridge` deliberately joins neither `PIPELINE_STAGE_PACKAGES` nor
  `CROSS_CUTTING_OBSERVER_PACKAGES` in `scripts/check_architecture.py` —
  it holds no decision authority and is not a read-only analytics
  observer; it is consumed only through `mt5_bridge`'s existing
  constructor-injection point, the same relationship `MT5Adapter`
  already has.
- Not deployed to live and not wired into any default startup path —
  `EABrokerAdapter` is available but must be constructed explicitly by
  whichever deployment chooses an EA-backed terminal over the direct
  `MetaTrader5` adapter.

## 2026-07-07 (Statistical Risk Integration — ADR-022 Amendment 1)

### Added
- `docs/adr/ADR-022-statistical-risk-management.md` Amendment 1 —
  documents the one classification change (`analytics` leaves
  `scripts/check_architecture.py`'s `PIPELINE_STAGE_PACKAGES` restricted
  set, since it holds no decision authority — `ADR-010` §1/§3/§11) and
  the 8 additive integration points below.
- `phantom_pipeline/statistical_risk/dashboard.py` — `StatisticalRiskDashboardBuilder`,
  `trend_point_from_assessment()`; `StatisticalRiskTrendPoint`/
  `StatisticalRiskTrendReport`/`StatisticalRiskDashboardSnapshot` added to
  `statistical_risk/models.py`; `StatisticalRiskEngine.kelly_recommendation()`/
  `.compute_trend()`/`.confidence_interval()` added (all additive,
  `assess()`'s existing signature/return type unchanged).
- `phantom_pipeline/paper_trading/statistical_risk_backtest.py` —
  `StatisticalRiskBacktester`: compares actual realized PnL against what
  following each recommendation's implied risk fraction would have
  produced (a documented linear-scaling estimate, not a re-simulation).
- `tests/phantom_pipeline/orchestrator/test_statistical_risk_integration.py` —
  19 end-to-end tests: trace ID continuity, no regression (wiring in
  statistical_risk changes nothing else in a `CandidateCycleResult`),
  determinism across independent orchestrators, historical storage,
  dashboard rendering, knowledge ingestion (+ dedup), research desk
  integration (thesis/journal/strategy-research/explainable), paper
  trading backtest.

### Changed
- `scripts/check_architecture.py` — `analytics` removed from
  `PIPELINE_STAGE_PACKAGES` (joins `watchdog`/`dashboard`/`paper_trading`/
  `deployment` as already outside the restricted set); `statistical_risk`
  unchanged in `CROSS_CUTTING_OBSERVER_PACKAGES` — the 9 remaining
  pipeline-stage packages (`risk_engine` included) are still structurally
  forbidden from ever importing `statistical_risk`.
- **Orchestrator**: `PipelineOrchestrator` gains two new `Optional`,
  default-`None` constructor parameters (`statistical_risk`,
  `statistical_risk_records_provider`) — omitting either reproduces
  every prior caller's behavior exactly. `_run_candidate()` computes one
  `StatisticalRiskAssessment` immediately after `risk_decision` (never
  gating, altering, or delaying any stage below it) and forwards it to
  Analytics and a new, defaulted `CandidateCycleResult.statistical_risk_assessment`
  field. New `render_statistical_risk_dashboard_snapshot()` method,
  wholly separate from `render_dashboard_snapshot()`'s existing dict.
- **Analytics**: `TradeProvenanceRecord` gains two new, defaulted, loosely-
  typed (`Any`) fields — `statistical_risk_assessment`, `kelly_recommendation`
  — mirroring `account_snapshots`' own precedent, specifically to avoid
  an analytics ↔ statistical_risk circular import (`statistical_risk`
  already depends on `analytics.models.TradeProvenanceRecord`). New
  `collect_statistical_risk_assessment`/`collect_kelly_recommendation`
  methods on `AnalyticsEngine`, mirroring every existing `collect_*`.
- **Paper Trading**: `PeriodReport` gains two new, defaulted fields
  (`statistical_risk_trend`, `statistical_risk_backtest`); `ReportGenerator.generate*()`
  accept them as new, defaulted parameters. `PaperTradingRunner` gains
  `preview_statistical_risk()`.
- **Knowledge**: new `DocumentKind.STATISTICAL_RISK_ASSESSMENT` value
  (18th member); `ingestion.build_statistical_risk_document()`;
  `KnowledgeEngine.record_statistical_risk_assessment()`/`find_statistical_risk_assessments()`.
- **AI Research Desk**: `TradeThesisGenerator`/`AITradeJournal` read the
  already-recorded `TradeProvenanceRecord.statistical_risk_assessment`
  they already receive (no new parameter needed);
  `WeeklyInstitutionalReviewGenerator` reads `PeriodReport.statistical_risk_trend`/
  `.statistical_risk_backtest` it already receives;
  `StrategyResearchAgent.best_worst_statistical_recommendation()` (new
  method); `MarketResearchAgent` gains an optional `statistical_risk_assessments`
  parameter and `MarketStructureFinding.statistical_risk_summary` (new,
  defaulted field). `ExplainableDecisionEngine.explain_statistical_risk()`
  answers the 8 named question shapes via deterministic templates.
- `tests/phantom_pipeline/research_desk/test_structural_boundary.py` —
  `DocumentKind` count assertion updated 17 → 18 (the test's own stated
  purpose — catch an unreviewed drift — is satisfied by tracking every
  intentional, ADR-documented addition, not by freezing the enum).

### Confirmed unchanged
- `risk_engine/`, `compliance_engine/`, `execution_validator/`,
  `position_manager/`, `mt5_bridge/`, `scanner/`, `strategy_engine/`,
  `dashboard/` — `git diff --stat` against all eight is empty.
  `StatisticalRiskAssessment`'s 18-field contract and `RiskRecommendation`'s
  4-value enum are unchanged. Full suite: 1629/1629 tests (1610 existing
  + 19 new integration tests, zero regressions), `validate.py` 13/13,
  `scripts/check_architecture.py` clean (17 packages).

## 2026-07-07 (Statistical Risk Management — ADR-022)

### Added
- `docs/adr/ADR-022-statistical-risk-management.md` — Accepted, per
  explicit user specification this session. A cross-cutting observer
  (same posture as `knowledge`/`research_desk`) that reads already-
  recorded historical trade data and computes advisory-only statistics.
  The deterministic Risk Engine (`ADR-005`) is not modified and remains
  the sole risk authority — enforced structurally, not just documented,
  by adding `statistical_risk` to `scripts/check_architecture.py`'s
  `CROSS_CUTTING_OBSERVER_PACKAGES`, so no pipeline-stage package
  (`risk_engine` included) may ever import it.
- `phantom_pipeline/statistical_risk/` — a new, 17th package (12 modules
  + `__init__.py`): `models.py` (`StatisticalRiskAssessment` — 18 named
  fields; `RiskRecommendation` — the 4-value advisory-only enum
  `NORMAL_RISK`/`REDUCE_RISK_25`/`REDUCE_RISK_50`/`SKIP_HIGH_RISK`),
  `config.py`, `expectancy.py` (rolling win-rate/profit-factor/
  expectancy/Sharpe/Sortino — windowed variants of statistics
  `analytics.performance` already computes whole-sample, never
  duplicated), `drawdown.py` (rolling max drawdown, Monte-Carlo-derived
  expected drawdown), `monte_carlo.py` (seeded, bootstrap-resampled
  simulation over real historical P/L — `hashlib`-derived seed per
  `trace_id`, never Python's randomized global `random` state),
  `probability.py` (probability of reaching the daily/total drawdown
  limit, Risk of Ruin — all three read off the same Monte Carlo engine
  at different thresholds), `volatility.py` (ATR via Wilder's method and
  realized volatility, computed from `data_pipeline.NormalizedBar` OHLC
  history — no ATR value exists anywhere else in the repository),
  `correlation.py`/`portfolio.py` (correlation-bucket concentration,
  portfolio heat, position concentration, currency exposure — all read
  from `risk_engine.models.OpenPosition`/`AccountState` verbatim, never
  a second parallel type), `engine.py` (`StatisticalRiskEngine` — VaR/
  CVaR historical simulation, Kelly Criterion, regime-based confidence,
  and the top-level `assess()` orchestrator that combines every signal
  into the single most conservative recommendation), `logging_sink.py`,
  `metrics.py`.
- `tests/phantom_pipeline/statistical_risk/` — 113 tests: per-module
  unit tests, a determinism suite (identical historical input + seed →
  byte-identical `StatisticalRiskAssessment`, including Monte Carlo,
  across independent engine instances), a structural-boundary suite (no
  pipeline-stage package imports `statistical_risk`; `risk_engine`'s
  own files are unmodified; no decision-verb method names; no arbitrary
  directory/`.env` access), and an end-to-end integration suite.
- `docs/plans/statistical-risk-management.md` — the RPI Research/Plan/
  Validation artifact for this change.

### Changed
- `scripts/check_architecture.py` — `statistical_risk` added to
  `CROSS_CUTTING_OBSERVER_PACKAGES` (one-line set addition plus updated
  docstrings/comments); now checks 17 packages.
- Nothing in `risk_engine/`, `compliance_engine/`, `execution_validator/`,
  `position_manager/`, `mt5_bridge/`, `scanner/`, `strategy_engine/`, or
  any of the other 9 existing packages, or any pre-existing test —
  confirmed via `git status`/`git diff` showing no changes outside the
  new `statistical_risk/` package, its tests, the two new docs, and the
  one-line `check_architecture.py` change. Full suite re-run: 1610/1610
  tests (1497 existing + 113 new, zero regressions), `validate.py`
  13/13, `scripts/check_architecture.py` clean (17 packages, no cycles,
  no cross-package private-state access, no pipeline-stage → observer
  import).

## 2026-07-07 (DEPLOYMENT_PACKAGE full rebuild — 16 packages)

### Added
- `DEPLOYMENT_PACKAGE/` — deleted in full (157 files, 14-package
  snapshot from commit `a90f7c6`) and rebuilt entirely from scratch
  against the current repository (commit `f5c5e3e`), rather than
  patched in place. Now contains all 16 `phantom_pipeline` packages,
  including `knowledge/` (`ADR-020`) and `research_desk/` (`ADR-021`),
  which the previous snapshot predated and therefore omitted — 182
  files total. `diff -rq phantom_pipeline DEPLOYMENT_PACKAGE/phantom_pipeline`
  is empty: byte-for-byte identical.
- `DEPLOYMENT_AUDIT.md` — complete 182-file listing of the rebuilt package.
- `DEPLOYMENT_MANIFEST.md` — every file mapped to its `C:\phantom\...`
  destination on the VPS.
- `FINAL_DEPLOYMENT_READINESS_REPORT.md` — package-completeness,
  sync-verification, and validation-results report.

### Changed
- `COPY_TO_VPS.md` §1 — "14 packages" corrected to "16 packages,"
  `knowledge`/`research_desk` named explicitly with a note that both are
  read-only observers, not wired into the trading loop by default.
- `DEPLOYMENT_PACKAGE/requirements.txt` — added `sentence-transformers`
  (optional, lazily imported by `knowledge/embeddings.py`'s real neural
  embedding provider; confirmed via a fresh repository-wide import scan
  across all 16 packages that no other new third-party dependency was
  introduced since Phase 5).
- `DEPLOYMENT_PACKAGE/VERSION.txt` — regenerated: current commit hash,
  16-package list, explicit "rebuilt from scratch" note.
- Nothing in `phantom_pipeline/` itself, any test, or any trading-logic
  file — confirmed via `git status` showing no changes outside
  `DEPLOYMENT_PACKAGE/` and the three docs above. Full suite re-run:
  1497/1497 tests (unchanged), `validate.py` 13/13,
  `scripts/check_architecture.py` clean (16 packages). `start_phantom.py`
  DEV-profile smoke test re-run from inside the rebuilt package —
  constructs cleanly.

## 2026-07-06 (Phantom AI Research Desk — ADR-021)

### Added
- `docs/adr/ADR-021-ai-research-desk.md` — Accepted, per explicit user
  specification this session. Establishes the Research Desk as a
  cross-cutting observer one layer above `phantom_pipeline.knowledge`
  (`ADR-020`), with no decision, execution, risk, compliance, or scoring
  authority; every recommendation is exported data requiring human
  approval before becoming production logic.
- `phantom_pipeline/research_desk/` — a new, 16th package, built
  **on top of, not beside**, `phantom_pipeline.knowledge`: no second
  vector store, no second document repository, no second dashboard-
  snapshot type, no second `ResearchSuggestion` type. Every new report
  type converts to a `knowledge.KnowledgeDocument` using an
  already-existing `DocumentKind` value — zero modification to
  `knowledge/models.py`.
  - `market_research.py` — `MarketResearchAgent`: structure/volatility/
    liquidity/session/regime analysis from `ScannerObservation`;
    macro-news/economic-calendar analysis honestly scoped to the one
    real feed that exists (`NewsCalendarState.blackout_windows`, per
    `ADR-006` §8) — no richer feed fabricated.
  - `debate.py` — `BullBearDebateAgent`: per-symbol bullish/bearish/
    neutral thesis with a transparent (agreeing-signals/considered-
    signals) confidence score; `DebateThesis` has no direction/size/
    entry field — structurally never a trading signal.
  - `trade_thesis.py` — `TradeThesisGenerator`: institutional context/
    expected continuation/risk factors/lessons learned, read entirely
    from the same `TradeProvenanceRecord` a `TradeMemoryRecord` was
    already built from.
  - `trade_journal.py` — `AITradeJournal`: reuses
    `knowledge.ExplanationEngine` for risk/execution narrative (never a
    second explanation implementation); `suggested_improvements` is the
    one new heuristic. `JournalEntry` is frozen with no update method
    anywhere — a correction is a new entry, never an edit of history.
  - `strategy_research.py` — `StrategyResearchAgent`: reuses
    `AnalyticsEngine.group_by_pair/session/regime`; rule-combination
    co-occurrence frequency is genuinely new analysis;
    `analyze_parameter_sensitivity` always reports `available=False` —
    no backtest/parameter-sweep module exists anywhere in
    `phantom_pipeline`, a real gap, not fabricated.
  - `institutional_review.py` — `WeeklyInstitutionalReviewGenerator`:
    composes an already-built `paper_trading.PeriodReport` (never
    recomputes it) into a narrative executive/performance/risk/
    compliance/execution/market review with recurring-mistake detection
    read from `PeriodReport`'s own already-attributed block-count
    dictionaries.
  - `explainable.py` — `ExplainableDecisionEngine`: delegates every
    already-supported natural-language question shape to
    `knowledge.SemanticSearchService` (reused, not duplicated);
    `compare_periods`/`what_changed_over` are the new query shapes,
    built entirely from two `PeriodReport`s' own fields.
  - `dashboard.py` — `ResearchDeskDashboardBuilder`: wraps
    `knowledge.KnowledgeDashboardSnapshot` verbatim as a field on a new
    `ResearchDeskDashboardSnapshot`; `dashboard/` (`ADR-012`) and
    `knowledge/` (`ADR-020`) are both untouched.
  - `models.py`, `config.py`, `logging_sink.py`, `metrics.py`,
    `__init__.py`.
- `tests/phantom_pipeline/research_desk/` — 100 tests: unit coverage per
  agent, replay determinism, a shared-`KnowledgeEngine`-reuse integration
  test, and a dedicated structural-boundary suite (no decision-verb
  method names, no pipeline-stage import of `research_desk` or
  `knowledge`, `dashboard.models.ViewName` still 10 values,
  `knowledge.models.DocumentKind` still 17 values, `JournalEntry`/
  `AITradeJournal` have no update method, `DebateThesis`/`ThesisCase`
  have no signal-shaped field).
- `docs/plans/ai-research-desk.md` — the RPI Research/Plan artifact,
  including the full duplicate-logic reuse map against `ADR-020`.
- `RESEARCH_DESK_GUIDE.md` — wiring guide; every code sample verified to
  actually run against this repository.

### Changed
- `scripts/check_architecture.py` — the `ADR-020` knowledge-import check
  is generalized to a `CROSS_CUTTING_OBSERVER_PACKAGES` set covering both
  `knowledge` and `research_desk`; no pipeline stage may import either.
- `tests/phantom_pipeline/knowledge/test_structural_boundary.py` — one
  assertion updated to match the generalized check's new output string
  (no behavior change to the check itself beyond the `research_desk`
  addition).
- Nothing else in any existing `phantom_pipeline`/`tests` file —
  confirmed via `git diff --stat` showing only the two files above
  modified against every tracked file; this change is otherwise 100%
  new files. Full suite re-run: 1497/1497 tests (was 1397), `validate.py`
  13/13, `scripts/check_architecture.py` clean (16 packages, no new
  cycle, no cross-package private-state access, no pipeline-stage →
  observer-package import).

## 2026-07-06 (Knowledge & RAG subsystem — ADR-020)

### Added
- `docs/adr/ADR-020-knowledge-rag-subsystem.md` — Accepted, per explicit
  in-session user direction. Establishes the Knowledge/RAG subsystem as
  a cross-cutting observer (like Watchdog/Dashboard), with no decision,
  execution, risk, compliance, or scoring authority; additive to
  Dashboard only; deterministic-template explanations for Phase 1 (an
  LLM "assistant mode" explicitly deferred); a real neural embedding
  backend as an optional, lazily-imported production option behind the
  same interface as the deterministic default.
- `phantom_pipeline/knowledge/` — a new, 15th package: `models.py`,
  `config.py`, `embeddings.py` (`HashingEmbeddingProvider` default,
  `SentenceTransformerEmbeddingProvider` optional real backend),
  `vector_store.py` (`InMemoryVectorStore`), `memory.py`
  (`TradeMemoryStore`), `ingestion.py` (document ingestion restricted to
  a named source set + `KnowledgeDocumentStore` with content-hash
  dedup/incremental-update semantics + `build_trade_memory_record`,
  which reads every field from an already-produced
  `TradeProvenanceRecord`, never re-deriving one), `retriever.py`,
  `search.py` (`SemanticSearchService` — winners/losers/similar-trades/
  setup-pattern/drawdown-threshold convenience queries),
  `engine.py` (`KnowledgeEngine` orchestrator + `ExplanationEngine`,
  deterministic templates over each decision's own `reason_codes`/
  `blocking_rules`/`blocking_reasons`/`decision_reason`), `logging_sink.py`,
  `metrics.py`, `__init__.py`.
- `tests/phantom_pipeline/knowledge/` — 133 tests: determinism/replay
  determinism across independent engines, search accuracy, duplicate
  prevention, memory integrity (every `TradeMemoryRecord` field traced to
  its source), thread safety, documentation/trade indexing, vector
  retrieval, and a dedicated structural-boundary suite (no pipeline
  stage imports `knowledge`, `dashboard.models.ViewName` untouched, no
  decision-verb method names, no arbitrary directory walk).
- `docs/plans/knowledge-rag-subsystem.md` — the RPI Research/Plan
  artifact, including the TF-IDF → feature-hashing design change
  (corpus-order independence, needed for incremental indexing).
- `docs/architecture/knowledge-subsystem-diagram.md` — Mermaid data-flow
  diagram.
- `KNOWLEDGE_DEPLOYMENT_GUIDE.md` — wiring guide (construct, prime from
  docs, record trades, search, weekly review, dashboard snapshot);
  every code sample verified to actually run against this repository.

### Changed
- `scripts/check_architecture.py` — extended with a third check (no
  pipeline-stage package may import `knowledge`, `ADR-020` Hard Rule 9);
  the two pre-existing checks are unchanged.
- Nothing else in any existing `phantom_pipeline`/`tests` file —
  confirmed via `git diff --stat` showing only `check_architecture.py`
  modified against every tracked file; this change is otherwise 100%
  new files. Full suite re-run: 1397/1397 tests (was 1264), `validate.py`
  13/13, `scripts/check_architecture.py` clean (15 packages, no new
  cycle, no cross-package private-state access, no pipeline-stage →
  `knowledge` import).

## 2026-07-06 (VPS deployment package)

### Added
- `DEPLOYMENT_PACKAGE/` — a fresh, VPS-ready snapshot of the current
  working Phantom runtime only, built fully from this repository (no
  assumption that any old VPS files are usable):
  - `phantom_pipeline/` — byte-identical copy of all 14 packages
    (`analytics`, `compliance_engine`, `dashboard`, `data_pipeline`,
    `deployment`, `execution_validator`, `mt5_bridge`, `orchestrator.py`,
    `paper_trading`, `position_manager`, `risk_engine`, `scanner`,
    `scoring_engine`, `strategy_engine`, `watchdog`) — confirmed via
    `diff -rq` showing zero output against the source tree. Legacy
    `phantom/` and `phantom_institutional.py` are deliberately excluded
    (reference-only, "not a running authority" per `CLAUDE.md` §2) — not
    packaged as if they were part of the current runtime.
  - `config/{dev,paper,live}.env.template` — profile configuration
    templates matching `ConfigurationManager`'s and `MT5Adapter`'s real
    env-var names.
  - `scripts/start_phantom.py` — the new production entry point (the
    "EA" driver for the current, sole authoritative system): wires the
    Phase 3 real adapters and every stage engine exactly as
    `tests/phantom_pipeline/orchestrator/_fixtures.py`'s own
    `build_orchestrator()` already proves works, auto-discovering real
    playbooks/scoring rules (never hand-listed), then dispatches by
    `DeploymentProfile` — DEV (construction-only smoke test), PAPER
    (delegates to the existing `PaperTradingRunner`'s demo-account-
    guarded loop, unchanged), LIVE (configuration validation, service
    startup, and all 10 `DeploymentValidator` go-live checks wired to
    real probes, including `emergency_stop_functional` driving
    `PositionManager`'s own `EMERGENCY_CLOSE` path against a synthetic
    probe position — stated honestly as *not* including a continuous
    live-order-submission scheduler, since none exists yet anywhere in
    `phantom_pipeline`).
  - `scripts/start_phantom.bat`/`stop_phantom.bat` — Windows wrappers.
  - `requirements.txt` — `MetaTrader5`/`requests`, confirmed as the only
    two third-party imports anywhere in `phantom_pipeline` via a
    repository-wide import scan.
  - `VERSION.txt` — exact source commit/branch/build timestamp.
- `COPY_TO_VPS.md`, `START_PHANTOM.md`, `VERIFY_DEPLOYMENT.md` — operator
  procedures: backup-before-overwrite VPS copy steps, per-profile startup
  instructions, and a verification checklist that does not assume the
  (deliberately unshipped) test suite is present on the VPS.

### Changed
- Nothing in any existing `phantom_pipeline`/`tests`/`scripts` file —
  confirmed via `git status --porcelain` showing only new files. Full
  suite re-run: 1264/1264 tests (unchanged), `validate.py` 13/13,
  `scripts/check_architecture.py` clean (14 packages).

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
