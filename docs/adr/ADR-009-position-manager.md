# ADR-009 — Position Manager

Status: Proposed

Owner: Backend Architect (analogous to `ADR-005`/`ADR-008` — reliability
and lifecycle-state ownership)

Reviewed by: SRE (operational monitoring of open positions is squarely
its "Watchdog function" lane per `TEAM.md`), Security Architect
(emergency-close and kill-switch-adjacent paths warrant the same
consultation `TEAM.md` gives Risk/Compliance/MT5 Bridge)

**Note:** `.claude/agents/TEAM.md`'s RACI table has no existing row for
"Position Manager" (its per-component table only covers components that
already existed as of the last audit: Scanner, Scorer, Strategy
Orchestrator, Risk Engine, Compliance, MT5 Bridge, Execution, Watchdog,
API, Dashboard, Testing). This ADR does not modify `TEAM.md` to add one —
that is a documentation change outside this deliverable's scope — but
flags it below as a finding for the architectural review.

Date: 2026-07-04

Depends on: `ADR-001-single-authority-architecture.md` (Accepted),
`ADR-002-scanner.md` (Accepted, including Amendment 1),
`ADR-003-strategy-engine.md` (Accepted), `ADR-004-scoring-engine.md`
(Proposed), `ADR-005-risk-engine.md` (Proposed),
`ADR-006-compliance-engine.md` (Proposed),
`ADR-007-execution-validator.md` (Accepted),
`ADR-008-mt5-bridge.md` (Accepted)

---

# Pipeline position

Market Data → Scanner → Strategy Engine → Scoring Engine → Risk Engine →
Compliance Engine → Execution Validator → MT5 Bridge → **Position
Manager** → Analytics

The Position Manager begins **only after MT5 confirms an order has been
executed** — it consumes MT5 Bridge's `ExecutionReceipt`/`FillReport`
(`ADR-008` §5) and never acts before a fill exists. It does not define
Analytics (`ADR-010`, not yet drafted), which is the intended consumer of
the position history this stage produces.

---

# 1. Mission

**The Position Manager answers exactly one question: "How should an
already-open position be managed throughout its lifecycle?"**

**It never decides whether to open a trade.** That decision was already
made, in full, by Strategy Engine, Scoring Engine, Risk Engine,
Compliance Engine, and Execution Validator, and already executed by MT5
Bridge. This stage exists entirely downstream of a fill — it manages what
already exists, it does not create what doesn't.

---

# Hard Rules

These override any other requirement in this document if they ever
appear to conflict:

- **Never creates trades, never generates `CandidateTrade`.** If a
  position-management rule concludes that a *new* trade would be
  desirable (e.g. re-entry after a stop-out), that conclusion is not
  this stage's to act on — it would have to re-enter the pipeline from
  Scanner, like any other candidate. This stage manages existing
  positions only.
- **Never modifies any upstream decision** — `ScannerObservation`,
  `ScoreResult`, `RiskDecision`, `ComplianceDecision`, `ExecutionDecision`
  all remain immutable, read-only, historical record.
- **Never bypasses MT5 Bridge.** Every position modification (SL/TP
  change, partial close, full close) this stage decides on is expressed
  as an output request (`PositionCloseRequest` /
  `PositionAdjustmentRequest`, §5) that flows back through MT5 Bridge for
  actual broker communication. The Position Manager never talks to MT5
  directly — see §9 for why this reverse edge does not violate
  `ADR-001`'s single-authority pipeline.
- **Never overrides Compliance.** A kill-switch or lockout state from
  Compliance Engine constrains what this stage may do (e.g. emergency
  close may still be required, but no *new* risk may be added to a
  position while Compliance is in a blocking state); this stage cannot
  lift or override that state.
- **If synchronization cannot be restored: freeze management. Never
  invent position state. Never guess.**

---

# 2. Responsibilities

The Position Manager SHALL:

- Monitor open positions.
- Track unrealized P/L.
- Move Stop Loss when rules allow.
- Move to Break Even.
- Manage Trailing Stops.
- Manage Partial Closures.
- Manage Time-Based Exits.
- Manage Emergency Exits.
- Detect synchronization discrepancies reported by `ADR-008`
  (`SynchronizationStatus`).
- Resolve position synchronization after reconnect — the resolution
  authority `ADR-008` §8/§9 explicitly forward-declared to this stage.
- Produce `PositionManagementDecision` objects.

---

# 3. The Position Manager shall never

