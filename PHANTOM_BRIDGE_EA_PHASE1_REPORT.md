# Phantom — Phase 1: PhantomBridgeEA Foundation — Implementation Report

Status: **Complete.** This is the single execution authority for the
new, from-scratch Phantom architecture. Original implementation only —
no source code was copied from any reference repository (EA31337,
MQL5-JSON-API-2, dwx-zeromq-connector, backtrader). Every design
decision informed by prior research is cited inline against the
relevant audit in `docs/research/`.

**Scope discipline honored:** no strategy logic, no scanner, no
indicators, no AI/intelligence, no statistical risk, no backtesting, no
optimization, no placeholder code, no TODOs. This phase implements
exactly the seven responsibility groups specified and nothing else.

---

## 1. Folder structure

```
phantom/
├── __init__.py
└── bridge/
    ├── __init__.py
    ├── models.py
    ├── config.py
    ├── validation.py
    ├── connection_health.py
    ├── command_queue.py
    ├── logging_sink.py
    ├── metrics.py
    ├── engine.py
    └── server.py

mt5/
├── PhantomBridgeEA.mq5
└── PhantomBridgeEA.set

tests/phantom/
├── __init__.py
└── bridge/
    ├── __init__.py
    ├── _fixtures.py
    ├── test_models.py
    ├── test_config.py
    ├── test_validation.py
    ├── test_connection_health.py
    ├── test_command_queue.py
    ├── test_engine.py
    ├── test_http_server.py
    └── test_structural_boundary.py
```

## 2. Complete file list

10 Python source files, 2 MQL5 files, 9 Python test files (85 tests
total), 1 report — 22 files.

## 3. Responsibility of every file

| File | Responsibility |
|---|---|
| `phantom/__init__.py` | Package marker; documents Phase 1 scope and that later phases are added only once approved |
| `phantom/bridge/models.py` | Every wire-message type: `CommandKind` (6 values), `PositionDirection`, `ErrorCode` (named, stable), `HeartbeatMessage`, `AccountState`, `PositionReport`, `PendingOrderReport`, `TradeCommand`, `ExecutionReport`, `TradeTransactionReport`, `ErrorReport`, `EmergencyStopState` — all frozen dataclasses |
| `phantom/bridge/config.py` | `BridgeConfig` — the bridge's own local configuration (api_key, allowed_symbols, magic_number, max_lot_size, max_slippage_points, heartbeat_timeout_seconds, command_ttl_seconds, log_level) |
| `phantom/bridge/validation.py` | Every transport-integrity check (API key, magic number, symbol allowlist, volume, SL/TP sanity, timestamp freshness) — "validate before acknowledge" lives here |
| `phantom/bridge/connection_health.py` | Liveness tracking only — deliberately separate from the command queue's authorization state |
| `phantom/bridge/command_queue.py` | The single transport chokepoint: idempotent enqueue/poll by `correlation_id`, fail-closed, emergency-stop state, execution-report recording |
| `phantom/bridge/logging_sink.py` | Structured logging for every event: heartbeat, account state, positions, pending orders, command submission/delivery, execution reports, trade-transaction mirror, errors, emergency stop |
| `phantom/bridge/metrics.py` | Export-only counters for every event type above |
| `phantom/bridge/engine.py` | `BridgeEngine` — orchestrates health + queue + validation; the only place `submit_command()` exists; the drift-detection cross-check for trade-transaction mirrors |
| `phantom/bridge/server.py` | The 9-route stdlib HTTP server; every handler validates before acknowledging |
| `mt5/PhantomBridgeEA.mq5` | The only MQL5 file — MT5 connection, all 6 trade-execution commands, position/order/account reads, all 5 event handlers, HTTP communication with bounded retry, safety (fail-closed, emergency disable), structured error reporting |
| `mt5/PhantomBridgeEA.set` | Default input parameter template |
| `tests/phantom/bridge/*` | Full unit + integration coverage (see §10-11) |

## 4. Data flow

1. EA reads MT5 terminal/account/position/order state via native MQL5
   APIs (`AccountInfoDouble`, `PositionGetTicket`, `OrderGetTicket`,
   etc.).
2. EA serializes that state to JSON and POSTs it to the bridge server
   (`/bridge/heartbeat`, `/bridge/account`, `/bridge/positions`,
   `/bridge/orders`).
3. `server.py` validates each payload (`validation.py`) before ever
   calling into `BridgeEngine`; `BridgeEngine` stores the latest
   snapshot as a read model (`engine.py`).
4. A command enters the system exclusively via
   `BridgeEngine.submit_command()` (Python-side caller — nothing
   automatic in this phase, since there is no strategy/risk authority
   yet to originate one).
5. The EA polls `/bridge/commands/poll`, receives only
   already-validated, not-yet-delivered, not-stale commands.
6. The EA executes via `CTrade`, reports the real outcome to
   `/bridge/execution/report`, and independently mirrors MT5's own
   native `OnTradeTransaction` event to `/bridge/trade-transaction`.

## 5. Communication flow

