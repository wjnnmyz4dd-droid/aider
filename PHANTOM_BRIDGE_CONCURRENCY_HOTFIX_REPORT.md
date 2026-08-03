# Phase 1 Hotfix — Bridge Concurrency Hardening

Scope actually touched: `phantom/bridge/command_queue.py` and one new
test file. Nothing else in the repository was modified. This is not
Phase 2, no architecture change, no new engine, no new package, no
runtime changes, no MQL5 change.

## 1. Files changed

- `phantom/bridge/command_queue.py` — added a single `threading.Lock`,
  wrapped every existing public method's body in `with self._lock:`.
  No method signature, return type, or behavior changed.
- `tests/phantom/bridge/test_command_queue_concurrency.py` (new) — the
  concurrency/stress test suite this hotfix's verification section
  required.

No other file was touched. `mt5/PhantomBridgeEA.mq5`, every other file
under `phantom/bridge/`, and every other engine/spec/doc are unchanged.

## 2. Why each change was necessary

`phantom/bridge/server.py` serves every HTTP route through
`http.server.ThreadingHTTPServer` — confirmed by direct inspection, one
thread spawned per connection. `CommandQueue` held `_commands`,
`_pending_order`, `_delivered_ids`, `_executed_ids`, and `_results` as
plain, unsynchronized `dict`/`list`/`set` attributes, mutated directly
by `enqueue`, `poll`, and `record_result`. Two concrete, verified
hazards this created:

1. **Lost/duplicated updates**: two threads calling `enqueue()` for the
   same `correlation_id`, or `record_result()` for the same id, could
   both pass their "not already present" check before either wrote,
   since CPython's GIL guarantees individual bytecode-op atomicity but
   not multi-statement check-then-act sequences.
2. **`RuntimeError` from concurrent iteration**: `all_results()`'s
   `tuple(self._results.values())` (and `poll()`'s iteration over
   `_pending_order`) could raise if another thread inserted into the
   same dict/list mid-iteration — a real, reproducible CPython failure
   mode under concurrent mutation, not a theoretical one.

A single lock around every public method closes both: every mutation
and every read of this queue's state now happens under mutual
exclusion, so no interleaving between two threads' check-then-act
sequences is possible, and no iteration ever races a concurrent
mutation.

## 3. Concurrency model

`CommandQueue` is reached from two independent call paths that can run
concurrently: (a) `BridgeEngine.submit_command` calling `enqueue()`
from whatever process embeds the Python bridge, and (b) the HTTP
server's per-request threads calling `poll()` (via `GET
/bridge/commands/poll`) and `record_result()` (via `POST
/bridge/execution/report`) on behalf of the MT5 EA's own independent
heartbeat/poll/report cadence. Any two of these can legitimately
overlap in wall-clock time. The fix treats `CommandQueue` as the single
shared-state boundary between them and serializes access to it; nothing
upstream or downstream of the queue needed to change, because nothing
else reaches into its internal attributes (verified: no other file
under `phantom/bridge/` references `_commands`, `_pending_order`,
`_delivered_ids`, `_executed_ids`, `_results`, or `_emergency_stop`
directly — confirmed by grep before making this change).

## 4. Locking strategy

One `threading.Lock` (non-reentrant), held for the full body of every
public method (`set_emergency_stop`, the `emergency_stop_state`
property getter, `enqueue`, `poll`, `record_result`, `command_for`,
`result_for`, `is_delivered`, `is_executed`, `all_results`). A plain,
non-reentrant `Lock` was chosen over `RLock` because no method in this
class calls another public method of the same class internally
(verified by inspection before choosing this) — there is no re-entrancy
to accommodate, and an `RLock` would only add overhead without adding
safety here. This is the smallest lock granularity that still
guarantees every state transition is atomic: one lock, one queue,
protecting exactly the state that is actually shared.

## 5. Deadlock analysis

No deadlock is possible with this design:

- **No re-entrant acquisition**: confirmed no method calls another
  method of `self` while holding the lock (each method's body is a
  single `with self._lock:` block with no nested call back into
  `self.<other_public_method>`).
- **No lock ordering issue**: this is the only lock `CommandQueue`
  introduces, and it is never held while waiting on another lock or
  blocking I/O — every method body does pure in-memory dict/list/set
  operations only, nothing that can block indefinitely while holding
  the lock.
- **No cross-object lock coupling**: `ConnectionHealth` (a separate
  class, out of scope for this hotfix — see §9) has its own state and
  is never accessed from inside a `CommandQueue`-locked block or vice
  versa, so there is no possibility of two locks being acquired in
  inconsistent order across the two classes.

The stress test (`TestStressAllOperationsTogether`, §6) exercises every
public method concurrently from up to 128 threads for a sustained run
and completed without hanging, corroborating this analysis empirically
as well as by inspection.

## 6. Test results

New file `tests/phantom/bridge/test_command_queue_concurrency.py`, 7
tests, all passing:

```
test_only_one_thread_wins_a_duplicate_correlation_id ... ok
test_many_threads_enqueueing_distinct_ids_lose_nothing ... ok
test_concurrent_duplicate_reports_for_same_id_recorded_once ... ok
test_concurrent_reports_for_distinct_ids_all_recorded ... ok
test_concurrent_poll_never_double_delivers_or_raises ... ok
test_concurrent_reads_during_writes_never_raise ... ok
test_stress_every_public_method_concurrently_no_corruption ... ok

