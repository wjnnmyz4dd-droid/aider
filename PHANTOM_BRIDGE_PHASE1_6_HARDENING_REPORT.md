# Phantom Bridge — Phase 1.6 Long-Run Hardening Report

**Status:** Complete. **Bridge is now frozen** (see closing declaration).

Scope: `phantom/bridge/` only. No architecture change, no new engines, no
public API removed or altered. This phase eliminates the last known
long-running operational weakness identified during Phase 1.5:
unbounded retention inside the Bridge.

---

## 1. Files changed

| File | Change |
|---|---|
| `phantom/bridge/config.py` | 8 new additive `BridgeConfig` fields, all with defaults (retention TTLs, cleanup interval, size caps). No existing field changed. |
| `phantom/bridge/command_queue.py` | New deterministic cleanup pass (`_run_cleanup_locked`), triggered from existing `enqueue()`/`poll()`/`record_result()` call sites using timestamps already available to each. 9 new additive observability getters. **Bugfix found by this phase's own tests:** cleanup purging a not-yet-executed, TTL-expired command from `_commands` without also removing it from `_pending_order` caused a `KeyError` crash in the very next `poll()`; fixed by filtering `_pending_order` against the same purge set inside the same locked pass. |
| `phantom/bridge/engine.py` | `_errors` / `_trade_transactions` changed from unbounded `list` to `collections.deque(maxlen=...)`. New `queue_retention_stats()` passthrough method. |
| `tests/phantom/bridge/test_command_queue_retention.py` | New — 12 tests covering the full "Testing" checklist in the task (TTL expiration, no premature deletion, count-based cap, no randomness, cleanup cadence, cleanup during concurrent requests, cleanup after restart, large volume, memory stabilization). |
| `tests/phantom/bridge/test_engine_retention_concurrency.py` | New — 3 tests empirically confirming the `deque` swap in `BridgeEngine` needs no new lock under concurrent load. |
| `PHANTOM_BRIDGE_PHASE1_6_HARDENING_REPORT.md` | This report. |

`PhantomBridgeEA.mq5` was not touched. No public method's signature or
return type changed anywhere in this phase.

---

## 2. Retention model

Every stateful structure in the Bridge was inspected and classified:

