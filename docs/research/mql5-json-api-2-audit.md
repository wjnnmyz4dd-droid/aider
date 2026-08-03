# Repository Research — 1 of 5: Gunther-Schulz/MQL5-JSON-API-2

Status: **Complete.** Per the Repository Research Protocol, this covers
exactly one repository. Do not proceed to repo #2 (darwinex/dwx-zeromq-connector)
without explicit approval.

No code was written or copied. This repo was cloned to a scratch
directory for direct source inspection only (not vendored into this
repository, not committed). GPLv3 applies to the original codebase;
the bundled `Include/json.mqh` ("JAson") is separately MIT-licensed —
noted for completeness, moot either way since nothing is being copied.

---

## 1. Complete audit

### 1.1 Architecture

- `Experts/JsonAPI.mq5` (959 lines) — the EA: socket bootstrap, `OnInit`/`OnTimer`/`OnDeinit`, the request dispatcher (`RequestHandler`).
- `Include/MQL5-JSON_API/Broker.mqh` (316 lines) — positions/orders read, `TradingModule` (order placement/modify/close), `OnTradeTransaction` hook.
- `Include/MQL5-JSON_API/HistoryInfo.mqh` (307 lines) — bar/tick history, pushed over the wire or written to CSV.
- `Include/MQL5-JSON_API/StartIndicator.mqh` (244 lines) — attaches arbitrary indicators via `iCustom()`, streams buffer values.
- `Include/MQL5-JSON_API/ChartControl.mqh` (145 lines) — **marked "EXPERIMENTAL — DO NOT USE" in its own header (line 7)**, yet compiled into the default build.
- `Include/json.mqh` (930 lines) — third-party JSON parser (MIT).
- `Include/controlerrors.mqh` (449 lines) — ~150 MQL5 error codes mapped to strings.
- `Include/StringToEnumInt.mqh` (382 lines) — brute-force string→enum resolver for wire-transmitted indicator params.
- `Indicators/JsonAPIIndicator.mq5` (619 lines) — a passive 30-buffer plotting indicator with no logic of its own.

**Control flow:** `OnInit` binds **7 ZeroMQ sockets** wildcard (`HOST="*"`), retrying twice with a 65s backoff. A **1-millisecond timer** (`EventSetMillisecondTimer(1)`) drives the entire event loop: stream price data, one non-blocking `recv`, dispatch through `RequestHandler`. `OnTradeTransaction` is a separate MT5-native hook (not polled) firing on every trade-server round trip.

**7 sockets, by type and purpose:**

| Socket | ZMQ type | Purpose |
|---|---|---|
| `sysSocket` | REP | Command channel — always replies literal `"OK"` before doing any work |
| `dataSocket` | PUSH | Command *results* — fire-and-forget, no correlation ID |
| `liveSocket` | PUSH | Autonomous candle/tick push |
| `streamSocket` | PUSH | Autonomous `OnTradeTransaction` push |
| `indicatorDataSocket` | PUSH | Attached-indicator values |
| `chartDataSocket` | PULL | Inbound plot values (the "experimental" feature) |
| `chartIndicatorDataSocket`/`SUB` | PUB/SUB | Internal relay to the plotting indicator, subscribed to the empty topic (no filtering) |

A single logical "send order → get confirmation" round trip touches **two different sockets** the client must correlate itself — there's no unifying envelope.

### 1.2 Communication

Transport is **ZeroMQ** via an external MQL5 binding (`dingmaotu/mql-zmq`) — not `WebRequest()`, not file-based. Flat JSON dict, no schema versioning:

```json
{"action": null, "actionType": null, "symbol": null, "chartTF": null,
 "fromDate": null, "toDate": null, "id": null, "magic": null,
 "volume": null, "price": null, "stoploss": null, "takeprofit": null, ...}
```

Dispatch is a string match on `action` (`CONFIG`/`ACCOUNT`/`BALANCE`/`HISTORY`/`TRADE`/`POSITIONS`/`ORDERS`/`RESET`), with `TRADE` sub-dispatching on `actionType` through 8-10 levels of nested `if/else`.

### 1.3 Security

**None.** Grepped the entire tree for `auth|token|api[_-]?key|password|secret|whitelist|hmac|signature|nonce` — zero hits. No TLS. All 7 sockets bind wildcard (`HOST="*"`). No range/type/business-rule validation on inbound fields beyond JSON parsing — validation is entirely delegated to MT5's own trade-server rejection codes. **The `"magic"` field exists in the schema but is never read** by `TradingModule` — every trade this bridge places carries MT5's default magic (0); the isolation the field implies does not exist. No replay/duplicate-command protection at all — a retried `TRADE` request is indistinguishable from a new one.

