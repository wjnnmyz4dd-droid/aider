# Session Edge — MT5 Execution Adapter (Phase 3)

An **execution adapter only**. This Expert Advisor consumes the accepted
Filesystem Execution Bridge, submits the corresponding MT5 market orders, and
writes back acknowledgements and deterministic execution results. It is a bridge
*consumer* — nothing else.

**It never contains strategy logic.** No market-structure, breakout, retest,
price-action, health-gate, news, risk, stop or target calculation; it never
decides or changes trade direction. Direction / entry / stop / target are read
verbatim from the validated instruction. No indicators, no price-series reads,
no back-testing, no optimization, no prediction.

**Boundaries.** No HTTP, sockets, REST/RPC, external APIs, news feeds, or
external process execution. Only the **MT5 trade API** and the **filesystem
bridge**.

## What ships vs. what is tested here

| Artifact | Role | Runs where |
|---|---|---|
| `SessionEdgeExecutionEA.mq5` | The shipped Expert Advisor | MetaTrader 5 terminal (compiled with MetaEditor) |
| `JsonBridge.mqh` | EA helpers: bridge file I/O, JSON scalar extraction, SHA-256 digest verify | compiled into the EA |
| `execution_consumer.py` | Executable **reference/specification** of the EA | this repo (pytest) |
| `mock_mt5.py` | Programmable MT5 terminal **test double** | this repo (pytest) — never shipped in the EA |
| `tests/` | Behavioural acceptance tests of the protocol | this repo (pytest) |

> **The MQL5 EA is not compiled or run in this environment** — there is no
> MetaTrader terminal or MQL compiler on the CI platform. The `.mq5`/`.mqh`
> sources are written to mirror `execution_consumer.py` one-to-one; the Python
> reference + mock terminal are what prove the protocol here. A live-terminal
> test plan is below. This is stated plainly as a Phase-3 blocker, not hidden.

## Architecture (bridge consumer)

The adapter reuses the Phase-2 bridge as the **single source of truth** — the
same `Consumer`, `SeenResolver`, serializer, validator, atomic writer, dedup
ledger, audit log and archival. It adds only the two things the bridge
deliberately lacks because it has no broker:

1. an **MT5 order hook** (`ExecutionConsumer._execute`), and
2. **broker-aware restart recovery** (`ExecutionConsumer.recover`).

The reference consumer runs the bridge `Consumer` with hook posture
`NON_IDEMPOTENT_EXECUTION`, so the bridge’s own reconciliation never blindly
re-invokes the order hook; recovery is resolved against broker truth instead.

### Bridge interface additions (Phase 3, minimal)

Only interface-compatibility changes were made to the bridge:

- `contract.ResultState` gains terminal states `EXECUTED` / `EXECUTION_FAILED`
  (previously reserved for the execution layer).
- `terminal_family()` maps `EXECUTED` to the **accepted** family (so a completed
  execution is accepted terminal evidence for dedup / no-double-order);
  `EXECUTION_FAILED` archives with the **rejected** family.
- `build_result(..., execution=…)` optionally populates the execution-only result
  fields; they remain `null` for every transport result.
- `build_ack()` + `paths.acks` (`inbox/acks/`) + `ack_name()` for non-terminal
  acknowledgements.
- `consumer._finish` forwards `detail["execution"]` to the single terminal writer.

No transport logic, validation, dedup, or archival behaviour changed.

## MT5 interface (the only broker surface used)

`BUY` / `SELL` market submission, stop-loss + take-profit placement, ticket
tracking, position lookup, order-result status, position-close detection,
trade-rejection handling, broker-error reporting, and symbol normalization —
via `CTrade`, `OrderSend`/position functions, `SymbolInfoDouble`,
`SymbolSelect`, `PositionGet*`, `TerminalInfoInteger(TERMINAL_CONNECTED)`.
Nothing more. `OnTick` is intentionally empty (no quote reactions).

