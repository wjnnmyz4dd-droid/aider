# ADR-037 — ORB Cross-Pair Session Opportunity Selection

Status: **Proposed** (revised). No implementation accompanies this
document, and none is authorized by it. This is a governance/architecture-
decision artifact only, produced in response to a dedicated governance
pass following the completed Research artifact
`docs/plans/adr-036-session-scoped-orb-selection-research.md` (commit
`a13e5c0`). It does not itself constitute the "established process"
`CLAUDE.md` §1.10 requires before implementation — an independent
governance review of this document is the next required gate, per §14.

**Revision history:** first drafted Proposed (commit `e3717c5`). An
independent governance review of that draft found the overall direction
sound but identified five required revisions (F1–F5, all HIGH/MEDIUM):
an unaddressed Runtime control-flow/barrier requirement for cross-pair
placement (F1); a session-identity claim that did not reconcile against
`OpeningRangeState`'s own documented "session is descriptive only"
invariant (F2); a missing fail-closed tie between this ADR's new
enabled-sessions configuration and ADR-036 Amendment 1's existing Gate A/
Gate B invariant (F3); an unargued ownership choice that never tested
the smallest alternative (F4); and a candidate-completeness check with
no named source for "expected count" (F5). This revision addresses all
five directly, below, without reopening the settled conclusions the
review confirmed (governance vehicle, pre-Risk placement, no-silent-
fallback default, the ADR-036 broad-Gate-A-only dependency).

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

## 5. Pipeline placement and control-flow architecture (revised — F1)

**Decision (unchanged from the prior draft): immediately after Strategy
Engine qualification, before Risk Engine — but this revision now
specifies the control-flow model required to achieve that placement,
which the reviewed draft omitted.**

**What the independent review found, verified fresh against source for
this revision:** `RuntimeOrchestrator`'s only production entry point,
`run_cycle()` (`titan_protocol/runtime/engine.py:413`), loops
`for pair in sorted(pairs)` and calls `run_cycle_for_pair()`
(`engine.py:110`) once per pair. `run_cycle_for_pair()` is a single,
monolithic function that runs Evidence → Market Intelligence → Strategy
→ Risk → Compliance → Bridge **all the way through for one pair, in one
call**, with early-exit on any rejection, before the loop advances to
the next pair. There is no existing point at which Runtime holds
multiple pairs' Strategy Engine outputs simultaneously. Inserting a
cross-pair stage between Strategy and Risk is therefore not a diagram
edit — it requires a real, if narrowly scoped, restructuring of how
Runtime sequences the affected pairs. That restructuring is specified
below, at the architecture level, not deferred to an implementer.

**The control-flow model:**

1. **Scope of the restructuring.** Only pairs whose Strategy Engine
   output is (a) a winning ORB qualification and (b) tagged with a
   `range_start` (§8) belonging to a **currently enabled session**
   (§8/§11) are affected. Every other pair — evaluated by a legacy
   strategy, or by ORB against an anchor whose session is not enabled,
   or with no formed range at all — continues through the existing,
   entirely unmodified single-pass `run_cycle_for_pair()` exactly as
   today: Evidence → Market Intelligence → Strategy → Risk → Compliance
   → Bridge, independently, with no barrier and no engine call added.
   This ADR's mechanism is additive for a defined subset of cycles, not
   a rewrite of Runtime's default behavior.
2. **Front half / back half.** For a pair that *is* in scope, Runtime's
   existing per-pair sequence is split at the same point this ADR
   already identified as the placement boundary: a **front half**
   (Evidence → Market Intelligence → Strategy, unmodified engine calls,
   in the same order, on the same per-pair signatures ADR-031 §3
   already specifies) and a **back half** (Risk → Compliance → Bridge,
   likewise unmodified). Both halves reuse today's exact engine calls;
   nothing about Evidence/MI/Strategy/Risk/Compliance/Bridge's own
   `evaluate()` signatures changes.
