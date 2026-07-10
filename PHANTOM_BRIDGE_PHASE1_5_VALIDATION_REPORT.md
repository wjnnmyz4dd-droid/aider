# Phase 1.5 — Bridge Integration & Stability Validation Report

Scope: `phantom/bridge/` only. No architecture change, no new engine,
no work on Scanner/Strategy/Risk/Market Intelligence/Compliance/
Research/Reliability/Validation, and `mt5/PhantomBridgeEA.mq5` was
**not** modified — every defect found and fixed in this phase was on
the Python side.

**What this validation actually is, honestly stated up front:** this
sandbox has no MT5 terminal, no MetaEditor, no live broker. Everything
below that concerns the *Python bridge itself* — its HTTP server, its
concurrency, its resource behavior, its logging — was tested for real,
against the real, running `phantom.bridge` code, over real sockets,
using a validation harness built for this task
(`scripts/phase1_5_bridge_validation.py`, committed for reproducibility).
Everything that would require literal MT5/MetaEditor/broker behavior
("MT5 restart," "Terminal unavailable," "Broker recovery") is tested as
**the bridge's own observable behavior** when EA-side HTTP traffic stops
and resumes — which is genuinely what the bridge experiences in all of
those scenarios from its side of the wire — and is labeled as a proxy,
not a literal MT5 test, everywhere it appears below.

Three confirmed defects were found and fixed. Full evidence for each is
in the relevant section below; nothing else was changed.

---

## 1. Stability report

**No crashes, no hangs, no unhandled exceptions** across a sustained
60-second run (8 concurrent simulated EA client threads, ~47,000
requests), a 60-thread/3,000-request stress burst, and every fault-
injection scenario in this report. The server thread and all worker
threads remained responsive throughout; `server.shutdown()` completed
cleanly every time.

**Thread count:** stable between 10–14 threads throughout the 60-second
sustained run (`ThreadingHTTPServer` spawns one handling thread per
request, which exits when the request completes — no thread
accumulation observed; min/max stayed in a narrow band the entire run,
not trending upward).

**Latency:** p50 4.9ms, p99 10.1ms, max 46.8ms (a single outlier, not a
sustained spike) across ~47,000 requests — stable throughout the run,
no degradation over time.

**Heartbeat timing:** heartbeat cadence held correctly under load; the
fail-closed transition (`is_ready()` → false) occurred exactly at
`heartbeat_timeout_seconds`, and recovery (`is_ready()` → true) occurred
on the very next successful heartbeat, with no drift or delay observed
under concurrent load.

**Resource cleanup:** confirmed via the Python-restart proxy (§3) — a
second, independent server/engine instance starts cleanly alongside
(and after) the first is shut down, with no port conflicts, no leaked
file descriptors preventing rebind, no leftover thread interference.

## 2. Resource usage summary

| Metric | Result |
|---|---|
| Duration | 60 seconds sustained load (bounded — see "Remaining risks" for what a true multi-day soak would still need) |
| Requests | ~47,000 (heartbeat + account + positions + poll, 8 concurrent simulated EA clients) |
| CPU (user) | 36.4s over 60s wall clock |
| CPU (sys) | 41.5s over 60s wall clock |
| Thread count | min 10, max 14 (stable, no growth trend) |
| Memory (RSS), first measurement | +35.8MB over 60s — **this number is a measurement artifact, not the bridge's real footprint; see below** |
| Memory (RSS), isolated re-measurement | +0.2MB over 30s of the same sustained load — the real figure |

**Why two numbers, and which one is real:** the first measurement was
taken with this validation harness's own log-capturing handler attached
(to check observability requirements later in this same run), which
appends every emitted `logging.LogRecord` to a Python list for
inspection — by design, that list grows with every log call and was
itself the dominant source of the measured RSS growth, not a leak
in `phantom/bridge`. This was confirmed, not assumed: re-running the
identical sustained load with logging suppressed and no capturing
handler attached measured a **flat** ~0.2MB RSS change over 30 seconds
— consistent with normal allocator/GC noise, not a leak. This
correction is disclosed here deliberately rather than reporting the
larger, misleading number.