## Validation pipeline (fail closed; no order on any failure)

Mirrors `bridge/validate.py`, in order: schema version → integrity digest →
required-field completeness → strategy id/version → `signal_id` form + filename
match → expiration (`now >= expiration ⇒ EXPIRED`) → future-skew → canonical
symbol format → direction + price geometry. Then broker-side input checks
(tradable symbol, broker volume min/max/step, stops present, terminal
connected). Any failure writes a terminal `REJECTED` / `EXPIRED` /
`EXECUTION_FAILED` result with a deterministic reason code and **never** places
an order.

**Digest verification is textual and byte-exact.** The producer wrote
`canonical_json(record_with_digest)`; the digest is
`sha256(canonical_json(record_without_digest))`. Because keys are sorted and
separators compact, the EA deletes the `"integrity_digest"` member (and one
adjacent comma) from the raw file bytes to reproduce the without-digest bytes
exactly — so it never reformats numbers and cannot drift from the producer.

## Order lifecycle

```
claim (exclusive rename pending→claimed)
  └─ dedup: terminal evidence? → adopt (DUPLICATE), no order
  └─ validate contract ── fail → REJECTED / EXPIRED (no order)
       └─ broker already holds signal_id? → adopt EXECUTED, no resend
       └─ write ACK (ea id, mt5 terminal id, timestamp)
            └─ broker input checks ── fail → EXECUTION_FAILED (no order)
                 └─ OrderSend BUY/SELL + SL/TP, comment = signal_id
                      ├─ DONE     → EXECUTED  (ticket, fill, slippage) → archive/accepted
                      └─ non-DONE → EXECUTION_FAILED (mapped reason)    → archive/rejected
```

Exactly one terminal result per `signal_id` (deterministic `result_id =
sha256(signal_id|status)[:16]`), then the claimed file is archived.

### Reason codes

Transport (from the bridge): `E_SCHEMA`, `E_INTEGRITY`, `E_FIELDS`,
`E_STRATEGY`, `E_ID`, `E_EXPIRED`, `E_FUTURE`, `E_SYMBOL`, `E_STRUCT`, `E_DUP`.
Execution (broker): `X_OK`, `X_ADOPTED`, `X_INVALID_SYMBOL`, `X_INVALID_VOLUME`,
`X_INVALID_STOPS`, `X_BROKER_REJECT`, `X_MARKET_CLOSED`, `X_REQUOTE`,
`X_OFF_QUOTES`, `X_TRADE_BUSY`, `X_NO_MONEY`, `X_DISCONNECTED`, `X_BROKER_ERROR`,
`X_RECONCILE`.

## Recovery behavior (restart)

State is reconstructed from the **filesystem bridge + the MT5 terminal**, never
from memory. Per stranded `claimed/` instruction:

| Evidence | Action | Order? |
|---|---|---|
| bridge terminal result/archive exists | adopt it (archive, no hook) | no |
| conflicting evidence | quarantine (fail closed) | no |
| broker holds a position for the `signal_id` | finalize `EXECUTED` from broker truth (`X_RECONCILE`) | no |
| ack present, no broker position | `RECONCILIATION_REQUIRED` (outcome unknown) | no |
| no ack, no broker position | never attempted → process normally | first order |

The ticket↔`signal_id` map is rebuilt from open positions (order comment =
`signal_id`). **A second order is never submitted for a `signal_id`** — enforced
three ways: bridge dedup, a point-of-execution broker check, and this recovery.

## Audit structure

Append-only JSONL under `bridge_root/health/audit.jsonl`; every claim, ack,
result, quarantine and reconciliation emits one deterministic line
(`timestamp, action, outcome, reason_code, signal_id, detail`). Timestamps are
inputs in the reference impl, so audit output is deterministic in tests.

## Deployment notes (real terminal)

- Copy `SessionEdgeExecutionEA.mq5` + `JsonBridge.mqh` into
  `MQL5/Experts/SessionEdge/` and compile in MetaEditor.