3. **The barrier.** For each enabled session, Runtime completes the
   front half for **every** candidate pair in that session's frozen
   candidate universe (§7 defines "frozen" and the universe's source)
   before continuing *any* of them into the back half. This is the
   barrier the reviewed draft's diagram implied but never located.
   Completing the front half for the whole set, then pausing, is new
   sequencing behavior for `run_cycle`/`run_cycle_for_pair` — it does
   not exist today and must be added.
4. **Who owns the barrier.** **Runtime owns the barrier's mechanics**
   (knowing which pairs belong to which enabled session's candidate
   universe — a static configuration membership fact, not a computed
   trading decision; counting front-half completions against §7's
   frozen expected count; and, once complete, invoking the Opportunity
   Selection Engine). **The Opportunity Selection Engine owns the
   decision** (which pair, if any, wins). This split mirrors the same
   division of labor Runtime already has with every other engine: it
   sequences and checks results, it does not compute them.
5. **How the engine receives the complete set.** Runtime passes the
   Opportunity Selection Engine the full set of that session's front-
   half results — each candidate's `QualificationResult`/
   `StrategySnapshot` (including the `range_start` identity required by
   §4/§8) — once §7's completeness check confirms the frozen universe
   was fully evaluated. An incomplete set is never passed forward as if
   complete (§7).
6. **How exactly one selected pair proceeds.** The engine returns
   `Optional[pair]` (§6, unchanged). Runtime reads that result and
   continues the back half **only** for the pair matching it — an
   equality check against a value another engine's public interface
   already returned, the same verification shape ADR-031 §2 already
   requires of every Runtime conditional.
7. **How rejected/non-winning pairs stop before Risk.** Every other pair
   in that session's candidate universe ends its cycle at this point
   with a new, explicit terminal outcome ("not selected this session") —
   the same shape as existing `CycleOutcome` terminal values
   (`runtime/models.py`'s existing enum already models per-pair cycle
   endings this way, e.g. `NO_STRATEGY`, `RISK_REJECTED`); this ADR does
   not invent the mechanism, only requires that one exists so a non-
   winning pair's cycle is recorded as ended, not silently dropped.
   Risk, Compliance, and Bridge are never invoked for a non-winning pair
   this cycle.
8. **Overlapping enabled sessions.** Each enabled session gets its own
   independent candidate universe, its own barrier, and its own
   Opportunity Selection Engine invocation — even when two sessions'
   time windows overlap. This is safe by construction because Gate B's
   own anchor validation (`_validate_no_overlapping_anchors`,
   `evidence_engine/config.py`) already guarantees every configured
   anchor's `[range_start, range_end)` window is disjoint from every
   other's; a pair cannot simultaneously have two different "currently
   relevant" ranges (`orb_breakout.py`'s own `latest_range_end` logic
   already collapses to at most one per pair per cycle, §2), so a pair
   present in two sessions' *nominal* candidate universes is only ever
   an active candidate in **whichever one session** its currently-formed
   range actually belongs to that cycle — never both at once. Runtime
   does not need to pre-partition pairs into sessions; membership in a
   given cycle's barrier is determined dynamically by which range each
   pair's front half actually produced, filtered to enabled sessions.
9. **Pairs/session-ranges not participating.** Can exist, and must not
   silently fall back to unrestricted execution — this is exactly F3's
   subject; see §11's new structural-readiness invariant, which this
   subsection depends on: the routing rule above is only safe if every
   configured anchor whose session is *not* enabled is caught at startup
   (§11), not encountered for the first time at runtime.

**Capital-preservation analysis — why not after Risk Engine (unchanged
from the prior draft, still sound):** the Research (§3.5, §4) flagged
that placing selection *after* Risk Engine would require Risk Engine to
first create a reservation for every candidate pair in a session, then
release every reservation except the winner's — structurally the same
class of defect as this project's own prior, already-fixed
`ReservationLedger` leak (session history: `S415`/`2173`/`2184`).
Placing selection *before* Risk Engine, via the barrier above, means at
most one reservation is ever created per session per cycle (for the
winner only), eliminating that entire risk class by construction.