Ran 7 tests in 0.864s — OK
```

Coverage against the hotfix's verification requirements:

| Required | Test | Result |
|---|---|---|
| Concurrent enqueue | `TestConcurrentEnqueue` | 32 threads × 200 ids, all enqueued, none lost |
| Concurrent dequeue | `TestConcurrentPollAndEnqueue` | interleaved enqueue+poll from 64 threads, no double-delivery |
| Duplicate command handling | `TestConcurrentDuplicateHandling` | 64 threads racing one `correlation_id`, exactly 1 winner |
| Concurrent execution reports | `TestConcurrentExecutionReports` (2 tests) | distinct ids all recorded; same id recorded exactly once under 64-way race |
| Concurrent result retrieval | `TestConcurrentResultRetrieval` | reads and writes interleaved, zero exceptions |
| No RuntimeError during iteration | all of the above + stress test | zero exceptions across every run |
| No lost commands | `TestConcurrentEnqueue`, `TestConcurrentPollAndEnqueue`, stress test | every enqueued id verified present/delivered |
| No duplicated commands | `TestConcurrentPollAndEnqueue` | delivered-id set has no duplicates across all `poll()` calls combined |
| No corrupted state | `TestStressAllOperationsTogether` | every method hammered concurrently (128 threads total across 4 roles), final state fully consistent |
| Stress test, many simultaneous workers | `TestStressAllOperationsTogether` | 32 enqueue + 32 poll + 32 report + 32 read threads simultaneously |

**Not applicable / out of scope** (see §9): "concurrent heartbeat
updates" and "concurrent cancellation" are not tested here —
heartbeat state lives in `ConnectionHealth`, a different file, and
`CommandQueue` has no cancellation API to test. Neither is fixed by
this hotfix; both are named explicitly in §9 rather than silently
skipped.

## 7. Regression results

- Full existing Phase 1 bridge suite: **92/92 passing** (the original
  85 tests + this hotfix's 7 new concurrency tests), via
  `python3 -m unittest discover -s tests/phantom/bridge`.
- Full repository regression suite (`pytest tests/`): **1721/1721
  passing**, excluding three pre-existing, unrelated collection errors
  in `tests/test_account_snapshot.py`, `tests/test_journal_fields.py`,
  and `tests/test_score_signal.py` — all three fail at import time with
  `ModuleNotFoundError: No module named 'flask'`, confirmed via `git
  stash` to be present identically **before** this change as well (a
  pre-existing sandbox dependency gap in `phantom_institutional.py`,
  unrelated to `phantom/bridge/` and untouched by this hotfix).
- Nothing outside `phantom/bridge/` was modified, and nothing outside
  it failed.

## 8. Performance impact

Measured on this sandbox (uncontended, single-threaded, 50,000
iterations each):

- `enqueue()`: ~2.68 microseconds/call average.
- `record_result()`: ~2.72 microseconds/call average.
- `poll()` (50,000 pending): ~15.65ms total for the batch.

This is the cost of one uncontended `Lock` acquire/release per call —
negligible against this queue's actual call frequency (bounded by
`HeartbeatIntervalSeconds`/timer-driven polling, on the order of once
per second per EA instance) and against the HTTP request-handling
overhead (milliseconds) each call is already embedded in. No
measurable behavioral slowdown is expected in the running system.

## 9. Remaining known limitations

- **`ConnectionHealth`'s heartbeat state is unsynchronized and out of
  scope for this hotfix.** This hotfix's authorization was explicitly
  scoped to `phantom/bridge/command_queue.py` only. `ConnectionHealth`
  (a separate file) has the same class of unsynchronized shared-state
  exposure under `ThreadingHTTPServer`, previously noted in
  `docs/specs/09_bridge_concurrency_hardening.md`. It is **not** fixed
  here and requires its own, separate authorization — flagged
  explicitly rather than silently left unaddressed or silently
  expanded into.
- **No exposure-reservation state exists in `CommandQueue` to protect** —
  the "reservation state" item named in this hotfix's requirements is a
  Portfolio Statistical Risk Engine concept specified for a future
  phase (`docs/specs/03_portfolio_statistical_risk_engine.md` §3); it
  does not exist anywhere in Phase 1's already-built code, so there was
  nothing in `command_queue.py` to lock for it.
- **No cancellation API exists to protect** — `CommandQueue` has no
  `cancel`/`cancel_command` method in its current public surface, and
  this hotfix did not add one ("do not change public APIs unless
  absolutely required" / "no new responsibilities"), so "concurrent
  cancellation" has no corresponding test.
- This fix addresses thread-safety only. It does not change, and was
  not asked to change, any of `CommandQueue`'s existing business logic,
  return values, or fail-closed/idempotency semantics — every one of
  those is byte-for-byte identical to before this hotfix, which is what
  the unchanged 85 pre-existing tests passing unmodified confirms.

---

Stopping here per this task's instructions. Waiting for authorization
before any additional work.
