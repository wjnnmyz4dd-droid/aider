# Technical Specification — System Reliability Engine

Specification only. Cross-references `PHANTOM_FINAL_ARCHITECTURE.md`
and `PHANTOM_IMPLEMENTATION_ROADMAP.md` Phase 3c (core) and Phase 8
(full extension).

## 1. Purpose

Watch every other component's health and hold the one system-wide
kill switch that sits above PhantomBridgeEA's own transport-level halt
— a distinct, higher authority, never merged with it.

## 2. Responsibilities (Phase 3c core scope — this spec's build target)

- Define health models and a service monitor.
- Monitor heartbeats (from PhantomBridgeEA's existing
  `ConnectionHealth` and, as later components come online, their own
  liveness signals).
- Provide structured logging interfaces underlying every other
  component's own `logging_sink.py`.
- Provide recovery interfaces (no restart logic implemented yet, per
  this task's explicit scope — interfaces only).
- Hold `kill_switch` state and expose `is_halted()` for every live
  component to check as a precondition.

## 3. Public interfaces

```
reliability_engine.kill_switch.trip(reason: str, now: Clock) -> None
reliability_engine.kill_switch.clear(now: Clock) -> None
reliability_engine.is_halted() -> bool
reliability_engine.health_monitor.report(component_name: str, status: HealthStatus) -> None
reliability_engine.health_monitor.snapshot() -> Mapping[str, HealthStatus]
```

`auto_recovery.py`'s recovery-action interface is defined but has no
implemented action in this phase (see §9).

## 4. Inputs

- Health/heartbeat reports from every other live component (each
  component calls `health_monitor.report(...)`, mirroring how
  PhantomBridgeEA already reports its own connection health).
- Configuration: health-check intervals, latency thresholds,
  kill-switch trigger conditions (`config.py`).

## 5. Outputs

`HealthStatus` snapshots (per component and system-wide), `AlertEvent`
records, and the boolean `is_halted()` gate every live component must
check.

## 6. Internal data models

| Model | Shape |
|---|---|
| `HealthStatus` | component name, status (healthy/degraded/unhealthy/unknown), last-report timestamp, detail |
| `AlertEvent` | severity, source component, message, timestamp |
| `KillSwitchState` | active/inactive, trigger reason, tripped_at, cleared_at |

## 7. Decision authority

The one system-wide halt authority above every live component's own
internal state. `kill_switch.trip()` must be respected unconditionally
by Strategy Engine, Risk Engine, and Compliance Engine's `is_halted()`
checks — none of them may proceed on the theory that their own inputs
still look fine.

## 8. Dependencies

`phantom/shared/`, plus PhantomBridgeEA's existing telemetry/
`ConnectionHealth` for the connectivity piece (Phase 1, already built,
read-only).

## 9. Explicit non-responsibilities (this phase)

- **No restart logic yet** — `auto_recovery.py`'s interface is defined
  (a named recovery-action type) but no action is implemented; this is
  explicit scope for this phase, not an oversight.
- Never makes a trading decision — it can only halt, never select,
  size, or approve a trade.
- Never duplicates PhantomBridgeEA's own transport-level
  `EmergencyStopState` — this is a separate, higher-layer authority
  (per the architecture freeze §13 item 5), not a second copy of the
  same mechanism.
- Never becomes a second logging system — `logging.py` is the
  underlying sink every other component's own `logging_sink.py` writes
  through; it does not compete with them.

## 10. Test plan

- Unit tests for `KillSwitchState` transitions (trip/clear, including
  clearing while not tripped, tripping while already tripped).
- Integration test: a fixture caller's `is_halted()` check reflects a
  trip immediately, regardless of what that caller's own internal
  state claims.
- Health-monitor test: a component that stops reporting within its
  configured interval surfaces as `unhealthy`/`unknown` in
  `snapshot()`.
- Structural-boundary test: no file under `phantom/reliability/`
  contains a decision-shaped function name (`decide_`, `score_`,
  `size_`, `select_`) — mirrors Phase 1's own `test_structural_boundary.py`
  pattern.

## 11. Performance requirements

Health reporting/kill-switch checks must be cheap enough to call as a
precondition on every other live component's decision cycle without
becoming a bottleneck (target: sub-millisecond `is_halted()` check,
validated during implementation).

## 12. Failure modes

| Failure | Expected behavior |
|---|---|
| A component stops reporting health | Surfaces as `unhealthy`/`unknown`, does not itself trip the kill switch automatically in this phase (auto-recovery/auto-trip policy is explicitly out of scope here — interfaces only) unless a future, separately-approved policy adds that behavior. |
| `kill_switch.trip()` called concurrently from two sources | Idempotent — the switch is either tripped or not; the second call is a no-op recording an additional reason, not a second state. |

## 13. Security considerations

In-process library, no external network surface in this phase.
Clearing a tripped kill switch should be logged with who/when once an
operator-facing surface exists (out of scope for this phase's
interfaces-only build).

## 14. Logging requirements

`logging.py` is the structured-log sink/rotation/retention layer every
other component's own `logging_sink.py` writes through — one logging
infrastructure, not eight. `metrics.py` tracks per-component health
status over time, kill-switch trip/clear events, and (once wired)
latency measurements.