**Accepted tradeoff, explicitly not resolved further here:** a winner
selected pre-Risk/Compliance can still be rejected by Risk or Compliance
after selection (insufficient margin, correlation breach, compliance
veto, etc.), with **no automatic fallback to the session's second-best
candidate**. This is a deliberate scope boundary, not an oversight — see
§10.

**ADR-031 compatibility, reassessed (the review's central question):**
the Hard Rules (`ADR-031` §2 — Runtime must never generate signals,
calculate evidence, calculate risk, make compliance decisions, or
override any engine, verified by requiring every Runtime conditional to
be an equality/membership check) **remain satisfied by the model above,
and require no text change.** Every new thing Runtime does under this
model reduces to membership/equality checks against values already
computed elsewhere: "does this pair's front-half range belong to an
enabled session" (a static config-membership check), "has the front half
completed for every pair in the frozen universe" (a count comparison
against a config-derived number, §7), "does this pair equal the engine's
returned winner" (an equality check). Runtime is not deciding *who wins*
— the Opportunity Selection Engine is — Runtime is only deciding *when
to call it* and *which pair's back half to continue*, both sequencing
decisions, not trading decisions. This is the same distinction ADR-031
already draws between Runtime and every other engine it calls.

**However, `ADR-031` §3 ("Pipeline (exactly)") itself is not merely
compatible without change.** §3 is written as a strict, linear, per-pair,
per-cycle six-stage sequence with early-exit discipline — accurate today
for every pair, unconditionally. Under this ADR's model, that description
becomes accurate only for pairs *outside* an enabled session's candidate
universe; pairs inside one instead go through the front-half/barrier/
back-half sequence in §5.3–§5.7. **This is a real, substantive change to
what §3 documents as Runtime's actual sequencing behavior — not a
cosmetic one — and it requires its own future ADR-031 amendment before
implementation**, describing the two-phase, session-scoped sequencing
precisely (which this revision has now specified at the architecture
level, so that future amendment has a concrete model to formalize rather
than an open question). Consistent with this task's constraint not to
touch ADR-031 during this revision, **that amendment is required but
explicitly deferred**, and is now added to §17's preconditions as a named
item, more concretely scoped than the prior draft's vague "one row"
characterization.

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

## 7. Candidate-set completeness and synchronization (revised — F5)

A session's selection is only meaningful if it was computed over the
*complete, frozen* intended candidate universe for that session. The
independent review correctly found that the prior draft never named
where "expected count" comes from, risking a circular definition
("expected" silently redefined as "however many results arrived," which
would defeat the check entirely). This revision names the source:

**Authoritative candidate universe for a session's scan (frozen at scan
start):** the intersection of

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
**same** intersection therefore applies to every enabled session's scan
unless and until a future, separately authorized Plan introduces session-
specific narrowing — not decided or implied here.

**Freezing:** this intersection is computed **once, at the start of that
session's scan**, and held fixed for the duration of that scan/cycle —
never recomputed mid-scan. This directly satisfies three of the review's
named scenarios: (a) a mid-scan config reload cannot silently narrow or
widen what "complete" means, because completeness is judged against the
frozen count, not a live recount; (b) a retry/reconnect for one pair
cannot redefine "complete" as "however many results eventually arrived,"
because the frozen expected count doesn't change; (c) "expected count"
is never circularly defined as "actual count," because it is fixed
before any front-half result exists for that scan.

The new stage's requirements, otherwise unchanged from the prior draft:

- Compare the frozen expected count against the actual count of front-
  half results (`QualificationResult`/`StrategySnapshot`, §4) received
  for that session's scan before selecting.
