# ADR-037 — ORB Cross-Pair Session Opportunity Selection

Status: **Proposed**. No implementation accompanies this document, and
none is authorized by it. This is a governance/architecture-decision
artifact only, produced in response to a dedicated governance pass
following the completed Research artifact
`docs/plans/adr-036-session-scoped-orb-selection-research.md` (commit
`a13e5c0`). It does not itself constitute the "established process"
`CLAUDE.md` §1.10 requires before implementation — an independent
governance review of this document is the next required gate, per §14.

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
satisfied; see §3 for why this ADR does not amend ADR-031 itself.
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
- **Not a substantive ADR-031 amendment.** ADR-031's Hard Rules require
  Runtime to never generate signals, calculate evidence, calculate risk,
  make compliance decisions, or override any engine — verified
  structurally by requiring every Runtime conditional to be an
  equality/membership check against a value another engine's public
  interface already returned. Placing cross-pair selection in a new,
  dedicated engine/component (§4) that Runtime merely *consults* (asking
  "is this pair this session's winner?" — a membership check) keeps
  Runtime's own compliance with ADR-031 intact without changing ADR-031's
  text. A **narrow, documentation-only future amendment** — adding one
  row naming the new stage to ADR-031's own "§3 Pipeline (exactly)"
  list, once the new stage is actually implemented — will eventually be
  required, but is explicitly **deferred, not performed by this ADR**:
  this document does not touch ADR-031, and no pipeline-list edit is
  authorized here.
- **New ADR-037 is the smallest accurate vehicle** because the
  capability has its own ownership question, its own persisted state,
  its own failure semantics, and its own adversarial risk profile (§15)
  — exactly the criteria this project's own ADR-per-stage discipline
  (`CLAUDE.md` §1.10) uses to justify a dedicated ADR rather than
  amending an existing one.

## 4. Ownership

A new, dedicated component owns cross-pair, within-session opportunity
selection. Working name: **Opportunity Selection Engine** (provisional —
not load-bearing; the eventual implementation Plan may rename it,
subject to its own review). It is a new pipeline-stage-level component
in the same sense Evidence Engine, Market Intelligence, Strategy Engine,
Risk Engine, and Compliance Engine are — i.e., it requires its own
Accepted ADR before any implementation, per `CLAUDE.md` §1.10, exactly
as this document provides.

It does **not** reuse or extend:
- `selection.py` (same-pair, cross-strategy — a different comparison
  axis entirely; the Research's own adversarial review and this ADR's
  §3 both treat modifying it as out of scope),
- `RiskEngine` (owns sizing, reservation, and portfolio-heat/correlation
  limiting — not opportunity discovery; see §6 for why placing selection
  inside or after Risk Engine is rejected),
- `RuntimeOrchestrator` (forbidden by ADR-031's Hard Rules — Runtime
  computes nothing).

## 5. Pipeline placement

**Decision: immediately after Strategy Engine qualification, before
Risk Engine.**

The real production pipeline (ADR-031 §3) is: Evidence Engine → Market
Intelligence Engine → Strategy Engine → Portfolio Statistical Risk
Engine → Compliance Engine → Bridge, with early-exit discipline at every
stage. This ADR's placement inserts a new stage between Strategy Engine
and Risk Engine, scoped to sessions where cross-pair selection applies:

Evidence Engine → Market Intelligence Engine → Strategy Engine →
**Opportunity Selection Engine** → Portfolio Statistical Risk Engine →
Compliance Engine → Bridge.

**Capital-preservation analysis — why not after Risk Engine:** the
Research (§3.5, §4) flagged that placing selection *after* Risk Engine
would require Risk Engine to first create a reservation for every
candidate pair in a session (to know each candidate's true sizing/risk
posture before comparing them), then release every reservation except
the winner's. This is structurally the same class of defect as this
project's own prior, already-fixed `ReservationLedger` leak (session
history: `S415`/`2173`/`2184` — reservation created but not correctly
released on a downstream rejection). Multiplying reservations by
candidate-set size multiplies the leak surface by the same factor,
directly before the exact subsystem that already had one leak bug in
this codebase's history. Placing selection *before* Risk Engine means
at most one reservation is ever created per session per cycle (for the
winner only), eliminating that entire risk class by construction rather
than by careful release-path auditing.

**Accepted tradeoff, explicitly not resolved further here:** a winner
selected pre-Risk/Compliance can still be rejected by Risk or Compliance
after selection (insufficient margin, correlation breach, compliance
veto, etc.), with **no automatic fallback to the session's second-best
candidate**. This is a deliberate scope boundary, not an oversight — see
§10.

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

## 7. Candidate-set completeness and synchronization

A session's selection is only meaningful if it was computed over the
*complete* intended candidate universe for that session. The new stage
must:

- Know, for each enabled session, the expected candidate-pair count
  (derived from that session's configured universe — §8/§11, not
  invented here).
