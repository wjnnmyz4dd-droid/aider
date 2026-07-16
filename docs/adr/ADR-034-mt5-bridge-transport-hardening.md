# ADR-034 — MT5↔Bridge Transport Hardening (Native Socket Transport)

Status: **Accepted**

Acceptance Date: 2026-07-16

Accepted By: User direction, this session (explicit: "Approve ADR-034 ...
Implement the native socket transport exactly as specified").

**Amendment 1 (2026-07-16 — accepted alongside the base ADR):** the
approving request refines §5's migration plan from simultaneous
HTTP+socket coexistence to a single-active-transport model: `BridgeConfig`
gains one `transport` field (`"http"` | `"socket"`), and the deployment
layer starts exactly one listener, selected by that field, never both at
once. HTTP remains available purely as a rollback path (flip the field
back, restart) — not a second concurrently-running transport. This is a
tightening of §5's already-additive, already-reversible design, not a
change to §4's recommendation or §2/§3's option comparison.

**Amendment 2 (2026-07-16 — "Produce a Clean Deployment Release"):**
`BridgeConfig.transport`'s shipped default flips from `"http"` to
`"socket"`, matching `TitanProtocolEA.mq5`'s `Transport` input default,
which also flips from `Http` to `Socket` — at explicit user direction, so
a fresh install ships already running the transport §4 recommended,
rather than requiring an opt-in edit after every clean install. `"http"`
remains fully supported and becomes the explicit rollback value
(`transport="http"` / `Transport=Http`) — no code path, message schema,
or validation rule from the base ADR or Amendment 1 changes; only which
value ships as the out-of-the-box default. `mt5/TitanProtocolEA.set`'s
`Transport` line is deliberately still omitted (see the file's own
comment) since this session could not confirm MQL5's `.set` serialization
convention for a custom enum input with confidence — the compiled
default carries the new value instead, which MT5 already applies
whenever a `.set` file's key is absent. Also normalizes
`BridgeConfig.magic_number`'s default from `20260709` to `20260710`
(matching `RuntimeConfig.magic_number`, which was already `20260710`) —
these two literals silently diverging was itself a drift risk this
amendment closes, not an architecture change.

Owner: Backend Architect (Accountable per `.claude/agents/TEAM.md` — same
rationale as `ADR-023`: this is a transport/protocol boundary between an
external process and the pipeline)

Reviewed by: Application Security Engineer (Consulted — changes the
authentication/trust mechanics of Titan Protocol's only inbound network
surface), SRE (Consulted — reconnect/heartbeat/connection-health behavior
is its lane per `TEAM.md`), Integration Engineer (Consulted — must confirm
no pipeline-stage package is touched, mirroring `ADR-023`'s own review
gate)

Date: 2026-07-16

Depends on: `ADR-001-single-authority-architecture.md` (Accepted),
`ADR-023-mql5-ea-bridge.md` and its Amendment 1 (Accepted — this ADR
supersedes **only** §2's HTTP transport substrate and §11-12's
HTTP-specific wire mechanics; it changes none of `ADR-023`'s message
schemas, validation semantics, security checks, Hard Rules, or ownership
boundaries, all of which carry over unchanged onto the new substrate),
`ADR-032-system-reliability-engine.md` (Accepted — heartbeat/connection-
health semantics this ADR's reconnect behavior must remain consistent
with), `ADR-033-market-data-ingestion-and-news-failover.md` (Accepted —
market-data messages this transport must continue to carry, unmodified in
shape)

---

# Origin and scope of this ADR

This ADR was requested after a multi-session diagnostic effort proved,
against the real running deployment, that MT5's `WebRequest()` calls
intermittently return undocumented pseudo-status codes (`1001`, `1003` —
neither is a real HTTP status nor a documented `GetLastError()` value;
both were observed on this exact installation in different sessions) that
originate client-side, inside the MT5 terminal's network stack — not from
`titan_protocol/bridge/server.py`, whose every code path was exhaustively
enumerated and proven incapable of emitting them, and not from any
API-key or `magic_number` misconfiguration, both independently confirmed
correct via direct `curl` tests against the Bridge. The same session also
hit a `NullReferenceException` from PowerShell's `Invoke-RestMethod`/
`Invoke-WebRequest`, a failure mode documented as tied to a broken or
unresolvable WinINet system-proxy configuration on the same machine —
`curl.exe`, which does not use WinINet, was unaffected throughout.

This ADR does not re-litigate that diagnosis. It treats "the MT5-side
WinINet/HTTP stack on this class of deployment is unreliable, for reasons
outside this codebase's control (proxy configuration, AV/firewall
interception, WinINet installation state)" as an established fact for the
purposes of transport selection, and asks only: **given that fact, what is
the simplest transport that does not depend on the failing layer?**