- Transport: HTTP via MQL5's native `WebRequest()` — no compiled DLL,
  no wildcard bind (server binds to `127.0.0.1` by default), API-key
  authentication on every route (`X-Phantom-Api-Key` header).
- Every route: **validate before acknowledge** — auth, magic number,
  symbol allowlist, schema all checked before any state change or
  200 response (`docs/research/mql5-json-api-2-audit.md` §1.4's
  ack-before-validation defect is the specific anti-pattern this
  design refuses to reproduce).
- Correlation: every `TradeCommand` carries a caller-supplied
  `correlation_id`; every `ExecutionReport` is keyed by the same ID,
  so a result always traces back to the exact request that caused it
  — neither audited reference repo does this reliably.
- Fail-closed, both sides: `ConnectionHealth.is_ready()` gates new
  command enqueue server-side; `IsFailClosed()` gates command
  polling/execution EA-side. Either side alone is sufficient to halt
  new execution.
- Retry policy: EA-side `WebRequest` calls retry up to `MaxRetries`
  times with a fixed `RetryDelayMs` delay — bounded, never unbounded
  (the blocking, unbounded MT4-era `Sleep()` retry loops flagged as an
  anti-pattern in `docs/research/dwx-zeromq-connector-audit.md` §1.7
  are explicitly not reproduced here).

## 6. Execution flow

1. `submit_command()` runs transport-integrity checks (symbol, volume,
   SL/TP, timestamp) before ever reaching the queue — this never
   re-decides whether a trade should happen (this phase has no such
   authority); it only defends the relay.
2. `CommandQueue.enqueue()` fails closed if the bridge isn't heartbeat-
   healthy or the emergency stop is active, and rejects a duplicate
   `correlation_id` outright.
3. The EA's `PollAndExecuteCommands()` re-verifies magic number and
   symbol allowlist itself before executing — defense in depth, never
   trusting the server's validation alone.
4. Every modify/close/partial-close operation calls
   `SelectOwnedPosition()` first, which checks
   `PositionGetInteger(POSITION_MAGIC) == MagicNumber` — a position
   belonging to any other source is never touched, on any of the four
   operations that act on an existing position (unlike
   `docs/research/dwx-zeromq-connector-audit.md`'s finding that its
   bulk-close/list-all operations bypass this exact scoping).
5. The execution result (success + broker ticket + fill price/volume,
   or failure + a named reason) is built strictly from the real
   post-attempt `CTrade` result, never before the attempt.
6. `OnTradeTransaction()` independently mirrors what MT5's own trade
   server actually did; `BridgeEngine.handle_trade_transaction()`
   checks whether its ticket matches a known `ExecutionReport` and logs
   a drift warning if not — informational only, never overriding the
   execution report.

## 7. Risk flow

Phase 1 has no risk-decision authority — by design, per scope. The
only "risk"-adjacent behavior here is transport-safety: volume/SL/TP
sanity checks in `validation.py`, the `max_lot_size` ceiling, and the
emergency-stop/fail-closed mechanisms. Position sizing, exposure,
drawdown protection, and statistical risk are explicitly out of scope
for this phase and belong to the future Risk Engine component.

## 8. AI flow

None. Phase 1 has no Intelligence component and none of its files
import anything resembling one.

## 9. Security review

| Concern | Phase 1 answer |
|---|---|
| Authentication | API key required on every route, `hmac.compare_digest` comparison (timing-safe), never a wildcard-bind-no-auth posture |
| Validate before acknowledge | Every handler runs full validation before any state change; no route ever acknowledges receipt as a proxy for validity |
| Replay / duplicate commands | `CommandQueue` rejects a duplicate `correlation_id` at enqueue; a duplicate execution report for an already-terminal command is a no-op |
| Isolation (magic number) | Enforced server-side (validation) **and** EA-side (redundant re-check before every execution, and ownership check before every modify/close/partial-close) — no unscoped "bulk" operation exists anywhere in this phase, unlike the dwx-zeromq-connector finding |
| Deserialization | JSON via Python's standard `json` module server-side; a fixed-shape hand-rolled extractor EA-side (documented Phase-1 limitation, not a general parser) — no `eval()` or equivalent anywhere, unlike the dwx-zeromq-connector finding |
| Fail-closed | Two independent mechanisms (server-side `ConnectionHealth`, EA-side `IsFailClosed()`); either alone halts new execution — neither audited reference repo has any equivalent |
| Emergency stop | A single, explicit, operator-only mechanism (`/bridge/emergency-stop`), requiring API key, immediately reflected in the next poll response |
| Secrets | `api_key` has no default value in `BridgeConfig` — a hardcoded default is structurally impossible, not just discouraged |

## 10. Failure-mode review

