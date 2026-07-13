# ADR-023 — Hybrid MT5 MQL5 EA Bridge

Status: Accepted

Acceptance Date: 2026-07-08

Accepted By: User direction, this session (explicit, full specification:
EA capabilities/prohibitions, architecture constraints, 6 named
deliverables, EA/security/Python-endpoint requirements, testing and
validation requirements) — the same in-session approving authority
already used to accept `ADR-020` through `ADR-022`.

Owner: Backend Architect (Accountable per `.claude/agents/TEAM.md` — a
new transport/protocol boundary between an external process and the
pipeline is exactly this role's mandate), Application Security Engineer
(Consulted — this ADR introduces Titan Protocol's first network-facing
inbound surface; API-key auth, replay/idempotency, and input validation
are reviewed as a security boundary, not just a transport detail)

Reviewed by: Integration Engineer (post-hoc interface-compatibility
verification — confirms `EABrokerAdapter` satisfies `mt5_bridge.broker_adapter.BrokerAdapter`'s
existing ABC byte-for-byte and that no pipeline-stage package changes)

Date: 2026-07-08

Depends on: `ADR-001-single-authority-architecture.md` (Accepted),
`ADR-008-mt5-bridge.md` and its Amendment 1 (Accepted — `BrokerAdapter`
is the existing abstraction this ADR implements a new instance of, never
modifies), `ADR-013-data-pipeline.md` (Accepted — `DataPipeline.process_raw_tick()`/
`load_historical_bars()` are the existing ingestion entry points EA-
reported ticks/bars are fed through, never re-implemented)

---

# Pipeline position

**The MQL5 EA and its Python-side bridge are not a pipeline stage and do
not add one.** `phantom_pipeline/ea_bridge/` is a transport package that
sits *behind* the already-Accepted `mt5_bridge` stage, in exactly the
position `MT5Adapter`/`FakeBrokerAdapter` already occupy: it implements
the same `BrokerAdapter` interface `MT5Bridge` already depends on, so
`MT5Bridge` itself needs zero code change to use it. The trading-decision
pipeline is completely unchanged:

**Data Pipeline → Scanner → Strategy Engine → Scoring Engine → Risk
Engine → Compliance Engine → Execution Validator → MT5 Bridge → Position
Manager → Analytics**

`MT5Bridge.submit_order()` still only ever accepts an `ExecutionDecision`
of `APPROVE` (`ADR-008` Hard Rules, unchanged) and still produces exactly
one `BrokerRequest`, translated exactly as `checks.translate_order()`
already does today. What changes is only *which* `BrokerAdapter`
implementation `MT5Bridge` was constructed with: `MT5Adapter` calls the
`MetaTrader5` Python package directly; `EABrokerAdapter` (this ADR)
instead places the already-approved `BrokerRequest` on a command queue
that an MQL5 EA running inside a MetaTrader 5 terminal polls and
executes, then reports the result back. **Both adapters coexist —
`MT5Adapter` is not removed, not modified, and remains the default
real-adapter choice; `EABrokerAdapter` is an additional, alternative
choice a deployer may select instead.**

---

# 1. Mission

**The EA bridge answers exactly one question: "How does an
already-Titan Protocol-approved order reach a MetaTrader 5 terminal, and how
does its result get back to Titan Protocol?"**

**It never answers:** Should this trade happen? How much risk? Is this
compliant? Is execution currently safe? Those remain each existing
stage's own question, entirely unchanged. The EA is a terminal-side
transport and execution relay — it receives a command Titan Protocol has
already fully decided, executes exactly that command via MQL5's
`OrderSend`, and reports back what happened. It has no branch anywhere
in its logic that originates, sizes, or re-prices a trade.

---

# Hard Rules

1. **Bridge only, structurally.** No file in `phantom_pipeline/ea_bridge/`
   and no code path in `mt5/TitanProtocolEA.mq5` computes a score, a
   risk percent, a compliance verdict, or an execution verdict. The EA's
   only trade-initiating action is executing a command it received from
   `/ea/commands/poll` — there is no local signal-generation code in the
   `.mq5` file at all.
2. **`mt5_bridge/` is not modified.** `EABrokerAdapter` implements
   `mt5_bridge.broker_adapter.BrokerAdapter`'s existing 7-method ABC
   exactly (`connect`, `disconnect`, `heartbeat`, `send_request`,
   `poll_execution`, `query_open_position_ids`, `query_account_equity`) —
   verified by a structural test that `EABrokerAdapter` is a subclass and
   implements no additional public trading method. `MT5Bridge.submit_order()`/
   `submit_position_adjustment()`/`submit_position_close()`/`poll_execution()`
   are called exactly as `ADR-008` already defines them; this ADR adds no
   new call path into `MT5Bridge`.
3. **No pipeline-stage package changes.** `risk_engine/`,
   `compliance_engine/`, `execution_validator/`, `position_manager/`,
   `scanner/`, `strategy_engine/`, `scoring_engine/`, `data_pipeline/`,
   `analytics/` are byte-for-byte unchanged. `ea_bridge` calls only
   `data_pipeline.DataPipeline`'s existing public `process_raw_tick()`/
   `load_historical_bars()` methods to ingest EA-reported ticks/bars —
   the same "another feed source, same public entry point" posture
   `data_pipeline.market_data_adapter.MarketDataAdapter` already
   established (`ADR-013`/Phase 3).
4. **Every command the EA executes must already be Titan Protocol-approved.**
   The only way an `ExecutionCommand` is created is inside
   `EABrokerAdapter.send_request()`, translating an already-produced
   `BrokerRequest` (itself only ever constructed by `mt5_bridge.checks.translate_order()`/
   `translate_position_adjustment()`/`translate_position_close()`, which
   in turn only ever run after `MT5Bridge`'s own Hard-Rule checks pass).
   No other code path in `ea_bridge` can enqueue a command.
5. **Fail-closed, on both sides.** Python side: if the EA has not sent a
   heartbeat within `EABridgeConfig.heartbeat_timeout_seconds`,
   `EABrokerAdapter.heartbeat()` returns `False`, which (per `ADR-008`
   §6, unchanged) drives `MT5Bridge.state` back to `DISCONNECTED` — no
   new command is ever placed on the queue while disconnected
   (`command_queue.py` refuses to enqueue when the bridge is not
   `READY`, mirroring `MT5Bridge._send_and_record`'s own connection-state
   gate). EA side: `TitanProtocolEA.mq5` treats a failed poll (network
   error, non-200, or a stale/absent heartbeat acknowledgement beyond its
   own `FailClosedTimeoutSeconds` input) as "stop opening anything new" —
   it never falls back to local decision-making.
6. **Transport-integrity validation is not re-deciding a trade.**
   `validation.py`'s checks (API key, command-ID idempotency, timestamp/
   staleness, symbol allowlist, volume sanity, SL/TP sanity, magic-number
   isolation) defend the *relay* from being corrupted, replayed, or
   spoofed between Python and MQL5 — they never change a command's
   symbol, size, direction, SL, or TP. A command that fails any check is
   dropped/rejected wholesale, never edited and re-issued.
7. **Idempotent by `execution_id`.** Every `BrokerRequest`/`ExecutionCommand`/
   `ExecutionReport` correlates by the same `execution_id` `mt5_bridge`
   already generates (`make_execution_id`) — `ea_bridge` invents no
   parallel ID scheme. A command already marked delivered/executed is
   never re-delivered or re-executed; a duplicate execution report for an
   already-recorded terminal result is accepted as a no-op, never a
   second fill.
8. **No live deployment, no real trades, in this ADR's scope.** This ADR
   and its implementation are a bridge and its test suite only. Wiring
   `EABrokerAdapter` into a live `MT5Bridge` instance against a real
   account, and running `TitanProtocolEA.mq5` against a live/funded
   terminal, are explicitly deferred operator actions — not performed or
   simulated against a real broker anywhere in this work.

---

# 2. Architecture

```
MetaTrader 5 terminal (Windows/Wine)
  └─ TitanProtocolEA.mq5  (attached to one chart; OnTimer-driven)
       │  HTTP (localhost or LAN, API-key authenticated)
       ▼
phantom_pipeline/ea_bridge/http_server.py   (stdlib-only, 9 routes)
       │
       ▼
phantom_pipeline/ea_bridge/engine.py  (EABridgeEngine)
       ├─ ingests ticks/bars  → data_pipeline.DataPipeline (existing, unmodified)
       ├─ stores account/position snapshots (ea_bridge's own read models)
       ├─ command_queue.py   ← EABrokerAdapter.send_request() enqueues here
       └─ validation.py      (API key, idempotency, staleness, allowlist,
                              volume/SL-TP sanity, magic number)

phantom_pipeline/ea_bridge/broker_adapter.py  (EABrokerAdapter)
       implements mt5_bridge.broker_adapter.BrokerAdapter
       ▲
       │ constructor-injected, exactly like MT5Adapter/FakeBrokerAdapter
       │
phantom_pipeline/mt5_bridge/engine.py  (MT5Bridge — UNCHANGED)
```

Every arrow above is either an already-existing public interface
(`DataPipeline.process_raw_tick`/`load_historical_bars`, the
`BrokerAdapter` ABC) or new code wholly inside `ea_bridge`/`mt5/`. Nothing
upstream of `MT5Bridge` (Data Pipeline's ingestion aside, which is a pure
data feed with no decision content) is touched.

## 2.1 EA responsibilities (may)

Attach to an MT5 chart; send heartbeat; send account state; send
symbol/tick data; send M15/H1/H4/D1 bars; receive approved execution
commands; execute only commands Titan Protocol has already approved; send
execution results back; send position updates back; fail closed if
Titan Protocol is offline.

## 2.2 EA prohibitions (must never)

Generate trades; score trades; override risk, compliance, or the
execution validator; open trades without a signed/approved Titan Protocol
command; change lot size; change SL/TP unless commanded by Titan Protocol;
continue trading if the Titan Protocol backend is offline.

---

# 3. Security model

- **API key required** on every request (`X-Titan-Protocol-Api-Key` header,
  checked against `EABridgeConfig.api_key`; constant-time comparison).
- **Command IDs are idempotent** — keyed by `execution_id`; a poll never
  redelivers an already-delivered command, an execution report for an
  already-terminal `execution_id` is a no-op.
- **No duplicate execution** — the same `has_executed`/`record_executed`
  discipline `mt5_bridge.idempotency_store` already established for
  transport-layer duplicate submission, mirrored here for the EA-facing
  side of the same `execution_id`.
- **Timestamp/staleness validation** — a command not delivered within
  `EABridgeConfig.command_ttl_seconds` of being enqueued is dropped, never
  handed to the EA; an execution report referencing a command older than
  the TTL is rejected.
- **Symbol allowlist** — `EABridgeConfig.allowed_symbols`; any inbound
  tick/bar/command for a symbol outside it is rejected.
- **Volume validation** — `lot_size` must be `> 0` and
  `<= EABridgeConfig.max_lot_size`.
- **SL/TP validation** — when present, must be strictly positive; when a
  recent tick for the symbol is known, must be on the direction-correct
  side of it (never validated against a fabricated price when none is
  known).
- **Magic number isolation** — every command and every execution/position
  report must carry `EABridgeConfig.magic_number`; a mismatched magic
  number is rejected, defending against cross-talk if more than one
  bridge/EA shares a terminal.

---

# 4. Interfaces

`phantom_pipeline/ea_bridge/`: `models.py` (types only —
`HeartbeatMessage`, `EAAccountState`, `TickMessage`, `BarMessage`,
`PositionReport`, `ExecutionCommand`, `ExecutionReport`, `ErrorReport`),
`config.py` (`EABridgeConfig` — api key, allowed symbols, magic number,
max lot size, max slippage, TTLs, intervals, fail-closed/emergency-stop
defaults), `command_queue.py` (`CommandQueue` — enqueue/poll/mark-delivered/
mark-executed, refuses to enqueue unless the bridge considers itself
`READY`), `validation.py` (every check in §3, each a pure function
returning `Optional[str]` reason, mirroring `execution_validator.checks`'s
own "value in, reason-or-None out" convention), `broker_adapter.py`
(`EABrokerAdapter(BrokerAdapter)`), `http_server.py` (`EABridgeHTTPServer`,
stdlib `http.server`-based, mirroring `titan_protocol/api.py`'s "Python stdlib
only" precedent), `engine.py` (`EABridgeEngine` — the top-level
orchestrator wiring `DataPipeline`, `CommandQueue`, and the read-model
stores together), `logging_sink.py`, `metrics.py`, `__init__.py`.

`mt5/TitanProtocolEA.mq5` (the EA source) and `mt5/TitanProtocolEA.set`
(a default input-parameter template) — outside `phantom_pipeline/`
entirely, since MQL5 is not Python and is never imported or compiled by
anything in this repository; it is source a deployer compiles inside the
MetaEditor bundled with MetaTrader 5.

---

# 5. Testing

Unit tests: command validation (every check in §3 independently), command-
ID idempotency (a second poll/report for the same `execution_id` never
re-delivers/re-executes), stale command rejection, duplicate command
rejection, heartbeat handling (timeout drives `EABrokerAdapter.heartbeat()`
to `False`), bar ingestion (forwarded to `DataPipeline.load_historical_bars()`
verbatim, never re-normalized a second way), execution report handling
(terminal states are idempotent), fail-closed behavior (`CommandQueue`
refuses to enqueue while not `READY`; emergency-stop halts new command
issuance). A structural boundary test confirms `EABrokerAdapter` is the
*only* new class satisfying `BrokerAdapter`, and that no file under
`risk_engine/`, `compliance_engine/`, `execution_validator/`,
`position_manager/`, `mt5_bridge/`, `scanner/`, `strategy_engine/`,
`scoring_engine/`, `data_pipeline/`, `analytics/` changed.

---

# 6. Acceptance criteria

- All Hard Rules above hold, verified by dedicated tests.
- `EABrokerAdapter` passes as a `BrokerAdapter` in a real `MT5Bridge`
  instance in tests (constructor-substitutable for `FakeBrokerAdapter`
  with zero `MT5Bridge`-side change).
- Full existing validation suite (`compileall`, `unittest discover`,
  `validate.py`, `scripts/check_architecture.py`) stays green.
- `git diff --stat` against every pipeline-stage package plus
  `mt5_bridge/` is empty.

---

# 7. Explicitly out of scope (this ADR)

- **Auto-converting EA-reported account state into `risk_engine.models.AccountState`/
  `compliance_engine.models.AccountState`/`execution_validator.models.AccountState`.**
  Those three types need drawdown-curve tracking (`paper_trading.AccountTracker`
  already owns that computation) — a caller wanting live `RiskAccountState`
  from EA-reported equity composes `AccountTracker.observe(equity, now)`
  themselves, exactly as `PaperTradingRunner.observe_account()` already
  does for the existing `MT5Adapter` path. `ea_bridge` does not duplicate
  that computation.
- **Wiring `EABrokerAdapter` into `orchestrator.py`/`start_titan_protocol.py` by
  default.** Both remain constructed with whichever `BrokerAdapter` a
  deployer chooses, exactly as today; this ADR adds a second available
  choice, it does not change the default.
- **Live deployment, real accounts, real trades.** Explicitly out of
  scope per the task's own closing instruction — this ADR delivers the
  bridge and its test suite, nothing is deployed or run against a live
  terminal.
- **TLS/HTTPS for the HTTP server.** Phase 1 assumes a trusted localhost/
  LAN transport between the terminal and the bridge process (the same
  trust boundary `MetaTrader5`'s own Python package already assumes
  against a local terminal) — API-key auth is the defense against an
  untrusted network peer, not encryption-in-transit; a TLS-terminating
  reverse proxy in front of `EABridgeHTTPServer` is a real, deliberately
  deferred operator option for a LAN deployment, not built here.

---

# 8. Related work (considered, not adopted)

Two existing MT5↔external-process bridge libraries were reviewed while
scoping this ADR. Neither is adopted, for the same two reasons in both
cases:

**[`Gunther-Schulz/MQL5-JSON-API-2`](https://github.com/Gunther-Schulz/MQL5-JSON-API-2)**
— a general-purpose bridge using ZeroMQ sockets (7 channels: system/data/
live/streaming/indicator-data/chart-data/chart-indicator) with a JSON
message schema covering account queries, order placement/modification,
history export, indicators, and chart plotting.

**[`darwinex/dwx-zeromq-connector`](https://github.com/darwinex/dwx-zeromq-connector)**
— Darwinex's own ZeroMQ-based MT4/MT5↔Python connector, in the same
architectural family (PUSH/PULL/SUB sockets carrying a custom message
protocol for orders, historical data, and live market data).

Not adopted, because:

1. **No documented authentication or replay protection in either.** This
   ADR's §3 security model (API key, command-ID idempotency, timestamp/
   staleness validation, symbol allowlist, volume/SL-TP validation,
   magic-number isolation) is a hard requirement of the originating task
   spec; adopting either library would mean building the same security
   layer on top of it rather than instead of building `ea_bridge`'s own,
   so it would not reduce scope.
2. **Scope mismatch.** Both are general-purpose bridges exposing broad
   MT5 functionality (indicators, chart plotting, arbitrary history
   export, generic tick/bar streaming) to any external client. `ADR-023`'s
   Hard Rule 1 requires the opposite posture — the narrowest possible
   surface, carrying only already-Titan Protocol-approved commands and their
   results, with no general-purpose query/control surface at all.

Both remain legitimate alternatives a future deployer could choose
instead of `phantom_pipeline/ea_bridge/` + `TitanProtocolEA.mq5` — e.g.
if they want ZeroMQ's lower latency/streaming ticks for a use case this
ADR does not target — but neither is what this ADR implements, and no
code from either is vendored into this repository.

**Also reviewed, and explicitly out of this ADR's scope entirely**
(unrelated to the MT5 transport question this ADR answers, deferred to
separate future work if ever pursued): `chroma-core/chroma` (a vector
database — relevant only to `knowledge/vector_store.py`'s `InMemoryVectorStore`,
not to this ADR), `mementum/backtrader` and `QuantConnect/Lean` (full
backtesting/algo-trading engines — relevant only to a possible future
replay/backtest-certification effort, not to this ADR). None of these
three are cited further here; no code or dependency change was made for
any of them.
