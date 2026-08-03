# Phase 1 Hotfix — ConnectionHealth Thread Safety

Scope actually touched: `phantom/bridge/connection_health.py` and one
new test file. Nothing else in the repository was modified. Not Phase
2, no architecture change, no new engine, no MQL5 change, no other
bridge file touched.

## 1. Files changed

- `phantom/bridge/connection_health.py` — added a single
  `threading.Lock`; every existing public method's body now runs under
  it. Factored the shared "is the heartbeat still within timeout"
  check into a private `_is_ready_locked()` helper (assumes the lock is
  already held) so `is_fail_closed()` can reuse `is_ready()`'s logic
  without a second lock acquisition. No public method's signature,
  return type, or behavior changed.
- `tests/phantom/bridge/test_connection_health_concurrency.py` (new) —
  the concurrency/stress test suite this hotfix's verification section
  required.

## 2. Confirmed race condition

`phantom/bridge/server.py` serves every route through
`http.server.ThreadingHTTPServer` (one thread per connection) —
verified directly, same as the prior `CommandQueue` hotfix.
`ConnectionHealth._last_heartbeat_at` is written by
`BridgeEngine.handle_heartbeat` (called from `POST /bridge/heartbeat`)
and read by `is_ready()`/`is_fail_closed()`/`last_heartbeat_at`, called
from the command-submission path (`BridgeEngine.submit_command`) and
poll path — confirmed by grepping every call site in
`phantom/bridge/engine.py` before making any change. Both the write and
every read can run on separate threads at the same time under
`ThreadingHTTPServer`. `ConnectionHealth` had zero synchronization: a
write to `_last_heartbeat_at` on one thread and a read via `is_ready()`
on another had no ordering guarantee beyond CPython's per-attribute
atomicity, and — more importantly — `is_fail_closed()` called
`self.is_ready()` internally, meaning any naive fix that simply wrapped
each method's own body in its own lock (without accounting for this
internal call) would have deadlocked immediately on a plain `Lock`.
That internal-call detail is what made "smallest correct
synchronization" require the `_is_ready_locked()` refactor rather than
a blind per-method lock wrap.

## 3. Locking strategy

One `threading.Lock` (non-reentrant, not `RLock`), held for the full
body of every public method (`record_heartbeat`, the
`last_heartbeat_at` property getter, `is_ready`, `is_fail_closed`,
`reset`). `RLock` was deliberately avoided: `is_fail_closed()`'s
original implementation called `self.is_ready()` internally, which
would have required re-entrant acquisition under a naive lock-wrap.
Instead, the shared check was factored into `_is_ready_locked()` — an
unlocked helper callable only while the lock is already held — so both
`is_ready()` and `is_fail_closed()` acquire the lock exactly once each
and call the helper directly, with no re-entrant acquisition anywhere.
This proves re-entrancy is *not* necessary here, per this hotfix's
explicit instruction to justify any `RLock` use — none was needed.

## 4. Deadlock analysis

- **No re-entrant acquisition**: confirmed by the `_is_ready_locked()`
  refactor above — the one place internal re-entrancy existed
  (`is_fail_closed` → `is_ready`) is now structured to avoid it
  entirely.
- **No lock ordering issue**: `ConnectionHealth` introduces exactly one
  lock and never acquires any other lock (including `CommandQueue`'s,
  from the prior hotfix) while holding its own — the two classes'
  locks are never nested in either direction, confirmed by inspection
  of every call site in `engine.py` (each call is to exactly one of
  `self._health.*` or `self._queue.*`, never both under one held lock).
- **No blocking I/O under the lock**: `_is_ready_locked()` calls
  `self._clock()`, which in every actual usage in this codebase is a
  fast in-memory call (`datetime.now(timezone.utc)` or a fixed-value
  test double) — never network I/O, never a blocking call, by the
  existing `Callable[[], datetime]` contract this class and its
  siblings (`CommandQueue`, `BridgeEngine`) already rely on throughout
  Phase 1. No new blocking risk is introduced by calling it under the
  lock.
- **No timeout semantics changed**: `_is_ready_locked()` is a verbatim
  copy of the original `is_ready()` body — same comparison, same
  `heartbeat_timeout_seconds` field, same fail-closed-before-any-
  heartbeat behavior.
- The stress test (`TestStressAllOperationsTogether`, §5) runs 128
  threads across writer/reader/resetter roles simultaneously and
  completed without hanging, corroborating this analysis empirically.

## 5. Tests added

`tests/phantom/bridge/test_connection_health_concurrency.py`, 8 tests,
all passing:

```
test_many_threads_recording_heartbeats_never_raise_or_corrupt ... ok
test_concurrent_is_ready_and_is_fail_closed_never_raise ... ok
test_concurrent_reads_during_writes_produce_no_exception ... ok
test_transitions_to_fail_closed_once_timeout_elapses ... ok
test_concurrent_reads_observe_lost_heartbeat_consistently ... ok
test_recovers_to_ready_after_a_fresh_heartbeat ... ok
test_concurrent_recovery_under_load ... ok
test_high_thread_count_stress_no_errors_no_deadlock ... ok

Ran 8 tests in 0.091s — OK
```