### 1.4 Error handling

Malformed JSON → custom error code, but the `"OK"` ack on `sysSocket` is sent **unconditionally, before validation** — a successful REQ/REP round trip means only "bytes arrived," never "your command is valid" or "your trade happened." **There is no fail-closed timeout on the EA side at all.** All socket ops are non-blocking; the EA never checks whether a client is even listening and will keep executing commands indefinitely if the Python side vanishes. The only liveness-detection burden is placed entirely on the client (`RCVTIMEO` in the Python example). MT5-server-side disconnection *is* handled (a one-time `DISCONNECTED` sentinel plus automatic resend of the last closed candle on reconnect) — but that's market-data connectivity, not Python-side liveness.

### 1.5 Performance

1ms busy-poll timer, fully non-blocking I/O, no batching (one ZMQ message per tick in the CSV-write path — the README itself admits "6-7 seconds to process 50000 M1 candles"), generous per-socket buffering (1000-message high-water mark) with no explicit backpressure handling beyond that.

### 1.6 Strengths

- Clean multi-channel separation at the protocol level (ack/result/market-data/trade-events on separate sockets avoids one common interleaving bug class).
- `OnTradeTransaction` mirrors MT5's *native* trade-transaction event independently of whatever the bridge's own execution code believes happened — a real defense-in-depth idea.
- Bind-retry-with-backoff engineered around a documented, real deployment failure mode (stale port hold after an ungraceful reload).
- Explicit, once-only `DISCONNECTED` sentinel + automatic re-send of last-known-good state on data-feed reconnect.
- Named retcode/error-code translation tables for client ergonomics.

### 1.7 Weaknesses

- No fail-closed behavior if the Python side dies — the single most serious gap relative to what an institutional system needs.
- The "OK" ack lies about success (sent before validation/execution).
- Magic-number isolation is decorative — promised by the schema, silently dropped in the implementation.
- Zero authentication, zero replay protection, wildcard bind.
- Fire-and-forget delivery for execution-critical confirmations — a lost confirmation for an executed trade is indistinguishable from one for a rejected trade.
- An "EXPERIMENTAL — DO NOT USE" module compiled into the default build path.
- Deeply nested if/else dispatch chains; a brute-force enum resolver that must be hand-extended for every new MT5 enum family.

### 1.8 Maintenance status

Last commit **2021-03-09** — over 5 years old as of today, abandoned. 77 commits, 15 GitHub stars. License: GPLv3 (original code), MIT (bundled `json.mqh` only).

---

## 2. KEEP / IMPROVE / REMOVE / IGNORE

