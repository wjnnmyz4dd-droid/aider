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
- Receive `phantom/runtime/runtime.py`'s per-cycle health/outcome
  report (Architecture Hardening — `docs/specs/00_runtime_orchestrator.md`
  §5 step 8, observer role) — this is now the concrete meaning of "watch
  every other component": Runtime tells this component what happened
  each cycle; this component does not itself drive the cycle.
- **Own operator authentication and authorization for every
  administrative action in the system** (Architecture Hardening,
  closes Red Team Audit Finding 17.1) — see §"Operator authentication"
  below.

## 3. Public interfaces

```
reliability_engine.kill_switch.trip(reason: str, operator: OperatorIdentity, now: Clock) -> None
reliability_engine.kill_switch.clear(operator: OperatorIdentity, now: Clock) -> None
reliability_engine.is_halted() -> bool
reliability_engine.health_monitor.report(component_name: str, status: HealthStatus) -> None
reliability_engine.health_monitor.snapshot() -> Mapping[str, HealthStatus]
reliability_engine.record_cycle(report: CycleReport) -> None
reliability_engine.operator_auth.authenticate(credentials: OperatorCredentials) -> Optional[OperatorIdentity]
reliability_engine.operator_auth.authorize(operator: OperatorIdentity, action: AdministrativeAction) -> bool
reliability_engine.operator_auth.audit(operator: OperatorIdentity, action: AdministrativeAction, result: bool, now: Clock) -> None
```

`auto_recovery.py`'s recovery-action interface is defined but has no
implemented action in this phase (see §9). `kill_switch.trip`/`clear`
now require an `OperatorIdentity` (revised from the prior, unauthenticated
signature) — every call must have already passed
`operator_auth.authenticate`/`authorize`.

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
| `KillSwitchState` | active/inactive, trigger reason, tripped_at, cleared_at, tripped_by/cleared_by (`OperatorIdentity`) |
| `OperatorIdentity` | authenticated operator's stable identifier (never a raw credential) |
| `OperatorCredentials` | opaque input to `authenticate()` — shape intentionally unspecified here (a future, separately-approved decision: password/token/SSO/etc.), so this spec commits only to the authentication *seam* existing, not a specific mechanism |
| `AdministrativeAction` | enum: `EMERGENCY_STOP`, `RESUME`, `MANUAL_OVERRIDE`, `MAINTENANCE_MODE_TOGGLE`, `CONFIGURATION_CHANGE` — the minimum set this hardening task names |
| `AuditRecord` | operator, action, result (allowed/denied), timestamp — one per `operator_auth.audit()` call, never overwritten |

## 7. Decision authority

The one system-wide halt authority above every live component's own
internal state, **and the one operator-authentication/authorization
authority for the whole system.** `kill_switch.trip()` must be
respected unconditionally by every live component's `is_halted()`
check — none of them may proceed on the theory that their own inputs
still look fine. No other component defines its own operator-identity
or authorization concept (see §"Operator authentication").

## 8. Dependencies

`phantom/shared/`, plus PhantomBridgeEA's existing telemetry/
`ConnectionHealth` for the connectivity piece (Phase 1, already built,
read-only), plus `phantom/runtime/runtime.py`'s per-cycle
`CycleReport` (observer input, §2).

## Operator authentication (Architecture Hardening — closes Red Team
Audit Finding 17.1)

Three separate mechanisms previously referenced "an operator clears
it" with no shared definition of who that is: Compliance Engine's
emergency lockout, Market Intelligence Engine's peg/policy block, and
this component's own kill switch. All three now route through this
component's `operator_auth` surface rather than each inventing its own
notion — a single, consistent authority, not three independent (and
potentially inconsistent) ones.

**Minimum administrative actions requiring authentication** (per this
hardening task's explicit list): emergency stop, resume, manual
overrides, maintenance-mode toggles, and configuration changes —
covering the kill switch (this component), the emergency lockout
(Compliance Engine), the peg/policy block (Market Intelligence Engine),
and any future rule-set/configuration change to any component.

**Procedure:** every administrative action calls
`operator_auth.authenticate(credentials)` to obtain an `OperatorIdentity`
(or `None`, meaning the action is refused outright), then
`operator_auth.authorize(operator, action)` to confirm that identity
may perform that specific action, then performs the action only if both
succeed, and finally calls `operator_auth.audit(...)` unconditionally —
recording denied attempts is as important as recording successful ones.

**What this component does not decide:** the actual credential
mechanism (password, token, SSO, hardware key) is deliberately left
open — committing to one here would be scope beyond "revise
specifications to close the audit findings." What this hardening task
does commit to is that the *seam* exists, is singular, and is audited,
so a future, separately-approved decision can fill in the mechanism
without touching three other components' specs again.

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
- Never drives the decision-cycle loop itself — that is
  `phantom/runtime/runtime.py`'s job (§2); this component only checks
  `is_halted()` is respected and receives the completed cycle's report.
- Never lets Compliance Engine or Market Intelligence Engine define
  their own operator-identity/authorization concept — both must call
  into this component's `operator_auth` surface.

## 10. Test plan

- Unit tests for `KillSwitchState` transitions (trip/clear, including
  clearing while not tripped, tripping while already tripped), now
  requiring a valid `OperatorIdentity` for both.
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
- **Unauthenticated-action-rejected test** (closes Finding 17.1): a
  `trip()`/`clear()` call with invalid/missing credentials is refused,
  performs no state change, and still produces an `AuditRecord` with
  `result: denied`.
- **Cross-component authorization test:** Compliance Engine's
  emergency-lockout clear and Market Intelligence Engine's peg/policy
  block clear both route through, and are both refused/audited
  identically by, this component's `operator_auth` surface — proving
  the "single authority, not three" property.
- **Every-administrative-action audited test:** each of the five
  `AdministrativeAction` values produces exactly one `AuditRecord` per
  attempt, success or failure.

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

In-process library, no external network surface in this phase beyond
whatever `operator_auth.authenticate()`'s eventual credential mechanism
requires (deliberately unspecified here, §"Operator authentication").
Every administrative action is authenticated, authorized, and audited
unconditionally — no action bypasses this path, including one taken by
whatever process embeds this engine (no "trusted internal caller"
exception, which would be exactly the kind of ad hoc, unaudited path
Finding 17.1 identified). Account-identifying data in `AuditRecord`/
`HealthStatus`/logs follows the redaction/retention policy in §14
(closes Red Team Audit Finding 18.1).

## 14. Logging requirements

`logging.py` is the structured-log sink/rotation/retention layer every
other component's own `logging_sink.py` writes through — one logging
infrastructure, not eight. **Redaction/retention policy (closes Finding
18.1):** account-identifying fields (balance, equity, account login)
passing through this sink are redacted per a configured policy before
long-term retention, enforced once, centrally, rather than by each of
the eight components' own `logging_sink.py` independently deciding
what to redact. `metrics.py` tracks per-component health status over
time, kill-switch trip/clear events, every `AdministrativeAction`
audit outcome, and (once wired) latency measurements.