- MT5 file access is sandboxed: `BridgeRoot` must live under the terminal
  `MQL5/Files/` folder, or set `UseCommonFolder=true` for the shared Files
  folder. Point the strategy producer at the same `bridge_root`.
- Enable **Algo Trading**. Inputs: `BridgeRoot`, `DefaultVolume`, `BrokerSuffix`,
  `PollSeconds`, `MagicNumber`. These are operational, not strategy, settings.

## Live-terminal test plan (deferred — needs MetaTrader)

1. **Compile** in MetaEditor (0 errors/warnings).
2. **Digest parity**: feed producer-written instructions; confirm
   `VerifyIntegrityDigest` accepts genuine files and rejects a tampered byte —
   validated against the Python `serialize.canonical_json` reference vectors.
3. **Strategy Tester / demo account**: BUY and SELL fills, SL/TP attached,
   `comment == signal_id`; result + ack + archive written.
4. **Rejections**: force market-closed / requote / off-quotes / invalid volume
   on a demo symbol; confirm mapped reason codes and no position.
5. **Restart**: kill the terminal mid-flight in each recovery state above;
   confirm no double order and correct finalization.

## Deviations

- **Order volume.** The frozen v1.4.0 instruction contract carries
  `risk_fraction` but **no executable volume**. The EA must not convert
  `risk_fraction` to lots (that is risk sizing, which it may never do). It
  therefore uses an explicit instruction `volume` **if present** (forward
  compatible with an upstream risk layer), otherwise an operator-configured
  constant lot (`DefaultVolume`). Turning risk into lots is out of scope for the
  execution adapter and belongs to a future risk-sizing layer upstream of the
  bridge.
- **MQL5 not compiled/run here** (see top). The Python reference + mock terminal
  are the executable proof on this platform.

## Tests

`tests/test_execution_adapter.py` — 34 stdlib/pytest tests: symbol
normalization, validation (schema/strategy/digest/completeness/expiry), broker
input checks, successful BUY/SELL, direction-taken-verbatim, broker rejection /
market-closed / requote / off-quotes / trade-busy / disconnected, duplicate
prevention, no-double-order (broker guard), restart recovery (all five states),
ticket-map rebuild, ticket correlation/lookup, position-close detection,
ack + result writing, audit generation, and static boundary enforcement
(no networking, no external-process execution, no indicator/price-series APIs).

Run: `pytest forex_swing_orb/ea_mt5/tests`

## Deterministic Position Manager (Phase 4D)

`position_manager.PositionManager` is the **single** stop-management subsystem.
It executes the frozen Phase 4C-R design (`forex_swing_orb/position/contract.py`
+ `spec.py`) against the MT5 terminal — all arithmetic and invariants come from
those modules; nothing is recomputed here. It is deterministic, contains no AI
authority, no networking, and never opens/directs a trade (it only modifies or
protectively closes an existing position).

- **Lifecycle:** `INITIAL → BREAKEVEN → LOCKED → TRAILING → CLOSED`, forward-only
  (a stop already at/beyond a phase target fast-forwards the phase without a
  redundant modification); every transition is audited.
- **Precedence (per cycle, one action):** broker reconciliation → manual
  intervention → kill switch → position closed → weekend → max duration →
  protective-stop integrity → break-even → profit-lock → structure trail →
  no-action. No lower-priority rule weakens a higher-priority protective action.
- **Immutable R** is derived every cycle from the immutable entry/initial_stop
  (never stored/recomputed differently); zero/negative/non-finite/wrong-sided R
  fails closed at `register`.
- **Break-even / profit-lock / trailing** use the frozen `spec` math (`>=`
  triggers, buffer+commission BE stop, `retain_r` lock, swing-offset trail);
  every candidate must strictly improve, satisfy broker min-stop distance, and be
  never-widen/never-loosen legal; broker success is verified before phase advance.