| Forbidden action | Owned instead by |
|---|---|
| Create trades | Strategy Engine (`ADR-003`) |
| Generate `CandidateTrade` | Strategy Engine (`ADR-003`) |
| Modify Scanner observations | Nobody — immutable (`ADR-002` §8) |
| Modify scores | Nobody — immutable (`ADR-004` §6) |
| Modify `RiskDecision` | Nobody — immutable (`ADR-005` §4) |
| Modify `ComplianceDecision` | Nobody — immutable (`ADR-006` §4) |
| Modify `ExecutionDecision` | Nobody — immutable (`ADR-007` §4) |
| Bypass MT5 Bridge | MT5 Bridge (`ADR-008`) — sole broker-communication authority |
| Override Compliance | Compliance Engine (`ADR-006`) |

---

# 4. Inputs

- **`ExecutionReceipt`**, **`FillReport`** (`ADR-008` §5) — the fill
  event that brings a position into existence for this stage; read-only.
- **Live Position State** — this stage's own tracked view of each open
  position's lifecycle (§7).
- **Broker Position State** — MT5's actual position record, read fresh,
  for reconciliation (§8's synchronization-recovery rule).
- **Account State** — current equity/margin, read fresh, for
  P/L tracking and emergency-close evaluation.
- **Market Data** — current price, for unrealized P/L, trailing-stop, and
  break-even evaluation.
- **Configuration** — break-even trigger distance, trailing-stop
  parameters, partial-close schedule, maximum duration, emergency-close
  conditions — all versioned, the same configuration-governance
  discipline established at every prior stage.
- **`SynchronizationStatus`** (`ADR-008` §5) — the discrepancy signal
  this stage is the designated consumer of (§8).

---

# 5. Outputs

One record per event, never discarded — the same discipline established
at every prior stage.

- **`PositionManagementDecision`** — the stage's own decision record (§6):
  what action was decided for a given position and why.
- **`PositionUpdate`** — a routine state update (P/L, current lifecycle
  stage, §7) that does not itself request any broker action.
- **`PositionCloseRequest`** — a request (full or partial) to close a
  position, routed to MT5 Bridge for execution; never sent to the broker
  directly (Hard Rules).
- **`PositionAdjustmentRequest`** — a request to modify SL/TP (break-even,
  trailing) on an open position, routed to MT5 Bridge for execution;
  never sent to the broker directly.
- **`PositionSynchronizationResult`** — the outcome of this stage's
  reconciliation after an `ADR-008` `SynchronizationStatus` discrepancy
  or a reconnect event (§8).

**Type-level guarantee:** none of these output types is structurally
capable of holding a modified upstream decision field or a new trading
instruction — the same guarantee established for every prior stage's
output type, verified by a dedicated test (§14).

**Immutability:** every output type, once produced, is immutable — a
record of a decision or an observation, not a mutable working object.

---

# 6. `PositionManagementDecision` model

**Allowed:**

- Action — one of: `NO_ACTION`, `MOVE_TO_BREAKEVEN`, `MOVE_STOP_LOSS`,
  `TRAIL_STOP`, `PARTIAL_CLOSE`, `TIME_EXIT`, `EMERGENCY_CLOSE`.
- `position_id`, `trace_id` (inherited from the position's originating
  `ExecutionDecision`), `decision_reason` (which rule in §8 produced this
  action).
- Timestamp, schema version, metadata.

**Forbidden:**

- Any modification to `ScannerObservation`, `ScoreResult`, `RiskDecision`,
  `ComplianceDecision`, or `ExecutionDecision`.
- Direct broker communication — an action here is a decision, not a
  submission; submission happens only via MT5 Bridge acting on
  `PositionCloseRequest`/`PositionAdjustmentRequest` (§9).
- A new `CandidateTrade` or anything resembling one (Hard Rules).

**Type-level guarantee and immutability:** as established in §5.

---

# 7. Position lifecycle

A position moves through the following states, tracked by this stage
from fill to close:

- **Open** — order submitted by MT5 Bridge, not yet confirmed filled.
- **Filled** — `ExecutionReceipt`/`FillReport` received; the position now
  exists for this stage's purposes.
- **Protected** — stop loss has been moved to break-even or better, per
  §8's break-even rule.
- **Trailing** — a trailing-stop rule (§8) is actively adjusting the stop
  as price moves favorably.
- **Scaling** — a partial-close rule (§8) has reduced the position's size
  at least once; the remaining portion continues through the lifecycle.
- **Closing** — a `PositionCloseRequest` has been issued and is awaiting
  broker confirmation via MT5 Bridge.
- **Closed** — broker-confirmed close; terminal state.
- **Recovered** — Live Position State was rebuilt from Broker Position
  State after a detected internal discrepancy (not preceded by a
  connection loss) — see §8.
- **Recovered After Disconnect** — Live Position State was rebuilt from
  Broker Position State specifically after an MT5 Bridge reconnect
  (`ADR-008` §9); tracked distinctly from **Recovered** so that
  reconnect-driven recoveries are separately auditable in logs and
  metrics (§11, §12).

A position may pass through **Protected**, **Trailing**, and **Scaling**
in any combination or order permitted by configuration; **Recovered** and
**Recovered After Disconnect** may interrupt any other state and return
the position to whichever state Broker Position State indicates it
actually belongs in.

---

# 8. Position management rules

- **Break-even** — once unrealized profit reaches a configured distance,
  stop loss moves to entry (or entry plus a configured buffer); moves the
  position to **Protected** (§7). Idempotent: re-evaluating an
  already-Protected position does not re-issue the same adjustment.
- **Trailing** — once configured trailing conditions are met, stop loss
  is adjusted to maintain a configured distance behind favorable price
  movement; never moved against the position's favor. Moves the position
  to **Trailing**.
- **Partial close** — at configured profit thresholds, a configured
  fraction of the position is closed via `PositionCloseRequest`; the
  remaining size continues through the lifecycle in **Scaling**.
- **Maximum duration** — a position open longer than a configured maximum
  duration is closed via a `TIME_EXIT` `PositionManagementDecision`,
  regardless of current P/L.
- **Emergency close** — a configured emergency condition (e.g. Compliance
  Engine kill-switch, `ADR-006` §14, becoming active while a position is
  open) produces an `EMERGENCY_CLOSE` decision; this is a close request,
  not an override of Compliance — the Position Manager is acting *in
  response to* Compliance's state, never overriding it (Hard Rules).
- **Synchronization recovery** — on a detected discrepancy
  (`SynchronizationStatus` from `ADR-008`, or an internally detected
  mismatch), Live Position State is rebuilt from Broker Position State,
  never the reverse — MT5's actual state is always ground truth for
  reconciliation. Produces a `PositionSynchronizationResult` and moves
  the affected position to **Recovered** or **Recovered After Disconnect**
  (§7) as applicable.

---

# 9. Closing the loop: routing through MT5 Bridge

**This stage is the first in the pipeline whose output flows backward to
an earlier stage rather than only forward.** `ADR-001`'s pipeline diagram
is linear; `PositionCloseRequest` and `PositionAdjustmentRequest` are
consumed by MT5 Bridge (`ADR-008`), which sits before this stage in that
diagram.

**This does not violate `ADR-001`'s single-authority principle.** What
flows backward is an execution *request* for an already-existing
position, not a new trading *decision* — the decision authority chain
(Strategy → Scoring → Risk → Compliance → Execution Validator) remains
strictly forward and is not reopened. MT5 Bridge's role in consuming
these requests is the same translation-and-submission role it already
has for opening trades (`ADR-008` §2) — it does not re-decide anything
here either, only relays to the broker.

**This reveals a genuine gap in `ADR-008` as currently Accepted, not a
new authority this ADR is claiming for itself.** `ADR-008` §2 and §5
describe MT5 Bridge accepting and translating `ExecutionDecision`
(opening trades) into `BrokerRequest`, and describe its outputs in terms
of that flow. `ADR-008` does not currently describe accepting a
`PositionCloseRequest` or `PositionAdjustmentRequest` as a distinct input
type, nor translating those into MT5 modify/close order requests. **This
ADR does not modify `ADR-008` to close that gap** — `ADR-008` is already
Accepted, and per this session's established pattern (`ADR-002`
Amendment 1), extending an Accepted ADR's scope requires an explicit
amendment, not a silent assumption baked into a downstream ADR. This is
raised as a finding in the architectural review below, for an explicit
decision on how to proceed.

