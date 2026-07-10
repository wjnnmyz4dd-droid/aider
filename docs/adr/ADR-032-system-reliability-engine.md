# ADR-032 — System Reliability Engine

Status: Accepted

Acceptance Date: 2026-07-10

Accepted By: Software Architect / Phantom Engineering Council (full
spec supplied in one message, per the `ADR-029`/`ADR-030`/`ADR-031`
"complete spec accepted in one pass" precedent).

Owner: SRE (Site Reliability Engineer) — the role already scoped in
`.claude/agents/TEAM.md` to "SLOs, error budgets, observability, chaos
engineering, and toil reduction for production systems," an exact
match for this ADR's mission.

Reviewed by: Software Architect (mandatory cross-cutting reviewer, same
as every prior stage this session), Minimal Change Engineer (Consulted
— this ADR's own scope discipline, §0/§2, is this role's charter)

Date: 2026-07-10

Depends on: `ADR-031-runtime-orchestrator.md` (Accepted — this ADR
consumes `RuntimeAuditRecord`/`CycleReport` as a read-only observer,
never modifying Runtime), `ADR-024` through `ADR-030` (Accepted — the
six engines whose health this ADR watches, never whose logic it
touches)

---

# 0. Relationship to prior work (disclosure, not duplication)

- **`docs/specs/07_system_reliability_engine.md`** is a pre-existing,
  specification-only document for an *earlier*, superseded pipeline
  shape (references `phantom/runtime/runtime.py` and
  PhantomBridgeEA's own `ConnectionHealth`, both predating the engines
  actually built this session). Its **ideas** are reused — a health
  monitor, heartbeat tracking, an `is_halted()`-style gate, injected
  resource-sampler callables that fail closed per-field — but its
  **literal interfaces are not**. Two deliberate scope cuts from that
  spec, both because Phase 3B's own responsibility list does not name
  them and its "no feature additions" bug policy forbids adding
  anything beyond what's asked:
  - **No `kill_switch`/operator-authentication surface.** That spec's
    §"Operator authentication" is real, valuable scope — but it is not
    one of Phase 3B's twelve named reliability responsibilities
    (engine health, heartbeat monitoring, timeout detection, snapshot
    freshness, runtime monitoring, memory monitoring, CPU monitoring,
    queue monitoring, watchdog integration, automatic recovery,
    graceful degradation, fail closed). Adding it now would be exactly
    the "feature addition" this phase's bug policy forbids. A future
    ADR-032 Amendment can add it if the Council decides to.
  - **No import of `phantom_pipeline.watchdog` or
    `phantom_pipeline.deployment.monitoring`.** Every `phantom/`
    package built this session enforces "zero import of
    `phantom_pipeline`" as an architecture invariant (verified by each
    package's own test). `phantom_pipeline/deployment/monitoring.py`'s
    **injected-sampler-callable pattern** (a CPU/memory sampler is a
    caller-supplied function, defaulting to a stdlib-only Linux/POSIX
    implementation that degrades a single reading to `None` on failure
    rather than aborting the whole snapshot) is mirrored here, not
    imported.
- **`ADR-031` §9 (`phantom/runtime/watchdog_integration.py`)** already
  implements per-cycle timeout detection (`detect_timeouts`,
  `detect_snapshot_timeout`) and a restart allow-list
  (`APPROVED_RESTART_COMPONENTS`, `is_approved_for_restart`) scoped to
  what Runtime itself needs to reason about *within* one cycle. This
  ADR **imports those two functions and that constant directly**
  (`phantom.runtime.watchdog_integration`, read-only) rather than
  redefining "which components are safe to restart" a second time —
  the exact "no duplicate calculations" discipline `ADR-029`/`ADR-030`
  already established for reused pure functions. This ADR's own scope
  is the layer *above* one cycle: aggregating heartbeats and cycle
  outcomes *across* cycles, tracking system resources, and deciding
  system-wide degradation level.
- **No legacy reliability engine exists in `phantom/`.** Designed from
  first principles for the six engines and the Runtime Orchestrator
  built this session.

---

# Pipeline position

**Cross-cutting, like Watchdog (`ADR-011`) and the Research & Learning
Engine (`ADR-029`) — not part of the live trading pipeline, and never
called *by* Runtime.** Runtime is frozen this phase (`DO NOT modify`);
this engine is an external, additive observer that a caller feeds
Runtime's already-returned `CycleReport`/`RuntimeAuditRecord` after
each `run_cycle()`/`run_cycle_for_pair()` call — Runtime itself
contains no call into this package, and none is added.

---

# 1. Mission

**The System Reliability Engine watches every other component's
health and provides the fail-closed signal every live component's
caller should check before proceeding.** It never trades, sizes,
selects a strategy, or makes a compliance decision — it only observes,
measures, and, within a narrow, pre-approved set of actions,
recovers.

---

# 2. Responsibilities (exactly Phase 3B's own list, nothing more)

1. Engine health — per-engine `ComponentHealth` (HEALTHY/DEGRADED/
   UNHEALTHY/UNKNOWN), derived from heartbeat recency and reported
   cycle outcomes.
2. Heartbeat monitoring — `report_heartbeat(component, now)`; staleness
   derived the same way `ADR-011`'s own Watchdog derives it (age vs. a
   configured interval), built fresh.
3. Timeout detection — reuses `ADR-031`'s own `detect_timeouts`/
   `detect_snapshot_timeout` directly (§0).
4. Snapshot freshness — `check_snapshot_freshness(generated_at, now,
   config)`, a small pure function, generalizing `ADR-031`'s
   snapshot-timeout signal into a directly-callable check any observer
   can use outside a `RuntimeAuditRecord`'s own stage timings.
