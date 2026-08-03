# Technical Specification — Runtime Orchestrator

Specification only. Closes Red Team Audit Finding 2.1 (Critical) and
Finding 12.1 (High). **Not a ninth engine** — a thin module,
`phantom/runtime/runtime.py`, that owns sequencing only.

## 1. Purpose

Be the one place that calls the 8 approved components in the approved
order, passes data between them, and enforces the two mandatory
preconditions (System Reliability's halt state, Market Intelligence's
entry gate) — so that no other component ever needs to reach across to
another live component on its own initiative, and no future
implementer has to *invent* an orchestration point because none was
ever named.

## 2. Responsibilities

- Drive one full evaluation cycle, per enabled pair, in exactly the
  approved order (see §5).
- Check System Reliability Engine's `is_halted()` once, at the start of
  each cycle, before calling anything else.
- Check Market Intelligence Engine's `get_entry_gate()` once per
  candidate `TradeIdea`, between Strategy Engine and Risk Engine.
- Pass each component's output to the next component's input exactly as
  each component's own spec defines — no transformation, no
  reinterpretation.
- Propagate a rejection from any stage (entry gate blocked, Risk Engine
  veto, Compliance Engine reject, or `submit_command`'s own rejection)
  to Research & Learning Engine's observer call, using each stage's own
  already-defined rejection/error type — never inventing a new
  business meaning for a rejection.
- Report cycle-level health/outcome (duration, which stage a cycle
  stopped at, error counts) to System Reliability Engine's observer
  surface.

## 3. Public interfaces

```
runtime.run_cycle(now: Clock) -> CycleReport
```

That is the only function. `run_cycle` takes no other input — every
other value it needs (enabled pairs, per-component config) is already
owned by the component that needs it; Runtime does not hold or pass
configuration on any component's behalf.

## 4. Inputs

A `Clock` (from `phantom/shared/`). Nothing else — every other input
Runtime touches is fetched from the component that owns it, not
supplied by a caller.

## 5. Execution order (per enabled pair, per cycle)

```
0. is_halted() check (System Reliability Engine)
   -- if true: skip this entire cycle, report "halted" to Reliability's
      own observer surface, do not call any of steps 1-8 below, for
      any pair.

For each enabled pair (order among pairs is unspecified/parallel-safe,
per Finding 16.1 -- no pair's evaluation may depend on another's):

1. Evidence Engine        get_pair_evidence(pair, now) -> PairEvidence
2. Strategy Engine        evaluate(pair, now, evidence) -> Tuple[TradeIdea, ...]
                          -- empty: this pair's cycle ends here, nothing
                             further is called for this pair.
3. Market Intelligence    get_entry_gate(pair, now) -> EntryGateDecision
   Engine                 -- checked once per pair (the gate is a pair-level
                             fact, independent of which candidate strategy
                             qualified); not ALLOWED: every candidate for
                             this pair is dropped, the gate's specific
                             BLOCKED_* value is reported to Research &
                             Learning Engine's observer call (see step 7)
                             as the stop reason; Risk Engine is never
                             called for this pair this cycle.
3.5. Tie-break            only runs if step 2 returned more than one
     resolution              candidate and step 3 was ALLOWED. Runtime
                             applies the fixed six-criterion cascade in
                             `docs/specs/02_strategy_engine.md` §7.1
                             (Evidence score -> historical strategy
                             performance -> statistical confidence ->
                             portfolio exposure -> liquidity quality ->
                             news risk), reading whatever Research/Risk/
                             Intelligence data each criterion needs.
                             Still tied after all six: reject -- reported
                             to step 7 as `TIE_UNRESOLVED`, no randomness,
                             no arbitrary/insertion-order pick. Exactly
                             one `TradeIdea` survives past this step in
                             every other case.
4. Portfolio Statistical  evaluate(idea, portfolio, now)
   Risk Engine              -> Union[SizingRecommendation, RiskVeto]
                          -- veto: reported as the stop reason to step 7;
                             Compliance Engine is never called.
5. Prop Firm Compliance   evaluate(sizing, account, now)
   Engine                   -> Union[TradeCommand, ComplianceRejection]
                          -- rejection: reported as the stop reason to
                             step 7; Bridge is never called.
6. PhantomBridgeEA        phantom.bridge.engine.BridgeEngine.submit_command(command)
   (Bridge)                 -> Optional[ErrorCode]
                          -- a non-None ErrorCode (DUPLICATE_CORRELATION_ID /
                             BRIDGE_NOT_READY / EMERGENCY_STOP_ACTIVE, all
                             already defined in phantom.bridge.models) is
                             reported as the stop reason to step 7 --
                             closes Finding 12.1 using the existing
                             ErrorCode type, introducing nothing new.
7. Research & Learning    record_trade(decision_chain_snapshot, outcome)
   Engine (observer)        -> None
                          -- called for EVERY idea that reached step 2,
                             whether it proceeded all the way to a
                             successful submission or stopped at step 3,
                             4, 5, or 6 -- the stop point and reason are
                             part of the recorded snapshot. Never called
                             for a pair where step 2 produced no idea at
                             all (nothing to record).
8. System Reliability     health/outcome report for this cycle
   Engine (observer)        (duration, per-pair stage reached, error counts)
```

**Why Market Intelligence Engine is its own numbered step, not a check
inside Strategy Engine:** this revises the prior specification (which
had Strategy Engine call `get_entry_gate` internally). Centralizing the
gate check in Runtime removes a direct dependency Strategy Engine
previously held on Market Intelligence Engine, so Strategy Engine's own
dependencies shrink to Evidence Engine only (§8 of
`docs/specs/02_strategy_engine.md`, revised) — less hidden coupling,
and it is Runtime, not Strategy Engine, that now owns "what must be
true before an idea proceeds."

**Why `is_halted()` isn't a numbered arrow between two components:** it
gates whether the *entire cycle* runs at all, not a data-flow step
between two components' outputs and inputs — it is checked once, by
Runtime, before step 1 for any pair. System Reliability Engine's
*observer* role (step 8) is a separate concern: receiving the
already-completed cycle's outcome for monitoring, not gating it.

## 6. Internal data models

| Model | Shape |
|---|---|
| `CycleReport` | cycle timestamp, per-pair outcome (`stage_reached`, `outcome` [idea_submitted / no_idea / blocked_entry_gate / risk_veto / compliance_rejected / bridge_rejected], duration) |
| `DecisionChainSnapshot` | unchanged from `docs/specs/06_research_learning_engine.md` §6, now explicitly populated by Runtime, not by any live component itself |

Runtime introduces no new business-meaning type — `CycleReport`'s
`outcome` values are direct restatements of each stage's own existing
return types (`EntryGateDecision`, `RiskVeto`, `ComplianceRejection`,
`ErrorCode`), not a new taxonomy.

## 7. Decision authority

**None whatsoever.** Runtime never scores, selects, sizes, approves, or
executes. Every branch in §5 is a direct pass-through of a decision
another component already made (`if gate != ALLOWED: stop` is control
flow over an already-computed value, not a new decision). This is
enforced the same way every other component's boundary is: a
structural test asserting no function in `phantom/runtime/` contains a
decision-shaped name, and that `runtime.py`'s only conditional
branches are equality/membership checks against values returned by
another component's public interface — never a threshold, weight, or
rule computed inline.

## 8. Dependencies

Every one of the 8 approved components' public interfaces (Evidence,
Strategy, Market Intelligence, Risk, Compliance, Bridge, Research,
Reliability), plus `phantom/shared/`. Runtime is the only file in the
entire system permitted to depend on all 8 — that is precisely its
job, and precisely why nothing else may.