| Structure | Owner | Class | Retention |
|---|---|---|---|
| `_emergency_stop` | `CommandQueue` | Permanent | Single current value, no retention concern. |
| `_latest_account_state`, `_latest_positions`, `_latest_pending_orders` | `BridgeEngine` | Permanent (latest-value cache) | Overwritten each update; no growth. |
| `ConnectionHealth._last_heartbeat_at` | `ConnectionHealth` | Permanent (latest-value cache) | Single timestamp overwritten each heartbeat; already bounded before this phase. |
| `_pending_order` | `CommandQueue` | Temporary | Self-clears every `poll()` cycle (whole list replaced with `[]`); now also purged of any id that expires mid-cycle (this phase's bugfix). |
| `_commands`, `_results` | `CommandQueue` | Recoverable | Needed to answer `command_for`/`result_for`/audit lookups. Bounded by the new TTL + count-cap cleanup. |
| `_executed_ids` | `CommandQueue` | Idempotency | Guards `record_result()` against a second fill for the same correlation_id. Bounded by the same cleanup pass (a correlation_id is only forgotten once it's outside every retention window). |
| `_errors`, `_trade_transactions` | `BridgeEngine` | Audit | Append-only diagnostic history. Bounded via `deque(maxlen=...)`, oldest dropped first. |

**Configuration added** (all in `BridgeConfig`, all additive with
defaults):

`execution_report_ttl_seconds` (3600s), `duplicate_detection_ttl_seconds`
(900s), `correlation_ttl_seconds` (7200s), `cleanup_interval_seconds`
(60s), `max_completed_commands` (10000), `max_cached_reports` (10000),
`max_heartbeat_history` (1 — reserved, see note below),
`max_error_history` (1000), `max_trade_transaction_history` (1000).

Two of these (`max_error_history`, `max_trade_transaction_history`)
are not on the task's literal minimum list but were added because
`_errors`/`_trade_transactions` are exactly the kind of "retained result
collection" the task's scope explicitly calls out, and both were
genuinely unbounded before this change.

`max_heartbeat_history` is present because it's on the mandated minimum
list, but `ConnectionHealth` already retains only the single most recent
heartbeat (the minimum required for fail-closed logic) — there is no
growing history for it to bound. It is documented as reserved/inert
rather than inventing new state to consume it, per "no speculative
improvements."

---

## 3. Cleanup algorithm

Lazy, request-driven, deterministic — no background thread, no
randomness, no LRU-by-access.

**Trigger:** `_run_cleanup_locked(now)` runs at most once per
`cleanup_interval_seconds`, called from inside the existing lock in
`enqueue()`, `poll()`, and `record_result()`, using each call's own
already-available timestamp (`command.issued_at`, `now`,
`report.reported_at` respectively). No new parameter was added to any
public method. In `poll()`, the cleanup check runs *before* the
emergency-stop early return, since a long halt is exactly when retention
would otherwise grow unchecked.

**Purge rule, evaluated per correlation_id:**
- Not yet executed: purge if `now - command.issued_at > correlation_ttl_seconds`.
- Executed: purge if `now - report.reported_at > max(execution_report_ttl_seconds, duplicate_detection_ttl_seconds)` — `max()`, not `min()`, so both "keep the report until its TTL" and "keep duplicate-detection long enough" are satisfied by one rule.
- Additionally: if completed correlation_ids exceed `min(max_completed_commands, max_cached_reports)`, the oldest (by `reported_at`) are purged first until back under the cap.

Purging removes the correlation_id from `_commands`, `_pending_order`,
`_delivered_ids`, `_executed_ids`, and `_results` together — one
consistent removal, no partial state.

---

## 4. Thread-safety verification

- `_run_cleanup_locked()` assumes `self._lock` is already held (same
  pattern as the earlier `ConnectionHealth` hotfix's
  `_is_ready_locked()`); it is only ever called from within an existing
  `with self._lock:` block in `enqueue`/`poll`/`record_result`.
- The `deque(maxlen=...)` swap in `BridgeEngine` needed no new lock:
  `deque.append()` is atomic under CPython's GIL, the same guarantee the
  `list.append()` it replaced already relied on. This was verified
  empirically, not just asserted — see
  `test_engine_retention_concurrency.py` (32 threads × 200 iterations
  each of concurrent `handle_error`/`handle_trade_transaction`, mixed
  together in one test): zero exceptions, exact bound respected.
- `test_command_queue_retention.py::TestCleanupDuringConcurrentRequests`
  hammers `enqueue`/`record_result`/`poll`/every read method from 16
  threads × 200 iterations concurrently with cleanup firing mid-flight;
  zero errors, state stays bounded.

---

## 5. Memory-growth analysis

A 24-simulated-hour run (86,400 command/execution cycles, one per
simulated second, default retention config) against the real
`CommandQueue`:

```
 hour  tracked_ids  pending  completed  est_bytes
    0         3600        0       3600    2764800
    1         3660        0       3660    2810880
    2         3660        0       3660    2810880
   ...        ...         0       3660    2810880
   23         3660        0       3660    2810880

cleanup_run_count: 1440
expired_entries_removed_count: 82740
total commands submitted: 86400
```

Tracked state plateaus at hour 1 (~3660 correlation_ids, ~2.8MB
estimated) and stays exactly flat for the remaining 23 simulated hours,
despite 86,400 total commands having passed through — i.e. retained
state is bounded by *rate × TTL*, not by *total volume ever processed*.
82,740 of the 86,400 submitted commands were purged over the run; this
is the expected steady state given `execution_report_ttl_seconds` (3600s,
the larger of the two TTLs at default config) against one
command/second of traffic.

`estimated_memory_bytes()` is a documented approximation (fixed
per-entry byte costs × entry count) for observability/alerting
trend-watching only — never used for a correctness decision.

`TestLargeVolume` (in the unit suite) additionally confirms the same
plateau behavior at a smaller configured cap (1000) over 50,000
enqueue/execute cycles — a practical stand-in for "millions" of
completed command IDs, since a literal multi-million real-time run isn't
practical as a fast unit test but the same bounded-by-cap mechanism
governs both.

---

## 6. Test results

- New `test_command_queue_retention.py`: **12/12 pass** (found and fixed
  one real defect — see §1 — before all 12 passed).
- New `test_engine_retention_concurrency.py`: **3/3 pass**.
- Full `phantom/bridge` suite: **121/121 pass** (106 pre-existing + 15
  new), zero regressions.
- Existing concurrency suites re-run explicitly
  (`test_command_queue_concurrency.py`, `test_connection_health_concurrency.py`,
  `test_server_concurrency.py`): **17/17 pass**.
- Full repository suite (`pytest tests/`, excluding the 3 pre-existing
  unrelated flask-import collection errors documented in prior hotfix
  reports): **1747/1747 pass**.
- `python3 -m compileall phantom/bridge/ tests/phantom/bridge/`: clean.
- `python3 scripts/check_architecture.py`: **PASS** (no circular
  imports, no cross-package private-state access, no pipeline-stage
  importing a cross-cutting observer package).

---

## 7. Performance impact

Cleanup is throttled to at most one pass per `cleanup_interval_seconds`
(default 60s) — every other call in that window pays a single
`datetime` subtraction and comparison before returning, negligible
relative to existing lock-acquisition overhead. When a cleanup pass does
run, its cost is O(n) in the number of currently-tracked correlation_ids
(bounded by the retention policy itself, so this is bounded, not
unbounded), plus an O(k log k) sort only when the count-based cap is
exceeded (k = number of completed survivors, typically ≤
`max_completed_commands`). No new thread, no new lock, no additional
per-request allocation beyond what cleanup itself needs when it fires.

---

## 8. Remaining limitations

- `estimated_memory_bytes()` is a fixed-cost approximation, not a true
  `sys.getsizeof`-based measurement — adequate for trend-watching, not
  for precise capacity planning.
- `max_heartbeat_history` is inert/reserved — there is currently no
  growing heartbeat history in `ConnectionHealth` for it to bound. If a
  future phase adds heartbeat history (e.g. for jitter analysis), this
  config field is already in place to govern it.
- `max_completed_commands` and `max_cached_reports` are enforced as a
  single combined cap (`min()` of the two) because, in this Bridge's
  current design, a completed command and its cached execution report
  are the same correlation_id's record, not two independently-sized
  stores. If a future phase splits these into genuinely separate
  stores, the two config values would need to be applied independently.
- Cleanup is lazy/request-driven: if the Bridge receives zero requests
  for longer than several TTL windows and then a burst arrives, the
  first request after the gap pays for a larger-than-usual cleanup pass
  (bounded, but not amortized). This was an explicit, deliberate
  trade-off against adding a background thread, which this phase's
  authorization did not permit ("do not redesign the bridge").

---

## 9. Recommendation

Ship as-is. All nine deliverables above are satisfied, all requested
test categories are covered and passing, and the one real defect this
phase's own tests surfaced (the `_pending_order` purge gap) is fixed and
regression-tested. No further Bridge work is needed to satisfy Phase
1.6's stated objective.

---

## Bridge is now frozen

Per this phase's closing instruction: **the Bridge accepts bug fixes
only from this point forward.** No new features, no architecture
changes, no new engines will be added to `phantom/bridge/` or
`mt5/PhantomBridgeEA.mq5` going forward except to fix a confirmed defect.

All future development effort moves to, in order:

1. Evidence Engine
2. Strategy Engine
3. Portfolio Statistical Risk Engine
4. Market Intelligence Engine
5. Prop Firm Compliance Engine
6. Research & Learning Engine
7. Validation

Per Phantom Protocol rule §1.10, implementation on any of these does not
begin until that stage has its own **Accepted** ADR under `docs/adr/`.