Coverage against the hotfix's verification requirements:

| Required | Test |
|---|---|
| Concurrent heartbeat updates | `TestConcurrentHeartbeatUpdates` — 32 threads × 500 writes |
| Concurrent health reads | `TestConcurrentHealthReads` — 32 threads asserting `is_ready`/`is_fail_closed` stay exact opposites throughout |
| Concurrent stale-state checks | `TestConcurrentStaleStateChecks` — writer advancing a shared mutable clock while 32 readers poll concurrently |
| Lost-heartbeat transitions | `TestLostHeartbeatTransition` (2 tests) — single-threaded transition proof + concurrent-read-during-transition |
| Recovery after heartbeat resumes | `TestRecoveryAfterHeartbeatResumes` (2 tests) — single-threaded recovery proof + concurrent-read-during-recovery |
| No inconsistent snapshots | `TestConcurrentHealthReads`'s `ready != fail_closed` assertion on every iteration |
| No RuntimeError | asserted (`errors == []`) in every concurrency test |
| No deadlock | every test completing at all is the proof; the 128-thread stress test specifically targets this |
| High-thread-count stress testing | `TestStressAllOperationsTogether` — 128 threads (writers + readers + resetters) simultaneously |

A `_MutableClock` test helper (itself lock-protected, since it is set
from the main test thread while read from worker threads) was added
purely to let these tests provoke real lost-heartbeat/recovery
transitions under concurrent load — it is test-only code, not a change
to `ConnectionHealth` or any other production file.

## 6. Stress-test results

`test_high_thread_count_stress_no_errors_no_deadlock`: 128 threads (64
writers × 100 heartbeats each, 32 readers × 100 read-triples each, 32
resetters × 5 reset/re-heartbeat cycles each) running concurrently
against one `ConnectionHealth` instance. Result: 0 exceptions, test
completed in well under a second, no hang. Combined with the other 7
tests (each independently exercising 32-way concurrency), the full
suite ran in 0.091s with zero failures.

## 7. Regression results

- Full bridge suite: **100/100 passing**
  (`python3 -m unittest discover -s tests/phantom/bridge`) — the 92
  tests from the prior `CommandQueue` hotfix plus this hotfix's 8 new
  tests.
- Full repository suite: **1729/1729 passing**
  (`pytest tests/ --ignore=tests/test_account_snapshot.py
  --ignore=tests/test_journal_fields.py
  --ignore=tests/test_score_signal.py`) — the same 3 pre-existing,
  unrelated `flask`-import collection errors noted in the prior hotfix
  report remain, confirmed still present and unrelated to this change.
- `python3 -m compileall phantom/bridge/ tests/phantom/bridge/`: clean,
  no syntax/compile errors.
- `python3 scripts/check_architecture.py`: **PASS** — no circular
  imports, no cross-package private-state access, no pipeline-stage
  importing a cross-cutting observer package (this check scopes to
  `phantom_pipeline/`, which this hotfix never touched; run anyway per
  this task's explicit instruction, confirmed green).
- No file outside `phantom/bridge/connection_health.py` and the one new
  test file was modified; nothing outside the bridge was affected or
  could have been.

## 8. Performance impact

Measured on this sandbox (uncontended, single-threaded, 200,000
iterations each):

- `record_heartbeat()`: ~0.18 microseconds/call average.
- `is_ready()`: ~0.68 microseconds/call average.

Cost of one uncontended `Lock` acquire/release per call, negligible
against this class's real call frequency (bounded by heartbeat cadence
and per-request HTTP handling, both orders of magnitude slower than a
microsecond) and consistent with the equally negligible overhead
measured for the prior `CommandQueue` hotfix.

## 9. Remaining limitations

- This fix addresses thread-safety only, exactly as authorized. Every
  public method's external behavior, fail-closed semantics (never
  ready before any heartbeat, fail-closed once `heartbeat_timeout_seconds`
  elapses), and timeout comparison logic are byte-for-byte identical to
  before — confirmed by the pre-existing 5 `test_connection_health.py`
  tests passing unmodified.
- Scanner, Strategy, Risk, Market Intelligence, Compliance, Research,
  Reliability, Validation, and `mt5/PhantomBridgeEA.mq5` were not
  touched, inspected for changes, or affected by this fix, per this
  task's explicit restriction.
- With this and the prior `CommandQueue` hotfix both applied,
  `phantom/bridge/`'s two stateful, concurrently-reachable components
  are now both synchronized. No other shared mutable state is known to
  remain unprotected in `phantom/bridge/` as of this hotfix — a fresh,
  independent audit would be the way to confirm that rather than
  asserting it here from memory alone.

---

Stopping here per this task's instructions.
