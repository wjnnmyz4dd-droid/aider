# ADR-011 — Watchdog & Recovery

Status: Accepted

Acceptance Date: 2026-07-04

Accepted By: Software Architect / Titan Protocol Engineering Council

Owner: SRE (Accountable per `.claude/agents/TEAM.md` §5 RACI, Watchdog
row — this ADR is that row's own governance, made concrete)

Reviewed by: Backend Architect (Consulted per `TEAM.md`'s RACI —
infrastructure/reliability contract), Security Architect (Consulted per
`TEAM.md`'s RACI — the restart/recovery surface sits adjacent to every
trading stage including MT5 Bridge, warranting the same review posture
`TEAM.md` already gives Compliance/Execution/MT5 Bridge). Software
Architect is Informed per the same RACI row, not a required reviewer.

Date: 2026-07-04

Depends on: `ADR-001-single-authority-architecture.md` (Accepted),
`ADR-002-scanner.md` (Accepted, including Amendment 1),
`ADR-003-strategy-engine.md` (Accepted), `ADR-004-scoring-engine.md`
(Accepted), `ADR-005-risk-engine.md` (Accepted),
`ADR-006-compliance-engine.md` (Accepted),
`ADR-007-execution-validator.md` (Accepted),
`ADR-008-mt5-bridge.md` (Accepted, including Amendment 1),
`ADR-009-position-manager.md` (Accepted),
`ADR-010-analytics-decision-provenance.md` (Accepted),
`docs/adr/ADR-015-external-data-sources-api-governance.md` (Proposed —
already names this ADR as the consumer of Database session logs, the
Telegram alerting channel, and the health signals defined in its §10
Operational Requirements; this ADR fulfills those forward references)

---

# Pipeline position

**The Watchdog is not part of the deterministic trading pipeline.** It is
a cross-cutting operational service that observes every stage —
Market Data through Analytics — without occupying a position in the
decision chain. Nothing in the pipeline (Scanner through Analytics)
depends on the Watchdog to produce a trading decision; the Watchdog
depends on every stage to produce the health/metrics signals it observes.

---

# 1. Mission

**The Watchdog answers exactly one question: "Is the Titan Protocol system
healthy enough to continue operating safely?"**

**It never answers:** Should we trade? Should we execute? Should we
modify a position? Should we change risk? Should we bypass compliance?
Those are the trading pipeline's questions, each already answered by its
own Accepted ADR. The Watchdog's entire mandate is operational: it
observes, it reports, and within a narrow, explicitly bounded set of
infrastructure actions (§7), it recovers — it never decides.

---

# Hard Rules

These override any other requirement in this document if they ever
appear to conflict:

- **The Watchdog never makes a trading decision, directly or indirectly.**
  It has no output any trading stage (Scanner through Analytics) is
  required, or permitted, to treat as an instruction.
- **Never hide failures. Never fabricate a healthy status.** An unknown
  or unreachable component is reported as unknown or unreachable, never
  defaulted to `HEALTHY` for the sake of a quiet dashboard.
- **Recovery is infrastructure-only.** The Watchdog may restart processes,
  reconnect dependencies, and perform the bounded actions in §7 — it may
  never create, close, or modify a trade or a position, and it may never
  override Compliance, Risk, or the Execution Validator (§4).
- **No hidden execution path.** The Watchdog has no broker authority, no
  trade authority, no strategy authority (§15).
- **Bounded recovery, not infinite retry.** Repeated recovery failure
  escalates and freezes further automatic recovery for that component
  (§8) — it never loops indefinitely hoping the next attempt succeeds.

---

# 2. Responsibilities — what the Watchdog monitors

The Watchdog SHALL monitor, as a read-only observer:

**Pipeline stages** (via each stage's own already-Accepted Logging/Metrics
outputs — see the boundary note below): Market Data (tracked as the MT5
Broker Feed's health, `ADR-015`), Scanner (`ADR-002`), Strategy Engine
(`ADR-003`), Scoring Engine (`ADR-004`), Risk Engine (`ADR-005`),
Compliance Engine (`ADR-006`), Execution Validator (`ADR-007`), MT5
Bridge (`ADR-008`), Position Manager (`ADR-009`), Analytics (`ADR-010`).

**Infrastructure:** CPU, Memory, Disk, Network, VPS, System Clock,
Filesystem.

**External dependencies** (per `ADR-015`'s already-governed list):
External APIs (MT5, News/Calendar), Database, Configuration, Secrets,
Network, Clock synchronization.

**Operational surfaces:** Log Health (are logs being written/rotated as
expected), Heartbeat Health (§9).

**Boundary note — the Watchdog introduces no new instrumentation
requirement on already-Accepted stage ADRs.** Every pipeline stage
(`ADR-002` through `ADR-010`) already mandates its own Logging and
Metrics sections, each independently accepted. The Watchdog's per-stage
monitoring is built entirely on top of what those sections already
export — it does not retroactively require Scanner, Strategy Engine,
Scoring Engine, Compliance Engine, Execution Validator, Position Manager,
or Analytics to add anything they don't already have. One real gap
follows from this: only `ADR-008` (MT5 Bridge) currently defines an
explicit **heartbeat** concept (§6, Connection management). For every
other stage, the Watchdog's "Heartbeat Health" (§9) is necessarily a
**liveness proxy** — whether that stage's already-defined periodic
metric/log output arrived within its expected interval — not a
dedicated heartbeat signal, because no such signal exists yet in those
stages' Accepted text. This is flagged as an open item in the
architectural review below, not silently assumed resolved.

---

# 3. Position and scope

- The Watchdog is a **cross-cutting operational service**, not a pipeline
  stage. It has no `trace_id`-chained position between two adjacent
  stages the way Scanner through Analytics do.
- **It observes every stage. It controls no trading decisions.**
- It is distinct from Analytics (`ADR-010`): Analytics owns permanent
  **decision provenance** — what a trade was, why it happened, replayable
  business history. The Watchdog owns **operational health** — is the
  system alive, responsive, and running within its infrastructure limits,
  right now. Analytics answers "what happened to this trade"; the
  Watchdog answers "is the system currently able to keep operating
  safely." Overlap is intentional at the edges (both consume some of the
  same underlying metrics) but their outputs (`TradeProvenanceRecord` vs.
  `SystemHealth`, §5) are never confused with each other, and neither
  feeds into a live trading decision (`ADR-010` §3, this ADR's Hard
  Rules).

---

# 4. The Watchdog must never

| Forbidden action | Owned instead by |
|---|---|
| Create trades | Strategy Engine (`ADR-003`) |
| Close trades | Position Manager (`ADR-009`) |
| Modify positions | Position Manager (`ADR-009`) |
| Override Compliance | Compliance Engine (`ADR-006`) — see §6's boundary note on how the Watchdog's signals reach Compliance without overriding it |
| Override Risk | Risk Engine (`ADR-005`) |
| Override the Execution Validator | Execution Validator (`ADR-007`) |
| Bypass MT5 Bridge | MT5 Bridge (`ADR-008`) — sole broker-communication authority |
| Author or choose configuration values | Whichever stage's own ADR owns that configuration (§7 — the Watchdog may only trigger an already-defined reload, never invent a value) |

---

# 5. `SystemHealth` model

**Allowed:**

- **Overall Health** — the worst (most severe) state across every
  monitored component (§6's severity ladder), never an average or a
  majority vote — the same "never assume the best case" discipline every
  fail-closed stage in this pipeline already follows.
- **Component Health** — per-stage breakdown, one entry per pipeline
  stage (§2).
- **Infrastructure Health** — per-resource breakdown (CPU, Memory, Disk,
  Network, VPS, Filesystem, Clock).
- **External Dependency Health** — per-dependency breakdown (§10), sourced
  from `ADR-015`'s already-defined health signals, never re-derived.
- **Heartbeat Status** — per §9.
- **Synchronization Status** — the Watchdog's own aggregated *view* of
  `SynchronizationStatus` (`ADR-008` §5) and `PositionSynchronizationResult`
  (`ADR-009` §5); the Watchdog observes and surfaces these, it does not
  recompute or reissue them — MT5 Bridge and Position Manager remain the
  sole authorities on what those objects mean.
- **Recovery Status** — whether recovery is currently in progress for a
  component, and the outcome of the most recent attempt (§7, §8).
- **Failure Reason** — why a component is not `HEALTHY`, if applicable.
- **Timestamp, `trace_id`, System Version** — `trace_id` here identifies
  a health-event chain (this ADR's own monitoring activity), distinct
  from a trading `trace_id` chain (`ADR-002` §8 onward); System Version
  identifies the deployed code/config/ADR-set version, the system-wide
  analogue of each stage's own `schema_version`.

**Forbidden:**

- Any trading instruction, any modification to a trading decision object,
  any field resembling `CandidateTrade`/`ScoreResult`/`RiskDecision`/
  `ComplianceDecision`/`ExecutionDecision`/`PositionManagementDecision`.

**Type-level guarantee:** `SystemHealth` is structurally incapable of
holding a trading instruction or a modified trading-decision field — the
same guarantee established for every prior stage's output type, verified
by a dedicated test (§14).

**Immutability:** each `SystemHealth` snapshot, once produced, is
immutable — a point-in-time record, superseded by the next snapshot, never
rewritten in place.

---

# 6. Health states

`UNKNOWN`, `STARTING`, `HEALTHY`, `DEGRADED`, `WARNING`, `RECOVERING`,
`CRITICAL`, `OFFLINE`, `SHUTDOWN`.

**Severity ladder, least to most severe, used for Overall Health
aggregation (§5):**

`HEALTHY` → `DEGRADED` → `WARNING` → `RECOVERING` → `CRITICAL` →
`OFFLINE`

- **`UNKNOWN` is treated as at least as severe as `CRITICAL`** for
  aggregation — an unreachable or unreported component is never assumed
  better than the worst known state (Hard Rules: never fabricate
  healthy).
- **`STARTING` and `SHUTDOWN` are lifecycle-phase states, not severity
  states.** A component in `STARTING` does not drag Overall Health to
  `CRITICAL`, but is also never reported as `HEALTHY` until it actually
  reaches that state. `SHUTDOWN` is a deliberate, operator-initiated stop
  — distinct from `OFFLINE`, which means unexpectedly down.
- **`RECOVERING`** means an active recovery action (§7) is in progress for
  that component; it is more severe than `WARNING` because it indicates a
  detected fault, even though remediation is underway.

---

# 7. Recovery

**The Watchdog may:**

- Restart failed services.
- Restart failed workers.
- Reconnect dependencies.
- Rebuild connections.
- Clear stale heartbeats.
- Restart monitoring.
- Rotate logs.
- Reload configuration.

Every one of these is a bounded **infrastructure** action, not a
**decision** action:

- **"Restart failed services/workers"** — restarts the *process*. It does
  not, and cannot, skip whatever reconnection/reconciliation behavior
  that stage's own Accepted ADR already requires after a restart (e.g.
  `ADR-008` §9's mandatory synchronization before resuming submission,
  `ADR-009` §8's freeze-until-reconciled fail-safe). The Watchdog
  triggers the restart; the stage's own already-Accepted logic governs
  what happens next. The Watchdog never holds or exercises the
  credentials that would let it skip that logic (§15).
- **"Reload configuration"** — triggers an already-defined reload
  mechanism for a stage's already-versioned configuration (e.g. `ADR-005`
  §"no self-adjusting risk without versioned configuration"). The
  Watchdog never authors, selects, or modifies a configuration value —
  it only triggers the reload of a value some other stage's own ADR
  already governs (§4's table).
- **"Clear stale heartbeats"** — resets the Watchdog's own tracking
  record so a falsely-flagged-stale-but-actually-alive component can be
  re-evaluated fresh. This is not the same as asserting the component is
  healthy — the next real signal still has to arrive and be evaluated
  before `HEALTHY` is reported (Hard Rules: never fabricate).

**Bounded recovery — repeated-restart protection:** recovery attempts for
a given component are bounded and backoff-based, the same shape
`ADR-008` §6 already established for its own reconnect policy. Exceeding
the bound within a configured window moves that component to `CRITICAL`
and **freezes further automatic recovery** for it (§8) — the Watchdog
does not loop indefinitely.

**Determinism of recovery policy:** given the same health-state history
and the same bounded-attempt configuration, the Watchdog's recovery
*policy* (whether to attempt recovery, and when to stop and escalate
instead) is deterministic and configuration-driven — the same "no
randomness, no AI, no learning" requirement every trading stage carries.
This is distinct from the infrastructure state it observes, which is
inherently real-time and non-deterministic; that distinction does not
weaken the requirement, since the Watchdog makes no trading decision for
determinism to protect in the first place.

**The Watchdog must never:** create trades, close trades, modify
positions, override Compliance, override Risk, override the Execution
Validator, or bypass MT5 Bridge (§4) — restated here because every action
in this section sits operationally adjacent to the trading pipeline, and
none of them may cross into it.

---

# 8. Fail-safe behavior

**If recovery fails: escalate. Alert. Freeze recovery. Never hide
failures. Never fabricate healthy status.**

- Escalation raises the alert severity (§11) and, per `TEAM.md`'s SRE
  ownership of "incident response," is the point at which a human is
  expected to intervene — the Watchdog does not attempt to resolve a
  frozen component on its own beyond this point.
- Freezing recovery means no further automatic restart/reconnect attempt
  is made for that component until either a human clears the freeze or a
  fresh, unambiguously-healthy signal is observed directly (not induced
  by the Watchdog's own action).
- The component remains reported at its true severity (`CRITICAL` or
  `OFFLINE`) for as long as it is actually unhealthy — there is no
  mechanism by which a frozen, unrecovered component is reported as
  anything better than its last true observed state.

---

# 9. Heartbeats

- **Heartbeat intervals** — configured per monitored component; for MT5
  Bridge this is the interval already defined in `ADR-008` §6; for every
  other pipeline stage it is the liveness-proxy interval noted in §2's
  boundary note (derived from that stage's own existing periodic
  metric/log cadence, not a new dedicated signal).
- **Missed heartbeat thresholds** — a configured number of consecutive
  missed heartbeats before a component's severity increases (§6); a
  single missed heartbeat is not, by itself, treated as `CRITICAL`.
- **Recovery thresholds** — the bounded-attempt configuration referenced
  in §7; exceeding it triggers §8's freeze.
- **Heartbeat expiration** — a heartbeat older than its configured
  maximum age is treated as **no heartbeat received**, not as a stale-but-
  still-valid signal — mirroring `ADR-008` §6's "a missed heartbeat beyond
  a configured threshold transitions the connection state machine toward
  Disconnected."
- **Heartbeat history** — a bounded, TTL-pruned record of recent
  heartbeat events per component, the same bounded-and-pruned discipline
  `ADR-007` §7 and `ADR-008` §7 already established for their own
  state — unbounded growth here would repeat the same class of defect
  flagged elsewhere in the reference material.

---

# 10. Dependency monitoring

Monitored, per `ADR-015`'s already-governed external-dependency list:

- **MT5** (Broker Feed and MT5 Calendar) — health signal per `ADR-015`'s
  MT5 Broker Feed / Economic Calendar sections.
- **News** — the research-only/AI news layer's own availability
  (`ADR-016`), monitored the same way as any other external dependency;
  this is purely an uptime/reachability concern and has no bearing on
  `ADR-016`'s data-plane isolation from the live pipeline.
- **Database** — per `ADR-015`'s Database section.
- **Analytics** — included here per this task's own dependency list, but
  classified precisely: Analytics is not a true external dependency the
  way MT5/News/Database are — it is an internal pipeline stage with its
  own Accepted ADR (`ADR-010`). The Watchdog monitors Analytics' health
  the same way it monitors any other pipeline stage's health (§2), not
  as an "external dependency" in `ADR-015`'s sense.
- **Filesystem** — log directories, configuration files, and any local
  state the Watchdog or other stages depend on being writable/readable.
- **Configuration** — whether the currently-loaded configuration version
  matches what each stage expects (a mismatch is a Watchdog-observable
  condition, never a Watchdog-authored correction — §7's boundary).
- **Secrets** — whether credential/secret material required by a stage is
  present and unexpired, per `ADR-015` §9's least-privilege/rotation
  requirements; the Watchdog observes secret *availability and expiry*,
  it never reads, logs, or transmits secret *values*.
- **Network** — connectivity to every external dependency above.
- **Clock synchronization** — drift between the local system clock and a
  trusted time source; relevant because several stages (`ADR-002`'s
  session-window clock, `ADR-007`'s staleness/order-age checks) depend on
  an accurate clock to make correct fail-closed decisions.

---

# 11. Alerting

- **Critical alerts** — any component at `CRITICAL` or `OFFLINE`.
- **Warning alerts** — any component at `DEGRADED` or `WARNING`.
- **Recovery alerts** — entry into and exit from `RECOVERING`, and the
  outcome (success, or escalation per §8) of every recovery attempt.
- **Escalation rules** — a component remaining at `CRITICAL` beyond a
  configured duration, or exceeding the bounded-recovery-attempt limit
  (§7, §8), raises the alert's severity/urgency rather than repeating the
  same alert indefinitely at the same level.
- **Alert suppression** — a component in a deliberate `SHUTDOWN` state
  (planned maintenance) suppresses alerts for that component; this is the
  only condition under which an alert is suppressed, and it is always a
  deliberate, operator-visible state, never a silent default.
- **Alert deduplication** — repeated identical alerts for the same
  component within a configured window are collapsed into one alert with
  a repeat count, not resent individually — consistent with `ADR-015`
  §9's Telegram rate-limit constraint and its "must not retry so
  persistently that it delays a more urgent alert" requirement.
- **Delivery channel:** Telegram Bot API, per `ADR-015`'s Notifications
  section — **strictly outbound, notify-only.** The Watchdog never
  accepts an inbound command through this or any other channel; `ADR-015`
  §9 already prohibits Telegram as an inbound control surface by default,
  and this ADR does not reopen that prohibition (§15).

---

# 12. Logging

Every health event must include:

- `trace_id` (the Watchdog's own health-event chain, §5 — not a trading
  `trace_id`)
- `component`
- `severity`
- `timestamp`
- `reason`
- `recovery_action` (if any was attempted)

This makes every state change and every recovery action attributable
without re-running anything, the same explainability discipline
established at every prior stage.

---

# 13. Metrics

- Uptime
- Availability
- Recovery time
- Restart count
- Crash frequency
- Heartbeat latency
- Recovery success rate
- Dependency failures
- Export-only, additive — the same discipline established at every prior
  stage.

---

# 14. Testing

- **Unit tests** — isolated, fixture-based, no dependency on a live
  broker connection or live infrastructure.
- **Crash recovery test** — a simulated component crash triggers restart
  (§7) and correct `SystemHealth` reporting through the recovery cycle.
- **Heartbeat recovery test** — a missed-then-resumed heartbeat sequence
  produces the correct severity transitions (§6, §9).
- **Dependency failure test** — a simulated MT5/News/Database/Secrets
  failure (§10) is correctly reflected in External Dependency Health.
- **Network partition test** — a simulated network loss produces
  `CRITICAL`/`OFFLINE` for the affected dependencies, not a silent gap in
  reporting.
- **Database outage test** — a Database outage is reported and does not
  itself crash the Watchdog's own operation.
- **MT5 disconnect test** — mirrors `ADR-008` §13's disconnect/reconnect
  tests from the Watchdog's observing side: the Watchdog correctly
  reflects MT5 Bridge's own reported connection state, never
  re-deriving it.
- **Repeated restart protection test** — exceeding the bounded-recovery-
  attempt limit (§7) freezes recovery (§8) rather than looping.
- **Alert generation test** — every severity transition in §6 produces
  the correct alert class (§11).
- **False-positive suppression test** — a transient, single missed
  heartbeat below the configured threshold (§9) does not itself trigger
  a `CRITICAL` alert.
- **Boundary/type-level test** — `SystemHealth` cannot hold a trading
  instruction or a modified trading-decision field (§5).

---

# 15. Security

- **The Watchdog must never become a hidden execution path. It has no
  broker authority. It has no trade authority. It has no strategy
  authority.** (Hard Rules.)
- **No order-placement credentials.** Per `ADR-008` §10, MT5 Bridge
  remains the sole stage with order-placement capability; the Watchdog
  can restart the MT5 Bridge *process* (§7) but holds none of its
  credentials and cannot exercise or bypass its broker connection.
- **Telegram remains outbound-only.** Per `ADR-015` §9, the alerting
  channel is notify-only by default; this ADR introduces no inbound
  control surface, and any future proposal to add one requires its own
  ADR with explicit Security Architect review (`ADR-015` §9's own
  condition, not weakened here).
- **Secret values are never logged or transmitted** by the Watchdog — only
  their availability/expiry status (§10).
- **Configuration values are never authored by the Watchdog** — only
  reload of an already-versioned value it does not choose (§7).

---

# 16. Architectural invariants

- The Watchdog observes.
- It reports.
- It recovers infrastructure.
- It never makes trading decisions.
- Every recovery action is logged.
- Every restart is traceable.

---

# 17. Acceptance criteria

ADR-011 is acceptable only if it guarantees:

- ✓ Every component has health monitoring (§2, §5, §10).
- ✓ Every recovery action is deterministic — as a policy, not as a
  reflection of inherently real-time infrastructure state (§7).
- ✓ No trading authority exists (§1, §4, Hard Rules).
- ✓ Recovery sequencing is documented — bounded attempts, backoff,
  freeze-and-escalate on exhaustion (§7, §8).
- ✓ `SystemHealth` is fully defined (§5).

---

# 18. Reference material — ideas only, not authority

- **No legacy Watchdog implementation exists anywhere in this repository**
  (verified: no `watchdog.py` or equivalent in `titan_protocol/` or
  `phantom_institutional.py`). As with `ADR-008` and `ADR-009`, there is
  no legacy module to mine for ideas — this stage is designed entirely
  from first principles.
- `ADR-008` §6's connection-state-machine and heartbeat design is the
  direct structural idea behind this ADR's own heartbeat/health-state
  model (§6, §9) — generalized from one connection to every monitored
  component.
- `ADR-015` §9/§10 (Notifications, Operational Requirements) already
  specifies the Watchdog's alerting channel, alert triggers, and health-
  signal sources in detail; this ADR is the formal definition of the
  stage `ADR-015` was written anticipating, not a competing design.
- `TEAM.md`'s standing backlog item 2 (the account-feed observability
  gap — "no telemetry distinguishes 'account feed never connected' from
  'account feed healthy'") is the direct motivating example behind this
  ADR's `UNKNOWN`-is-at-least-`CRITICAL` aggregation rule (§6) — the
  exact defect this rule is designed to prevent from recurring.

---

Per `ADR-001` and `CLAUDE.md` §1.10, **no implementation begins until this
ADR's Status changes from Proposed to Accepted.**