| Item | Verdict | Why |
|---|---|---|
| HTTP + API-key transport (Phantom's existing design choice) | **KEEP** | Strictly safer than this repo's wildcard-bind, zero-auth socket model — validated by contrast, not just assumption |
| Validate-then-acknowledge command handling | **KEEP** | This repo's ack-before-validation is a real bug; Phantom's design must never regress toward it |
| Idempotent, server-issued command IDs | **KEEP** | This repo has no equivalent — a real gap in it, a real strength already decided for Phantom |
| Magic number as an actually-enforced isolation field, tested end-to-end | **KEEP** | Contrast case: a schema field that *looks* like a safety guarantee but isn't wired is worse than not having it at all |
| Fail-closed timeout when the counterpart goes silent | **KEEP** | This repo has none; it's a hard requirement for Phantom |
| Native trade-transaction mirroring as an independent cross-check | **IMPROVE** | Genuinely good idea — an EA-side hook reporting MT5's own trade-transaction event, correlated against (not trusted over) the EA's own execution report, as drift detection |
| Explicit "gap" sentinel + automatic resend of last-known-good state on data-feed reconnect | **IMPROVE** | Worth considering for bar/tick delivery — signal a data gap explicitly rather than silently resuming |
| Named platform-error → stable-string translation table | **IMPROVE** (low priority) | Ergonomic polish for error reporting, not core to correctness |
| Documented-root-cause retry/backoff on startup | **IMPROVE** (low priority, general pattern only) | The *pattern* (bounded retry, log why) is reusable; the specific port-hold failure mode is ZMQ/Wine-specific and doesn't transfer directly to an HTTP bridge |
| ZeroMQ multi-socket transport itself | **IGNORE** | Requires a compiled DLL binding loaded into the MT5 terminal — a real operational/security tradeoff already weighed and rejected in favor of `WebRequest()`, MQL5's native no-DLL HTTP primitive |
| Chart-plotting/indicator-relay feature (`ChartControl.mqh`, `JsonAPIIndicator.mq5`) | **IGNORE** | Visualization tooling, out of scope for a trading-decision bridge |
| CSV history export to the MT5 Files sandbox | **IGNORE** | Historical-bar loading is a data-pipeline responsibility, not a bridge responsibility |
| Ack-before-validation | **REMOVE** (anti-pattern, never adopt) | See §1.7 |
| Decorative/unenforced safety-looking fields | **REMOVE** (anti-pattern) | Any isolation/safety field must be provably wired end-to-end with a test, or removed |
| Wildcard bind with zero authentication | **REMOVE** (anti-pattern) | Not acceptable for a prop-firm system under any framing |
| No fail-closed timeout as a design default | **REMOVE** (anti-pattern) | The opposite of a hard requirement |
| Fire-and-forget delivery for execution-critical confirmations | **REMOVE** (anti-pattern) | Needs guaranteed-delivery semantics or a durable execution log, not a bare push |
| Shipping an "EXPERIMENTAL — DO NOT USE" module in the default build | **REMOVE** (anti-pattern) | Exactly the kind of scope-creep drift a minimal-change discipline exists to prevent |
| Deeply nested if/else dispatch chains | **REMOVE** (anti-pattern) | Hard to read, error-prone to extend |

---

## 3. Recommended architecture (provisional — for the EA↔Python communication component only)

This is a partial input to the eventual "PhantomBridgeEA.mq5" component of the
from-scratch redesign, informed by this one repository. It will be revisited
after darwinex/dwx-zeromq-connector (transport-model comparison) and the
MetaTrader 5 Standard Library audit (execution-primitive comparison) —
treat everything below as provisional, not final.

**Transport:** HTTP over `WebRequest()`, not a socket library — confirmed
again as the right call by direct contrast with this repo's un-authenticated,
wildcard-bound, DLL-dependent ZeroMQ model.

**Command lifecycle, in order:**
1. EA polls a single command endpoint.
2. Server validates the command fully (auth, schema, business rules)
   *before* responding — never acknowledge receipt as a proxy for validity.
3. Server issues a stable command ID at validation time; the EA reports
   execution result keyed by that same ID, so success/failure always
   correlates to the request that caused it — no orphaned pushes.
4. A parallel, independent channel — an EA-side hook mirroring what the
   MT5 trade server actually did — cross-checks the execution report
   against ground truth, without ever being treated as more authoritative
   than the validated command itself.
5. A single, explicit liveness/timeout mechanism, owned by the EA and by
   the server both, ends command execution the moment either side stops
   proving it's alive — no silent indefinite continuation.

**Isolation:** any field claiming to isolate this bridge's own orders
(magic number or equivalent) must be enforced at the point of order
placement and covered by a test asserting it — never merely present in a
schema.

### 4. Original Phantom implementation plan (conceptual — no code, no ADR)

This is a design-stage description of how the bridge's communication
concepts above would be built, once approved. It is not a plan document
in the RPI-workflow sense (no ADR exists or is being proposed here).

1. Define the full command/telemetry message vocabulary the bridge needs
   (heartbeat, account/tick/bar telemetry, command poll, execution
   report, error report, emergency stop) as an explicit, versioned
   contract — not a flat "do everything" dict like this repo's schema.
2. Design the validate-before-acknowledge rule as a structural invariant
   of the request-handling path (not an easy-to-forget convention) —
   e.g., the transport layer should make it structurally awkward to
   respond before validation completes.
3. Design the cross-check mirror (MT5-native trade-event vs. EA-reported
   execution) as an independent, additive verification step that can
   only ever flag a discrepancy, never override the validated result.
4. Design the liveness/timeout mechanism once, shared by both directions
   of the channel, rather than leaving it as a client-side-only
   responsibility.
5. Design the isolation-field enforcement (magic number or equivalent)
   with its own explicit test proving a foreign-magic order is never
   touched by this bridge.

Each of these becomes real, ADR-gated implementation only after you
approve the final architecture — this is groundwork, not a build plan.

### 5. Concepts worth carrying forward (consolidated)

1. Independent trade-transaction mirroring as a drift-detection cross-check.
2. Explicit "gap" sentinel + last-known-good resend on market-data reconnect.
3. Named platform-error → stable-string translation (ergonomic polish).
4. The general pattern of bounded, logged-reason retry on startup
   connectivity (not the specific ZMQ/Wine failure mode itself).

Everything else from this repository is either already correctly decided
against in Phantom's existing bridge design, or out of scope entirely
(see the IGNORE/REMOVE rows in §2).

---

## Next repository

Per the stated order, repository **2 of 5 — `darwinex/dwx-zeromq-connector`**
is next. **Waiting for your explicit approval before starting that research.**