Per the originating request, this document is **ADR-only**. No
implementation, no code change, and no file outside `docs/adr/` is
touched by this ADR.

---

# Pipeline position

**This ADR does not touch, move, or add a pipeline stage.** Exactly as
`ADR-023` already established, the MQL5 EA and its Python-side bridge sit
*behind* the pipeline, not inside it:

Market Data → Scanner → Strategy Engine → Scoring Engine → Risk Engine →
Compliance Engine → Execution Validator → **MT5 Bridge** → Position
Manager → Analytics

`titan_protocol/runtime/engine.py`'s `RuntimeOrchestrator` and every
engine it calls (Evidence, Market Intelligence, Strategy, Risk,
Compliance) are unaffected by which bytes-on-the-wire mechanism carries an
already-decided command to the terminal, or an already-observed bar/tick/
account-state back. This ADR is scoped exclusively to the substrate
underneath `titan_protocol/bridge/` and `mt5/TitanProtocolEA.mq5`.

---

# 1. Mission

**This ADR answers exactly one question: "What is the simplest transport
substrate that reliably carries the already-defined Bridge message set
between MT5 and Python, without depending on the specific network layer
this session proved unreliable?"**

It does not re-decide what messages exist (`ADR-023` §4/§11 already
define them), what validation applies to them (`ADR-023` §3's checks are
unchanged), or any trading, risk, compliance, or execution logic
whatsoever.

---

# Hard Rules (carried forward from the originating request; binding on
whichever option is selected)

1. **No full-system rebuild.** This ADR proposes a substrate swap under
   `titan_protocol/bridge/` and `mt5/TitanProtocolEA.mq5` only.
2. **No changes to Strategy, Risk, or Compliance Engine logic**, or any
   other pipeline-stage package.
3. **No duplicate business logic.** `validation.py`'s existing checks
   (API key, idempotency, staleness, symbol allowlist, volume/SL-TP
   sanity, magic-number isolation) are reused verbatim, applied to
   messages arriving over the new substrate exactly as they are applied
   today over HTTP — never re-implemented a second way.
4. **One canonical transport.** The end state is a single transport in
   active use; §7 below defines a bounded, explicitly-scoped coexistence
   period for migration only, not a second permanent transport.
5. **Existing command/result models unchanged where possible.** Every
   dataclass in `titan_protocol/bridge/models.py` (`HeartbeatMessage`,
   `EAAccountState`, `RawBarMessage`/`RawTickMessage`, `ExecutionCommand`,
   `ExecutionReport`, `PositionReport`, `ErrorReport`) keeps its exact
   field set; only how its JSON serialization is framed on the wire
   changes.
6. **New transport must cover the full existing message surface**:
   heartbeat, account-state, market-data (bars/ticks), command-polling,
   execution-reporting, and emergency-stop-state — nothing narrower than
   what HTTP carries today.
7. **All failures explicit and logged.** Connection-state transitions,
   send/receive failures, and reconnect attempts are logged with the same
   metadata-only discipline already established for `DiagnosticMode`/
   Bridge lifecycle logging this session (method/path/sizes/timestamps/
   status — never API keys, account numbers, trade payload contents,
   credentials, or secrets).
8. **Existing positions keep being managed during transport loss.**
   Exactly as `ADR-023` Hard Rule 5/§13 already require for HTTP,
   transport unavailability under the new substrate must never abandon
   already-open positions — Position Manager's own management is
   independent of which transport is currently up.
9. **New entries fail closed while transport is unhealthy.** Mirrors
   `ADR-023` Hard Rule 5 exactly: no new command is issued, and the EA
   opens nothing new, while the connection (however implemented) is not
   confirmed healthy.

---

# 2. Options considered

Four options were evaluated, exactly as scoped by the originating
request. Each was verified against MT5/MQL5's actual documented
capabilities (`mql5.com/en/docs/network/*`), not assumed.

## Option 1 — Harden the existing HTTP/`WebRequest()` transport