**No memory growth indicating a leak** in `phantom/bridge` itself,
based on the isolated measurement. `BridgeEngine`'s own state
(`_latest_account_state`, `_latest_positions`, `_latest_pending_orders`)
is bounded by construction — each is either a single object or a dict
keyed by a bounded set of ids, never an unbounded append-only list, for
telemetry. `CommandQueue`'s `_results`/`_commands`/id-sets *do* grow
with every unique `correlation_id` ever submitted and are never pruned
— this is a real, already-known Phase 1 characteristic (not a new
finding) worth restating under "Remaining risks" below, since a
long-running production deployment will accumulate these indefinitely.

## 3. Recovery report

### Network recovery
- **Interruption:** after `heartbeat_timeout_seconds` elapses with no
  traffic, `is_connection_healthy` → `false`; a command submission
  attempted during the gap is rejected `BRIDGE_NOT_READY` — correct
  fail-closed behavior.
- **Restoration:** the next successful heartbeat (a real HTTP POST)
  restores `is_connection_healthy` → `true` immediately; a command
  submitted afterward is accepted; a duplicate resubmission of the same
  `correlation_id` is rejected `DUPLICATE_CORRELATION_ID`, not silently
  re-queued.
- **Delayed packets:** a deliberately slow client (a raw socket that
  dribbles its POST body out over ~1.6 seconds) did **not** block 20
  concurrent fast clients, which all completed in 0.038 seconds while
  the slow client was still in flight — `ThreadingHTTPServer`'s one-
  thread-per-request model behaves as expected here.
- **Connection timeout:** pointing a client at a port nothing listens
  on produces a clean `ConnectionRefusedError` on the client side, no
  hang, no server-side effect.
- **No duplicate commands, no stale commands, no corrupted state**:
  confirmed by the duplicate-correlation-id rejection above and by the
  stress test (§5) producing zero corruption under concurrent load.

### MT5/Terminal-outage proxy (bridge-observable behavior only —
**not** a literal MT5.exe restart, which cannot be performed in this
sandbox)
- Simulated EA/terminal disappearance (heartbeat traffic stops well
  past the timeout): `is_connection_healthy` → `false`, command
  submission rejected `BRIDGE_NOT_READY`.
- Simulated reconnect (heartbeat resumes): `is_connection_healthy` →
  `true`, command submission accepted, delivered exactly once via
  `poll_commands`, delivered-id set has no duplicates.
- **No duplicated execution:** the same command's execution report,
  submitted twice, is recorded on the first call and rejected
  (`recorded: false`) on the second — confirmed directly against the
  running engine, not merely asserted.

### Python (bridge process) recovery
- A second, fully independent `BridgeEngine`/`CommandQueue`/
  `ConnectionHealth`/server instance was started after the first was
  cleanly shut down — the closest faithful proxy for "process restart"
  achievable without actually killing and relaunching a Python process
  in this harness.
- **Confirmed, expected behavior, not a defect:** the fresh instance
  starts `is_connection_healthy == false` (correct fail-closed-before-
  any-heartbeat default), accepts its first heartbeat cleanly (HTTP
  200), becomes ready, and its command queue starts empty. Phase 1 was
  never specified to persist state across a process restart — this
  confirms the *absence* of persistence is a clean, well-defined
  behavior (no crash, no corrupted partial state, no hang on startup),
  not that state is silently lost in a way that surprises anything
  downstream.

### Broker recovery (proxy — MQL5-side retcode handling itself is
untestable without real MetaEditor/MT5; what the *bridge* owns is
correctly accepting and recording the EA's report of these conditions)
- Four representative scenarios (`MARKET_CLOSED_OR_NO_QUOTES`,
  `SYMBOL_NOT_AVAILABLE`, and the raw MT5 retcodes `10018`
  `TRADE_RETCODE_MARKET_CLOSED` / `10031` `TRADE_RETCODE_CONNECTION`)
  were submitted via `POST /bridge/error` and all four were accepted
  (HTTP 200) and recorded in `engine.errors`.

