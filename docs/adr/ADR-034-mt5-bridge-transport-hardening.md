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

**Amendment 3 (2026-07-16 — "Root-Cause: Socket 4014 despite correct
whitelisting"):** a live deployment hit `SocketConnect` error `4014`
("address not in Tools→Options→Expert Advisors whitelist") after
whitelisting `http://127.0.0.1:8788`, `http://127.0.0.1`, and
`127.0.0.1:8788` — every reasonable variant of the address. This
session's research (MQL5 docs and forum threads via `mql5.com`) could
not establish, with the confidence this charter requires before
shipping a fix, the exact whitelist-entry format MT5 expects for
`Socket*` functions specifically (as opposed to `WebRequest()`, whose
format is well-documented) — official documentation is silent on this
point beyond "add the address," and community threads are inconsistent.
Guessing a fourth whitelist format and shipping it as "the fix" would
repeat the exact mistake this charter's §7 ("never guess") exists to
prevent. Per the originating request's own item 8, this amendment
instead makes the failure mode self-healing rather than requiring the
correct answer to a question this session cannot verify:

1. **Bridge dual-listens when `transport="socket"`.** `start.py` now
   binds *both* the socket listener (primary) and the HTTP listener
   (fallback) against the same `BridgeEngine`/`CommandQueue`/
   `ConnectionHealth` instance whenever `bridge.transport == "socket"`
   — both are already-thread-safe shared state (`ConnectionHealth`'s and
   `CommandQueue`'s own docstrings established this under concurrent
   HTTP-handler-thread access; a second listener thread is the same
   category of access, not a new one). This is a deliberate, narrow
   exception to Amendment 1's "never both at once" rule, scoped
   specifically to the fallback safety net — not a return to permanent
   dual-transport operation. When `transport == "http"`, behavior is
   unchanged (HTTP only; there is no lower fallback beneath the
   already-declared rollback value).
2. **The EA auto-detects and falls back.** `TitanProtocolEA.mq5` tries
   `Transport=Socket` (the shipped default) first; if
   `SocketConnect()`/`SocketCreate()` fail for `SocketFailoverAfterAttempts`
   consecutive reconnect attempts (new input, default `5`), it logs a
   clear, named Journal message and switches to HTTP for the remainder
   of the run, via a new runtime-only `g_effectiveTransport` variable
   (the `Transport` input itself is read-only at runtime in MQL5, so a
   separate variable is the only way to represent "started as Socket,
   now effectively HTTP" without reattaching). Because the Bridge is
   already listening on HTTP too (item 1), this fallback actually
   reaches it — a client-side-only fallback with no server-side listener
   would just trade one connection failure for another.
3. **Not a guarantee of zero errors.** HTTP's own `WebRequest()`/WinINet
   layer was independently proven earlier this session to have its own
   intermittent failure mode (`1001`/`1003`). This amendment guarantees
   the EA is never permanently stuck on a transport it cannot use — not
   that the fallback transport is itself failure-free. Both transports
   remain fully implemented, fully tested (Python-side), and this
   amendment does not change either one's internal behavior once
   connected.
4. **Explicitly out of scope, still.** No pipeline-stage engine, no
   message schema, no validation rule changes. `install.py`/
   `health_check.py` are updated only to verify/report both listeners
   when `transport == "socket"`, and to extend the existing `.set`-file
   drift check to `SocketHost`/`SocketPort` in addition to
   `MagicNumber`.

**Amendment 4 (2026-07-21 — "Corrective patch based on forensic
findings"):** a live deployment's MT5 Experts log showed every
`/bridge/heartbeat`, `/bridge/account`, `/bridge/positions` request
failing identically: `WebRequest()` returning `1001`, `GetLastError()`
`5203`, ~7000ms elapsed. A full forensic trace (this session, read-only,
no code changed until this amendment) found two separate, real defects,
neither a transport redesign:

1. **The EA's own status classification bucketed a WinINet transport
   pseudo-status as if it were a genuine HTTP response.**
   `HttpPost()`/`HttpGet()` treated any `WebRequest()` return `> 0` as
   "a real HTTP response, just not success," printing `"rejected, HTTP
   1001"` — but this Bridge only ever returns 100-599 (in practice
   200/400/401/404/500; `server.py`'s complete response table). A
   pseudo-status like `1001` is outside that range and is not something
   the Bridge could have sent. Worse, this misclassification skipped
   `PrintWebRequestWhitelistGuidance()` entirely (only called from the
   `status <= 0` branch), so the one `TITAN_DIAG BLOCKED` marker
   `diagnose_communication.py` depends on to tell "blocked before the
   Bridge" apart from "the Bridge responded" was never emitted for this
   exact signature — the diagnostic tool could still reach the right
   answer only via its conservative unmatched-fallback path, never with
   confidence. Fixed: `HttpPost()`/`HttpGet()` now classify strictly —
   100-599 is a genuine HTTP response (unchanged), `<= 0` is a
   `WebRequest()`-layer failure (unchanged, still `BLOCKED`), and a
   positive value outside 100-599 is now its own explicit, honestly-
   labeled transport-layer pseudo-status branch (`TITAN_DIAG
   NO_RESPONSE`, never worded "HTTP `<n>`" or "rejected" — this
   codebase's Amendment 3 §3 already anticipated `1001`/`1003` as HTTP's
   own known intermittent failure mode; this amendment makes the EA's
   own logging honest about which case it's in, not new behavior).
   `diagnose_communication.py` is extended with the same 100-599
   boundary so this signature classifies directly, as state 2, rather
   than falling through to the tool's uncertain default branch.
2. **Reverts Amendment 2's shipped default from `"socket"` back to
   `"http"`** on both `BridgeConfig.transport` and the EA's `Transport`
   input. The forensic trace could not rule out a socket-primary
   deployment's HTTP-fallback-listener bind failing silently (logged
   only as a warning, `start.py`'s dual-listen path) as a contributing
   factor, and HTTP is the better-understood, more broadly-compatible
   substrate to ship by default while that path receives further
   hardening. `"socket"` remains fully supported as an explicit opt-in —
   no code path, message schema, or validation rule from the base ADR
   or any prior amendment changes; only which value ships as the
   out-of-the-box default (the same category of change Amendment 2 made
   in the other direction). `mt5/TitanProtocolEA.set`'s `Transport` line
   remains deliberately omitted for the same `.set`-serialization-
   confidence reason Amendment 2 gave; the compiled default now carries
   `Http` instead. Amendment 3's dual-listen/auto-fallback safety net is
   unchanged in behavior — it still binds a second listener whenever
   `transport == "socket"` is chosen, and is simply inactive (as already
   documented) when `transport == "http"` is the primary, since HTTP is
   then already the only transport, not a fallback.

Neither part of this amendment touches a pipeline-stage engine, a
message schema, a validation rule, or the Bridge's route behavior.

**Amendment 5 (2026-07-21 — "HTTP poll-level backoff + runtime state-
machine fix"):** a live deployment reported the Amendment 4 fixes working
as designed (transport-pseudo-status failures now correctly classified
and logged) but the underlying instability continuing, visible as
continuous per-second `TITAN_DIAG ATTEMPT`/failure spam in the Experts
log ("looping"), and asked directly what Titan's own implementation got
wrong relative to the reference architectures it was modeled after. Two
distinct, real defects were found and fixed, neither a transport
redesign:

1. **`/bridge/commands/poll` had no backoff between polling cycles**,
   unlike `EnsureSocketConnected()`'s own reconnect backoff for the
   Socket transport. `HttpGet()`'s existing `MaxRetries`/`RetryDelayMs`
   bounds retries *within* one poll call, but `OnTimer()` called
   `PollAndExecuteCommands()` again every single tick (once per second)
   regardless of the previous cycle's outcome — a persistently failing
   poll therefore retried at full intensity forever. Fixed:
   `PollAndExecuteCommands()` now gates itself behind
   `IsPollCooldownElapsed()`, an exponential backoff (`PollBackoffBaseDelayMs`
   × 2^attempt, capped at `PollBackoffMaxDelayMs` — 500ms/1s/2s/4s/8s/15s,
   matching `EnsureSocketConnected()`'s own technique), reset immediately
   on the next successful poll. HTTP-only by construction
   (`g_effectiveTransport == TRANSPORT_HTTP`) — Socket's own reconnect
   backoff is untouched, and this amendment changes no Socket-path
   behavior. A skipped tick returns before even printing the `TITAN_DIAG
   ATTEMPT` line, which is what actually eliminates the per-tick spam;
   a real, failed poll attempt (already rate-limited by the backoff
   itself) logs once with `consecutivePollFailures`/`cooldownMs`/
   `nextPollAt`/`lastSuccessfulPollAt`.
2. **The deeper "why doesn't Titan ever trade" question** traced to a
   genuine runtime-state-machine gap, not the transport layer: a
   `TradeCommand` Compliance approves is enqueued into `CommandQueue`
   (`BridgeEngine.submit_command()`) independently of whether the EA
   ever successfully polls it. `CommandQueue.poll()` silently drops a
   pending command once it exceeds `BridgeConfig.command_ttl_seconds`
   (15s default) — the EA simply never receives it, with no signal back
   to Runtime. Before this fix, `InFlightCommandRegistry.has_unresolved()`
   had no way to distinguish "the EA is still working on this" from
   "this command already vanished, undelivered, 285 seconds ago" — both
   looked identical (an entry present, not yet resolved) — so the pair
   stayed blocked for the full in-flight `ttl_seconds` (300s, `deployment_windows/
   start.py`'s `_IN_FLIGHT_COMMAND_TTL_SECONDS`) regardless. Under a
   persistently flaky poll transport this reproduces indefinitely:
   submit, silently expire undelivered within 15s, wait out most of a
   5-minute window doing nothing, resubmit, repeat — Compliance keeps
   approving entries that never reach the market, with no error anywhere
   in the loop. Fixed: `BridgeEngine.command_delivered()` (new, mirrors
   `command_resolved()`) exposes `CommandQueue.is_delivered()`;
   `InFlightCommandRegistry` gained an optional `undelivered_grace_seconds`
   constructor parameter and an optional `is_delivered` parameter on
   `reconcile()` (both default to the prior behavior when omitted) — an
   entry that was never delivered and is older than that grace period
   (wired to `BridgeConfig.command_ttl_seconds` in `start.py`) is now
   dropped as abandoned immediately, freeing the pair for a fresh
   submission in ~15s instead of ~300s. A resolved entry (a real
   `ExecutionReport` arrived) always takes priority over this check —
   only a genuinely undelivered, expired command is treated as abandoned.
3. **A new diagnostic, `deployment_windows/verify_transport_configuration.py`**,
   answers "are the EA and Bridge actually running the same transport"
   from real evidence (never assumed): the Bridge's configured
   `bridge.transport`, the EA's own OnInit-resolved `Transport=` value,
   the Bridge's actual bound listener(s), a per-request tally of the
   EA's own `TITAN_DIAG ATTEMPT transport=` lines, and whether the EA's
   automatic Socket→HTTP fallback (Amendment 3) fired — reusing
   `diagnose_communication.py`'s own log-location/parsing helpers rather
   than a second, divergent implementation.

Comparison against the reference-repo research this session's audits
already captured (`docs/research/mql5-json-api-2-audit.md`,
`docs/research/dwx-zeromq-connector-audit.md`): the one lesson those
audits flagged as actually transferable — "bounded, logged-reason retry
on startup connectivity" — was already correctly implemented in this
codebase, but only on the Socket transport; item 1 above closes that gap
on the HTTP transport too. The reference repos' own reliability strategy
otherwise routes through a compiled DLL + ZeroMQ, a tradeoff already
evaluated and rejected for Titan Protocol on trust-boundary grounds
(unchanged by this amendment) — there was no transplantable fix to adopt
from there for either defect above.

Neither part of this amendment redesigns the transport protocol or
changes Bridge route behavior. Item 2 touches only
`titan_protocol/runtime/in_flight_commands.py` (additive, backward-
compatible parameters) and `titan_protocol/bridge/engine.py` (one new
passthrough method, same pattern as `command_resolved()`) — no pipeline-
stage engine, message schema, or validation rule changes.

**Amendment 6 (2026-07-21 — "Production-readiness review of Amendment 5's
undelivered-command abandonment"):** before Amendment 5's item 2 shipped
to production, a review raised two correctness requirements against it:
(1) the registry must never release a delivered command merely because
it aged out of tracking — the reservation must remain until execution/
rejection reconciliation, or a separate execution timeout; (2) the
delivery check and queue-expiry check must be race-safe — a `poll()`
landing at nearly the same moment as an abandonment decision must not
result in both a release and a live delivery for the same
`correlation_id`. Both were real, on inspection:

1. Amendment 5's `is_delivered`/`undelivered_grace_seconds` design
   composed two independently-timed reads — `InFlightCommandRegistry`'s
   own `age = now - entry.submitted_at` (using Runtime's own clock
   reading, captured once per live-cycle tick) and a separate call into
   `CommandQueue.is_delivered()` (guarded by `CommandQueue`'s own,
   different lock) — with no atomicity between them. Under a
   `correlation_ttl_seconds` configured shorter than this registry's own
   windows, `CommandQueue`'s retention purge could clear a genuinely
   delivered command's `_delivered_ids` entry, making a real delivery
   look like "never delivered" again. More fundamentally, even with
   default retention, a `poll()` call succeeding a fraction of a second
   after `InFlightCommandRegistry` had already committed to "abandoned"
   (based on its own, possibly slightly earlier, clock reading) could
   still deliver the command to the EA after Runtime had already freed
   the pair and potentially resubmitted a fresh command for it — a
   duplicate-command/duplicate-position risk (Phantom Protocol §2: "No
   duplicate trades. No uncontrolled pyramiding").
2. **Fixed by moving the entire delivered-or-abandoned decision into
   `CommandQueue` itself**, the only object that actually owns both
   facts, and making it a permanent, mutually-exclusive outcome rather
   than a transient read:
   - `CommandQueue.is_abandoned(correlation_id, now)` (new) is evaluated
     entirely under `CommandQueue`'s own single lock: a command already
     in `_delivered_ids` is never abandoned, regardless of age. One
     never delivered and already past `command_ttl_seconds` is marked
     into a new, permanent `_abandoned_ids` set and reported abandoned.
   - `poll()` now refuses to ever deliver a `correlation_id` already in
     `_abandoned_ids` — closing the residual race precisely: Runtime's
     live-cycle loop and the Bridge's request-handling threads each call
     their own clock independently (`deployment_windows/start.py`'s
     `_utc_now()`), so a `poll()` call could carry a `now` a fraction of
     a second "behind" the `now` a concurrent `is_abandoned()` call used
     — without this check, that poll() could still deliver a command
     Runtime had already released. With it, "delivered" and "abandoned"
     become permanent, mutually exclusive facts, decided by whichever of
     `poll()`/`is_abandoned()` acquires the lock first; the other,
     whenever it runs, observes that committed outcome and can never
     contradict it.
   - `BridgeEngine.command_delivered()` (Amendment 5) is removed —
     superseded by `BridgeEngine.command_abandoned(correlation_id, now)`,
     the sole passthrough `InFlightCommandRegistry.reconcile()` now uses.
   - `InFlightCommandRegistry.reconcile()`'s `is_delivered`/
     `undelivered_grace_seconds` parameters are replaced by a single
     `is_abandoned` callable; the registry no longer independently
     computes or duplicates any age/grace threshold of its own for this
     purpose (Phantom Protocol §1.4: "check for duplicate...filters") —
     `CommandQueue.is_abandoned()` is the sole source of truth.
   - Verified with a real multi-threaded test
     (`tests/titan_protocol/bridge/test_command_queue.py`'s
     `TestIsAbandonedConcurrencySafety`) that races a `poll()` call and
     an `is_abandoned()` call at deliberately disagreeing clock readings
     (one just under `command_ttl_seconds`, one just over) across 500
     iterations, asserting the two outcomes are never both true for the
     same `correlation_id`.

No transport redesign, no Bridge route behavior change, no pipeline-stage
engine touched.

**Amendment 7 (2026-07-21 — "Revert shipped default back to socket, field
evidence exhausted for HTTP"):** the operator's own live VPS, running the
Amendment 5/6 build, produced fresh Experts-log evidence
(`TITAN_DIAG NO_RESPONSE transport=HTTP method=POST endpoint=/bridge/
heartbeat pseudoStatus=1001 lastError=5203 elapsedMs=7016`, repeated
across `/bridge/heartbeat` and `/bridge/account`, `~7000ms` elapsed each
time) proving two things conclusively:

1. **The classification and abandonment fixes are working exactly as
   designed** — the log is now honest (`NO_RESPONSE`/`pseudoStatus=`,
   never "rejected, HTTP 1001"), confirming Amendments 4-6 shipped
   correctly.
2. **The underlying HTTP/WebRequest() instability is unresolved and, on
   this specific deployment, persistent rather than merely intermittent**
   — every observed heartbeat/account attempt failed the same way. Worse,
   the elapsed time (~7000ms) consistently exceeds `WebRequest()`'s own
   5000ms timeout parameter, indicating something below the MQL5
   application layer (WinINet itself, a system proxy, or AV/firewall
   interception) is holding the connection past the timeout MT5 asked
   for — a system-level symptom this codebase cannot fix from inside the
   EA or Bridge, and precisely the class of problem Option 3 (native
   socket transport, this ADR's own original recommendation, §4) was
   chosen specifically to route around.

Given persistent (not merely occasional) failure on the operator's actual
deployment, continuing to ship HTTP as the default is no longer
defensible caution — it is shipping a substrate already proven broken on
this machine as the out-of-the-box experience. **Both shipped defaults
revert to `"socket"`/`TRANSPORT_SOCKET`:**

- `BridgeConfig.transport` default: `"http"` → `"socket"`.
- `TitanProtocolEA.mq5`'s `Transport` input default:
  `TRANSPORT_HTTP` → `TRANSPORT_SOCKET`.
- `deployment_windows/config/titan_protocol_config.example.json`'s
  `bridge.transport` and its own note updated to match.
- `"http"`/`TRANSPORT_HTTP` remain fully supported as an explicit
  rollback — no code path, message schema, or validation rule changes,
  only which value ships as the out-of-the-box default (the same
  category of change as every prior transport-default amendment).

**Operational note, critical for applying this across an already-running
deployment:** `Transport` is a compiled MQL5 input — an already-attached
chart keeps whatever value it was attached with, regardless of what the
newly-compiled `.ex5`'s default says. Recompiling this file alone does
**not** change a currently-running EA instance's active transport. To
actually pick up this default on a live deployment: recompile
`TitanProtocolEA.mq5` (or load the refreshed `.set`/select `Transport=
Socket` explicitly in the Inputs tab), **fully close and reopen the MT5
terminal** (not merely reattach — a documented ADR-034 Amendment 3
finding that also applies here), then reattach the EA to **every** chart
it runs on. Restart the Bridge process separately to pick up
`bridge.transport`'s new default (or its own explicit override). Use
`deployment_windows/verify_transport_configuration.py` afterward against
the real logs to confirm the EA's OnInit-resolved transport, the Bridge's
configured transport, and the per-request `TITAN_DIAG ATTEMPT
transport=` tally all agree on Socket, with no fallback event —
"recompiled" is not the same claim as "confirmed running."

No transport redesign, no Bridge route behavior change, no pipeline-stage
engine touched.

**Amendment 8 (2026-07-21 — "Bounded timeout for the position-confirmation
wait"):** a live-deployment production-readiness review identified that
`InFlightCommandRegistry`'s post-resolution position-confirmation wait
(added to close the ExecutionReport-vs-PositionReport race, see this
ADR's own command-lifecycle hardening) had no upper bound — if
`/bridge/positions` reporting permanently stopped after a command
resolved, the pair would stay blocked forever even though the underlying
command is long since terminal (execution/rejection already happened;
only confirming the resulting position count was outstanding).

Fixed with a new, configurable `position_confirmation_timeout_seconds`
(`RuntimeConfig`, default 120.0 seconds — comfortably many multiples of
the EA's own telemetry cadence, `HeartbeatIntervalSeconds=5` by default,
so a normal momentary delay never trips it): once a pair has waited
longer than this bound, `InFlightCommandRegistry.
expire_stale_position_confirmations()` releases it outright, logs a
`logger.warning("position_confirmation_timeout_released", ...)` citing
the pair, correlation_id, and exact wait duration, and increments a
cumulative `position_confirmation_timeout_count()` counter surfaced in
`run_status`/`health_check.py` alongside the existing (instantaneous)
`awaiting_position_confirmation_count()`.

**Why this preserves, rather than weakens, capital preservation:**
releasing the pair only permits a *future* cycle to submit a fresh
command if every other gate (Strategy, Risk, Compliance) still approves
one — it does not itself submit, execute, or assume anything succeeded.
`ComplianceEngine`'s own `check_position_limits()` reads
`portfolio_state.positions_for_pair` from the Bridge's actual, live
`/bridge/positions` reports — entirely independent of this registry —
and still refuses a second position for a pair whose prior one is
genuinely still open, once positions reporting resumes at all. This
timeout only prevents *this registry* from becoming an unrecoverable,
permanent deadlock when telemetry alone has stalled; it never fabricates
a position count or bypasses the real guard against a duplicate
position.

Additive only: `InFlightCommandRegistry.__init__` gains one new parameter
with a default (`position_confirmation_timeout_seconds`), so every
existing caller is unaffected unless it opts into a different value via
`RuntimeConfig`/the JSON config's `runtime.position_confirmation_timeout_seconds`
key. `reconcile()`/`confirm_position_report()`'s existing signatures,
return values, and tested behavior are unchanged.

No transport change, no Bridge route behavior change, no pipeline-stage
engine touched.

**Amendment 9 (2026-07-21 — "Restart-safe persistence for unresolved
in-flight commands"):** the same review identified that `CommandQueue`
and `InFlightCommandRegistry` are entirely in-memory — a Bridge process
restart between "command delivered" and "reconciled" forgets the command
existed until the next positions snapshot arrives, risking a duplicate
submission for a pair whose prior command might still resolve into a
real position at the broker.

Fixed with a new, lightweight `titan_protocol.runtime.in_flight_store`
module (`InFlightCommandStore`/`InFlightStoreConfig`), reusing the same
atomic-write technique already proven by
`titan_protocol.compliance_state_store.store.ComplianceStateStore`
(temp file + `fsync` + `os.replace`, `.bak` rotation before every
overwrite):

- Persists only the four minimal fields
  `InFlightCommandRegistry.snapshot_for_persistence()` exposes —
  correlation_id, pair, state (`"in_flight"` or
  `"awaiting_position_confirmation"`), and the entry's *original*
  timestamp — deliberately never the original `TradeCommand`.
  `CommandQueue` itself remains unpersisted; a restored entry can
  therefore only ever be released by its own TTL/timeout, never by a
  late-arriving `ExecutionReport` for a correlation_id the fresh
  `CommandQueue` has no memory of. This is a scope limit chosen to keep
  persistence lightweight (no database, no second source of truth for
  command content), not an oversight — see the accepted, documented
  limitation below.
- On Bridge startup, `InFlightCommandRegistry.restore(entries, now)`
  reinserts each entry using its *original* timestamp (never restart
  time), so its existing TTL/position-confirmation-timeout window keeps
  counting from when it actually happened rather than resetting on every
  restart. An entry already past its own TTL/timeout as of restart time
  is skipped entirely. Restoring never submits, executes, or resolves
  anything itself — it only re-establishes `has_unresolved()`/
  `is_awaiting_position_confirmation()` returning `True` for whatever was
  still open at shutdown, which is what prevents the duplicate
  submission; the ordinary `reconcile()`/`confirm_position_report()`/
  `expire_stale_position_confirmations()` cycle machinery (entirely
  unmodified by this amendment) takes over from there.
- The full current snapshot is saved once per live cycle, always
  overwriting rather than patching, immediately after that cycle's
  `reconcile()`/`confirm_position_report()`/
  `expire_stale_position_confirmations()` calls — a pair any of those
  already dropped this cycle (resolved-and-confirmed, abandoned, or
  timed out) is structurally absent from the very next save, so
  persistence can never resurrect an abandoned or already-terminal
  command.
- Corruption is handled fail-safe, not fail-closed, unlike
  `ComplianceStateStore`: a missing, corrupted, or schema-mismatched
  state file (and an equally unusable `.bak`) makes `load()` return an
  empty tuple rather than raising. Losing this best-effort bookkeeping
  for one restart only returns that restart to today's pre-hardening
  behavior for whatever was mid-flight at the crash instant — never a
  refusal to start the Bridge — and `ComplianceEngine`'s own independent
  live position-limit check (unaffected by this file's state) remains
  the actual duplicate-position guard regardless.

**Accepted, documented limitation:** a command genuinely delivered before
a restart, whose `ExecutionReport` only arrives after the restart, cannot
be recorded by the restarted `CommandQueue` (which never enqueued it) —
`handle_execution_report()` correctly returns `False` for it, exactly as
it would for any unknown correlation_id. The pair stays protected by its
own (restart-surviving) TTL until that elapses, rather than by ever
truly resolving the stale command. Persisting the full `TradeCommand` to
close this residual gap was deliberately rejected as disproportionate to
the risk it would close, given `ComplianceEngine`'s independent guard
already covers the actual duplicate-position outcome once
`/bridge/positions` reporting resumes post-restart.

Additive only: `deployment_windows/start.py` gains one new constructed
object (`InFlightCommandStore`) and threads it through
`_live_cycle_loop()`'s existing parameter list (the same pattern
`compliance_state_store` already uses); no existing function signature's
*behavior* changes for a caller that does not construct/pass this new
argument (every call site in this codebase does, since restart-safety is
enabled unconditionally, matching this amendment's charter mandate).

No transport change, no Bridge route behavior change, no pipeline-stage
engine touched.

**Amendment 10 (2026-07-22 — "Remove native socket transport entirely;
HTTP-only"):** at the operator's explicit direction, after this exact
deployment's own field evidence — collected during this same session,
methodically, after Amendment 7 shipped socket as the default — showed
`SocketConnect()` persistently failing with `GetLastError=4014` despite a
confirmed-correct allow-list entry and full terminal restarts (root cause
never conclusively established; see Amendment 3's own admission that
MQL5's `Socket*()` whitelist-entry format could not be confirmed with
confidence), the operator asked to roll back to `Transport=Http` as a
diagnostic step. The resulting Experts log showed HTTP failing
**identically** to the pre-Amendment-7 evidence that originally justified
socket becoming the default: `pseudoStatus=1001`/`5203`, elapsed time
(~7000ms) exceeding `WebRequest()`'s own 5000ms timeout parameter — a
WinINet-layer problem, unchanged since Amendment 4, and demonstrably still
present on this VPS.

Presented with both transports independently failing on this specific
deployment, the operator was given three options — keep Socket and keep
diagnosing the 4014 root cause; remove Socket and go HTTP-only anyway,
modeled on the original Phantom architecture (a Flask REST API reached
over plain `WebRequest()`); or implement HTTP-only but keep it dormant
behind a flag — and explicitly chose the second: **remove native socket
transport completely, standardize on HTTP.** This is recorded here
because it is an operational/organizational decision made with full
knowledge of the WinINet evidence above, not a claim that this amendment
fixes the underlying WinINet failure — it does not, and cannot; the
WinINet-layer issue is a property of this VPS/terminal's environment, not
of Titan Protocol's own code. Continuing to operate with HTTP as the sole
transport on a VPS with this history is the operator's own accepted risk;
if the WinINet issue is later diagnosed and resolved (e.g. proxy
configuration, corrupted WinINet cache, a Windows update), HTTP should
work reliably again, at which point this amendment's removal of the
socket fallback becomes purely a maintenance-surface win rather than a
availability tradeoff.

**What was removed, in full:**
- `titan_protocol/bridge/socket_transport.py` (the entire native-socket
  server module: `_BridgeSocketHandler`, `_BridgeSocketServer`,
  `serve_socket()`, the length-prefixed JSON frame protocol, the
  route-to-HTTP-path mapping, per-connection strictly-increasing `seq`
  replay guard) — deleted entirely, not deprecated in place.
- `BridgeConfig.transport`, `VALID_TRANSPORTS`, `socket_port`,
  `socket_max_message_bytes`, `socket_idle_timeout_seconds`,
  `socket_max_connections`, and the `__post_init__` transport validation
  — removed from `titan_protocol/bridge/config.py`. `BridgeConfig` no
  longer has a concept of "which transport" — there is only ever one.
- `BridgeMetrics`'s ten `socket_*` counters and `socket_health_snapshot()`
  — removed from `titan_protocol/bridge/metrics.py`; the general
  (non-socket-specific) counters are untouched.
- `server.py`'s socket-frame-only rejection labels
  (`invalid_json_frame`, `missing_or_invalid_seq`,
  `missing_or_invalid_route`, `missing_or_invalid_body`,
  `duplicate_or_replayed_seq`) — removed from `_REJECTION_LABELS`; these
  strings were only ever produced by the now-deleted socket handler.
- `TitanProtocolEA.mq5`'s entire socket-transport section: the
  `ENUM_TRANSPORT_MODE` enum and `Transport` input, all `Socket*`-prefixed
  inputs (`SocketHost`, `SocketPort`, `SocketConnectTimeoutMs`,
  `SocketReadTimeoutMs`, `SocketReconnectBaseDelayMs`,
  `SocketReconnectMaxDelayMs`, `SocketMaxMessageBytes`,
  `SocketFailoverAfterAttempts`), the runtime-fallback globals
  (`g_effectiveTransport`, `g_hasFallenBackToHttp`, `g_socket`,
  `g_socketSeq`, `g_lastConnectAttemptAt`, `g_reconnectAttempt`), and
  every socket-transport function (`LogSocketDiagnostics()`,
  `CheckSocketFailoverThreshold()`, `EnsureSocketConnected()`,
  `SocketSendFrame()`, `SocketReadExact()`, `SocketReadFrame()`,
  `SocketRequest()`) — `BridgeRequest()`/`BridgePollCommands()` are now
  thin, HTTP-only wrappers. `PollAndExecuteCommands()`'s HTTP poll-backoff
  cooldown (Amendment 5) is now unconditional, since HTTP is the only
  transport it could ever have gated.
- `deployment_windows/start.py`'s Amendment-3 dual-listen logic (socket
  primary + HTTP fallback listener) — collapsed to a single
  `bridge_serve()` call; the `bridge_transport`/`bridge_socket`/
  `http_fallback_active` health-snapshot fields are gone from
  `health.json`'s `run_status`/top-level payload.
- `deployment_windows/config_loader.py`'s `bridge.transport`/`socket_*`
  JSON config keys, `install.py`'s `SocketHost`/`SocketPort` `.set`-file
  personalization and its HTTP-fallback-listener verification step,
  `install_mt5_files.py`'s `SocketHost`/`SocketPort` from
  `_PERSONALIZABLE_KEYS`, and `health_check.py`'s per-transport
  reachability branching (now a single `bridge reachable (http)` check).
- `deployment_windows/verify_transport_configuration.py` and its test —
  deleted outright; this tool existed solely to diagnose a socket-vs-HTTP
  transport mismatch between the EA and the Bridge, a condition that
  cannot occur once only one transport exists.
- `diagnose_communication.py`'s socket-frame log parsing
  (`_SOCKET_LOG_LINE_RE`, `_parse_bridge_rotating_log()`, the rotating-log
  discovery step) and the `Socket`-branch of its event-matching
  functions — the classifier is now HTTP-only; its EA-route-label-to-
  HTTP-path mapping (previously imported from `socket_transport.py`) is
  now defined locally since that module no longer exists.

**What was explicitly preserved, unchanged:** every reliability
improvement built on top of the transport layer, none of which cared
which transport carried the bytes — HTTP poll-level exponential backoff
(`PollBackoffBaseDelayMs`/`PollBackoffMaxDelayMs`,
`IsPollCooldownElapsed()`), the atomic Delivered-vs-Abandoned in-flight
command lifecycle, `InFlightCommandRegistry`'s position-confirmation
timeout (Amendment 8) and restart-safe persistence (Amendment 9), replay
protection at the command-queue level, health monitoring, and every
`describe_rejection()`-driven diagnostic that isn't socket-specific.
Trading logic, Compliance Engine, AI/research packages, command
lifecycle semantics, and risk management are untouched by this amendment
— it is strictly a transport-layer simplification.

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