- Compare expected count against actual `QualificationResult` count
  received before selecting.
- **Fail closed on incompleteness:** if the actual count is less than
  expected (a pair's upstream evaluation errored, timed out, or was
  skipped), the stage must not select a winner from the partial set —
  no winner is produced for that session that cycle. Treating a partial
  scan as if it were complete is exactly the "silent narrowing" failure
  mode this task's governing instructions repeatedly warn against.

## 8. Session identity and lifecycle (configurable, no anchor values chosen)

Per §2's Session configuration requirement, sessions are a
**configurable list**, each entry carrying:

- A stable **session identifier** (e.g. a name/key distinct from the
  pair identifiers already in use).
- A cross-reference to Gate B's existing anchor mechanism
  (`EvidenceEngineConfig.opening_range_anchors`, keyed by
  `SessionName`/hour/minute per Research §1) — this ADR does not choose
  which sessions are enabled or what their anchor hours/minutes are;
  that remains Gate B's own unresolved production-value decision
  (§13/ADR-036).
- An enabled/disabled flag, so the list's *cardinality* is a
  configuration matter, never a code change.

**Explicitly not decided here:** how many sessions are enabled in
production, which named sessions they are, and their exact anchor clock
values. London and New York remain, per §2, the *intended initial
policy content* for this list — never an architectural upper or fixed
bound.

## 9. Winner cardinality, persistence, and fail-closed semantics

- **Cardinality:** at most one winner per `(enabled session, range_start)`
  pair. Never more than one pair proceeds downstream per session per
  range.
- **Persistence:** the winner (or the fact that no winner was selected)
  must be recorded in a **new, dedicated, restart-safe, persisted
  store**, distinct from `OrbQualificationStore` and
  `FormationBlackoutStore` (Research §3.7) — those are keyed by `(pair,
  range_start)`; this store is keyed by `(session, range_start)`,
  reflecting that the decision being persisted is *about* a session, not
  a pair. This follows the same established design pattern (restart-safe,
  fail-closed-on-corruption) without merging into either existing
  store's key space.
- **Fail-closed on store corruption or unavailability:** if the winner
  store cannot be read or is corrupt, the stage must behave as if no
  winner exists for that session/range — never fail open by allowing an
  unselected pair to proceed, and never fabricate a winner from stale
  data.
- **Idempotency:** re-evaluating the same `(session, range_start)` after
  a winner is already persisted must not silently overwrite it or
  produce a second winner; the exact re-evaluation policy (reject vs.
  return the existing winner unchanged) is left to the implementation
  Plan, constrained only by "never produces a second concurrent winner
  for the same session/range."

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

## 11. Gate A / Gate B implications (kept unresolved)