---

# 10. Fail-safe behavior

**If synchronization cannot be restored: freeze management.** No
`PositionCloseRequest`, `PositionAdjustmentRequest`, or any other action
besides continued monitoring is issued for an affected position until
Live Position State and Broker Position State are reconciled. **Never
invent position state. Never guess** — an unreconciled position is
neither assumed open-as-expected nor assumed closed; it is held in an
unresolved state, monitored, and reported, exactly as `ADR-008` §8
already establishes for its own safe-halt behavior.

---

# 11. Determinism

Same inputs (including current Live Position State and configuration) →
same `PositionManagementDecision`. No randomness, no AI, no learning —
the same requirement `ADR-001` establishes for every stage in the
decision-making pipeline.

---

# 12. Logging

Every position action must carry:

- `trace_id`
- `position_id`
- `decision_reason`
- `timestamp`

Every logged action is attributable to a specific position and a
specific rule (§8) without re-running anything, the same explainability
discipline established at every prior stage.

---

# 13. Metrics

- Open position count.
- Positions per lifecycle state (§7).
- Break-even/trailing/partial-close/time-exit/emergency-close counts,
  each as its own labeled counter.
- Synchronization-recovery count, split by **Recovered** vs. **Recovered
  After Disconnect** (§7).
- Average position duration.
- Export-only, additive — the same discipline established at every prior
  stage.