| Failure | Behavior |
|---|---|
| Python bridge process dies | EA's `IsFailClosed()` trips once `FailClosedTimeoutSeconds` elapses since the last successful contact; polling/execution stop, telemetry sending continues to attempt (harmlessly failing) so reconnection is automatic |
| EA/terminal goes silent | Server-side `ConnectionHealth.is_ready()` returns `False` once the heartbeat timeout elapses; `submit_command()` is refused with `BRIDGE_NOT_READY` |
| Malformed JSON body | `server.py`'s `do_POST` catches `ValueError`/`UnicodeDecodeError` and returns 400 without touching engine state |
| Duplicate execution report (e.g. retried EA POST) | `CommandQueue.record_result()` returns `False`, the original result is never overwritten |
| A command's TTL expires before the EA polls | `CommandQueue.poll()` drops it silently rather than delivering a stale instruction |
| Emergency stop activated mid-flight | `poll()` returns `()` unconditionally and clears any still-pending backlog; new `enqueue()` calls are refused |
| EA attempts to modify/close a position it doesn't own | `SelectOwnedPosition()` fails the magic-number check; `ExecutionReport` reports `UNKNOWN_OR_FOREIGN_POSITION`, no MT5 API call is made |
| WebRequest fails (network/DNS/not-allowlisted) | Bounded retry (`MaxRetries`/`RetryDelayMs`); on exhaustion, the call returns silently and the next `IsFailClosed()` check will trip if this persists |
| Partial-close volume ≥ owned volume | Rejected before any `CTrade` call, reported as `INVALID_PARTIAL_CLOSE_VOLUME` |

## 11. Unit tests

76 unit tests across `test_models.py`, `test_config.py`,
`test_validation.py`, `test_connection_health.py`,
`test_command_queue.py`, `test_engine.py`, `test_structural_boundary.py`
— covering model immutability, config defaults, every validation
function, connection-health liveness transitions, command-queue
idempotency/staleness/fail-closed behavior, engine-level
telemetry/submission/drift-detection/emergency-stop handling, and
structural boundary guarantees (no decision-verb method names, no
imports beyond this package, no `phantom_pipeline` reference).

## 12. Integration tests

9 full HTTP-stack tests in `test_http_server.py`, run over a real
socket via `urllib.request` — the same path the MQL5 EA itself uses:
all 9 routes exercised, a full submit→poll→execution-report round
trip, duplicate-report rejection, missing/wrong API key rejection,
magic-number-mismatch rejection, emergency-stop activate/deactivate
with poll reflecting the change, and 404/400 handling for unknown
routes and malformed bodies.

**Full suite result: 85/85 passing.** Full-repo regression check:
`tests/phantom_pipeline/` still at 1629/1629 passing (unchanged from
before this phase — confirms zero collateral impact on any other
package).

## 13. Compile verification / Architecture verification

- **Python**: `python3 -m compileall phantom phantom_pipeline tests
  scripts` — clean. `python3 -m unittest discover -s tests/phantom` —
  85/85 passing. `python3 -m unittest discover -s tests/phantom_pipeline`
  — 1629/1629 passing (no regression).
- **MQL5**: **not compiled** — this sandbox has no MetaEditor/MT5
  terminal available. This is an honest, disclosed limitation, not a
  gap I'm glossing over: `mt5/PhantomBridgeEA.mq5`'s correctness rests
  on careful construction against documented MQL5 API semantics
  (`CTrade`, `WebRequest`, `PositionGetTicket`/`PositionSelectByTicket`,
  `OrderGetTicket`/`OrderSelect`, `MqlTradeTransaction`/`MqlTradeResult`),
  not automated verification. Compile it in a real MetaEditor and test
  on a demo account before trusting it with even paper capital.
- **Architecture verification**: `test_structural_boundary.py` confirms
  (a) no method on `BridgeEngine` resembles a decision-authority verb,
  (b) no file in `phantom/bridge/` imports a sibling `phantom` package
  or `phantom_pipeline` at all, (c) `git status --porcelain` shows only
  the paths this phase is scoped to (`phantom/`, `mt5/`,
  `tests/phantom/`, `docs/research/`) changed. `scripts/check_architecture.py`
  (scoped to `phantom_pipeline/`) still passes cleanly at 17 packages
  (down from 18 — `ea_bridge` retired, see below).

---

## Prerequisite retirement (committed separately, before this phase's new code)

Two commits preceded this phase's implementation, both already pushed:

1. **Retired the legacy `phantom/` package** (pre-ADR-001 system,
   confirmed fully orphaned by the earlier internal architecture audit)
   plus its only dependents: `validate.py`, `run_demo.py`, and the
   legacy test suite that tested it in isolation
   (`tests/test_pipeline.py`, `tests/test_orchestrator.py`,
   `tests/test_playbooks_7_8.py`, `tests/fixtures.py`). This freed the
   `phantom/` namespace the approved architecture names, per your
   explicit direction. `phantom_institutional.py` and its own dedicated
   tests are untouched — no collision, out of scope.
2. **Retired the old `ea_bridge` component** (ADR-023,
   `phantom_pipeline/ea_bridge/`, its test suite, `mt5/PhantomBridgeEA.mq5`,
   `mt5/PhantomBridgeEA.set`, `MT5_EA_BRIDGE_GUIDE.md`) — the exact
   responsibility being rebuilt from scratch in this phase. Keeping
   both would have been duplicate functionality for the same job.

Everything removed remains fully recoverable via git history.

---

## Stop.

Per your instruction: **not beginning Scanner, Strategy, Risk,
Watchdog, Intelligence, or Validation** until Phase 1 is explicitly
approved.