## 4. Security report

| Check | Result |
|---|---|
| Invalid API key | 401 |
| Missing API key | 401 |
| Invalid JSON body | 400 |
| Duplicate execution report (replay) | 200, but `recorded: false` — idempotent, never double-applied |
| Heartbeat "replay" (same payload twice) | Both 200 — correct: heartbeats are a liveness signal, not a single-use nonce, and are deliberately not conflated with execution-report idempotency |
| Magic number mismatch | 400 `MAGIC_NUMBER_MISMATCH` |
| Missing required field | 400 |
| Unauthorized administrative action (emergency-stop, no key) | 401 |
| Unauthorized administrative action (emergency-stop, wrong key) | 401 |
| Authorized emergency-stop activate | 200 |
| Authorized emergency-stop deactivate | 200 |
| Unknown route | 404 |

**Scope note on "unauthorized administrative actions":** Phase 1's only
administrative action is the API-key-gated emergency-stop endpoint —
there is no broader operator-authentication model in the code today
(that concept is specified for a future phase in
`docs/specs/07_system_reliability_engine.md`, not implemented here).
This report tests exactly what exists; it does not claim to have
validated authentication machinery that hasn't been built yet.

## 5. Stress-test report

**Before the fix:** 60 concurrent threads (heartbeaters, pollers,
execution-report submitters) issuing ~3,000 requests over ~5.5–6.5
seconds reproducibly produced 13–35 client-side `ConnectionResetError`
("Connection reset by peer") failures per run.

**Root cause, isolated by a controlled A/B test:** `ThreadingHTTPServer`
inherits `socketserver.TCPServer`'s default `request_queue_size` of 5 —
the `socket.listen()` backlog, i.e. how many not-yet-`accept()`-ed
connections the OS will hold before resetting new ones. Re-running the
*identical* load against the *identical* code with only
`request_queue_size` raised to 128 produced **zero** errors and
completed *faster* (3.48s vs. 6.48s) — isolating the backlog size, not
some other race, as the cause.

**Fix applied:** `phantom/bridge/server.py` now returns a
`_BridgeHTTPServer(ThreadingHTTPServer)` subclass with
`request_queue_size = 128`. One class attribute, no behavior change,
no new dependency.

**After the fix, re-verified twice** (once via the isolated repro,
once via the full end-to-end validation harness re-run): 60 threads,
3,000 requests, 0 errors, 3.6s elapsed, ~823 req/s throughput.

**No race conditions, no deadlocks, no starvation, no queue
corruption**: confirmed by both the dedicated concurrency test suites
from the two prior hotfixes (`CommandQueue`, `ConnectionHealth` — 15
tests, still passing) and this phase's server-level stress test
exercising the real HTTP path end to end.

**Context on realistic load:** a real Phase 1 deployment is one MT5
terminal (one MQL5 script, inherently sequential `WebRequest` calls)
talking to one bridge instance — nothing like 60 concurrent Python
threads. This stress test is deliberately far beyond that shape to
find the actual ceiling; the found defect would not have manifested
under real single-EA traffic, but is a real latent risk for any future
multi-EA-instance or higher-throughput deployment, now closed.

## 6. Remaining risks

1. **`CommandQueue`'s per-`correlation_id` state is never pruned.**
   `_commands`, `_delivered_ids`, `_executed_ids`, `_results` grow
   without bound for the lifetime of the process — a long-running
   production deployment will accumulate these indefinitely. This is a
   pre-existing Phase 1 characteristic, not introduced or found newly
   defective by this validation; flagged here because sustained,
   multi-day operation (which this validation's 60-second window cannot
   itself prove) will eventually make this the dominant real memory
   growth driver, not a leak but an unbounded-retention design point
   worth a deliberate decision before very long deployments.