Keep `WebRequest()` as the wire mechanism; add forced `Connection: close`
per request, bounded retry with backoff, and the `DiagnosticMode`
instrumentation already shipped this session (commit `6d82dd5`).

## Option 2 — File-based local queue via `MQL5\Files\Common`

Replace HTTP with `FileOpen(..., FILE_COMMON)` reads/writes to a shared
folder both the MT5 terminal and the Python Bridge process can reach,
polled by both sides.

## Option 3 — Local socket transport natively supported by MT5

Use MQL5's built-in `SocketCreate`/`SocketConnect`/`SocketSend`/
`SocketReceive`/`SocketIsConnected`/`SocketClose` functions (documented at
`mql5.com/en/docs/network/socketcreate` et al.) to open a persistent raw
TCP connection from the EA to the Bridge.

## Option 4 — Named-pipe / lightweight localhost relay

Considered only conditionally, per the originating request's own framing
("only if actually MT5-supported and justified"). **It fails the first
test.** MQL5 has no native named-pipe API; the only path to one is
`#import`ing `kernel32.dll` functions (`CreateFileW`/`ReadFile`/
`WriteFile`/`CloseHandle`), which requires enabling "Allow DLL imports"
for the EA — a materially larger permission grant than either the
WebRequest allowed-URL list or the Socket allowed-address list, since DLL
imports let arbitrary native code execute inside the terminal process,
outside any MQL5-level sandboxing. This is precisely the class of risk
prop-firm compliance reviews flag, and precisely what this charter's
capital-preservation-first posture (§2, Risk philosophy) counsels against
accepting for a transport-layer convenience. **Option 4 is rejected
outright** and is not scored further below; it is retained here only to
show it was considered and why it does not qualify as a viable candidate.

---

# 3. Comparison — 8 criteria, Options 1-3

| Criterion | Opt 1: Hardened HTTP | Opt 2: File queue | Opt 3: Native socket |
|---|---|---|---|
| **MT5 compatibility** | Native, already shipped, zero new permission surface | Native (`FileOpen`/`FILE_COMMON`); needs no Tools→Options allowed-address entry at all | Native, documented, no DLL imports; needs one allowed-address entry (same list `WebRequest` already uses) |
| **Reliability** | Still routes through WinINet — the exact layer proven unreliable this session; hardening reduces symptom frequency but cannot fix a layer it doesn't control | Fully bypasses the network stack (no WinINet, no Winsock); only failure modes are disk I/O and cross-process file-locking races, both local and controllable | Uses raw Winsock/system sockets, architecturally distinct from WinINet — directly bypasses the diagnosed root cause instead of hardening around it |
| **Latency** | Low, unchanged from today (single request/response) | Highest of the three — bounded by both sides' polling interval, no push | Lowest — persistent connection, push-capable (Bridge can write as soon as data is ready) |
| **Implementation complexity** | Lowest — `Connection: close` header + retry/backoff on top of already-shipped instrumentation | Moderate-high — needs an atomic write protocol (write-temp-then-rename) on both sides, a per-message-type naming/sequencing scheme, and a rotation/cleanup policy | Moderate — needs a message-framing protocol (sockets are a byte stream, not request/response) and an explicit connect/reconnect state machine |
| **Security** | Unchanged; already-reviewed API-key header model | No transport-level auth exists for shared-filesystem writes — "whoever can write to the Common folder can inject a message" is a materially different trust boundary than an authenticated request and needs new reasoning | Same API-key-in-payload model as today carries over unchanged; TLS available via `SocketTlsHandshake` if ever needed, not required to match `ADR-023`'s existing accepted localhost/LAN trust posture |
| **Reconnect behavior** | Stateless per-call; no persistent-connection state to recover, and no way to detect a half-open connection between polls | No connection to lose; "reconnect" reduces to "resume polling," but stalled-peer detection needs its own heartbeat-file-staleness timeout, duplicating `ConnectionHealth` logic in a new form | `SocketIsConnected()` gives a first-class, inspectable signal `WebRequest()` never provided; one reconnect/backoff loop, built once, reused for every message type |
| **Demo-testability** | Fully testable today; no new risk | Fully testable, easiest to isolate (no external dependency at all) | Fully testable on demo/localhost; identical MT5-side risk profile to what's already running |
| **Operational support burden** | Low ongoing effort, but the root cause remains unresolved — expect continued unpredictable `1001`/`1003`-class incidents | Low once running, but shifts burden to disk hygiene (orphaned files, disk-full) and correctly implementing atomicity — a new bug class this codebase doesn't have today | Moderate — one new failure class (connection-state transitions) to monitor, but with far better diagnostics (explicit connected/disconnected state) than `WebRequest()`'s opaque pseudo-codes ever offered |