- **Structure trailing** consumes confirmed strategy swings (no pivot recompute,
  no future bars); stale → `PM_DATA_STALE`, missing → `PM_TRAIL_PENDING`,
  duplicate structure reference → `PM_TRAIL_NO_IMPROVEMENT`.
- **Manual intervention:** tightening adopted (`PM_MANUAL_CHANGE_ADOPTED`),
  loosening/SL-removal rejected and the protective stop restored
  (`PM_MANUAL_CHANGE_REJECTED` / `PM_STOP_LOOSEN_REJECTED`), manual close →
  `PM_POSITION_CLOSED`, partial close reconciled (`PM_PARTIAL_CLOSED`),
  ticket/symbol mismatch → fail closed.
- **Reconciliation & restart:** state is rebuilt from MT5 truth + the append-only
  PM audit log (`pm_audit.jsonl`), never RAM only; phase never regresses; an
  uncertain modification is **never blindly retried** — broker truth is verified
  and adopted first.
- **Audit:** one canonical `AUDIT_RECORD_FIELDS` record per evaluation/attempt,
  deterministic, append-only, non-finite values sanitized to null.

`mock_mt5` is extended (test harness only) with `position_by_ticket`,
`modify_stop` (+ scriptable `done`/`reject`/`invalid_stops`/`requote`/`disconnect`/
`applied_but_unacked`). Tests: `tests/test_position_manager.py` (71 tests across
break-even, profit-lock, trailing, never-widen/loosen, manual, reconciliation,
restart, precedence, audit, boundaries, and the Phase 4D-R fixes). The shippable
MQL5 EA mirrors this Python reference and is not compiled here (same platform
limitation as above).

### Phase 4D-R — live-transition safety (F1/F2)

- **Broker-tick quantization (F2).** Every candidate/current/broker/verification
  stop is compared on the symbol's tick grid (from `symbol_info().point`, fallback
  5-digit). Candidates are `NormalizeDouble`-quantized **before** they are sent, so
  a broker that normalizes to its tick verifies as success and never triggers a
  phantom manual-change/reconciliation. Break-even, profit-lock, trailing,
  trigger, and minimum-improvement comparisons all run in integer tick space
  (also removing exact-boundary double-rounding). A broker value that normalizes
  *weaker* than requested is still caught as `RECONCILIATION_REQUIRED` (never a
  false success). The frozen `position/contract.py` and `spec.py` are unchanged —
  quantization is an application-layer normalization in the Position Manager only.
- **Crash-safe audit (F1).** A stop modification records its **intent before**
  the broker call; if the intent audit cannot be written, the manager **fails
  closed and does not modify the stop** (`RECONCILIATION_REQUIRED` /
  `audit_intent_failed`). If the broker modification succeeds but the completion
  audit fails, the manager **never throws** — it flags reconciliation
  (`completion_audit_failed`); broker truth is intact (state + broker hold the
  applied stop) and is rebuilt cleanly on the next cycle / on restart with no
  blind retry. All audit writes go through a non-throwing sink.

### Position Manager authority (explicit)

The deterministic Position Manager is authorized to **protectively close** an
existing position — for the weekend-flatten, kill-switch, and maximum-duration
policies (`PM_WEEKEND_EXIT` / `PM_KILL_SWITCH` / `PM_MAX_DURATION_EXIT`), via the
broker close operation. This is a **protective, risk-reducing** action on an
already-open position; it is **not** new-trade authority: the manager never opens
a position, never creates or changes trade direction, and never sizes a trade.

### Trailing structure freshness (mandatory)

A trailing stop moves only on a **confirmed, closed, fresh** strategy swing. The
caller must supply `bars_since_swing`; if it is missing or exceeds
`stale_structure_max_bars`, the manager emits `PM_DATA_STALE` and does not move
the stop. Swings are consumed from the strategy — pivots are never recomputed and
no future-bar information is used.