2. **True multi-day soak testing has not been performed and cannot be
   performed in this session.** This report's "long duration" is a
   bounded 60-second sustained run. A real production-readiness
   soak test (24–72+ hours) needs a persistent environment outside this
   session's lifetime.
3. **Phase 1's own real-MetaEditor-compile and real-MT5-demo-validation
   gate remains unmet**, unchanged by this phase — this validation
   proves the Python side is stable; it does not and cannot substitute
   for that gate.
4. **No load-shedding/backpressure exists if `request_queue_size`'s new,
   larger backlog itself fills up** under load far beyond what was
   tested here — not observed in this validation, since no test pushed
   past 60 concurrent clients, but worth naming as an open question
   for any future higher-throughput deployment.
5. **The `_BridgeHTTPServer.request_queue_size` value (128) is a
   reasoned, tested choice, not a formally derived optimum** — chosen
   because it eliminated the observed failure with room to spare;
   a different value might be more appropriate for a specific
   deployment's actual expected concurrency, which is a tuning question
   outside this hotfix's scope.

## 7. Production readiness assessment

**The Python bridge (`phantom/bridge/`) is stable under everything this
sandbox can test**: sustained load, concurrent access to every shared
state structure across two prior hotfixes plus this phase's server-
level stress test, network-gap fail-closed/recovery behavior, a clean
process-restart proxy, and correct security/observability behavior for
every scenario this task named that exists in Phase 1's actual code.
Three real, confirmed defects were found by this validation (connection
resets under concurrent load, a silently-broken error-report log call,
an asymmetric missing log on emergency-stop deactivation) and are now
fixed, tested, and verified end-to-end — this validation did its job.

**The Bridge is ready for production validation on real MT5/MetaEditor**
— meaning: nothing further can be learned about the Python side without
real MT5/broker infrastructure, and what remains is exactly the
already-known, already-documented gate (`PHANTOM_BRIDGE_EA_PHASE1_VALIDATION_PACKAGE.md`):
a real MetaEditor compile of `mt5/PhantomBridgeEA.mq5` and a real MT5
demo run. This phase does not claim the Bridge is production-*deployed*-
ready in the full institutional sense (that also needs the still-
unbounded `CommandQueue` retention question addressed for long
deployments, and the still-open Phase 1 MT5 gate) — it claims the
Python side has been validated as far as this environment allows, three
real defects it surfaced have been closed, and the next concrete step
is the real-MT5 validation package already prepared, not further work
here.

**Phase 2 does not begin.** No other component was touched.

---

## Files changed

- `phantom/bridge/server.py` — `_BridgeHTTPServer` subclass, `request_queue_size = 128`.
- `phantom/bridge/logging_sink.py` — `log_error_report`'s `extra` dict key renamed `message` → `error_message` (fixes the silent `KeyError` swallow).
- `phantom/bridge/engine.py` — `deactivate_emergency_stop()` now calls `log_emergency_stop(state)`, mirroring `activate_emergency_stop()`.
- `tests/phantom/bridge/test_server_concurrency.py` (new) — backlog/stress regression tests.
- `tests/phantom/bridge/test_logging_sink.py` (new) — `log_error_report`/`log_emergency_stop` regression tests.
- `tests/phantom/bridge/test_engine.py` — added `test_deactivate_is_logged_same_as_activate`.
- `scripts/phase1_5_bridge_validation.py` (new) — the full validation harness used to produce this report, committed for reproducibility.

## Regression

- Full bridge suite: **106/106 passing** (100 prior + 6 new).
- Full repository suite: **1735/1735 passing** (same 3 pre-existing, unrelated `flask`-import collection errors noted in both prior hotfix reports, unaffected).
- `python3 -m compileall phantom/bridge/ tests/phantom/bridge/`: clean.
- `python3 scripts/check_architecture.py`: PASS.