---

# 4. Recommendation

**Option 3 — native MQL5 socket transport (`SocketCreate`/`SocketConnect`
family)** is the simplest transport that reliably solves the diagnosed
problem.

Rationale, in order of weight:

1. **It is the only option that directly addresses the proven root
   cause.** This session's diagnostics did not point at the Bridge, at
   configuration, or at API-key/magic-number mismatches — all three were
   independently ruled out. They pointed at MT5's WinINet-based network
   stack specifically. Option 1 keeps using that exact stack; Option 3 is
   documented to use raw system sockets (Winsock) instead, a genuinely
   different code path, not a cosmetic change.
2. **It requires no new permission category.** Unlike Option 4 (DLL
   imports) or a hypothetical TLS-terminating proxy, Option 3 uses the
   same Tools→Options→Expert Advisors allowed-address list `WebRequest()`
   already requires today — a deployer adds one more line to a list they
   already maintain, not a new kind of grant to justify to a prop firm's
   compliance review.
3. **It is bounded in new complexity.** Option 2's atomicity/rotation
   design is a larger new surface than Option 3's framing/reconnect
   state machine, for a capability (fully bypassing any network stack)
   this problem does not actually require — the diagnosed failure is
   WinINet-specific, not "all networking on this machine is unreliable."
4. **It preserves every existing security and message semantic.** The
   same API-key-carrying payload model, the same `validation.py` checks,
   and the same message dataclasses all carry over unchanged (Hard Rules
   3/5 above) — this is a substrate swap, not a redesign of what is
   authenticated or how.

Option 1 is not recommended as the end state: it is real, low-cost
hardening but does not change the layer already shown to fail, so
residual `1001`/`1003`-class incidents should be expected to continue at
some (possibly reduced) rate. Option 2 is not recommended: its full
bypass of the network stack is more isolation than the diagnosis calls
for, and it introduces a new atomicity/rotation problem class this
codebase does not otherwise have. Option 4 is rejected per §2.

---

# 5. Migration plan

