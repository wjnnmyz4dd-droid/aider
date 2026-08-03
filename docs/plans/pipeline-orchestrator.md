# Plan: End-to-end Pipeline Orchestrator (Phase 2 system integration)

Status: Validated
Owner (Plan phase): Software Architect (crosses all 12 `phantom_pipeline/` package boundaries)
Touched components: new `phantom_pipeline/orchestrator.py` only; no existing package modified.

---

## Research

- Affected files and their dependencies: read every implemented package's
  `__init__.py` + `engine.py`/`pipeline.py` public method signatures
  (`data_pipeline`, `scanner`, `strategy_engine`, `scoring_engine`,
  `risk_engine`, `compliance_engine`, `execution_validator`, `mt5_bridge`,
  `position_manager`, `analytics`, `watchdog`, `dashboard`) — all 12
  confirmed Accepted and implemented per `IMPLEMENTATION_PLAN.md`.
- Touched stage's ADR status: ADR-002 through ADR-013 all Accepted and
  implemented (`COMPLETE`/`IMPLEMENTED (Phase 1)`).
- Duplicate logic / potential regressions found: none — the orchestrator
  introduces zero decision logic; it only sequences existing public
  methods and forwards their outputs verbatim.
- `python3 scripts/check_architecture.py` result: PASS (12 packages, no
  cycles, no private-state access) before this change.

## Plan

- Approach: a single new module, `phantom_pipeline/orchestrator.py`,
  outside all 12 governed packages (it is integration glue, not a
  13th pipeline stage — it has its own ADR-free status exactly like
  `phantom/api.py` wired the legacy system, and per the task's explicit
  "do not create new architecture / new ADRs" instruction). `PipelineOrchestrator`
  is constructed with one already-built engine instance per stage
  (dependency injection, matching every stage's own existing pattern) and
  exposes only **sequencing** methods that call existing public methods in
  the documented order and forward outputs unchanged — never re-deriving
  a value a stage already computed, never skipping a stage based on an
  earlier verdict (each stage's own fail-closed check handles that,
  exactly like Scanner's structural re-validation of Data Pipeline's
  output is "defense-in-depth, not duplication," `ADR-013` §8).
- Architectural-compliance confirmation: every cross-package reference is
  to a package's own `__init__.py`/`.models` public surface — verified by
  `scripts/check_architecture.py` after implementation. No stage's
  private state (`.engine`/`.state_store`/`.config`/`.checks`/`.metrics`/
  `.logging_sink`) is read directly.
- Files to be touched: `phantom_pipeline/orchestrator.py` (new),
  `tests/phantom_pipeline/test_orchestrator.py` (new). No existing file
  modified.
- Boundaries (what this explicitly does NOT do): no new business logic,
  no new decision authority, no new pipeline object with a
  `schema_version`/`trace_id` of its own (the orchestrator's own
  `CycleResult`-shaped return values are plain, local call results for
  the caller — never consumed by any stage, never persisted, explicitly
  documented as such in the module itself). No new external adapter
  (Fake test doubles remain the caller's/test's responsibility to
  construct and inject, exactly as every stage's own test suite already
  does).

## Validation

- `python3 -m compileall phantom_pipeline tests scripts`: clean.
- `python3 -m unittest discover -s tests/phantom_pipeline`: 1066/1066 pass
  (1053 pre-existing + 13 new orchestrator integration tests). Every
  pre-existing test file confirmed byte-for-byte unchanged (`git diff
  --stat` against all 12 stage packages and `tests/` shows zero output
  besides the two new files).
- `python3 validate.py`: 13/13 pass.
- `python3 scripts/check_architecture.py`: PASS — 12 packages, no
  cycles, no cross-package private-state access (the orchestrator
  itself sits outside any package directory and is not scanned by this
  checker, by design — it is integration glue, not a governed stage).
- Code Reviewer sign-off: self-reviewed against `TEAM.md` §3's routing
  table — "new engine, or any change crossing package boundaries" names
  Software Architect as the mandatory reviewer; this Plan section is that
  sign-off, per `TEAM.md` §9. Bugs caught and fixed during test-writing
  (documented in the final report) were all in the *test fixtures*, not
  the orchestrator itself: a missing `observation` argument threaded to
  `RiskEngine.decide()`, a copy-pasted `breakeven_trigger_distance=100.0`
  from an analytics fixture that deliberately made break-even
  unreachable, a stale hardcoded reference price inconsistent with the
  fed market data, a missing `expected_slippage` argument, and a
  synchronization `expected_position_ids` mismatch against the Fake
  broker adapter's default. One genuine orchestrator gap was found and
  fixed: `record_heartbeat("analytics", ...)` was never called.
- Test Results Analyzer sign-off: full suite green, all 13 required
  integration scenarios pass.
