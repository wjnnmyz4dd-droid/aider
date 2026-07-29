# ADR-037 — ORB Cross-Pair Session Opportunity Selection

Status: **Accepted** (2026-07-28 — governance/architecture decision
only; see below for what this does and does not authorize). No
implementation accompanies this document. This Acceptance authorizes
only the architectural decisions recorded in §1–§13 (governance
vehicle, ownership, pipeline placement and control-flow model,
selection contract, completeness semantics, session identity, winner
cardinality/persistence, the enabled-sessions structural-readiness
invariant, and the ADR-036 relationship). It does **not** authorize
implementation: per `CLAUDE.md` §1.10, no code implementing this ADR's
architecture may be written until (a) the future, dedicated ADR-031 §3
amendment this document requires (§5, §17) is itself independently
researched, governed, and Accepted, and (b) a dedicated ADR-037
implementation Plan (its own RPI Research → Plan → Implement cycle,
including independent Plan review) is completed. Ranking formula/weights,
tie-handling policy, and exact production sessions/pairs/anchors remain
separately unresolved product-policy decisions, not settled by this
Acceptance. Gate A/Gate B activation and legacy-strategy retirement
remain governed exclusively by ADR-036/Amendment 1 and are not touched
by this ADR. The ADR-035 Phase 5 anchor hour/minute validation
follow-up remains separately gated, unauthorized, and unrelated to this
ADR throughout.

**Revision and review history:** first drafted Proposed (commit
`e3717c5`). An independent governance review of that draft found the
overall direction sound but identified five required revisions (F1–F5,
all HIGH/MEDIUM): an unaddressed Runtime control-flow/barrier
requirement for cross-pair placement (F1); a session-identity claim that
did not reconcile against `OpeningRangeState`'s own documented "session
is descriptive only" invariant (F2); a missing fail-closed tie between
this ADR's new enabled-sessions configuration and ADR-036 Amendment 1's
existing Gate A/Gate B invariant (F3); an unargued ownership choice that
never tested the smallest alternative (F4); and a candidate-completeness
check with no named source for "expected count" (F5). A revision
(commit `b3bd62d`) addressed all five without reopening the settled
conclusions that review confirmed (governance vehicle, pre-Risk
placement, no-silent-fallback default, the ADR-036 broad-Gate-A-only
dependency). A subsequent Final Independent Governance Acceptance Review
of that revision found the overall direction still sound but identified
a genuine internal inconsistency in the F1 barrier mechanics (G1 — the
control-flow model's own items 1, 3, and 8 contradicted each other on
whether/how the front half could be run once per pair without a
circular routing decision) and an ambiguous completeness definition
(G2 — whether an ordinary rejection counted as a "received" result). A
correction (commit `d481cc9`) resolved both by specifying one consistent
model: exactly one shared front-half execution per pair per cycle,
post-result classification, and a precise terminal-front-half-outcome
definition distinguishing a complete scan with no candidates from an
incomplete scan that fails closed. A second, independent **Final
Independent Governance Acceptance Re-Review** of that correction
(reviewing commit `d481cc9` fresh against source, not the revision's own
report) found G1 and G2 genuinely resolved, re-confirmed F2/F3/F4/F5
independently rather than on say-so, found one new LOW, non-blocking
wording-precision observation (§5.A's phrasing, read in isolation,
could be misread as narrowing which pairs receive a front half — resolved
by reading §5.A together with §5.G, which states the correct behavior
unambiguously; not corrected here per that review's own instruction not
to opportunistically edit it during acceptance), and returned:
**ADR-037 CONFORMS — ACCEPTED**. This entry now formally records that
Acceptance. No governance defect was found unresolved at the time of
Acceptance.

Owner: Principal Software Architect (drafting); permanent ownership of
the capability this ADR describes is assigned to a new component, not
yet built — see §4.

Depends on: `ADR-026-strategy-engine.md` (Accepted) — Strategy Engine's
per-pair qualification output (`QualificationResult`) is this ADR's
input; this ADR does not modify `selection.py` or any strategy
implementation. `ADR-027-portfolio-statistical-risk-engine.md`
(Accepted) — `ReservationLedger`/correlation clustering remain
downstream and unmodified; §6 explains why this ADR's mechanism sits
*before*, not inside, that engine. `ADR-031-runtime-orchestrator.md`
(Accepted) — Runtime's Hard Rules and exact pipeline are the binding
constraint this ADR's placement decision (§5) is designed to keep
satisfied; see §3/§5 for why this ADR's Hard-Rule compatibility needs no
ADR-031 text change, but a separate, future, deferred ADR-031 amendment
to §3's pipeline description is required before implementation (§17).
`ADR-035-orb-strategy.md` (Accepted; Phases 0–7 independently accepted)
— ORB's own qualification logic (`orb_breakout.py`) is unmodified and is
this ADR's primary source of per-pair candidates. `ADR-036-orb-strategy-consolidation.md`
(Accepted; Amendment 1 Accepted, commit `1164062`) — the originating
context; see §13 for the precise relationship, which this ADR does not
redefine.