- **Gate A** (`DEFAULT_APPROVED_PAIRS_BY_STRATEGY`'s ORB entry) must
  remain a **broad structural eligibility list** — the candidate
  universe a session scans — not a single pair; a single-pair Gate A
  would make this ADR's mechanism a no-op (nothing to select between).
  The *width* of that list for production is now a decision coupled to
  this ADR's own eventual Acceptance and implementation, not a
  standalone ADR-036 decision. This ADR does not set that list's
  contents.
- **Gate B** (`opening_range_anchors`) remains session/time-of-day-keyed,
  never pair-specific, consistent with its existing shape (Research §1).
  Session *enablement* (§8, which sessions are turned on) and anchor
  *configuration* (Gate B's existing hour/minute values) are likely two
  distinct, cross-validated configuration concepts rather than one
  merged field — the exact schema is implementation-Plan work, not
  decided here.
- Both gates remain **unresolved** by this document, exactly as directed.

## 12. Observability and fail-closed requirements

The new stage must emit distinct signals for at least:

- Session scan started / completed, with expected-vs-actual candidate
  counts (§7).
- No candidates available for a session.
- Winner selected (session, range_start, pair).
- Tie / no-winner produced despite candidates existing.
- Incomplete scan detected (§7's fail-closed path taken).
- Selector failure of any kind (exception, store unavailable, etc.).
- Stale winner detected (a persisted winner from a range that should
  already be closed).
- Downstream rejection of a session's winner (§10).

**Absolute requirement:** any selector failure mode must result in
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
approved production pair" and "≥1 valid anchor entry." That narrow path
can proceed to its own deployment-profile decision and implementation
independent of this ADR's Acceptance or implementation status.

This ADR does **not** redefine ADR-036 §13's governance-gate text,
Amendment 1's Gates A/B conditions, or ADR-036's Completion phase in any
way. ADR-036 implementation remains blocked for the reasons already on
record (Plan §P16, this session's own prior dispositions) regardless of
this ADR's outcome, until whichever Gate A/B path (narrow or broad) is
actually chosen and resolved.

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

## 15. Capital-preservation adversarial review

| # | Scenario | Exposure if unaddressed | Disposition under this ADR |
|---|----------|--------------------------|------------------------------|
| 1 | London winner contaminates New York's selection (state not cleared between sessions) | A stale pair trades under the wrong session's risk/liquidity profile | Winner store is keyed by `(session, range_start)`, not global; a new session/range is a new key, never inherited (§9) |
| 2 | Overlapping sessions (e.g. London/NY overlap window) share winner state | Two sessions could either double-count or improperly veto each other's selection | Session identity (§8) is a distinct configured entity even where anchor hours overlap; each session's key is independent — this ADR does not merge overlapping sessions into one state slot |
| 3 | A disabled session still scans and/or selects | Wasted computation is the benign case; the dangerous case is a disabled session's "winner" leaking into execution | Enablement is part of session configuration (§8); a disabled session must not enter the scan/select path at all — an implementation detail this ADR requires but does not itself code |
| 4 | Candidate-pair universe changes mid-session (config reload between range formation and selection) | Selection computed against a universe that no longer matches what was actually scanned | §7's expected-vs-actual completeness check is evaluated against the universe in effect at scan time; a mid-session change is exactly the kind of mismatch §7 is designed to catch and fail closed on |
| 5 | Test-only pair/session configuration mistaken for production policy | A fixture list (e.g. Research's own test pairs) silently becomes a production eligibility decision | This ADR explicitly declines to name any pair, anchor time, or session count as production policy (§2, §8, §11); the eventual Plan/deployment-profile decision must draw production values from an authoritative operator decision, not test fixtures — same discipline already established in ADR-036's Gate A/B history |
| 6 | Selector throws an exception mid-scan | Partial state could be misread as a valid empty or full result | §7/§12 require selector failure of any kind to produce zero winners and zero downstream pairs for that session that cycle — never partial-result interpretation |
| 7 | Winner store is corrupted or unreadable | A stale or fabricated winner could be read back and trade | §9 requires fail-closed treatment (as if no winner exists) on any store corruption/unavailability, never fail-open |
| 8 | Two winners persisted for the same `(session, range_start)` due to a race | Two pairs could proceed downstream for what should be a single-winner session | §9 requires the store's write path to guarantee at most one winner per key; idempotent re-evaluation must not create a second winner |
| 9 | Downstream Risk/Compliance rejects the winner and an implicit fallback silently promotes the runner-up | An un-reviewed, undecided fallback policy could effectively activate cross-pair retry logic never governed | §10 explicitly forbids any automatic fallback; the only authorized behavior absent a future fallback decision is "no trade that session, that cycle" |
| 10 | Reservation multiplicity if selection were placed after Risk Engine | Repeats this project's own prior `ReservationLedger` leak defect class at multiplied scale | §5's placement decision (before Risk Engine) eliminates multi-reservation-per-session by construction |
| 11 | Incomplete candidate scan (one pair's evaluation errors out) treated as a complete, smaller universe | A session could select a "best" pair from an artificially narrowed set, silently | §7 requires expected-vs-actual count comparison and fail-closed non-selection on mismatch |
| 12 | New pipeline stage violates ADR-031's Hard Rules (Runtime computing something) | Would break this project's core "Runtime is orchestration-only" safety invariant, structurally verified today | §3/§4 place the new logic in a dedicated engine Runtime only *consults* via membership/equality check, preserving ADR-031's existing structural verification without modifying ADR-031 |
| 13 | Session count silently hardcoded to two (London/NY) despite the configurability requirement | Adding, removing, or reconfiguring a session would require a code change and redeploy, contradicting §2's explicit requirement | §2/§8 require the session list to be configurable with arbitrary cardinality; London/NY are recorded only as intended initial policy content, never as an architectural constant — this ADR's design is non-conforming if any future implementation hardcodes the count |
| 14 | Stale winner from a closed range read and acted on in a later cycle | A pair could trade against an opening range that has already ended | §12 requires an explicit stale-winner observability signal; §9's keying by `range_start` means a new range is a new key, and the implementation Plan must ensure stale keys are never read as current |

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

## 17. Preconditions for the next phase

Before any Research/Plan work implementing this ADR's architecture may
begin:

1. An independent governance review of this document (§14).
2. If review finds defects: a revision pass, mirroring the ADR-036
   Amendment 1 precedent (draft → independent review → revision →
   final acceptance review → acceptance recorded).
3. Only after Acceptance: a dedicated Plan artifact (its own RPI Research
   → Plan → Implement cycle), which is where the ranking formula, exact
   session list, exact pairs, and exact anchors would eventually be
   *proposed* (still subject to their own authorization, per §2/§8/§11 —
   this ADR does not pre-authorize any of them).

---

*This document is the governance/architecture-decision artifact for
session-scoped cross-pair ORB opportunity selection. It supersedes
nothing; it is additive context alongside ADR-035 and ADR-036, both
unmodified by it.*
