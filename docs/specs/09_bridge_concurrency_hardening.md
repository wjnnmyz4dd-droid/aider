# Specification Revision — PhantomBridgeEA (Bridge) Concurrency Hardening

Specification only. **`mt5/PhantomBridgeEA.mq5` and every file under
`phantom/bridge/` remain unmodified by this task** — this document
specifies the requirement so that an explicitly-authorized, separate
future change can implement it against Phase 1's already-built,
already-frozen code. Closes Red Team Audit Finding 5.1 (Critical) and
Finding 5.2 (Medium).

## 1. What was found (restated from the audit, not re-derived)

`phantom/bridge/server.py` serves every HTTP route through
`http.server.ThreadingHTTPServer` (confirmed at the line that
constructs it), which spawns one thread per connection.
`phantom/bridge/command_queue.py`'s `CommandQueue` holds `_commands`,
`_pending_order`, `_delivered_ids`, `_executed_ids`, and `_results` as
plain, unsynchronized `dict`/`list`/`set` attributes, mutated directly
by `enqueue`, `poll`, and `record_result` with no lock anywhere in the
file, `engine.py`, or `connection_health.py`.

## 2. Required properties (this task's explicit requirements, mapped
to the actual file each applies to)

| Requirement | Applies to |
|---|---|
| Thread-safe command queue | `CommandQueue._commands` / `_pending_order` (`enqueue`, `poll`) |
| Thread-safe pending commands | `CommandQueue._pending_order` (same as above — one structure, restated because it is touched by both `enqueue` and `poll` from different request threads) |
| Thread-safe execution reports | `CommandQueue._results` / `_executed_ids` (`record_result`, `result_for`, `all_results`) |
| Thread-safe heartbeat tracking | `ConnectionHealth`'s `_last_heartbeat_at` (`record_heartbeat`, `is_ready`, `is_fail_closed`) — not flagged by the audit's grep, added here for completeness since it is the same class of unsynchronized shared state under the same `ThreadingHTTPServer` |
| Thread-safe result cache | `CommandQueue._results` (same structure as "execution reports" above — one requirement, not two) |

**No shared mutable state without synchronization** — the rule applies
to every attribute listed above, not a subset.

## 3. Specified fix (for the future authorized change, not applied here)

- One `threading.Lock` (or `RLock`, if any method needs to call another
  locked method internally) added to `CommandQueue`, held for the
  duration of each public method's body (`enqueue`, `poll`,
  `record_result`, `command_for`, `result_for`, `is_delivered`,
  `is_executed`, `all_results`).
- The same treatment for `ConnectionHealth`'s single piece of mutable
  state (`_last_heartbeat_at`).
- No change to any method's external behavior or return type — this is
  a synchronization-only fix, not a logic change, and must be
  verifiable as such by a diff review before it is applied.

## 4. Required concurrency tests (to accompany the future fix)

- **Concurrent-poll-and-report stress test:** many threads calling
  `poll()` and `record_result()` against the same `CommandQueue`
  simultaneously, for a large number of iterations; assert zero
  exceptions (specifically, no `RuntimeError` from concurrent
  dict/set mutation during iteration) and that the final state
  (`all_results()`'s contents) matches exactly what a single-threaded
  run with the same inputs would produce.
- **Idempotency-under-concurrency test:** two threads calling
  `enqueue()` with the *same* `correlation_id` at (as close to)
  the same instant as the test harness can arrange; assert exactly one
  succeeds and the other receives `DUPLICATE_CORRELATION_ID` — never
  both succeeding, never both failing.
- **Heartbeat-under-load test:** `record_heartbeat()` called
  concurrently with `is_fail_closed()`/`is_ready()` reads from other
  threads; assert reads never observe a torn/partial write.
- **No-deadlock test:** a stress run exercising every public method
  concurrently for a fixed duration completes within a bounded time
  budget (proving the lock never self-deadlocks via an uncontrolled
  re-entrant call).
- **Regression test:** the full existing 85-test Phase 1 suite
  (`tests/phantom/bridge/`) must still pass unchanged after the fix —
  proving the synchronization-only nature of the change.

## 5. Why this is the *only* concurrency-hardening item, architecturally

Every component from Evidence Engine through System Reliability Engine
(components 2–8) is now called exclusively by
`phantom/runtime/runtime.py` (`docs/specs/00_runtime_orchestrator.md`),
which is specified as a strictly serial, single-threaded caller with no
concurrency primitives of its own (§9 of that spec). None of those 8
components' own internal state needs to be thread-safe *because of
Runtime's existence* — this was Finding 5.2's concern, and it is closed
by Runtime's specification rather than by adding locks to eight
separate components.

`phantom/bridge/` is the one exception, and remains one, because it
independently serves the MT5 EA's own asynchronous HTTP traffic
(heartbeats, polls, execution reports arriving on the EA's own timer,
decoupled from Runtime's cycle) through `ThreadingHTTPServer` — a
second, genuinely concurrent entry point into the system that existed
before Runtime and continues to exist alongside it. This is why Finding
5.1's fix is scoped to exactly one component rather than being a
system-wide locking exercise.