## 9. Explicit non-responsibilities

- Owns no business logic, no trading logic, no risk logic, no strategy
  logic, no compliance logic — restated per this hardening task's own
  requirement, and enforced structurally (§7).
- Never retries a rejected idea within the same cycle — a rejection at
  any stage ends that pair's cycle; whether a *later* cycle re-evaluates
  the same pair is entirely up to Evidence/Strategy Engine's own next
  evaluation, not something Runtime remembers or forces.
- Never mutates any component's internal state directly — it only
  calls each component's own public function and passes the result to
  the next.
- Never holds a lock, a queue, or any concurrency primitive of its own
  — it is a strictly serial, single-threaded caller (see
  `docs/specs/09_bridge_concurrency_hardening.md` §5 for why this
  matters and what remains genuinely concurrent).

## 10. Test plan

- **Sequencing test:** a fixture cycle asserts the 8 components are
  called in exactly the order in §5, using recording stubs — no
  reordering, no skipped step outside the documented early-exit
  conditions.
- **Determinism test:** identical inputs (including a fixed `Clock`)
  produce an identical `CycleReport` on every run — required by this
  hardening task's "maintain deterministic execution."
- **Halt-gate test:** `is_halted() == True` skips every pair's entire
  cycle; zero calls into Evidence Engine or any later component.
- **Entry-gate test:** a `BLOCKED_*` result stops the idea before Risk
  Engine is ever called (mock Risk Engine asserts zero invocations).
- **Veto/rejection propagation tests:** one test per stop point (Risk
  veto, Compliance rejection, Bridge `ErrorCode`), each asserting (a)
  no later stage is called and (b) Research & Learning Engine's
  `record_trade` receives the correct stop reason using the originating
  stage's own existing type, unmodified.
- **No-idea test:** Strategy Engine returning `None` calls no further
  stage, including Research & Learning Engine (nothing to record).

## 11. Performance requirements

`run_cycle` for the full enabled-pair list must complete within
whatever cadence the deployment configures (a target validated during
implementation, not fixed here) — since per-pair evaluation has no
cross-pair shared state (§5's parenthetical), pair evaluation may be
parallelized by an implementation without changing this specification,
provided the *within-pair* stage order in §5 remains strictly serial
(a `TradeIdea` must never reach Risk Engine before Market Intelligence
Engine has been consulted for that specific idea).

## 12. Failure modes

| Failure | Expected behavior |
|---|---|
| Any component raises an unexpected exception mid-cycle | Caught per-pair at the Runtime level, logged, that pair's cycle reports a failure outcome; other pairs in the same cycle are unaffected (mirrors Evidence Engine's own per-pair isolation in `docs/specs/01_evidence_engine.md` §12). |
| `is_halted()` itself is unreachable/errors | Fail closed — treat as halted; skip the cycle rather than assume not-halted. |

## 13. Security considerations

No external network surface, no user-supplied input beyond the
`Clock`. Runtime is in-process glue; it holds no credentials of its
own.

## 14. Logging requirements

Logs one `CycleReport` per cycle (via System Reliability Engine's
shared `logging.py` sink, per the existing "one logging infrastructure"
rule) — per-pair stage reached, outcome, and duration. This log is the
primary artifact for diagnosing "why didn't this pair trade this
cycle," since Runtime is now the only place that sequence is decided.