5. Runtime monitoring — `record_cycle(cycle_report)`: aggregates
   `RuntimeAuditRecord.outcome`/`duration_ms` history per pair, over a
   configurable rolling window.
6. Memory monitoring — an injected sampler callable (§0), degrading to
   `None` on failure, never raising.
7. CPU monitoring — same pattern.
8. Queue monitoring — `report_queue_depth(name, depth)`; a plain
   gauge, since no queue implementation exists yet anywhere in
   `phantom/` to observe directly (Bridge's own command handling is
   synchronous per-call, per `ADR-023`) — this is the *observation
   surface* for a future queue, not a claim one exists today.
9. Watchdog integration — this ADR's whole relationship to `ADR-031`
   §9 (§0).
10. Automatic recovery — `attempt_recovery(component, now) ->
    RecoveryOutcome`: constructs a fresh instance of exactly one of the
    four components `ADR-031`'s own `APPROVED_RESTART_COMPONENTS`
    names (Evidence/Market Intelligence/Strategy/Risk Engine) — refuses
    unconditionally, with no code path at all, for Compliance Engine or
    Bridge (verified structurally, `ADR-031` Hard Rule extended here).
11. Graceful degradation — a four-level `DegradationLevel`
    (NORMAL/DEGRADED/CRITICAL/HALTED) derived deterministically from
    aggregate component health + resource thresholds, never from a
    single noisy sample.
12. Fail closed — `is_halted()` returns `True` whenever aggregate
    health cannot be established (missing/stale heartbeats past a
    grace period) as well as when `DegradationLevel.HALTED` is reached
    — "unknown" is never treated as "healthy."

---

# 3. Public interfaces

```
ReliabilityEngine(config, metrics=None)
  .report_heartbeat(component: str, now: datetime) -> None
  .record_cycle(cycle_report: CycleReport) -> None
  .report_resource_usage(now: datetime) -> ResourceUsage   # samples memory/CPU via injected callables
  .report_queue_depth(name: str, depth: int) -> None
  .evaluate_health(now: datetime) -> SystemHealthSnapshot
  .is_halted(now: datetime) -> bool
  .attempt_recovery(component: str, now: datetime) -> RecoveryOutcome
```

---

# 4. Inputs

- Heartbeats (`component: str`, caller-supplied).
- `CycleReport`/`RuntimeAuditRecord` (`ADR-031`'s own output types,
  read-only, never re-derived).
- Resource samples via two injected callables (`cpu_sampler`,
  `memory_sampler`), each `Callable[[], Optional[float]]`, defaulting
  to a stdlib-only Linux/POSIX implementation mirroring (not
  importing) `phantom_pipeline/deployment/monitoring.py`'s own pattern.
- Queue-depth reports (`name: str`, `depth: int`), plain gauges.

---

# 5. Outputs

- `ComponentHealth` (per component), `SystemHealthSnapshot` (aggregate:
  overall `DegradationLevel`, per-component health, resource usage,
  queue depths, timestamp).
- `RecoveryOutcome` (component, action taken or refused, reason,
  timestamp) — one per `attempt_recovery()` call, never overwritten.
- `is_halted(now) -> bool` — the fail-closed gate.

**Type-level guarantee:** none of these output types is structurally
capable of holding a trade instruction, a strategy selection, or a
compliance decision — verified by a dedicated architecture test,
mirroring every prior stage's own.

---

# 6. Hard Rules

1. **Never trades, sizes, selects, or approves.** Verified structurally
   (no decision-shaped name anywhere in `phantom/reliability/`).
2. **Never calls into Runtime.** This engine is fed Runtime's already-
   produced output by an external caller; it holds no reference to a
   `RuntimeOrchestrator` instance and imports no Runtime *engine*
   module (only its `models`/`watchdog_integration` — types and the
   already-accepted restart allow-list, per §0).
3. **Recovery is bounded to exactly the four components `ADR-031`
   already approved for restart — Compliance Engine and Bridge are
   structurally unreachable**, not merely policy-excluded (`ADR-031`'s
   own allow-list is the single source of truth, imported, never
   redefined).
4. **A resource sampler's failure degrades that one reading to `None`,
   never aborts the whole health snapshot** (mirrors the
   `phantom_pipeline` pattern this ADR mirrors, §0).
5. **Fail closed.** Missing or stale data is never treated as healthy;
   `is_halted()` defaults `True` when health cannot be established.
6. **No new external dependency.** Default samplers are stdlib-only
   (`os`, `resource`/`/proc` where available); a real deployment
   injects its own sampler for its actual platform (mirrors the
   `phantom_pipeline/deployment/monitoring.py` docstring's own
   guidance).

---

# 7. Testing

Unit, Integration, Concurrency, Architecture, Regression, Recovery
(Bridge restart refusal, Runtime restart, engine timeout, snapshot
timeout, lost heartbeat, slow engine, partial engine failure, queue
congestion, repeated failures — Phase 3B's own recovery-test list,
scoped to what this engine actually owns).

---

# 8. Acceptance criteria

- ✓ Exactly Phase 3B's twelve named responsibilities, nothing more
  (§0, §2).
- ✓ Never calls into Runtime; never imports a Runtime *engine* module
  (§6.2).
- ✓ Compliance Engine and Bridge structurally unreachable for restart
  (§6.3, reusing `ADR-031`'s own allow-list).
- ✓ A single sampler failure degrades one field, never the whole
  snapshot (§6.4).
- ✓ `is_halted()` defaults `True` on missing/stale data (§6.5).

Per `ADR-001` and `CLAUDE.md` §1.10, accepted above in the same single
pass `ADR-029`/`ADR-030`/`ADR-031` used, since the full spec arrived in
one message.
