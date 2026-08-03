# Plan: Phase 3 — Real infrastructure adapters

Status: Validated
Owner (Plan phase): Backend Architect
Touched components: `phantom_pipeline/mt5_bridge`, `phantom_pipeline/data_pipeline`, `phantom_pipeline/dashboard`, `phantom_pipeline/watchdog` (new files only)

---

## Research

- **Affected files and their dependencies**: Phase 1 shipped four documented
  fake test doubles, each behind its own ABC, each carrying an explicit
  "a real adapter is future work, not invented here" note:
  - `mt5_bridge/broker_adapter.py` — `BrokerAdapter` ABC + `FakeBrokerAdapter`.
  - `dashboard/prometheus_port.py` — `PrometheusReadPort` ABC + `FakePrometheusReadPort`.
  - `watchdog/recovery_executor.py` — `RecoveryActionExecutor` ABC + `FakeRecoveryActionExecutor`.
  - `data_pipeline/pipeline.py` — no adapter ABC exists yet; ingestion is
    push-based (`DataPipeline.process_raw_tick`/`load_historical_bars`/
    `warm_start`) and `data_pipeline/models.py`'s own docstring for
    `DataQualityReport.latency_seconds` states explicitly: "Phase 1 has no
    live broker feed adapter yet... until a real feed supplies a receipt
    time (§6, `received_at`)" — confirming this is the intended Phase 3 gap.
- **Touched stages' ADR status**: `ADR-008` (MT5 Bridge), `ADR-011`
  (Watchdog), `ADR-012` (Dashboard), `ADR-013` (Data Pipeline) are all
  Accepted. `ADR-015` (External Data Sources & API Governance) is Accepted
  and defines the binding "Adapter Forbidden Responsibilities" table every
  adapter below must honor: translation only, no business/strategy/scoring/
  risk/compliance/AI-reasoning logic, no mutation of a pipeline object, no
  bypass of a pipeline stage.
- **Duplicate logic / potential regressions found**: none. Each new adapter
  is a pure implementation of an already-Accepted ABC (or, for Data
  Pipeline, a thin caller of its already-existing public methods) — no
  existing engine, model, or check function changes shape or behavior.
- **`python3 scripts/check_architecture.py` result (baseline, before this
  change)**: PASS — 12 packages, no cycles, no private-state access.

## Plan

- **Approach**: add one new adapter module per stage, each implementing the
  existing ABC (or, for Data Pipeline, wrapping the existing public
  `DataPipeline` methods) with a real MetaTrader5/Prometheus/OS-process
  backend. Every adapter accepts its underlying client (the `MetaTrader5`
  module, an HTTP session, a command runner) as an **injectable
  constructor parameter**, defaulting to the real one lazily imported —
  the same dependency-injection seam `BrokerAdapter`/`PrometheusReadPort`/
  `RecoveryActionExecutor` already establish as ABCs, extended one level
  further so the translation logic itself is unit-testable without a
  live MT5 terminal, a live Prometheus server, or real OS process control.
  This environment cannot install the `MetaTrader5` package (Windows/MT5-
  terminal-only), so the real module is imported lazily inside `connect()`,
  never at module load time — an environment without it can still import
  and unit-test the adapter's translation logic via the injected fake.
- **Architectural-compliance confirmation**: no new pipeline stage, no new
  ADR, no new decision object, no change to any existing engine's decision
  logic. `MT5Adapter`/`MarketDataAdapter` perform translation only (field
  mapping to/from the vendor shape); `PrometheusAdapter` is read-only
  (no `set_*`/`write_*` method, mirroring the ABC's own structural
  guarantee); `RealRecoveryActionExecutor` performs only the 8 named,
  bounded `RecoveryActionType` actions, never a trading action, never
  holding a broker credential.
- **Files to be touched** (all new; zero existing `phantom_pipeline` file
  is modified, per explicit instruction):
  - `phantom_pipeline/mt5_bridge/mt5_adapter.py` + tests
  - `phantom_pipeline/data_pipeline/market_data_adapter.py` + tests
  - `phantom_pipeline/dashboard/prometheus_adapter.py` + tests
  - `phantom_pipeline/watchdog/real_recovery_executor.py` + tests
- **Boundaries (what this change explicitly does NOT do)**:
  - Does not modify any existing `phantom_pipeline` file (including
    `__init__.py` exports) — new adapters are imported directly from their
    own module, exactly as `tests/.../test_broker_adapter.py` already
    imports `FakeBrokerAdapter` directly from `.broker_adapter` rather
    than through the package `__init__`.
  - Does not touch `orchestrator.py` — wiring a real adapter into a running
    orchestrator instance is a deployment-time constructor-injection
    choice, not a code change, and out of this task's explicit scope.
  - Does not build a real Prometheus *exporter* for each stage's existing
    in-memory `metrics.py` objects — that is a separate, larger gap
    (flagged in the final report), out of scope for "Dashboard remains
    read-only."
  - Does not add new business/strategy/scoring/risk/compliance logic
    anywhere, per explicit instruction.

## Validation

- `python3 -m compileall phantom_pipeline tests scripts`: clean.
- `python3 -m unittest discover -s tests/phantom_pipeline`: full suite green,
  no regression against the pre-change baseline.
- `python3 validate.py`: 13/13.
- `python3 scripts/check_architecture.py`: PASS, no new cross-package
  private-state access, no new cycle.
- Code Reviewer / Test Results Analyzer / Integration Engineer sign-off:
  self-certified in this same session per the Council's existing solo-session
  precedent (Phase 1/Phase 2 tasks); Integration Engineer's verification
  checklist applied directly since this change crosses package boundaries
  (four packages touched, each with a new file).
