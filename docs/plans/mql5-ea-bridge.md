# Plan: Hybrid MT5 MQL5 EA Bridge

Status: Validated
Owner (Plan phase): Backend Architect
Touched components: `phantom_pipeline/ea_bridge` (new), `mt5/` (new,
outside `phantom_pipeline/`)

---

## Research

- Affected files and their dependencies:
  - `phantom_pipeline/mt5_bridge/broker_adapter.py` — read in full.
    `BrokerAdapter` ABC has exactly 7 methods: `connect`, `disconnect`,
    `heartbeat`, `send_request`, `poll_execution`,
    `query_open_position_ids`, `query_account_equity`. `EABrokerAdapter`
    implements this exactly; zero change to `mt5_bridge/` needed.
  - `phantom_pipeline/mt5_bridge/models.py`, `engine.py` — read in full.
    `BrokerRequest`/`BrokerAcknowledgement`/`ExecutionReceipt`/`BrokerError`
    are the exact types `send_request()`/`poll_execution()` must produce;
    `MT5Bridge.submit_order()`/`submit_position_adjustment()`/
    `submit_position_close()` already gate everything upstream (Hard
    Rules, idempotency, connection-state) before ever calling
    `adapter.send_request()` — `ea_bridge` inherits all of that for free
    by being "just another `BrokerAdapter`."
  - `phantom_pipeline/mt5_bridge/mt5_adapter.py` — read in full as the
    direct precedent for a real `BrokerAdapter` implementation: lazy
    external-dependency handling, translation-only responsibility,
    ticket/execution_id correlation dict for async polling. `EABrokerAdapter`
    mirrors this shape (a pending-commands dict keyed by `execution_id`
    instead of MT5 tickets).
  - `phantom_pipeline/mt5_bridge/idempotency_store.py` — read in full as
    the precedent for `ea_bridge`'s own idempotency tracking (submitted/
    delivered/executed states keyed by `execution_id`, TTL-pruned).
  - `phantom_pipeline/data_pipeline/__init__.py`, `pipeline.py` — read in
    full. `DataPipeline.process_raw_tick()` and `load_historical_bars()`
    are the existing public ingestion entry points; `ea_bridge` calls
    these directly for EA-reported ticks/bars, never re-implementing
    normalization/bar-building.
  - `phantom/api.py` (legacy) — read as the "Python stdlib only" HTTP
    server precedent (`http.server.BaseHTTPRequestHandler`/
    `ThreadingHTTPServer`, an explicit route table) — the same approach
    `ea_bridge/http_server.py` uses, avoiding a new third-party HTTP
    framework dependency for 9 simple routes.
  - `paper_trading/account_tracker.py` — confirmed `AccountTracker.observe(equity, now)`
    already owns drawdown-curve tracking; `ea_bridge` does not duplicate
    it (§7 of `ADR-023`).
- Touched stage's ADR status: `ADR-023-mql5-ea-bridge.md` — **Accepted**
  (this session, explicit full user specification).
- Duplicate logic / potential regressions found: none in the 17 existing
  packages needs changing. The only duplication risk identified and
  avoided: re-implementing tick/bar normalization (already
  `data_pipeline`'s job) and drawdown-curve tracking (already
  `paper_trading.AccountTracker`'s job).
- `python3 scripts/check_architecture.py` result (before this change):
  17 packages, PASS on all three checks (baseline, confirmed during the
  Statistical Risk integration work).

## Plan

- Approach: build `phantom_pipeline/ea_bridge/` as an 18th package —
  stateless-per-request transport/execution bridge, never a pipeline
  stage. `EABrokerAdapter` is a drop-in alternative to `MT5Adapter`/
  `FakeBrokerAdapter` for `MT5Bridge`'s existing constructor parameter —
  no `mt5_bridge/` file changes. Write `mt5/PhantomBridgeEA.mq5` as a
  pure relay: poll for commands, execute via `OrderSend`, report results —
  no local signal generation, no risk/compliance logic.
- Architectural-compliance confirmation: against `ADR-001`'s pipeline,
  this package occupies no stage position (mirrors `ADR-011`/`ADR-020`/
  `ADR-021`/`ADR-022`'s own non-stage posture, applied here to the
  *execution* side rather than the *analysis* side). Against `ADR-008`
  (MT5 Bridge), zero modification — confirmed by `git diff` scope after
  implementation showing no hunks under `mt5_bridge/`.
- Files to be touched (all new):
  `phantom_pipeline/ea_bridge/{__init__.py,models.py,config.py,
  command_queue.py,validation.py,broker_adapter.py,http_server.py,
  engine.py,logging_sink.py,metrics.py}`,
  `mt5/{PhantomBridgeEA.mq5,PhantomBridgeEA.set}`,
  `tests/phantom_pipeline/ea_bridge/`, `MT5_EA_BRIDGE_GUIDE.md`,
  `CHANGELOG.md`.
- Boundaries (what this change explicitly does NOT do):
  - Does not modify `mt5_bridge/`, `risk_engine/`, `compliance_engine/`,
    `execution_validator/`, `position_manager/`, `scanner/`,
    `strategy_engine/`, `scoring_engine/`, `data_pipeline/`,
    `analytics/` — not one line.
  - Does not wire `EABrokerAdapter` into `orchestrator.py`/
    `start_phantom.py` by default — a deployer opts in explicitly,
    exactly as choosing `MT5Adapter` vs `FakeBrokerAdapter` already
    works today.
  - Does not deploy to live, does not place a real trade, does not run
    against a real MetaTrader 5 terminal anywhere in this work.
  - Does not add TLS/HTTPS termination (§7 of `ADR-023`).

## Validation

- `python3 -m compileall phantom_pipeline tests`: PASS (clean compile,
  including the new package and its tests; `.mq5`/`.set` are not Python
  and are not compiled by this check).
- `python3 -m unittest discover -s tests/phantom_pipeline`: PASS, full
  suite plus new `ea_bridge` tests, zero regressions in any existing
  package's tests.
- `python3 validate.py`: PASS, all checks unaffected by this addition.
- `python3 scripts/check_architecture.py`: PASS — 18 packages, no
  circular imports, no cross-package private-state access, no pipeline-
  stage → observer-package import (unaffected; `ea_bridge` is not added
  to either `PIPELINE_STAGE_PACKAGES` or `CROSS_CUTTING_OBSERVER_PACKAGES`
  since it is neither a decision-authority stage nor a read-only
  analysis observer — it is consumed by `mt5_bridge` only via the
  existing `BrokerAdapter` constructor-injection point, the same
  relationship `MT5Adapter` already has).
- Code Reviewer sign-off: `EABrokerAdapter`'s conformance to
  `BrokerAdapter`'s ABC, idempotency-by-`execution_id`, and the
  transport-validation-never-re-decides boundary all verified by
  dedicated tests, not just prose.
- Integration Engineer (`TEAM.md` RACI): confirms `mt5_bridge/` and the
  other 9 pipeline-stage packages are byte-for-byte unchanged.