- **Fail closed on incompleteness:** if the actual count is less than
  the frozen expected count (a pair's upstream evaluation errored, timed
  out, or was skipped), the stage must not select a winner from the
  partial set — no winner is produced for that session that cycle.
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
   prevent this configuration from ever being live; §5.9's runtime
   routing rule (fail closed with an explicit signal, §12) is the
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

This document is **Proposed**. It is not marked Accepted by this task,
per this task's own explicit instruction: no established repository
process in this session authorizes self-acceptance of a newly drafted
ADR — every prior ADR/Amendment in this session's history (ADR-036 and
its Amendment 1) reached Accepted status only after a separate,
independent governance review pass found no unresolved defect. The next
required gate for this document is exactly that: an independent
governance review of this ADR's decisions (§3–§13) before it can be
considered for Acceptance.

## 15. Capital-preservation adversarial review (updated — identity and control-flow corrections)

| # | Scenario | Exposure if unaddressed | Disposition under this ADR |
|---|----------|--------------------------|------------------------------|
| 1 | London winner contaminates New York's selection (state not cleared between sessions) | A stale pair trades under the wrong session's risk/liquidity profile | Winner store is keyed by `range_start` alone, not global and not by `SessionName` (§8/§9, revised); a new opportunity window is always a new key, never inherited |
| 2 | Overlapping sessions (e.g. London/NY overlap window) share winner state | Two sessions could either double-count or improperly veto each other's selection | Gate B's own `_validate_no_overlapping_anchors` already guarantees distinct, non-overlapping `range_start` windows per configured anchor (§8, verified against `evidence_engine/config.py`); overlapping *sessions* are still distinct keys by construction, never merged |
| 3 | A disabled session still scans and/or selects | Wasted computation is the benign case; the dangerous case is a disabled session's "winner" leaking into execution | Enablement is part of session configuration (§8); §5's routing rule only admits a pair to the barrier when its currently-relevant range's session is enabled — a disabled session's pairs never enter the barrier at all |
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
| 16 (new) | Runtime cannot batch all of a session's candidates before any proceeds to Risk, because no such control-flow point exists today | Cross-pair selection is either unimplementable as specified, or implemented ad hoc without a governed control-flow model | §5 (revised) specifies the front-half/barrier/back-half model explicitly, names Runtime as the barrier's owner, and identifies the required (deferred) ADR-031 §3 amendment rather than leaving the gap unaddressed |
| 17 (new) | Zero enabled sessions configured, but Gate A is broad (multi-pair) — Amendment 1's Gate A/B conditions pass, but no selection mechanism ever runs | Every broad-Gate-A pair proceeds independently and unrestricted, reintroducing the exact multi-simultaneous-trade risk this ADR exists to prevent, with no structural failure signal | §11 (new) requires a fail-closed detection of this specific combination before the broad-Gate-A flavor may be considered structurally ready |
| 18 (new) | A Gate B anchor is configured but its session is never added to the enabled-sessions list | `orb_breakout.py::qualify()` (unmodified) still qualifies against that anchor's range regardless of the enabled-sessions list, with no governed disposition for the resulting winning pair | §11 (new) requires this be caught at startup; §12 (new bullet) requires a defense-in-depth runtime signal and fail-closed suppression if it is ever reached anyway |

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
   final acceptance review → acceptance recorded) — this document is
   itself one iteration of that cycle, addressing F1–F5 from the first
   such review.
3. **A future, dedicated ADR-031 amendment** (not performed by this
   document, not authorized here) formalizing the two-phase, session-
   scoped front-half/barrier/back-half sequencing §5 specifies at the
   architecture level — required before implementation, since it changes
   what ADR-031 §3 documents as Runtime's actual sequencing behavior for
   the affected subset of pairs (§5's ADR-031 compatibility analysis).
   This is a named precondition, not merely a possibility.
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