Originating artifacts: `docs/plans/adr-036-legacy-strategy-retirement.md`
§P16 (commit `ecaa415`, the scoped-out architectural finding) and
`docs/plans/adr-036-session-scoped-orb-selection-research.md` (commit
`a13e5c0`, the Research pass this ADR's decisions are drawn from). This
ADR does not repeat that Research's evidence; it cites section numbers
from it (`§3.N`) where a decision rests on a specific finding.

---

## 1. Problem statement

ADR-036 (as amended) permits ORB to become the sole production strategy
once Gates A and B are lifted with real values. The product requirement
behind those values — precisely and completely, per the Research and
this task's own instruction — is:

- ORB evaluates one or more **configured trading sessions**
  independently (§2).
- For each configured session, ORB forms that session's opening range,
  scans a **candidate universe of eligible pairs** for that session, and
  **selects the single best qualifying opportunity** for that session
  using the existing qualification/scoring architecture.
- A session's selection never carries over to another session; each
  session's scan and selection is fresh.

The Research (§2, §3.1, §3.9) established that no component in the
repository today owns this comparison. Every existing per-pair path
(`RuntimeOrchestrator.run_cycle_for_pair()`, `StrategyEngine.evaluate_batch()`,
`RiskEngine.evaluate_batch()`) processes pairs independently with zero
cross-item aggregation, and `selection.py::select_winning_strategy()`
compares strategies competing for the *same* pair, never pairs against
each other. This ADR decides how that gap is closed at the architecture
level, without inventing the product-policy values (ranking weights,
exact pairs, exact anchor clock times, exact session count) that remain
out of scope for a governance decision.

## 2. Preserved product requirement (precise)

**Session-based ORB** (fits the existing model, no new architecture
required): opening ranges and opportunities belong to a session; ORB's
existing per-pair, per-`(pair, range_start)` qualification and lockout
logic (`orb_breakout.py`'s `latest_range_end`/`currently_relevant`
filtering, Research §2) already gives "no carryover between sessions"
for a *single* pair with zero new code. This part of the requirement was
already true before this ADR and remains unchanged by it.

**Best-pair-per-session selection** (does not exist today, and is this
ADR's actual subject): compare the qualified opportunities *across*
pairs, within one session, and choose at most one winner for that
session.

**Session configuration requirement (new, stated explicitly per this
task's instruction):** the set of sessions ORB evaluates MUST be a
**configurable list**, not an architectural constant. The architecture
this ADR describes must support any number of enabled sessions (zero,
one, two, or more), each independently defined. **London and New York
are the intended *initial production policy*** — i.e., the first values
an operator is expected to configure — but nothing in this ADR's
architecture may hardcode "exactly two sessions" or name London/New York
in a way that would require a code change to add, remove, or reconfigure
a session. This distinction (configurable architecture vs. initial
policy content) is load-bearing for every other decision in this
document and is repeated where relevant.

## 3. Governance vehicle

**Decision: a new, dedicated ADR — this document, ADR-037 — not an
amendment to ADR-031, ADR-035, or ADR-036.**

Reasoning:

- **Not ADR-036.** ADR-036 is a product-direction decision about
  retiring five legacy strategies in favor of ORB; it explicitly places
  Evidence Engine and pair-eligibility mechanics outside its own scope
  (§9 Non-Goals, cited in Amendment 1's own gap analysis). The
  cross-pair selection capability this ADR describes is not itself
  about strategy retirement — it is a precondition only for one
  specific *flavor* of Gate A/B resolution (§13). Folding it into
  ADR-036 would make ADR-036 responsible for a capability with its own
  independent ownership, lifecycle, and failure modes, contradicting
  this task's own explicit instruction not to force the decision into
  ADR-036 merely because its absence currently blocks ADR-036.
- **Not ADR-035.** ADR-035 owns ORB's own qualification algorithm
  (breakout distance, FVG confirmation, MI eligibility). Cross-pair
  comparison is not a qualification rule change — a pair still qualifies
  or doesn't under ADR-035's existing rules — it is a new decision made
  *after* qualification, over a set of already-qualified candidates.
  Amending ADR-035 would blur qualification (single-pair, single-strategy)
  with selection (cross-pair), which the Research (§3.9) identified as
  precisely the boundary the existing architecture is careful to keep
  separate (qualification lives in Strategy Engine; the existing
  cross-strategy-same-pair comparison lives in `selection.py`, a
  distinct, narrower mechanism).
- **ADR-031's Hard Rules (§2) require no text change; §3's pipeline
  description does need a future amendment, precisely scoped, not
  performed here.** ADR-031's Hard Rules require Runtime to never
  generate signals, calculate evidence, calculate risk, make compliance
  decisions, or override any engine — verified structurally by requiring
  every Runtime conditional to be an equality/membership check against a
  value another engine's public interface already returned. Placing
  cross-pair selection in a new, dedicated engine/component (§4) that
  Runtime merely *consults* (sequencing membership/equality checks, §5)
  keeps Runtime's own compliance with the Hard Rules intact without
  changing that text. However, §5 (revised) establishes that ADR-031 §3's
  literal, unconditional "per pair, per cycle, six-stage" sequencing
  description will no longer be accurate for pairs inside an enabled
  session's candidate universe once this ADR is implemented — a
  **substantive**, not cosmetic, future amendment to §3 is required, and
  is explicitly **deferred, not performed by this ADR** (this document
  does not touch ADR-031's text) — see §5's full analysis and §17's
  precondition list.
- **New ADR-037 is the smallest accurate vehicle** because the
  capability has its own ownership question, its own persisted state,
  its own failure semantics, and its own adversarial risk profile (§15)
  — exactly the criteria this project's own ADR-per-stage discipline
  (`CLAUDE.md` §1.10) uses to justify a dedicated ADR rather than
  amending an existing one.

## 4. Ownership (revised — F4)

**The reduction itself** (comparing N candidates and returning at most
one winner) is owned by a new, dedicated component. Working name:
**Opportunity Selection Engine** (provisional — not load-bearing; the
eventual implementation Plan may rename it, subject to its own review).
It is a new pipeline-stage-level component in the same sense Evidence
Engine, Market Intelligence, Strategy Engine, Risk Engine, and
Compliance Engine are — i.e., it requires its own Accepted ADR before
any implementation, per `CLAUDE.md` §1.10, exactly as this document
provides.

**The independent review required this section to explicitly test the
smallest alternative rather than assert a new component — done here:**

- **Alternative tested: extend `StrategyEngine` itself with a cross-pair
  reduction method**, consuming `evaluate_batch()`'s already-existing
  per-pair output directly, with no new package at all. **Rejected**,
  for a reason stronger than "Research proposed something else": every
  existing `StrategyEngine` method (`evaluate()`, `evaluate_batch()`)
  preserves a strict *shape* invariant — exactly one result per pair
  fed in, never fewer, never a cross-pair reduction. `evaluate_batch()`'s
  own docstring is explicit that it "evaluates every pair" (plural
  outputs, one per pair); it never collapses pairs into a single answer.
  Bolting a many-to-one reduction onto that shape would silently change
  what every existing caller of `StrategyEngine` can assume about its
  output cardinality, which is exactly the kind of blurred-boundary risk
  `ADR-026`'s own charter (per-pair qualification, per-pair `TradeIntent`,
  Amendment 1) was written to prevent. A new component with its own
  many-to-one contract keeps that invariant intact for `StrategyEngine`
  and gives the new reduction a home whose *contract* is honestly N-to-1,
  not a bolted-on exception to a component whose contract is 1-to-1.
- `selection.py` remains **same-pair, cross-strategy** selection only —
  explicitly confirmed unmodified and unrepurposed for cross-pair
  selection; it compares strategies competing for the *same* pair, never
  pairs against each other, and this ADR does not change that.
- `RiskEngine` (owns sizing, reservation, and portfolio-heat/correlation
  limiting — not opportunity discovery; see §6 for why placing selection
  inside or after Risk Engine is rejected).
- `RuntimeOrchestrator` (forbidden by ADR-031's Hard Rules for the
  *reduction itself* — Runtime computes nothing; see §5 for what Runtime
  *does* own: sequencing and membership checks, not the comparison).

**A necessary, but smaller, consequence for `StrategyEngine`'s existing
models:** the new engine's input must carry each candidate's opening-
range identity (§8's `range_start`) alongside its `QualificationResult`/
`StrategySnapshot`, so the new engine can group candidates by opportunity
window without re-deriving that identity itself. Today, **neither
`QualificationResult` nor `StrategySnapshot` carries this identity** —
verified directly against `strategy_engine/models.py`: both types name
`pair`, score/confidence/reason fields, and `trade_intent`, but no
`range_start`/session field. The identity currently lives only in
`EvidenceSnapshot.opening_ranges`, and `orb_breakout.py::qualify()`
already contains the one authoritative "currently relevant range"
selection logic (`latest_range_end`/`currently_relevant`, §2). **The new
engine must consume that identity as `StrategyEngine` already computed
it — it must not re-derive or duplicate "which range is currently
relevant" itself**, which would violate `CLAUDE.md` §1.4 (no duplicate
filters). This means a future Plan will need an additive, backward-
compatible field on `QualificationResult`/`StrategySnapshot` carrying the
already-computed `range_start` (precedent: Amendment 1's own addition of
`trade_intent` to the same models) — a small, existing-pattern change to
`StrategyEngine`'s data model, distinct from and much narrower than
giving `StrategyEngine` ownership of the reduction itself. This ADR
requires that the identity travel this way; it does not specify the
exact field name or type, which is Plan-level work.

## 5. Pipeline placement and control-flow architecture (revised — F1, corrected after final review's G1 finding)

**Decision (unchanged from the prior draft): immediately after Strategy
Engine qualification, before Risk Engine.**

**Correction to this revision's history:** the prior revision's control-
flow model (items 1, 3, and 8, as originally drafted) was found by an
independent final review to be internally inconsistent — item 1 stated a
routing criterion (a pair's own Strategy Engine output) that could not
be known before the very decision it was meant to control; item 3
implied re-running each pair's front half once per enabled session,
duplicating computation and contradicting item 8, which already implied
(correctly, but inconsistently with item 3) a single shared pass. This
section replaces that model with one, consistent architecture, stated
once, below. Nothing about the underlying placement decision (pre-Risk),
the barrier's necessity, or Runtime's role changes — only the previously
contradictory mechanics are corrected.

**What remains true from source, re-verified for this correction:**
`RuntimeOrchestrator`'s only production entry point, `run_cycle()`
(`titan_protocol/runtime/engine.py:413`), loops `for pair in sorted(pairs)`
and calls `run_cycle_for_pair()` (`engine.py:110`) once per pair.
`run_cycle_for_pair()` is a single, monolithic function that runs
Evidence → Market Intelligence → Strategy → Risk → Compliance → Bridge
all the way through for one pair, in one call, with early-exit on any
rejection, before the loop advances to the next pair. There is no
existing point at which Runtime holds multiple pairs' Strategy Engine
outputs simultaneously — inserting a cross-pair stage requires a real,
narrowly scoped restructuring, specified below.

### A. Front-half execution — exactly once per pair per cycle

Every pair in the cycle's relevant configured universe (§7's frozen
`ORB Gate-A-approved pairs ∩ allowed_pairs` intersection) is processed
through Evidence → Market Intelligence → Strategy **exactly once per
Runtime cycle** — the same unmodified engine calls, in the same order,
on the same per-pair signatures ADR-031 §3 already specifies. **The
front half is never run once per enabled session and never run twice
for the same pair in the same cycle.** Runtime does not need to know,
before this front half runs, which enabled opportunity window (if any)
a pair will turn out to belong to — that information does not exist
until Strategy Engine has already produced it. This is the front-half
result that becomes shared input to whatever opportunity-window grouping
follows (§C, §E).

### B. Post-front-half classification

Only *after* a pair's front-half result exists may Runtime classify it.
Runtime may inspect only explicit, already-computed engine-produced
fields needed for orchestration:

- whether a usable Strategy result exists for this pair this cycle;
- whether `OPENING_RANGE_BREAKOUT` is the winning qualification
  (`StrategySnapshot.winning_strategy`, unmodified field);
- the explicit `range_start`/opportunity-window tag the additive field
  (§4) carries — Runtime reads this value, it does not compute it;
- whether that `range_start` corresponds to a currently enabled
  configured opportunity window (§8/§11) — a static configuration
  membership check.

Runtime must not reproduce ORB qualification, opening-range
"currently-relevant-range" logic, ranking, or any trading decision to
perform this classification — every one of the four checks above is a
membership/equality test against a value another engine's public
interface, or static configuration, already provided.

### C. Barrier participation

A pair never enters a special pre-Strategy branch, and no branching
decision is made before its one front-half execution completes. After
that single front-half execution:

- if its result's `range_start` corresponds to an **enabled** opportunity
  window (§B), it becomes a reported result contributing to that
  window's scan/barrier;
- otherwise (a legacy-strategy winner, an ORB result whose range belongs
  to a non-enabled or unconfigured window, or no formed range at all) it
  is **not** a candidate for any opportunity window this cycle.

**Non-participating results continue through existing behavior
unmodified and immediately** — most importantly during the pre-
retirement coexistence period this project's own governance history
(ADR-036, unmodified by this ADR) still permits: a pair whose Strategy
Engine result names one of the five legacy strategies as the winning
qualification proceeds directly into Risk → Compliance → Bridge exactly
as it does today, with **no waiting, no barrier participation, and no
added latency** — a broad Gate A universe does not hold unrelated
legacy-strategy execution hostage behind an ORB barrier; only a pair
whose *own* result is itself an enabled-window ORB candidate is ever
held back, and only until that specific window's barrier resolves.

### D. Completeness (resolves G2)

For each enabled opportunity window, the authoritative expected universe
(§7's `range_start`-independent, session-independent Gate A ∩
`allowed_pairs` intersection) is frozen at scan start, unchanged from
the prior revision.

**Terminal front-half outcome, defined:** a pair has reached a terminal
front-half outcome for the cycle once Evidence, Market Intelligence, and
Strategy Engine have all been invoked for it and produced a final
result for this cycle — whether that result is an explicit ORB
`QUALIFIED`, an explicit ORB `NOT_QUALIFIED`/rejection (holiday, market
closed, spread, liquidity, no formed range, no breakout — any of
`orb_breakout.py::qualify()`'s existing, unmodified rejection paths), or
a legacy strategy winning instead of ORB. **An explicit rejection is a
terminal outcome, not a missing one** — it must never be misclassified
as "incomplete." Conversely, a pair whose front half never completes
this cycle (an exception before Strategy Engine runs, an early-exit at
Evidence or Market Intelligence per ADR-031 §3's own existing early-exit
discipline, a timeout, or any other fault that prevents a Strategy
Engine result from ever being produced for that pair this cycle) has
**not** reached a terminal outcome, regardless of its presence in the
input universe.

**The completeness rule, precisely:**

1. **Complete scan, no qualifying opportunity:** every pair in the
   frozen universe reached a terminal front-half outcome this cycle, and
   none of those outcomes is an enabled-window ORB candidate (§C). This
   is a valid, complete result — the enabled window correctly produces
   no candidates and no winner this cycle, and this is *not* an
   incompleteness failure.
2. **Incomplete scan:** one or more pairs in the frozen universe did
   *not* reach a terminal front-half outcome this cycle. The enabled
   window's barrier must fail closed — no winner is selected from the
   partial set, regardless of how many terminal outcomes were, in fact,
   ORB candidates.

This distinction is exactly the one the final review required: "all
expected pairs were evaluated and none qualified" (case 1, safe, no
opportunity) versus "some expected pairs never reached evaluation" (case
2, unsafe, fails closed) are now structurally different conditions,
never conflated.

**Explicit disclosure, not a policy change (addresses the review's G3
observation):** because case 2's fail-closed rule applies per opportunity
window against the *whole* frozen universe, a single pair's fault (an
Evidence/MI-level early exit, a timeout, an exception) before its
Strategy Engine result exists renders that window's entire scan
incomplete for that cycle — suppressing selection for every other,
otherwise-healthy candidate pair in that window, that cycle. This is a
deliberate consequence of this project's capital-preservation-over-
profit posture (`CLAUDE.md` §2, "Capital preservation overrides
profit"), not an oversight, and this revision does **not** soften it. A
future rule for excluding a pair known-unavailable *before* scan start
from the expected universe (rather than counting it as expected and
then failing on it) is a legitimate question for later Research/
governance if the operational cost of this conservatism proves too
high — it is not decided, adopted, or silently optimized around here.

### E. Grouping and selection after the shared pass

Once every frozen-universe pair has reached a terminal front-half
outcome for the cycle (§D):

1. Group the enabled-window ORB candidates (§C) by their engine-
   produced `range_start` identity (§8) — never by re-deriving which
   range is "currently relevant," only by reading the value Strategy
   Engine's output already carries.
2. For each enabled opportunity window whose scan is complete (§D case
   1 — regardless of whether zero or more candidates resulted), invoke
   the Opportunity Selection Engine with exactly that window's candidate
   subset (an empty subset is a valid input, correctly yielding no
   winner). A window whose scan is incomplete (§D case 2) is never
   passed to the engine at all — it fails closed directly, without a
   selector call.
3. The engine selects at most one pair per `range_start` (§6, §9,
   unchanged).
4. **Only that winner** may continue into Risk → Compliance → Bridge
   for that opportunity window. Runtime reads the engine's
   `Optional[pair]` result and continues the back half only for the
   pair matching it — an equality check against a value another
   engine's public interface already returned.
5. Every other candidate that contributed to that window's barrier
   (§C) — i.e., every enabled-window ORB candidate that was not
   selected — ends its cycle at this point with a new, explicit terminal
   outcome ("not selected this opportunity window"), the same shape as
   existing `CycleOutcome` terminal values (`runtime/models.py`'s
   existing enum already models per-pair cycle endings this way, e.g.
   `NO_STRATEGY`, `RISK_REJECTED`); this ADR does not invent the
   mechanism, only requires that one exists so a non-winning candidate's
   cycle is recorded as ended, not silently dropped. Risk, Compliance,
   and Bridge are never invoked for a non-winning candidate this cycle.
   No selector result may release a non-winner into the back half.

### F. Multiple enabled windows

Because every pair's front half runs exactly once per cycle (§A) and
grouping/selection (§E) happens *after* that single shared pass, the
architecture requires **no duplicated front-half computation** for one
enabled window, two enabled windows, or more than two — each enabled
window simply filters the same shared result set to its own
`range_start` and runs its own independent Opportunity Selection Engine
invocation and its own independent completeness check (§D), against
that same shared, already-computed front-half data. A pair's single
front-half result is classified according to whichever range
`orb_breakout.py`'s existing, unmodified "currently relevant range"
logic (`latest_range_end`/`currently_relevant`, §2) determined for it
that cycle — this ADR does not invent multi-range qualification
behavior; a pair contributes to at most one enabled window's barrier per
cycle, exactly as the existing single-relevant-range design already
guarantees.

### G. Non-participating pairs and legacy coexistence

Explicit, at the architecture level: before ADR-036 retirement is
complete, the registry may still contain the five legacy strategies. A
pair whose Strategy Engine result is not an enabled-window ORB candidate
(§C) — including every legacy-strategy winner — is never silently
discarded because cross-pair ORB selection exists elsewhere in the
system; it follows the existing, entirely unmodified path (§C) with no
new trading-decision authority granted to Runtime and no redesign of any
legacy strategy. This ADR's mechanism is additive for a precisely
defined subset of cycles (enabled-window ORB candidates only), never a
rewrite of Runtime's default per-pair behavior for anything else.

**Capital-preservation analysis — why not after Risk Engine (unchanged
from the prior draft, still sound):** the Research (§3.5, §4) flagged
that placing selection *after* Risk Engine would require Risk Engine to
first create a reservation for every candidate pair in a session, then
release every reservation except the winner's — structurally the same
class of defect as this project's own prior, already-fixed
`ReservationLedger` leak (session history: `S415`/`2173`/`2184`).
Placing selection *before* Risk Engine, via the corrected model above,
means at most one reservation is ever created per opportunity window
per cycle (for the winner only), eliminating that entire risk class by
construction.

**Accepted tradeoff, explicitly not resolved further here:** a winner
selected pre-Risk/Compliance can still be rejected by Risk or Compliance
after selection (insufficient margin, correlation breach, compliance
veto, etc.), with **no automatic fallback to the session's second-best
candidate**. This is a deliberate scope boundary, not an oversight — see
§10.

**ADR-031 compatibility, reassessed against the corrected model:** the
Hard Rules (`ADR-031` §2 — Runtime must never generate signals,
calculate evidence, calculate risk, make compliance decisions, or
override any engine, verified by requiring every Runtime conditional to
be an equality/membership check) **remain satisfied, and require no
text change.** Every Runtime responsibility in the corrected model —
executing the existing engines unmodified (§A); reading explicit,
already-computed fields to classify a result (§B); counting terminal
front-half outcomes against a frozen, config-derived expected count
(§D); grouping candidates by an engine-produced identity value, never a
re-derived one (§E.1); consulting the Opportunity Selection Engine and
acting on its `Optional[pair]` result via equality check (§E.2–§E.4) —
reduces to execution, collection, counting, grouping by an already-
produced value, and membership/equality comparison. Runtime is not
deciding *who wins* — the Opportunity Selection Engine is — and it is
not calculating qualification, opening ranges, ranking, risk,
compliance, or any trade signal at any point in this model.

**However, `ADR-031` §3 ("Pipeline (exactly)") itself is not merely
compatible without change.** §3 is written as a strict, linear, per-pair,
per-cycle six-stage sequence with early-exit discipline — accurate today
for every pair, unconditionally. Under the corrected model, that
description remains accurate for every pair whose front-half result is
*not* an enabled-window ORB candidate (§C, §G) — the overwhelming
majority of cycles during coexistence — but becomes inaccurate for the
specific subset that *is* such a candidate, which now waits at a barrier
(§D) before its back half, rather than proceeding immediately. **This is
a real, substantive change to what §3 documents as Runtime's actual
sequencing behavior for that subset — not a cosmetic one — and it
requires its own future ADR-031 amendment before implementation**,
describing the corrected one-pass-front-half/terminal-outcome/
completeness/grouping/selection/winner-only-back-half model precisely
(now fully specified at the architecture level in §A–§G above, so that
future amendment has a concrete, internally consistent model to
formalize rather than an open or contradictory one). Consistent with
this task's constraint not to touch ADR-031 during this revision, **that
amendment is required but explicitly deferred**, and remains named in
§17's preconditions.

## 6. Cross-pair selection contract

The new stage's contract, deliberately **without** specifying a ranking
formula or weights (an explicit product-policy decision this ADR does
not make):

- **Input:** the set of `QualificationResult` (score, confidence,
  trade_intent, strengths/weaknesses — already-existing fields, Research
  §2) produced by Strategy Engine for every pair in that session's
  candidate universe, each tagged with the session identity and
  `range_start` it was evaluated against (§7).
- **Output:** a pure function of that input set, returning
  `Optional[pair]` — either the winning pair for that session/range, or
  nothing (§9 governs when "nothing" is the fail-closed-correct answer).
- **Determinism:** the selection function must be a deterministic,
  side-effect-free function of its candidate-set input. Persistence of
  the *result* (§9) is a separate concern from the selection computation
  itself.
- **Ranking policy — explicitly unresolved:** the actual comparison rule
  (e.g., which `QualificationResult` field(s) to rank on, how to weight
  them, whether confidence gates score) is a product-policy decision not
  authorized by this ADR. No default is implied by this document.
- **Tie handling — flagged, not decided:** `selection.py`'s own
  precedent ("still tied after all six steps: reject, never randomize")
  is a strong candidate default for this new stage, given this
  codebase's established risk posture. This ADR records that precedent
  as the leading candidate but does **not** adopt it as binding — the
  eventual implementation Plan must state and justify its tie-handling
  rule explicitly rather than silently inheriting `selection.py`'s.

## 7. Candidate-set completeness and synchronization (revised — F5; completeness definition corrected — G2, cross-referencing §5.D)

A session's selection is only meaningful if it was computed over the
*complete, frozen* intended candidate universe for that session. The
first independent review correctly found that the prior draft never
named where "expected count" comes from, risking a circular definition
("expected" silently redefined as "however many results arrived," which
would defeat the check entirely). The final review then found that even
after naming the source, the definition of what counts as a "received"
result was still ambiguous — specifically, whether an ordinary,
already-computed rejection (holiday, spread, no formed range, a legacy
strategy winning instead of ORB) counted toward completeness at all.
Both are resolved together here.

**Authoritative candidate universe for a scan (frozen at scan start):**
the intersection of

1. **Gate A's ORB-approved pairs** — `StrategyEngineConfig.approved_pairs_for(OPENING_RANGE_BREAKOUT)`,
   the same field ADR-036 Amendment 1's condition 1 already governs, and
2. **the active `TradingProfile`'s `allowed_pairs`** — the same
   restriction `RuntimeOrchestrator.run_cycle()` already applies today
   (`if pair not in profile.allowed_pairs: continue`, `engine.py:435`)
   before any engine is even called, for every pair, regardless of this
   ADR.

No third, session-specific pair sub-universe is invented: the Research
already established no session-specific pair-eligibility/liquidity table
exists in the repository today (`docs/plans/adr-036-session-scoped-orb-
selection-research.md` §3.3/§3.9), and this ADR does not create one. The
**same** intersection applies uniformly, regardless of how many enabled
opportunity windows exist — it is not defined per session and is not
recomputed per window; each enabled window's own completeness check
(§5.D) simply reuses this one frozen set as its "expected" side of the
comparison. This intersection is never dynamically narrowed by
profitability, liquidity scoring, or any other policy — no such policy
is invented here.

**Freezing:** this intersection is computed **once, at the start of the
cycle's front-half pass** (§5.A), and held fixed for the duration of
that cycle — never recomputed mid-scan, and never re-derived per
enabled window. This satisfies: (a) a mid-scan config reload cannot
silently narrow or widen what "complete" means, because completeness is
judged against the frozen count, not a live recount; (b) a retry/
reconnect for one pair cannot redefine "complete" as "however many
results eventually arrived," because the frozen expected count doesn't
change; (c) "expected count" is never circularly defined as "actual
count," because it is fixed before any front-half result exists for the
cycle.

**What counts as "received" — the precise distinction (§5.D, restated
here for this section's own completeness contract):** a pair counts as
having reached its terminal front-half outcome once Evidence, Market
Intelligence, and Strategy Engine have all been invoked for it and
produced a final result for the cycle — an explicit ORB qualification,
an explicit ORB rejection, or a legacy strategy winning instead of ORB
all count equally as "received." A pair whose front half never completes
this cycle (an early exit, an exception, a timeout, before a Strategy
Engine result exists) does **not** count, regardless of its membership
in the frozen universe. This is the exact distinction the final review
required: "every expected pair was processed and produced a terminal
front-half outcome, but zero pairs became qualifying candidates" (a
complete scan with no opportunity — not a failure) is now structurally
different from "one or more expected pairs never produced the required
terminal front-half outcome" (an incomplete scan — fails closed), per
§5.D.

**Fail closed on incompleteness:** if the actual terminal-outcome count
is less than the frozen expected count for a given cycle, every enabled
opportunity window's barrier that depends on that frozen universe fails
closed for that cycle — no winner is selected from a partial set.
Treating a partial scan as if it were complete is exactly the "silent
narrowing" failure mode this task's governing instructions repeatedly
warn against.

## 8. Session identity and lifecycle (revised — F2)

Per §2's Session configuration requirement, sessions are a
**configurable list**. The independent review correctly found that the
prior draft's proposal to key identity on `SessionName` (alone, or as
half of a composite key) did not reconcile against the existing,
authoritative model: `OpeningRangeState`'s own docstring
(`evidence_engine/models.py:362-365`) states plainly that *"`session` is
descriptive only — the identifying key is this instance's own
`range_start`/`range_end` window, never `session` alone (two configured
anchors can share a `SessionName`)."*

**Verified fresh for this revision, and the resolution:**
`EvidenceEngineConfig`'s own `_validate_no_overlapping_anchors`
(`evidence_engine/config.py:129-148`) already rejects, at startup, any
two configured anchors whose `[range_start, range_end)` windows coincide
or overlap — its own docstring states this exists *precisely* "for
`OpeningRangeState` to be disambiguated by its own window rather than by
`session` alone." `range_start` is a full `datetime`
(`now.replace(hour=..., minute=..., second=0, microsecond=0)`,
`evidence_engine/opening_range.py:137`), not a bare time-of-day, so it
already varies by calendar day and by each anchor's own hour/minute.

**Decision: the minimal correct identity for an opportunity window is
`range_start` alone — not `(SessionName, range_start)`, and not
`SessionName` in any form.** This is not a new invention; it is the
*same* identity Evidence Engine's own, already-Accepted design already
uses and already validates as collision-free, applied consistently
rather than reintroduced with `SessionName` mixed back in. `SessionName`
is retained as a **descriptive field only** — carried through for
observability and for the enabled-sessions configuration's own
bookkeeping (§11) — never as part of any key.

This resolves every identity scenario the review named:
- **Two configured anchors sharing a `SessionName`:** already produce
  distinct `range_start` values (different hour/minute or duration),
  already validated non-overlapping — no collision, no special handling
  needed beyond using `range_start` as the sole key.
- **Overlapping sessions/windows:** cannot exist as configured anchors
  (already rejected at startup by `_validate_no_overlapping_anchors`);
  "overlapping" enabled sessions in the everyday sense (e.g. London and
  New York both active in the same clock hour) are still two entirely
  separate `range_start` values with two separate windows, never a
  shared key.
- **One, two, or more enabled sessions:** each enabled session entry
  references one specific configured anchor (§11); cardinality is a
  list-length matter, unaffected by this identity choice.
- **Date boundaries / restarts:** already handled — `range_start`
  includes the date, so a new calendar day is automatically a new key,
  and a restart recomputes the identical `range_start` for the same
  real-world anchor window, since it is derived from `now`'s date plus
  the anchor's fixed hour/minute, not from wall-clock elapsed time.
- **State contamination between distinct opportunity windows:** ruled
  out by construction — distinct `range_start` values are, by Gate B's
  own existing validation, always distinct, non-overlapping windows.

**An "enabled session" configuration entry, revised:**
- References one specific configured `opening_range_anchors` entry (not
  merely a `SessionName` label) — i.e., points at a specific anchor,
  the same way `OpeningRangeState` itself is identified by its own
  window, not by the label attached to it.
- Carries `SessionName` only as a descriptive/observability field.
- Carries an enabled/disabled flag, so the list's *cardinality* is a
  configuration matter, never a code change.

**Explicitly not decided here:** how many sessions are enabled in
production, which named sessions they are, and their exact anchor clock
values. London and New York remain, per §2, the *intended initial
policy content* for this list — never an architectural upper or fixed
bound. **Whether pair belongs in the key or the value (review's own
question):** the value — `range_start` alone is the key; the winning
`pair` (or its absence) is what is stored *for* that key, exactly
mirroring `OrbQualificationStore`'s own key/value split (key = the
question being answered, value = the answer).

## 9. Winner cardinality, persistence, and fail-closed semantics (identity updated — F2)

- **Cardinality:** at most one winner per `range_start` (§8 — not a
  composite key; `range_start` alone is already unique by Gate B's own
  validated construction). Never more than one pair proceeds downstream
  per opportunity window.
- **Persistence:** the winner (or the fact that no winner was selected)
  must be recorded in a **new, dedicated, restart-safe, persisted
  store**, distinct from `OrbQualificationStore` and
  `FormationBlackoutStore` (Research §3.7) — those are keyed by `(pair,
  range_start)`; this store is keyed by `range_start` alone, with the
  originating `SessionName` and the winning `pair` (or its absence)
  carried as the stored value, reflecting that the decision being
  persisted is *about* an opportunity window, not a pair. This follows
  the same established design pattern (restart-safe, fail-closed-on-
  corruption) without merging into either existing store's key space.
- **Fail-closed on store corruption or unavailability:** if the winner
  store cannot be read or is corrupt, the stage must behave as if no
  winner exists for that range — never fail open by allowing an
  unselected pair to proceed, and never fabricate a winner from stale
  data.
- **Idempotency:** re-evaluating the same `range_start` after a winner
  is already persisted must not silently overwrite it or produce a
  second winner; the exact re-evaluation policy (reject vs. return the
  existing winner unchanged) is left to the implementation Plan,
  constrained only by "never produces a second concurrent winner for the
  same opportunity window."

## 10. Risk Engine / Compliance Engine / portfolio interaction

The selected winner proceeds through the existing, **entirely
unmodified** Risk Engine → Compliance Engine → Bridge path — exactly one
candidate per session enters that path, eliminating the reservation-
multiplicity risk (§5) by construction.

**Explicitly not decided by this ADR:** whether a downstream Risk or
Compliance rejection of the session's winner triggers any automatic
fallback (e.g., promoting the session's second-ranked candidate). This
is a distinct, separate future policy question. Absent such a decision,
the correct and only authorized behavior is: **the session produces no
trade that cycle** if its winner is rejected downstream — never an
implicit, un-reviewed fallback to a different pair.

Portfolio-heat/correlation limiting (`ReservationLedger`,
`compute_correlation_status()`) and in-flight command tracking
(`InFlightCommandRegistry`) remain entirely downstream of, and unaware
of, the new stage — no change to either is authorized or required by
this ADR.

## 11. Gate A / Gate B implications, and the enabled-sessions structural-readiness invariant (revised — F3)

**Gate A/Gate B production values remain unresolved by this document,
exactly as before.** What this revision adds is the fail-closed tie
between them and this ADR's own new configuration surface (enabled
sessions, §8), which the independent review correctly found missing:
ADR-036 Amendment 1's own condition 3 already established the precedent
that a structurally-satisfiable-but-practically-inert configuration is
exactly the silent-dormancy risk this project's governance closes, not
tolerates — and the reviewed draft introduced a *third* configuration
concept (enabled sessions) without extending that same discipline to it.

- **Gate A** (`DEFAULT_APPROVED_PAIRS_BY_STRATEGY`'s ORB entry) must
  remain a **broad structural eligibility list** when cross-pair
  selection is in effect — the candidate universe a session scans — not
  a single pair; a single-pair Gate A would make this ADR's mechanism a
  no-op (nothing to select between). The *width* of that list for
  production is now a decision coupled to this ADR's own eventual
  Acceptance and implementation, not a standalone ADR-036 decision. This
  ADR does not set that list's contents.
- **Gate B** (`opening_range_anchors`) remains session/time-of-day-keyed,
  never pair-specific, consistent with its existing shape (Research §1).
- **Enabled sessions** (§8) is a **third, independent** configuration
  concept, referencing specific Gate B anchors by identity (§8), not
  merged into Gate B itself.

**New required invariant (extends Amendment 1's condition 3, does not
alter its text):** whenever this deployment intends the "broad Gate A +
automatic selection" flavor (§13), fail-closed startup validation must
additionally enforce, alongside Amendment 1's existing Gate A/Gate B
checks:

1. **Every enabled-session entry must reference an existing, configured
   Gate B anchor.** An enabled session with no matching anchor can never
   form a range and is permanently vacuous — structurally guaranteed
   useless, the same standard Amendment 1 already applies to Gate A/B
   themselves.
2. **Every configured Gate B anchor whose session is *not* represented
   in the enabled-sessions list must be treated as a startup-time
   misconfiguration when cross-pair selection is active, not silently
   tolerated.** This is not merely tidiness: `orb_breakout.py::qualify()`
   is unmodified by this ADR (§16) and consults `opening_range_anchors`
   directly, with no awareness of the enabled-sessions list at all. A
   pair could therefore become "currently relevant" against an anchor
   whose session was never enabled for selection, and — absent this
   check — would have no authorized disposition: proceeding it
   unrestricted defeats the entire purpose of enabling selection at all
   (exactly the reservation-multiplicity risk §5 exists to prevent);
   silently suppressing it is a business/availability decision this ADR
   does not have authority to make silently. The startup check exists to
   prevent this configuration from ever being live; §5.B/§5.C's runtime
   classification rule (fail closed with an explicit signal, §12) is the
   required defense-in-depth backstop if it is ever reached anyway —
   mirroring this codebase's own established pattern of pairing a
   startup invariant with a runtime defense-in-depth check (e.g.
   `orb_breakout.py`'s own "unreachable under current anchor-overlap
   validation; retained as defense-in-depth" branch).
3. **Whenever the enabled-sessions list is empty, this ADR's mechanism is
   entirely inert, and this is only a safe configuration under the
   narrow/fixed Gate A route (§13) — never under the broad-Gate-A
   route.** An empty enabled-sessions list combined with a broad Gate A
   silently reverts that deployment to unrestricted multi-pair execution
   with **no structural signal that anything is wrong**, since Amendment
   1's own Gate A/Gate B conditions can both be satisfied without the
   enabled-sessions list ever being touched. This ADR requires that
   **some** fail-closed detection of this combination exist before the
   broad-Gate-A flavor may be considered structurally ready — mirroring
   Amendment 1's own condition 3 phrasing ("the exact mechanism... is
   deliberately left to a future Plan — this [ADR] requires the
   invariant, not its implementation"). This ADR does not invent the
   exact detection mechanism (e.g., a Gate-A-width threshold, or an
   explicit separate flavor-selection flag) — that is Plan-level work —
   but it requires that the invariant be enforced, not silently ignored.

**Explicitly preserved, not weakened by this invariant:** structural
readiness (checkable at startup/config-load time) remains categorically
distinct from dynamic qualification outcomes (holiday, spread, liquidity,
news blackout, no breakout, a tie, a Risk/Compliance rejection) — this
invariant governs only the former. A configuration satisfying items 1–3
above that still sees zero winners selected on a given cycle because no
candidate qualified, or because of a deterministic tie, is *outside*
this invariant's scope and does not violate it, exactly as Amendment 1
already establishes for Gate A/B themselves.

**This reconciles with, and does not alter, ADR-036 Amendment 1's own
text** — see §13.

## 12. Observability and fail-closed requirements (extended — F3 consequence)

The new stage must emit distinct signals for at least:

- Session scan started / completed, with expected-vs-actual candidate
  counts (§7).
- No candidates available for a session.
- Winner selected (`range_start`, `SessionName`, pair — §8/§9).
- Tie / no-winner produced despite candidates existing.
- Incomplete scan detected (§7's fail-closed path taken).
- Selector failure of any kind (exception, store unavailable, etc.).
- Stale winner detected (a persisted winner from a range that should
  already be closed).
- Downstream rejection of a session's winner (§10).
- **A pair's currently-relevant Gate B anchor has no matching enabled
  session, encountered at runtime** (§11 item 2's defense-in-depth
  backstop) — distinct from an ordinary "no candidates" signal, since
  this specifically indicates the startup-time invariant (§11) was
  either bypassed or is itself defective, and warrants operator
  attention distinct from routine "nothing qualified this cycle" noise.

**Absolute requirement:** any selector failure mode, and any encounter
with the misconfiguration in the new bullet above, must result in
**zero pairs proceeding** for that session that cycle. The architecture
must never fall back to today's unrestricted independent-per-pair
execution as a failure response — that would silently reintroduce the
exact multi-pair-per-session behavior this capability exists to replace,
without the review such a change requires.

## 13. Relationship to ADR-036 (precise, not a redefinition)

This ADR is a precondition **only** for the "broad Gate A + automatic
best-opportunity" flavor of ADR-036's Gate A/B resolution — i.e., a
future deployment-profile decision that opens Gate A to multiple pairs
per session and relies on this mechanism to pick among them.

It is **not** a precondition for ADR-036 legacy-strategy retirement as a
whole. A **narrow/fixed Gate A** (a single pair, or a small fixed list
with no cross-pair comparison required) remains a valid path already
established by ADR-036 Amendment 1 — nothing in Amendment 1's Gates A/B
conditions requires cross-pair selection to exist; it requires only "≥1
approved production pair" and "≥1 valid anchor entry," **re-verified
against Amendment 1's primary text for this revision** (`docs/adr/ADR-036-orb-strategy-consolidation.md`,
conditions 1–3). That narrow path can proceed to its own deployment-
profile decision and implementation independent of this ADR's Acceptance
or implementation status, and — per §11's new invariant — an empty
enabled-sessions list is precisely how that narrow path stays exempt
from this ADR's mechanism: §11 requires the fail-closed check only when
the broad-Gate-A flavor is *intended*, never for the narrow/fixed path.

This ADR does **not** redefine ADR-036 §13's governance-gate text,
Amendment 1's Gates A/B conditions, or ADR-036's Completion phase in any
way — §11's new invariant is additive, layered on top of Amendment 1's
existing conditions 1–3, not a substitute for or edit to them. ADR-036
implementation remains blocked for the reasons already on record (Plan
§P16, this session's own prior dispositions) regardless of this ADR's
outcome, until whichever Gate A/B path (narrow or broad) is actually
chosen and resolved.

## 14. Governance status and next gate

This document is **Accepted** (see header). It reached Accepted status
only after three independent governance review passes found no
unresolved defect at the end of the chain: an initial review (F1–F5),
a revision, a Final Independent Governance Acceptance Review that found
two further defects in the revision's own mechanics (G1, G2), a
correction, and a Final Independent Governance Acceptance Re-Review of
that correction that returned **ADR-037 CONFORMS — ACCEPTED** — the
same review-before-acceptance discipline this session's ADR-036/
Amendment 1 history already established.

**Acceptance does not authorize implementation.** The next required
governance step is: **ADR-031 §3 Pipeline Amendment Research** — an
independent Research pass (and subsequent governance/Acceptance cycle)
for the future, dedicated ADR-031 amendment §5/§17 already identify as
required before any code implementing this ADR's architecture may be
written. That Research is not performed by this document and is not
authorized here. Ranking/tie-handling policy and exact production
session/pair/anchor values remain separately unresolved and require
their own future governance or Plan-level decision before
implementation, independent of the ADR-031 amendment. Gate A/Gate B
activation and legacy-strategy retirement remain governed exclusively
by ADR-036/Amendment 1. The ADR-035 Phase 5 anchor hour/minute
validation follow-up remains separately gated, unauthorized, and
unrelated to this ADR.

## 15. Capital-preservation adversarial review (updated — identity and control-flow corrections)

| # | Scenario | Exposure if unaddressed | Disposition under this ADR |
|---|----------|--------------------------|------------------------------|
| 1 | London winner contaminates New York's selection (state not cleared between sessions) | A stale pair trades under the wrong session's risk/liquidity profile | Winner store is keyed by `range_start` alone, not global and not by `SessionName` (§8/§9, revised); a new opportunity window is always a new key, never inherited |
| 2 | Overlapping sessions (e.g. London/NY overlap window) share winner state | Two sessions could either double-count or improperly veto each other's selection | Gate B's own `_validate_no_overlapping_anchors` already guarantees distinct, non-overlapping `range_start` windows per configured anchor (§8, verified against `evidence_engine/config.py`); overlapping *sessions* are still distinct keys by construction, never merged |
| 3 | A disabled session still scans and/or selects | Wasted computation is the benign case; the dangerous case is a disabled session's "winner" leaking into execution | Enablement is part of session configuration (§8); §5.B/§5.C's post-front-half classification only admits a pair's result to a window's barrier when its `range_start` corresponds to an enabled window — a disabled window's pairs are classified as non-participating and proceed (or don't) exactly as any other non-candidate result |
| 4 | Candidate-pair universe changes mid-session (config reload between range formation and selection) | Selection computed against a universe that no longer matches what was actually scanned | §7 (revised) freezes the expected candidate universe (Gate A ∩ `allowed_pairs`) at scan start; a mid-scan change cannot silently redefine "complete" |
| 5 | Test-only pair/session configuration mistaken for production policy | A fixture list (e.g. Research's own test pairs) silently becomes a production eligibility decision | This ADR explicitly declines to name any pair, anchor time, or session count as production policy (§2, §8, §11); the eventual Plan/deployment-profile decision must draw production values from an authoritative operator decision, not test fixtures |
| 6 | Selector throws an exception mid-scan | Partial state could be misread as a valid empty or full result | §7/§12 require selector failure of any kind to produce zero winners and zero downstream pairs for that session that cycle — never partial-result interpretation |
| 7 | Winner store is corrupted or unreadable | A stale or fabricated winner could be read back and trade | §9 requires fail-closed treatment (as if no winner exists) on any store corruption/unavailability, never fail-open |
| 8 | Two winners persisted for the same `range_start` due to a race | Two pairs could proceed downstream for what should be a single-winner opportunity window | §9 requires the store's write path to guarantee at most one winner per key; idempotent re-evaluation must not create a second winner |
| 9 | Downstream Risk/Compliance rejects the winner and an implicit fallback silently promotes the runner-up | An un-reviewed, undecided fallback policy could effectively activate cross-pair retry logic never governed | §10 explicitly forbids any automatic fallback; the only authorized behavior absent a future fallback decision is "no trade that session, that cycle" |
| 10 | Reservation multiplicity if selection were placed after Risk Engine | Repeats this project's own prior `ReservationLedger` leak defect class at multiplied scale | §5's placement decision (before Risk Engine), now with an explicit barrier model, eliminates multi-reservation-per-session by construction |
| 11 | Incomplete candidate scan (one pair's evaluation errors out) treated as a complete, smaller universe | A session could select a "best" pair from an artificially narrowed set, silently | §7 (revised) requires the frozen expected count (Gate A ∩ `allowed_pairs`) vs. actual comparison, and fail-closed non-selection on mismatch |
| 12 | New pipeline stage violates ADR-031's Hard Rules (Runtime computing something) | Would break this project's core "Runtime is orchestration-only" safety invariant, structurally verified today | §5 (revised) places every new Runtime responsibility (session membership, completeness counting, winner equality-check) as membership/equality checks; §5 also identifies that ADR-031 §3's pipeline description itself requires a future, deferred amendment — not merely asserts compatibility |
| 13 | Session count silently hardcoded to two (London/NY) despite the configurability requirement | Adding, removing, or reconfiguring a session would require a code change and redeploy, contradicting §2's explicit requirement | §2/§8 require the session list to be configurable with arbitrary cardinality; London/NY are recorded only as intended initial policy content, never as an architectural constant |
| 14 | Stale winner from a closed range read and acted on in a later cycle | A pair could trade against an opening range that has already ended | §12 requires an explicit stale-winner observability signal; §9's keying by `range_start` alone means a new range is always a new key |
| 15 (new) | Two configured anchors share the same `SessionName` and a naive implementation keys on `SessionName` alone | Two genuinely distinct opportunity windows could collide under a single key, corrupting winner state for both | §8 (revised) makes `range_start` alone the key, never `SessionName`; two anchors sharing a `SessionName` already produce distinct, non-overlapping `range_start` values by Gate B's own existing validation |
| 16 (new) | Runtime cannot batch all of a session's candidates before any proceeds to Risk, because no such control-flow point exists today | Cross-pair selection is either unimplementable as specified, or implemented ad hoc without a governed control-flow model | §5 (corrected) specifies the one-pass-front-half/terminal-outcome/completeness/grouping/selection model explicitly, names Runtime as the barrier's owner, and identifies the required (deferred) ADR-031 §3 amendment rather than leaving the gap unaddressed |
| 17 (new) | Zero enabled sessions configured, but Gate A is broad (multi-pair) — Amendment 1's Gate A/B conditions pass, but no selection mechanism ever runs | Every broad-Gate-A pair proceeds independently and unrestricted, reintroducing the exact multi-simultaneous-trade risk this ADR exists to prevent, with no structural failure signal | §11 (new) requires a fail-closed detection of this specific combination before the broad-Gate-A flavor may be considered structurally ready |
| 18 (new) | A Gate B anchor is configured but its session is never added to the enabled-sessions list | `orb_breakout.py::qualify()` (unmodified) still qualifies against that anchor's range regardless of the enabled-sessions list, with no governed disposition for the resulting winning pair | §11 (new) requires this be caught at startup; §12 (new bullet) requires a defense-in-depth runtime signal and fail-closed suppression if it is ever reached anyway |
| 19 (new — final review's G1 finding) | A pair's front half is run once per enabled session instead of once per cycle, either wasting computation or, worse, requiring Runtime to know a pair's session membership before Strategy Engine has produced it | Duplicate computation (`CLAUDE.md` §1.4 violation) or an unimplementable circular routing decision | §5.A now requires exactly one front-half execution per pair per cycle, unconditionally; §5.B/§5.C classify the *already-produced* result afterward — no pre-evaluation routing decision exists anywhere in the corrected model |
| 20 (new — final review's G1 finding) | A legacy-strategy winner that happens to be a member of a broad ORB Gate A universe is held behind an ORB cross-pair barrier it has nothing to do with | Unnecessary latency/coupling for the majority of cycles during legacy/ORB coexistence, and a hidden new dependency of non-ORB execution on ORB's own barrier timing | §5.C/§5.G require a legacy-strategy (or any non-enabled-window) result to proceed immediately and independently, exactly as today — only a pair whose *own* result is itself an enabled-window ORB candidate is ever held back |

No adversarial scenario in this table is resolved by inventing a
product-policy value (a ranking weight, a pair, an anchor time, a
session count) — every disposition above is an architectural/process
control, consistent with this task's scope.

## 16. Preservation constraints (explicit)

This ADR does not authorize, and no implementation performed under it
may include, any of the following:

- Implementation of cross-pair selection logic.
- Retirement of any of the five legacy strategies.
- Activation of Gate A or Gate B (no pair, anchor, or session value is
  set).
- Ranking formula or weight values of any kind.
- Modification of `selection.py`, any strategy implementation
  (including `orb_breakout.py`), `RuntimeOrchestrator`, `RiskEngine`, or
  `ReservationLedger`.
- Modification of ADR-031, ADR-035, or ADR-036's text.
- Modification of any production configuration file.
- Phase 5 (ADR-035) anchor hour/minute validation work — remains
  separately gated and unauthorized, unrelated to this ADR.

## 17. Preconditions for the next phase (revised — F1 consequence named explicitly)

Before any Research/Plan work implementing this ADR's architecture may
begin:

1. An independent governance review of this document (§14).
2. If review finds defects: a revision pass, mirroring the ADR-036
   Amendment 1 precedent (draft → independent review → revision →
   final acceptance review → acceptance recorded) — this document has
   already gone through two such iterations (F1–F5 from the first
   review; G1–G2's barrier-mechanics correction from a second, final
   review), and would require a further iteration if a future review
   finds this correction still incomplete.
3. **A future, dedicated ADR-031 amendment** (not performed by this
   document, not authorized here) formalizing the corrected one-pass-
   front-half/terminal-outcome/completeness/grouping/selection/winner-
   only-back-half sequencing §5 specifies at the architecture level —
   required before implementation, since it changes what ADR-031 §3
   documents as Runtime's actual sequencing behavior for the affected
   subset of pairs (§5's ADR-031 compatibility analysis). This is a
   named precondition, not merely a possibility.
4. Only after this ADR's own Acceptance **and** item 3's ADR-031
   amendment: a dedicated Plan artifact (its own RPI Research → Plan →
   Implement cycle), which is where the ranking formula, exact session
   list, exact pairs, exact anchors, the exact enabled-sessions/Gate-A-B
   fail-closed detection mechanism (§11), and the additive
   `QualificationResult`/`StrategySnapshot` field carrying `range_start`
   (§4) would eventually be *proposed* (all still subject to their own
   authorization — this ADR does not pre-authorize any of them).

---

*This document is the governance/architecture-decision artifact for
session-scoped cross-pair ORB opportunity selection. It supersedes
nothing; it is additive context alongside ADR-035 and ADR-036, both
unmodified by it.*

---

# Amendment 1 (2026-07-29, Proposed — history preserved below, not backdated) — Persistence Semantics Correction

**Status: Proposed.** This amendment has not been independently reviewed
or Accepted. It does not, by itself, authorize anything §1–§17 above
does not already authorize, and it does not change ADR-037's own overall
Accepted status for §1–§17, none of which this amendment alters in
substance beyond the specific corrections named below (see "Unchanged
governance," §1).

**Why this amendment exists:** the independent "ADR-037 Implementation
Plan — Final Independent Plan Re-Review" of `docs/plans/adr-037-
implementation-plan.md` at commit `0388595` found that the Plan's
winner-only persistence design — needed to fix a genuine, independently-
discovered HIGH defect (a literal reading of §9's persistence text would
permanently lock a `range_start` to "no winner" starting from its very
first evaluated cycle, which is almost always empty during opening-range
formation) — could not be reconciled with §8/§9's own text as currently
written, since that text states plainly that "the fact that no winner
was selected must be recorded... in a ... persisted store." A dedicated
Research pass (`docs/plans/adr-037-persistence-semantics-amendment-
research.md`, commit `1f374d3`) traced ORB's actual multi-cycle lifecycle
from source (`titan_protocol/evidence_engine/opening_range.py`,
`titan_protocol/strategy_engine/strategies/orb_breakout.py`) and
confirmed: `range_start` is calendar-day-stable for a fixed anchor;
`qualify()` returns `NOT_QUALIFIED` throughout formation, by design; a
genuine breakout may legitimately arrive on any cycle strictly later
than a range's own formation cycle; and no source location defines an
authoritative point, earlier than calendar-day rollover, at which a
`range_start`'s opportunity to produce a winner can be said to have
concluded. That Research further found the implementation Plan's own
winner-only design (never persisting a negative outcome; only ever
persisting a genuine, immutable winner) is functionally indistinguishable
from an alternative "persisted provisional absence" design on every
capital-preservation, cardinality, restart, and concurrency dimension
tested, and that this codebase already has an Accepted precedent for
exactly the winner-only shape (`FormationBlackoutStore`, ADR-035 §2/§14
Amendment 1, Phase 7 — "a cycle that does not change the recorded value
skips the persist entirely... therefore never touches disk"). This
amendment implements exactly the correction that Research recommended:
§8/§9 reworded to match the Plan's already-correct design, a clarifying
sentence in §12, and procedural updates to §14/§17 — nothing more. No
discrepancy between the Research and current source was found while
drafting this amendment; nothing here departs from the Research's own
findings.

**Governance review and acceptance history:** first drafted Proposed
(this commit). No independent governance review has yet occurred. Per
this repository's established amendment pattern (ADR-031 Amendment 1;
ADR-036 Amendment 1; §17 item 2 above), this amendment requires an
independent governance review — and, if that review finds defects, a
revision pass — before it may be recorded as Accepted. Implementation of
ADR-037's architecture, and reconciliation of the implementation Plan
against this amendment's text, both remain blocked until that Acceptance
is recorded.

## 1. Unchanged governance (stated explicitly, not left implicit)

The following are **not reopened** by this amendment and require **no
textual change**:

- **§1–§4** (problem statement, preserved product requirement, governance
  vehicle, ownership) — unaffected. The dedicated Opportunity Selection
  Engine's ownership of the winner reduction (§4) is unchanged; this
  amendment corrects only what that engine's own store durably records,
  never who owns the decision.
- **§5** (pipeline placement and control-flow architecture) — unaffected
  in every particular: the single shared front-half pass (§5.A), post-
  front-half classification (§5.B), barrier participation (§5.C),
  completeness semantics (§5.D), grouping and selection after the shared
  pass (§5.E), multiple-enabled-windows independence (§5.F), and legacy
  coexistence (§5.G) are all unchanged. Pre-Risk/pre-Compliance placement
  is unchanged. This amendment corrects only §9's persistence contract
  and §8's value-side wording for what that contract stores — it does
  not touch when selection happens, who computes it, or what happens to
  a non-winning candidate that cycle (§5.E.5, unchanged: every
  non-winning candidate still ends its cycle at the barrier with the
  same explicit "not selected this opportunity window" terminal outcome,
  regardless of whether anything is persisted for that cycle).
- **§6** (cross-pair selection contract) — unaffected. Ranking policy
  remains explicitly unresolved; tie-handling remains flagged, not
  decided, by this ADR. This amendment does not adopt, alter, or imply
  any ranking formula, weight, or tie-tolerance value — those remain
  entirely the implementation Plan's own, separately-justified decisions
  (`docs/plans/adr-037-implementation-plan.md`'s own `tie_tolerance =
  0.5`, inclusive `<=`, and reject-on-tie choice are Plan-level content
  this amendment does not touch, reopen, or ratify).
- **§7** (candidate-set completeness and synchronization) — unaffected.
  The frozen candidate universe (Gate A ∩ `allowed_pairs`), the
  "received" vs. "terminal front-half outcome" distinction, and the
  fail-closed-on-incompleteness rule are all unchanged. An incomplete
  scan continues to mean zero candidates from that window may proceed
  into Risk that cycle — this amendment adds nothing to and removes
  nothing from that rule; it only confirms (§2 below) that an incomplete
  scan, like any other no-winner outcome, creates no durable winner-store
  entry.
- **§8, identity clause** — `range_start` alone remains the opportunity-
  window identity, unchanged; this is not reopened. Only §8's
  *value-side* sentence describing what is stored *for* that key is
  corrected (§3 below) — the key itself, its uniqueness, its calendar-day
  inclusion, and every scenario §8 already resolves (two anchors sharing
  a `SessionName`; overlapping-window rejection at startup; restart
  recomputing the identical `range_start`) are untouched.
- **§10** (Risk/Compliance/portfolio interaction) — unaffected. No
  automatic runner-up fallback remains the only authorized behavior when
  a winner is rejected downstream; this amendment does not touch, weaken,
  or reopen that.
- **§11** (Gate A/Gate B implications, enabled-sessions structural-
  readiness invariant) — unaffected. The three required checks (matching
  Gate B anchor; every configured anchor represented in the enabled-
  sessions list when selection is active; non-empty enabled-sessions list
  when selection is active), and their explicit separation from dynamic
  qualification outcomes, are unchanged. No Gate A or Gate B value is set
  or implied by this amendment.
- **§13** (relationship to ADR-036) — unaffected. This amendment does not
  redefine ADR-036's governance gate, Amendment 1's Gates A/B conditions,
  or the broad-Gate-A-vs-narrow/fixed-Gate-A distinction in any way.
- **§15** (capital-preservation adversarial review) — the existing 20
  rows are unaffected in substance; none of their dispositions depend on
  a negative outcome being durably persisted rather than cycle-local
  (independently re-checked against every row for this amendment). Row 7
  ("Winner store is corrupted or unreadable") and row 8 ("Two winners
  persisted... due to a race") remain accurate as written under the
  corrected persistence contract (§2 below) without modification — both
  concern the winner case only, which this amendment leaves unchanged in
  every fail-closed and cardinality particular.
- **§16** (preservation constraints) — unaffected; this amendment
  authorizes no code, no strategy modification, no configuration change,
  and no Gate A/B activation, exactly as §16 already requires of any
  change to this document.
- **ADR-031, ADR-031 Amendment 1, ADR-035, ADR-036, ADR-036 Amendment 1**
  — none is touched, reopened, or reinterpreted by this amendment. This
  amendment is entirely self-contained within ADR-037's own text and is
  independent of, and additional to, the separately-tracked ADR-031 §3
  amendment §17 item 3 already names.

## 2. Corrected persistence semantics (amends §9)

§9's second bullet is replaced in full:

> **Persistence (corrected):** at most one durable decision may ever
> exist for a given `range_start` — a genuine, single winning pair — and
> it is recorded in the same new, dedicated, restart-safe, persisted
> store §9 already establishes (distinct from `OrbQualificationStore` and
> `FormationBlackoutStore`, keyed by `range_start` alone). **A cycle that
> produces no winner — an empty candidate set, an unresolved tie, an
> incomplete scan (§7), or a selector/store failure of any kind — is
> fail-closed for that cycle (zero ORB candidates from that window may
> proceed into Risk) but creates no durable winner-store entry.** The
> absence of an entry for a `range_start` means exactly one thing: **no
> durable winner has yet been established for that opportunity window**
> — never "this opportunity window has permanently concluded with no
> winner." No terminal-window boundary is invented by this correction:
> `opening_range_duration_minutes` remains, exactly as before, the
> duration of the range's own *formation* period only (`range_end =
> range_start + duration`) — it is never read as marking when a window's
> opportunity to produce a winner ends, and this amendment does not
> introduce, imply, or require any other field or computation to serve
> that purpose. A `range_start` whose opportunity window remains
> currently relevant (§5.F, §8 — i.e., no newer range for the same anchor
> has yet formed) and has no durable winner-store entry remains eligible
> for re-evaluation on its next cycle, for as many cycles as it takes for
> a genuine winner to appear or for the window to be superseded by a
> newer range.

The **cardinality** bullet (at most one winner per `range_start`) and the
**fail-closed-on-store-corruption-or-unavailability** bullet are
unchanged in substance — restated here only to confirm they apply
identically under the corrected contract: if the store cannot be read or
is corrupt, the stage behaves as if no durable winner exists for that
range (never fail-open), which is now simply the same state as "no
winner yet established," not a distinct condition.

The **idempotency** bullet is corrected to remove an ambiguity the prior
text did not have occasion to address (since it assumed a persisted
negative value might also exist): idempotency is a property of the
**winner** case only. Once a genuine winner is durably established for a
`range_start`, it is **immutable** — no later cycle, restart, or
re-evaluation may replace it, silently overwrite it, or produce a second
winner for that same `range_start`; every later cycle or restart for that
`range_start` must converge on that same persisted winner without
recomputing a new one. Because no durable entry exists for the no-winner
case, there is no analogous "idempotency of absence" question to answer
— the absence of an entry is, by construction, always freely
re-evaluable, and this is not a gap the prior text's idempotency bullet
needed to close, since that text was itself never adopted as requiring
a persisted negative value in the first place (§3 below corrects the one
sentence that suggested otherwise).

**Atomicity, made explicit (a clarification, not a new requirement):**
the transition from "no durable winner exists for this `range_start`" to
"a durable winner exists" must be atomic with respect to Runtime's own
release of any candidate into Risk (§5.E.4) — i.e., the store's decision
for a given cycle must be fully and durably resolved before Runtime acts
on its result, and two concurrent attempts to establish a winner for the
same `range_start` must converge on a single, durably persisted winner;
neither may independently release a different locally-computed winner
into Risk. This restates, rather than adds to, §9's own already-Accepted
cardinality requirement ("never produces a second concurrent winner for
the same opportunity window") — the exact locking/atomicity mechanism
remains, as before, implementation/Plan-level work, not specified here.

**Restart, made explicit (a clarification, not a new requirement):**
restart before a winner is established resumes with no durable entry for
that `range_start`, exactly as if no cycle had run yet — restart must
never fabricate a "permanently no winner" decision that was never
durably made. Restart after a winner is established resumes with that
winner intact, unchanged and immutable, exactly as before restart —
identical in kind to `OrbQualificationStore`'s and `FormationBlackout
Store`'s own already-Accepted restart-resume behavior.

## 3. Corrected identity/value-side wording (amends §8)

§8's closing sentence — *"the value — `range_start` alone is the key;
the winning `pair` (or its absence) is what is stored *for* that key,
exactly mirroring `OrbQualificationStore`'s own key/value split"* — is
replaced:

> **The value:** `range_start` alone remains the key (unchanged, this
> section). When a value exists for that key, it is always a genuine,
> single winning pair — never a stored representation of "no winner." A
> key with no stored value correctly and permanently means "no durable
> winner has been established yet for this opportunity window" — the
> identical fact whether that key has never been evaluated or has been
> evaluated many times without producing a winner. This differs from
> `OrbQualificationStore`'s own key/value split only in this one respect
> (that store's value is a count that legitimately starts at, and may
> remain, zero as a *meaningful*, durably-recorded fact); the opportunity
> winner store's key/value split instead treats "not yet answered" and
> "answered in the negative" as the same, unrecorded state, since §9
> (corrected) establishes there is no negative answer this store durably
> records.

## 4. Cycle-local no-winner observability (clarifies §12; no redesign)

No signal in §12's existing list is added, removed, or altered by this
amendment. One clarifying sentence is added immediately following §12's
existing signal list:

> **Clarification:** the "No candidates available for a session," "Tie /
> no-winner produced despite candidates existing," "Incomplete scan
> detected," and "Selector failure of any kind" signals above are
> themselves how every cycle-local no-winner outcome remains observable
> and auditable. §9 (as corrected by Amendment 1) and this section
> describe two distinct mechanisms, not one: §9 governs the single,
> durable, immutable fact a `range_start` may eventually acquire (a
> genuine winner); this section governs the ordinary, cycle-local
> observability of every outcome that is not that fact. A cycle-local
> no-winner outcome being observable via this section's signals has never
> required, and does not now require, that it also be a persisted
> winner-store entry.

## 5. Procedural update (amends §14, §17)

§14's second paragraph gains one clause, appended after its existing
"Gate A/Gate B activation and legacy-strategy retirement remain governed
exclusively by ADR-036/Amendment 1" sentence:

> A second, independent, ADR-037-self-contained amendment (this document's
> own Amendment 1) corrects §8/§9's persistence semantics in light of
> source evidence gathered during the implementation Plan's own
> independent review cycle (`docs/plans/adr-037-persistence-semantics-
> amendment-research.md`); it is required, alongside the ADR-031 §3
> amendment already named above, before implementation may proceed, and
> follows the same draft → independent review → revision (if needed) →
> Acceptance-recorded sequence.

§17's precondition list gains one item, inserted as a new item 3 (existing
items 3–4 renumber to 4–5):

> 3. **This document's own Amendment 1** (persistence semantics
>    correction, §8/§9/§12/§14 above) must itself be independently
>    reviewed and Accepted — a named precondition, not merely a
>    possibility, exactly as item 4 (renumbered, the ADR-031 amendment)
>    already is.

## 6. Adversarial re-check of the corrected semantics

Re-checked against the Research's own adversarial matrix
(`docs/plans/adr-037-persistence-semantics-amendment-research.md` §5),
independently re-confirmed against this amendment's own final text
rather than assumed from the Research report:

| Scenario | Durable state after this amendment | May any candidate enter Risk? |
|---|---|---|
| Formation-period no winner → later winner | No entry after the formation cycle; a winner entry after the later cycle | Only the eventual winner, only after that later cycle |
| Formed range/no breakout → later breakout | Same shape | Same |
| Tie → later unique winner | No entry after the tie cycle; winner entry after the later cycle | Only the eventual unique winner |
| Repeated zero/tie cycles | No entry persists across any of them | None, for as long as no winner exists |
| Incomplete scan → later complete scan | No entry after the incomplete cycle (§7's fail-closed rule, unchanged); winner entry (if any) after a later complete, successful scan | None from the incomplete cycle; only a later genuine winner, if one is selected |
| Selector failure → later successful selection | No entry after the failure; winner entry after later success | None from the failed cycle; only the later winner |
| Restart before winner | No entry before or after restart — freely re-evaluable | None, until a winner is established |
| Restart after winner | Winner entry intact, unchanged, immutable, before and after restart | Only the already-established winner, identical to pre-restart behavior |
| Winner followed by a different/better candidate | Winner entry unchanged; the later, different candidate is never evaluated against it — the entry is returned unchanged | Only the original winner, never the later candidate |
| Concurrent attempts to establish different winners | Exactly one winner entry ever exists for the key — the store's own atomicity guarantee (§2 above) makes two different persisted winners for the same `range_start` structurally impossible | Never two winners; at most the one that is durably established |
| Persistence failure while establishing a winner | The in-memory decision stands for the process's remaining lifetime (identical, disclosed risk shape to `OrbQualificationStore`'s/`FormationBlackoutStore`'s own already-Accepted precedent — not introduced or worsened by this amendment) | Only the in-memory-decided winner, for that process's remaining lifetime; a restart before the failed write is retried resumes with no durable entry, per the restart clause above |
| Corrupted/unavailable winner state | Fails closed at read (as if no durable winner exists) — unchanged from §9's original fail-closed bullet | None, until the store is trustworthy again and a winner is (re-)established |
| Stale prior-day state | `range_start`'s calendar-day-inclusive construction (§8, unchanged) makes a new day a new key; no stale entry is ever consulted for a new day's `range_start` | Only via that day's own, freshly-evaluated `range_start` |
| Multiple independent windows | Each `range_start` is an independent key; no cross-window interaction | Each window's own winner (if any) proceeds independently |

**Every no-winner and failure case remains fail-closed for that cycle
under this amendment.** Nothing in this amendment creates, authorizes, or
implies any fallback to unrestricted per-pair execution — §12's absolute
requirement ("any selector failure mode... must result in zero pairs
proceeding for that session that cycle... never fall back to today's
unrestricted independent-per-pair execution") is unchanged and is not
weakened by this amendment in any row above.

## 7. Scope and non-authorization

This amendment does **not** authorize, decide, reopen, or imply:

- Implementation of the Opportunity Selection Engine, `OpportunityWinner
  Store`, or any Runtime restructuring — this remains governance-document
  work only.
- Any ranking formula, ranking weights, or tie-handling policy beyond
  what §6 (unchanged) already leaves unresolved. The implementation
  Plan's own `tie_tolerance = 0.5` (inclusive `<=`) and reject-on-tie
  choice are not reopened, revisited, or ratified here.
- The initial production policy of London + London–New York Overlap +
  Early New York, or any other exact session/pair/anchor value —
  unaffected, untouched, settled elsewhere (`docs/plans/adr-037-ranking-
  tie-session-policy-decision.md`).
- Liquidity/spread remaining eligibility **gates** in `orb_breakout.py`
  rather than ranking criteria — unaffected; this amendment touches
  neither `orb_breakout.py` nor any ranking mechanism.
- Any automatic runner-up fallback policy — §10 (unaffected) remains the
  sole governing text; the only authorized behavior on downstream
  rejection remains "no trade that session, that cycle."
- The ADR-036 broad-Gate-A-route relationship, or any ADR-036/Amendment
  1 text — §13 (unaffected).
- ADR-031 or ADR-031 Amendment 1 — neither is touched; this is a
  separate, independent, ADR-037-self-contained amendment.
- Gate A or Gate B activation, or any exact production pair/anchor/clock
  value.
- Legacy-strategy retirement, or any ADR-036 implementation sequencing.
- The ADR-035 Phase 5 anchor hour/minute validation follow-up — entirely
  untouched, unrelated, and unauthorized by this amendment.
- Any concrete store API, locking mechanism, data structure, test name,
  or implementation sequencing — these remain, exactly as before, the
  implementation Plan's own work (§2's "Persistence (corrected)" text
  above states invariants and ownership only; it does not specify
  `decide_once()`'s signature, `threading.Lock` usage, JSON schema, or
  any other implementation detail, all of which the Plan already
  specifies and this amendment does not restate or second-guess).
- Modification of `tests/titan_protocol/opportunity_selection_engine/
  test_store.py` or any other test — no test exists yet to modify. The
  Research's own LOW, non-blocking observation that the Plan's existing
  concurrency-test specification does not explicitly require differing
  per-thread candidate sets (`docs/plans/adr-037-persistence-semantics-
  amendment-research.md` §8) is preserved here as a **future Plan-
  reconciliation item** — this amendment does not solve a test-
  specification question inside the ADR, and the reconciliation gate
  after this amendment's own Acceptance is where that item belongs.

## 8. Acceptance criteria for this amendment

- ✓ `range_start` remains the sole opportunity-window identity,
  unchanged (§1, §3).
- ✓ A cycle may produce no winner without permanently concluding that
  opportunity window (§2).
- ✓ Empty candidate sets, unresolved ties, incomplete scans, selector
  failures, and every other no-winner outcome remain fail-closed for
  that cycle — zero ORB candidates proceed into Risk (§2, §6).
- ✓ Cycle-local no-winner outcomes remain observable/auditable via §12's
  existing signals without creating a durable winner-store entry (§4).
- ✓ Only a genuine selected winning pair becomes durable winner state
  (§2, §3).
- ✓ Once durably established, a winner is immutable, and later
  cycles/restarts converge on it (§2).
- ✓ Winner establishment is atomic with respect to Runtime's release of
  any candidate into Risk (§2).
- ✓ Absence of a winner-store entry means no durable winner has yet been
  established, never "permanently no winner" (§2, §3).
- ✓ Restart before winner establishment permits later re-evaluation;
  restart after winner establishment preserves the established winner
  (§2).
- ✓ No terminal opportunity-window boundary is invented;
  `opening_range_duration_minutes` remains formation duration only (§2).
- ✓ No settled decision named in §1/§7 above is reopened.
- ✓ No concrete store API, locking mechanism, data structure, test name,
  or implementation sequencing is specified by this amendment (§7).
- ✓ This amendment remains **Proposed** and self-evidently does not mark
  itself Accepted.

---

*This amendment is Proposed. It requires its own independent governance
review before Acceptance. It does not authorize implementation of
ADR-037's architecture, any ranking/tie/session-production-policy
decision, Gate A/Gate B activation, ADR-036 legacy-strategy retirement,
or reconciliation of the implementation Plan against this amendment's
text. The ADR-035 Phase 5 anchor hour/minute validation follow-up
remains separately gated, unauthorized, and out of scope.*