---

# 14. Testing

- **Unit tests** — isolated, fixture-based, no dependency on a live
  broker connection.
- **Reconnect recovery test** — Live Position State is correctly rebuilt
  from Broker Position State after a simulated `ADR-008` reconnect,
  landing in **Recovered After Disconnect**.
- **Duplicate fill handling test** — a duplicate `FillReport` for an
  already-tracked position does not create a second position or
  double-count size.
- **Partial close test** — a partial-close rule produces the correct
  remaining size and transitions to **Scaling**.
- **Trailing stop test** — stop-loss adjustments only ever move in the
  position's favor, never against it.
- **Break-even test** — the break-even rule is idempotent (§8) and
  transitions to **Protected** exactly once.
- **Synchronization recovery test** — an injected discrepancy between
  Live Position State and Broker Position State produces a
  `PositionSynchronizationResult` and freezes management (§10) until
  resolved.
- **Time-exit test** — a position exceeding maximum duration produces a
  `TIME_EXIT` decision regardless of P/L.
- **Emergency-close test** — a Compliance kill-switch event produces an
  `EMERGENCY_CLOSE` decision without this stage claiming override
  authority over Compliance.
- **Replay compatibility test** — identical historical inputs (fills,
  price series, configuration) reproduce identical
  `PositionManagementDecision` sequences.
- **Boundary/type-level test** — no output type (§5) can hold a modified
  upstream decision field or a new `CandidateTrade`.

---

# 15. Security

- The Position Manager holds **no order-placement credentials** — it
  never communicates with MT5 directly (§9), preserving `ADR-008` §10's
  invariant that MT5 Bridge is the sole stage with order-placement
  capability.
- All upstream inputs (`ScannerObservation`, `ScoreResult`,
  `RiskDecision`, `ComplianceDecision`, `ExecutionDecision`) remain
  read-only; none are mutated.
- Broker Position State is treated as ground truth for reconciliation
  (§8) but is never treated as authorization to act — every action still
  requires this stage's own rule evaluation (§8) before a request is
  issued.

---

# 16. Architectural invariants

- Position Manager only manages existing positions.
- It never creates new trades.
- It never changes upstream decisions.

---

# 17. Acceptance criteria

ADR-009 is acceptable only if it guarantees:

- ✓ Position lifecycle fully defined (§7).
- ✓ Synchronization recovery defined (§8, §10).
- ✓ No upstream authority duplicated — every immutable upstream object
  remains untouched (§3, §6).
- ✓ No execution authority duplicated — all broker communication routes
  through MT5 Bridge, never directly (§9, §15).
- ✓ No risk authority duplicated — this stage reacts to Compliance/Risk
  state (e.g. emergency close) but never overrides or resizes it (Hard
  Rules, §8).

---

# 18. Reference material — ideas only, not authority

- **No break-even, trailing-stop, partial-close, or position-lifecycle
  management code exists anywhere in this repository** (verified: no
  matches for trailing/break-even/partial-close logic in `phantom/` or
  `phantom_institutional.py`). As with `ADR-008`, there is no legacy
  position-management module to mine for ideas — this stage is designed
  entirely from first principles.
- `phantom_institutional.py`'s `open_positions` tracking
  (`update_position`, correlation-adjusted sizing over open positions) —
  studied only as an idea of what a minimal open-position ledger looks
  like; it is sizing-input bookkeeping, not lifecycle management, and is
  not otherwise reused here.
- `phantom/trade_router.py` and `phantom_institutional.py` more broadly —
  studied as the same negative example every prior ADR's reference
  review has identified: no distinct position-lifecycle stage exists,
  separate from sizing/decision logic.

---

Per `ADR-001` and `CLAUDE.md` §1.10, **no implementation begins until this
ADR's Status changes from Proposed to Accepted.**