1. **Bridge gains a socket listener, additive.** `BridgeConfig` gains one
   new optional field (e.g. `socket_port: Optional[int] = None`),
   defaulting to disabled — existing deployments are unaffected until a
   deployer explicitly opts in. The Bridge remains the server side of the
   connection (unchanged role from today's HTTP model); the EA remains
   the client (`SocketConnect`), also unchanged.
2. **Define wire framing.** Newline-delimited JSON: each message is one
   JSON object (the exact same shape `models.py`'s existing dataclasses
   already serialize to) followed by `\n`. No schema change — only how
   bytes are delimited changes (HTTP request/response body → a
   continuous framed byte stream).
3. **Reuse `validation.py` unchanged.** Every check in `ADR-023` §3 is
   applied per deserialized message exactly as it is applied per HTTP
   request today; no new validation file, no duplicate logic (Hard Rule
   3).
4. **EA-side implementation.** Add `SocketConnect`/`SocketIsConnected`/
   `SocketSend`/`SocketReceive`/`SocketClose` wrapper functions to
   `mt5/TitanProtocolEA.mq5`, alongside (not replacing, during migration)
   the existing `HttpPost`/`HttpGet`. Add a `TransportMode` input
   (`Http` | `Socket`), defaulting to `Http` — existing charts are
   unaffected until a deployer explicitly changes it. Extend the existing
   `DiagnosticMode` logging (commit `6d82dd5`) to cover socket
   connect/send/receive outcomes with the same metadata-only fields
   already established (never payload contents, never the API key).
5. **One active transport at a time (Amendment 1).** `BridgeConfig.transport`
   selects `"http"` or `"socket"`; the deployment layer starts exactly the
   listener that field names, never both. Migrating means changing the
   field and restarting the process, not running two listeners
   concurrently — HTTP is a rollback path, not a second permanent
   transport, satisfying Hard Rule 4 without needing a coexistence
   exception.
6. **HTTP removal is out of this ADR's scope.** Deleting the HTTP code
   path entirely (as opposed to leaving it as the `"http"` rollback
   option) is a separate, later, separately-approved change.

---

# 6. Compatibility impact

- **Zero impact on any pipeline-stage package.** Evidence, Market
  Intelligence, Strategy, Risk, Compliance, Runtime, and Market Data
  Ingestion are untouched — identical posture to `ADR-023`.
- **Zero impact on message schemas.** `titan_protocol/bridge/models.py`'s
  dataclasses are unchanged; only their wire encoding gains a second
  valid framing.
- **Zero impact on `validation.py`.**
- **`BridgeConfig` gains one new optional field**, fully backward
  compatible (a config omitting it behaves exactly as today).
- **`TitanProtocolEA.mq5` gains one new input** (`TransportMode`),
  defaulting to today's behavior — no existing deployment changes
  behavior without an explicit operator action.
- **`DiagnosticMode` instrumentation (this session's existing work) is
  extended, not replaced** — the same structured logging block gains
  socket-specific fields alongside the existing HTTP fields.

---

# 7. Test plan

- **Unit:** socket-framing encode/decode round-trip (byte-for-byte
  parity with existing dataclass JSON serialization); connect/reconnect
  state-machine tests (simulated mid-message drop, simulated partial
  read, simulated slow peer); every existing `validation.py` test
  re-run unchanged against messages delivered over the new substrate
  (proves zero business-logic regression).
- **Integration:** Bridge socket listener against a test TCP client
  standing in for the EA, covering heartbeat, account-state, market-data
  (bar/tick), command-polling, execution-reporting, and emergency-stop-
  state end-to-end — the full message surface required by Hard Rule 6.
- **Structural boundary test** (mirroring `ADR-023` §5's existing
  pattern): asserts no file under `evidence_engine/`,
  `market_intelligence/`, `strategy_engine/`, `risk_engine/`,
  `compliance_engine/`, `runtime/`, or `market_data_ingestion/` changed.
- **Manual demo-account test:** attach the EA with `TransportMode=Socket`
  on a demo chart; confirm heartbeat/account-state/bar-reporting/command-
  execution parity against the existing `TransportMode=Http` path
  side-by-side on the same account.
- **Regression:** full existing suite (`compileall`, `unittest
  discover`) stays green; every existing HTTP-path test continues passing
  unmodified — proves this is additive, not a rip-and-replace.

---

# 8. Rollback plan

- Because `BridgeConfig.socket_port` defaults to disabled and
  `TitanProtocolEA.mq5`'s `TransportMode` input defaults to `Http`,
  rollback for any single deployment is: leave (or revert) the chart
  input at `Http` — no Bridge redeploy required.
- The Bridge-side socket listener is deletable independently of the HTTP
  listener (a separate code path by design, per §5); reverting the
  commit(s) that add it is a clean revert with no HTTP-path change to
  undo.
- No data migration, no schema change, and no persisted-state format
  change is introduced by this ADR — there is no forward-only state to
  roll back. Rollback is purely a code/config revert.

---

# 9. Explicitly out of scope

- Any change to Evidence, Market Intelligence, Strategy, Risk,
  Compliance, Runtime Orchestrator, or Market Data Ingestion logic.
- Removing the existing HTTP transport (deferred, separate, separately-
  approved future change per §5.6).
- TLS/encryption-in-transit for the new socket substrate (available via
  `SocketTlsHandshake` if a future deployer wants it; not required to
  match `ADR-023`'s already-accepted localhost/LAN trust boundary).
- Any session/hours/trading-window EA input — unrelated to transport and
  already explicitly declined this session on architectural-authority
  grounds (`titan_protocol/runtime/profiles.py`'s `TradingWindow` is the
  canonical authority; the EA remains transport-and-execution-only).
- Deleting the HTTP transport code path (Amendment 1, Hard Rule 6).

---

# Sources consulted

- [`SocketCreate` — MQL5 Documentation](https://www.mql5.com/en/docs/network/socketcreate)
- [`SocketConnect` — MQL5 Documentation](https://www.mql5.com/en/docs/network/socketconnect)
- [`WebRequest` — MQL5 Documentation](https://www.mql5.com/en/docs/network/webrequest)
- [Network Functions — MQL5 Documentation](https://www.mql5.com/en/docs/network)
- [Working with sockets in MQL, or How to become a signal provider — MQL5 Articles](https://www.mql5.com/en/articles/2599)
- [Establishing and breaking a network socket connection — MQL5 Programming for Traders](https://www.mql5.com/en/book/advanced/network/network_socket_create_connect)
