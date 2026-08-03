# Research: ADR-031 §3 Pipeline Amendment — Minimum Governance Surface for ADR-037

Status: Research (read-only). No implementation, no ADR-031 edit, no
ADR-037 implementation, no configuration change, no Gate A/Gate B
activation.

Owner (Research phase): Principal Software Architect.

Touched components: none (documentation-only artifact).

---

## 0. Scope and instruction compliance

This document performs the **ADR-031 §3 PIPELINE AMENDMENT RESEARCH**
step named as the required next governance gate by ADR-037's own
Acceptance record (`docs/adr/ADR-037-orb-cross-pair-session-opportunity-selection.md`
§14, commit `527e6ba`). It is read-only: no ADR text is amended, no
code is written, no test is modified, no configuration value is chosen,
and no gate is activated. It answers exactly one question — what is the
**minimum** change ADR-031 needs so its Accepted text remains true once
ADR-037's Accepted architecture exists — and produces a recommendation
for the next gate (drafting the amendment itself), not the amendment.

---

## 1. Repository and governance state (independently verified)

- Branch `claude/phantom-ea-visibility-cjjf3a`, HEAD `527e6ba` at the
  start of this Research, clean tree, in sync with `origin` (fetched
  and compared; no divergence either direction).
- `docs/adr/ADR-037-orb-cross-pair-session-opportunity-selection.md`
  Status: `**Accepted**` (recorded at commit `527e6ba`, re-read in full
  for this Research — not inferred from a prior report).
- `docs/adr/ADR-031-runtime-orchestrator.md` Status: `Accepted`
  (2026-07-10), re-read in full for this Research.
- `docs/adr/ADR-035-orb-strategy.md` Status: `**Accepted**`.
- `docs/adr/ADR-036-orb-strategy-consolidation.md` Status: `**Accepted**`,
  Amendment 1 Accepted (`1164062`).
- Gate A: `OPENING_RANGE_BREAKOUT` absent from
  `DEFAULT_APPROVED_PAIRS_BY_STRATEGY` — re-verified by direct
  execution, still closed.
- Gate B: `EvidenceEngineConfig().opening_range_anchors == ()` —
  re-verified by direct execution, still empty.
- `grep -rl "OpportunitySelectionEngine\|opportunity_selection"
  titan_protocol/` — no matches. No implementation of ADR-037's
  architecture exists anywhere in the repository.
- No commit in this session's range touches ADR-036 legacy-strategy
  retirement or the ADR-035 Phase 5 anchor hour/minute validation
  follow-up.

---

## 2. ADR-031's current contract, reconstructed clause by clause

Read in full (`docs/adr/ADR-031-runtime-orchestrator.md`), not
paraphrased from memory. Each clause is classified:

- **A** — ADR-037 preserves this unchanged; no amendment needed.
- **B** — ADR-037 makes this clause inaccurate as currently worded;
  amendment required.
- **C** — clause might appear affected but, on inspection, remains
  valid as written (a consequence is authorized by ADR-037, but the
  clause's own text doesn't need to change).

| § | Clause (summarized) | Class | Why |
|---|---|---|---|
| §0 | Relationship to prior work / no `phantom_pipeline` reuse | A | Unaffected; ADR-037 introduces no `phantom_pipeline` dependency |
| Pipeline position | "Runtime is the live coordinator... neither Trading Profiles nor Configuration compute a trading decision" | A | The new Opportunity Selection Engine is not Runtime, Trading Profiles, or Configuration — it is a new engine, like the other five; this framing is unaffected |
| §1 | "Runtime is the ONLY live coordinator. It owns ZERO trading logic." | A | Still true under the corrected ADR-037 model — Runtime executes, collects, counts, groups by already-produced identity, and compares equality; it never decides who wins (ADR-037 §5, reassessed against source in this Research, §3 below) |
| §2 | Hard Rules 1–5 (never generate signals/evidence/risk/compliance/override) | **A** | Byte-for-byte unaffected — see §5 of this Research for the explicit re-verification; no wording change required |
| §2 | "no function in `titan_protocol/runtime/` contains a decision-shaped name... every conditional branch... is an equality/membership check" | A (text) / **B (enforcement)** | The prose itself remains accurate for Runtime's own code (the winner decision lives in a separate, new engine, not in `titan_protocol/runtime/`); but the *test* that verifies the second half of this sentence (`tests/titan_protocol/runtime/test_architecture.py::test_only_permitted_upstream_packages_are_imported`) hard-codes today's six upstream package prefixes as the only ones Runtime may import — see §9 of this Research; this is a required, disclosed *consequence* of the amendment, not a new defect in §2's own wording |
| §3 | Pipeline diagram (six engines, exactly) | **B** | The diagram omits the seventh, now-Accepted engine and its placement; must be revised |
| §3 | Per-stage `evaluate()` signatures (Evidence/MI/Strategy/Risk/Compliance/Bridge) | A | None of these six signatures change under ADR-037 (ADR-037 §5.A: "the same unmodified engine calls, in the same order, on the same per-pair signatures") |
| §3 | Early-exit discipline ("Any stage returning a rejection/no-qualification/veto stops that pair's cycle immediately — no later stage is called") | **B** | Needs a new clause distinguishing an ordinary early exit from (a) a pair pausing at the barrier pending a cross-pair decision, and (b) a non-winning candidate's termination after that decision — see §6 of this Research |
| §3 | `TradeCommand` construction (command_kind/volume/stop_loss/correlation_id/magic_number) | A | Entirely unaffected — this logic runs only for the one winning pair that reaches Risk→Compliance→Bridge, using the exact same already-computed fields it uses today |
| §4 | Trading Profiles (config-only, no duplicate logic) | A | ADR-037 introduces enabled-window configuration as a new, distinct configuration surface (its own §8/§11) — this does not blur or duplicate `RiskEngineConfig`/`ComplianceEngineConfig`/`MarketIntelligenceConfig` the way §4 forbids; no contradiction |
| §5 | Configuration Versioning (`profile_id`, `version`, engine version constants) | A | Unaffected; if the new engine is versioned like the other five, it slots into the existing pattern without amendment |
| §6 | `RuntimeContext` "One per cycle, per pair, containing exactly: [five snapshots]..." | **B** | This is an explicit, exhaustive, per-pair-only framing. ADR-037's barrier requires a transient, per-*opportunity-window* aggregate (multiple pairs' `StrategySnapshot`s plus `range_start` identity) that exists between Strategy and Risk for the affected subset — a structure §6 does not currently describe or permit. See §5 of this Research |
| §7 | Observability ("every early exit is recorded with the exact originating stage's own reason... never a generic 'skipped'") | **B** | A non-winning candidate's termination is not an early exit caused by any of the six existing engines rejecting it — it is a new termination cause (lost a cross-pair comparison) requiring its own recorded reason, not a stretch of an existing one |
| §8 | Error handling / Fail Closed table (unknown engine state, missing snapshot, invalid configuration) | **B** | All three existing rows are single-pair-scoped. ADR-037 introduces an aggregate-scoped failure category (an incomplete opportunity-selection scan) that is not a pair's own engine failing — it is a *different pair's* front-half failure causing *this* pair's window to fail closed. §8's table needs a new row (or an explicit pointer) acknowledging this category exists, without duplicating ADR-037's own contract into ADR-031 |
| §9 | Watchdog integration (four timeout kinds, restart allow-list, Compliance/Bridge never restarted) | **C** | Appears affected (a new engine exists that could time out) but is not: ADR-037 explicitly requires selector failure to fail closed, never to trigger an unbounded-restart attempt that could reintroduce unrestricted execution; whether the new engine is added to Watchdog's restart allow-list is Plan-level (an additive, non-textual decision, analogous to how each of the five existing engines was added), not an ADR-031 amendment question |
| §10 | Performance (sub-250ms, concurrent-safe, deterministic, no duplicate calculations; "pairs may be evaluated concurrently without changing this ADR's within-pair strict ordering") | **C** | Not contradicted — reinforced. ADR-037's single-shared-front-half-pass design (§3 of this Research) is precisely what "no duplicate calculations" already requires; §10's own allowance for concurrent per-pair evaluation is structurally the same join/barrier shape a future concurrent implementation of the front half would need regardless of ADR-037. No wording change required, though the amendment may usefully note this compatibility |
| §11 | Configuration validation (startup) | **C** | Appears affected (ADR-037 adds a new fail-closed invariant, its own §11) but is not: ADR-036 Amendment 1 already established `validate_profile()` as the open-ended, extensible architectural home for exactly this class of cross-component, deployment-profile-level check, citing this same ADR-031 §11 as precedent without ADR-031 itself needing to enumerate every check. ADR-037's enabled-sessions/Gate-A-B invariant is another instance of that same established pattern, not a new kind of clause ADR-031 must add |
| §12 | Audit (`RuntimeAuditRecord` fields) | **B** | `RuntimeAuditRecord.stage_reached: Optional[CycleStage]` and `outcome: CycleOutcome` are both closed enums (§3 of this Research) with no member for "reached the barrier but was not selected" — a genuinely new, disclosed vocabulary gap |
| §13 | Testing (10 categories) | A | Category names are unaffected; new tests for the barrier logic simply populate existing categories (Concurrency, Failover, Recovery, Architecture, Regression) |
| §14 | Acceptance criteria | **B** | Criterion "every early exit stops the cycle immediately, no later stage called" needs the same distinction as §3/§7 above; criterion "deterministic... identical `RuntimeAuditRecord` on every run" needs the barrier's candidate-set assembly to inherit `evaluate_batch()`'s existing sorted-iteration determinism discipline, or the guarantee weakens silently |

**Summary: the incompatibility is not confined to §3.** §3, §6, §7, §8,
§12, and §14 all require some amendment; §2, §9, §10, and §11 do not,
though §2's associated *test* (not its text) has a disclosed, authorized
consequence (§9 of this Research). This directly answers the task's own
instruction not to assume only §3 needs attention.

---

## 3. Actual Runtime control flow, reconstructed from source

Traced from the live entrypoint, not assumed:

- **Production entrypoint:** `deployment_windows/start.py:1090` calls
  `orchestrator.run_cycle(tuple(inputs.keys()), profile, inputs, now, cycle_id)`
  — confirmed the single production call site (re-grepped this
  Research pass; only reference to `run_cycle(` in that file).
- **`RuntimeOrchestrator.run_cycle()`** (`titan_protocol/runtime/engine.py:413-446`):
  loops `for pair in sorted(pairs): if pair not in profile.allowed_pairs:
  continue`, then calls `run_cycle_for_pair(...)` once per admitted
  pair, appending each pair's own `RuntimeAuditRecord` to one
  `CycleReport`. Confirmed: no cross-pair aggregation exists in this
  loop today — each `run_cycle_for_pair()` call runs to completion
  (or early exit) independently before the loop advances.
- **`run_cycle_for_pair()`** (`engine.py:110-410`): one sequential
  function body — Evidence (line 211) → session-rule early exit (216) →
  Market Intelligence (224) → Strategy (231) → `strategy.rejected` early
  exit (234-239) → Risk (243) → `not risk.approved` early exit (246-253)
  → Compliance (257) → `compliance.decision is REJECT` early exit
  (262-282, including the Risk-reservation release this project's own
  prior reservation-leak history made mandatory) → Bridge (284-391,
  including the in-flight-command guard and reservation-ownership
  handoff). There is **no existing return or pause point between
  Strategy (231) and Risk (243)** other than the `strategy.rejected`
  early exit — confirming ADR-037's own factual premise directly from
  source, not by assertion.
- **`StrategySnapshot.winning_strategy: Optional[WinningStrategy]`**,
  and `WinningStrategy.strategy_id: StrategyId`
  (`strategy_engine/models.py:102-104, 108-121`) — confirmed to exist
  and to be exactly the field ADR-037 §5.B cites for post-front-half
  classification ("whether `OPENING_RANGE_BREAKOUT` is the winning
  qualification").
- **`evaluate_batch()`** exists on both `StrategyEngine`
  (`strategy_engine/engine.py:78-91`) and `RiskEngine`
  (`risk_engine/engine.py:203-229`), each a pure per-item generator
  expression with zero cross-item aggregation — and, re-confirmed this
  Research pass via `grep -rn "evaluate_batch" titan_protocol/runtime/`,
  **neither is called anywhere in `titan_protocol/runtime/`.** Runtime
  today has no batching primitive to reuse or repurpose; ADR-037's
  barrier is new machinery, not an existing capability being exposed.
- **`CycleStage`** (`runtime/models.py:96-102`): a closed `Enum` with
  exactly six members (`EVIDENCE, MARKET_INTELLIGENCE, STRATEGY, RISK,
  COMPLIANCE, BRIDGE`) — no seventh member for a new stage exists.
- **`CycleOutcome`** (`runtime/models.py:105-119`): a closed `Enum`
  with `SUBMITTED, OUTSIDE_TRADING_WINDOW, SESSION_NOT_ALLOWED,
  NO_STRATEGY, RISK_REJECTED, COMPLIANCE_REJECTED, BRIDGE_ERROR, FAILED,
  IN_FLIGHT_COMMAND_PENDING` — no member for "reached the opportunity
  window but was not selected" exists.
- **`RuntimeAuditRecord`** (`runtime/models.py:129-` onward): one record
  per `(cycle_id, pair)`, carrying `outcome: CycleOutcome` and
  `stage_reached: Optional[CycleStage]` among its fields — confirming
  both enums above are the exact vocabulary gap ADR-037's new terminal
  outcomes ("not selected this opportunity window") would need to fill.
- **Deterministic ordering:** `run_cycle()`'s `for pair in sorted(pairs)`
  and `evaluate_batch()`'s `sorted(pairs.items())` both establish an
  existing, explicit precedent — deterministic iteration order by pair
  symbol — that a barrier's candidate-set assembly would need to inherit
  to preserve ADR-031 §14's determinism acceptance criterion (see §2's
  table row for §14, and §11 of this Research).

**This directly distinguishes the current implementation from the
future architecture ADR-037 authorizes:** today, every pair's cycle is
a single, uninterrupted, independent function call; ADR-037 requires a
front half / barrier / back half split for a defined subset of cycles,
which does not exist in any form today and is not a simple extension of
an existing primitive.

---

## 4. ADR-037's Accepted target contract (re-read directly, not assumed)

Re-read `docs/adr/ADR-037-orb-cross-pair-session-opportunity-selection.md`
in full for this Research. The following Accepted decisions are the
fixed target this amendment must make ADR-031 compatible with — none
are reopened here, per the task's own instruction, since no genuinely
contradictory new evidence was found against any of them during this
Research:

- Every pair's front half (Evidence → Market Intelligence → Strategy)
  runs **exactly once per Runtime cycle**, unconditionally — never once
  per enabled session (§5.A).
- §7's frozen `Gate A ∩ allowed_pairs` intersection is the
  **completeness-tracking subset** for cross-pair selection — not
  necessarily the entirety of Runtime's normal trading universe.
  Re-confirmed from source (§3 above): `run_cycle()`'s own
  `pairs ∩ profile.allowed_pairs` filter already governs which pairs get
  a front half *at all*, entirely independent of Gate A; Gate A only
  gates ORB's own internal eligibility inside `qualify()`. This Research
  carries forward the Accepted review's own precise interpretation of
  the reviewed LOW H1 observation exactly as instructed: §5.A's
  "relevant configured universe" names the *completeness-tracking*
  subset, not a restriction on which pairs get evaluated — every pair
  Runtime evaluates today keeps being evaluated; the amendment must not
  silently narrow this into a new product decision.
- No front-half evaluation is duplicated per enabled opportunity window
  (§5.A, §5.F).
- Classification (§5.B) occurs only after already-computed results
  exist, reading only explicit, already-produced fields — never
  re-deriving qualification, ranking, or a trading decision.
- Participating candidates are grouped by their engine-produced
  `range_start` identity (§5.E.1, §8) — never by re-deriving "currently
  relevant range."
- The Opportunity Selection Engine — a new, dedicated component, not
  Runtime, not `selection.py`, not Risk Engine (§4) — owns the winner
  decision.
- Runtime owns orchestration, collection, counting/grouping against a
  frozen expected value, and equality/membership comparison only (§5,
  reassessed against ADR-031 §2 in ADR-037's own text and independently
  re-verified in §5 of this Research).
- Selection occurs before Risk (§5, pre-Risk placement, unchanged from
  the original draft through both revisions).
- Only the selected winner proceeds into Risk → Compliance → Bridge for
  that opportunity window (§5.E.4); non-winners terminate with a new
  explicit outcome and never reach Risk (§5.E.5).
- Legacy-strategy winners and any other non-enabled-window result
  proceed immediately, unmodified, with no barrier participation and no
  added latency (§5.C, §5.G) — this is the coexistence guarantee
  ADR-036's still-live five legacy strategies depend on.
- Incomplete scans (one or more frozen-universe pairs failing to reach
  a terminal front-half outcome) fail closed for that opportunity
  window, that cycle (§5.D, §7) — never silently narrowed, never
  treated as complete.
- No selector or barrier failure may fall back to today's unrestricted
  per-pair ORB execution (§12's absolute requirement).

---

## 5. Minimum ADR-031 amendment surface

Answering the task's own enumerated questions directly:

- **Is amendment of §3 alone sufficient? No.** §6, §7, §8, §12, and §14
  each require a clause addition or correction (§2 of this Research).
  §3 itself needs two things: (a) the pipeline diagram gains the new
  engine, placed between Strategy Engine and Portfolio Statistical Risk
  Engine, scoped explicitly to the enabled-window ORB-candidate subset
  only (not a blanket insertion affecting every pair); (b) the
  early-exit discipline paragraph gains the three-way distinction in
  §6 below.
- **Does §2 require wording change? No — Hard Rules stay byte-for-byte
  intact.** Every new Runtime responsibility (§5.A's front-half
  execution is unchanged engine calls; §5.B's classification is
  membership/equality checks against already-produced fields; §5.D's
  completeness counting is a count comparison against a frozen,
  config-derived number; §5.E's grouping is by an already-produced
  identity value; §5.E.4's continuation is an equality check against
  the selector's own returned value) reduces to execution, collection,
  counting, grouping, and comparison — never generation, calculation,
  or override, which is exactly what §2 already forbids and exactly
  what it does not forbid. This is not asserted from ADR-037's own
  text; it was independently re-traced against §2's literal five
  prohibitions in this Research and found to hold in every case.
- **Do early-exit semantics require reconciliation? Yes** — see §6
  below; this is the single largest substantive item in the amendment
  surface.
- **Does the definition of a "pair cycle" need refinement? Yes.**
  ADR-031 §6 currently defines `RuntimeContext` as strictly "one per
  cycle, per pair." Once some pairs pause after Strategy pending a
  cross-pair decision that depends on *other* pairs' results, a purely
  per-pair `RuntimeContext` can no longer describe the state that
  exists at the Strategy→Risk boundary for that subset. The amendment
  needs a narrowly-scoped addition: a transient, per-*opportunity-
  window* collection (candidate `range_start`, contributing pairs'
  `StrategySnapshot`s) that exists only between Strategy and Risk for
  enabled-window ORB candidates, resolved into at most one pair's
  continued `RuntimeContext` once the Opportunity Selection Engine
  returns. This does not require redefining `RuntimeContext` itself for
  every pair — only acknowledging this additional, narrowly-scoped,
  transient structure exists for the affected subset.
- **Must ADR-031 distinguish a front-half terminal outcome from an
  ordinary current early exit? Yes** — this is precisely §6's subject
  below, and is the crux of the whole amendment.
- **Does Runtime's pair-iteration contract need amendment?** No new
  contract is needed for *iteration* itself (`run_cycle()`'s `for pair
  in sorted(pairs)` is unaffected — every pair is still iterated and
  still gets its front half run); what changes is what happens *after*
  Strategy for a defined subset, which is §3/§6's concern, not an
  iteration-order concern.
- **Does deterministic ordering need additional governance? A narrow
  addition, not new governance.** §14's existing determinism criterion
  needs one clause: the barrier's candidate-set assembly for a given
  opportunity window must use the same deterministic, sorted-by-pair-
  symbol ordering `evaluate_batch()` already establishes, so that
  identical inputs continue to produce an identical `RuntimeAuditRecord`
  set on every run. This is a narrow, mechanical addition, not a new
  governance question.
- **Does fail-closed barrier behavior need to appear in ADR-031, or is
  ADR-037's contract sufficient?** A pointer is needed, not a
  restatement. §8's existing Fail-Closed table is exhaustively pair-
  scoped ("Unknown engine state," "Missing snapshot," "Invalid
  configuration" — all about *this pair's own* engines/config). ADR-037
  introduces a fundamentally different failure shape: *this pair's*
  window failing closed because of *another pair's* incomplete
  processing. The minimum fix is one new table row naming this category
  and pointing to ADR-037 §5.D/§7/§12 for the full contract — not
  copying that contract's specifics into ADR-031's own text.
- **Does the new engine need to appear in ADR-031's canonical
  pipeline/component list? Yes** — this is §3's own headline change,
  already covered above.
- **Are startup validation, observability, or state ownership clauses
  affected?** Startup validation (§11) is not affected in its own text
  (Category C — ADR-036 Amendment 1's precedent already covers this).
  Observability (§7) and state ownership (§6, `RuntimeContext`) are
  both affected, as detailed above.
- **Are architecture tests enforcing assumptions that an amendment
  would deliberately change?** Yes — see §9 below; this is an
  authorized *consequence* of the amendment, not something to resolve
  by leaving the amendment narrower than it needs to be.

**The smallest amendment that makes ADR-031 truthful without copying
ADR-037 wholesale**, in outline (not drafted, per this task's scope):
one new §3 pipeline-diagram entry with an explicit "applies only to the
enabled-window ORB-candidate subset" qualifier; one new early-exit
category in §3's discipline paragraph (§6 below); one narrowly-scoped
addition to §6's `RuntimeContext` definition; one new observability
category in §7; one new fail-closed table row in §8 that points to
ADR-037 rather than restating it; two new closed-enum members
(`CycleStage`, `CycleOutcome`) reflected in §12's field description;
and two acceptance-criteria refinements in §14 (early-exit distinction,
determinism ordering). Everything else in ADR-031 (§0, Pipeline
position, §1, §2, §4, §5, §9, §10, §11, §13) requires no textual change.

---

## 6. Early-exit interaction — explicit analysis (not solved, per instruction)

ADR-031 §3 today states: "Any stage returning a rejection/no-
qualification/veto stops that pair's cycle immediately — no later stage
is called," with four enumerated cases (`strategy.rejected`, `not
risk.approved`, `compliance.decision is REJECT`, a non-`None`
`bridge_submit` `ErrorCode`). ADR-037 §5.D independently defines: a
pair reaches a "terminal front-half outcome" once Evidence, Market
Intelligence, and Strategy have all run and produced *any* final result
— an explicit ORB `QUALIFIED`, an explicit ORB `NOT_QUALIFIED`
rejection, or a legacy strategy winning instead of ORB all count
equally; only a pair whose front half never completes (an early exit at
Evidence/session-rule/MI, an exception, a timeout) does not count, and
its absence renders the *whole opportunity window's scan* incomplete
for that cycle — never treated as a softened, dynamically-shrunk
expected universe.

**Three genuinely distinct concepts exist, once these two documents are
read together, and ADR-031 currently has vocabulary for only the
first:**

1. **Normal per-pair termination** — ADR-031 §3's four existing
   early-exit cases, entirely unaffected by ADR-037, applying to every
   pair whether or not it is a completeness-tracked candidate.
2. **Completion-tracking for ADR-037** — a *new* concept ADR-031 has no
   existing name for: whether a completeness-tracked pair reached
   *any* terminal front-half outcome this cycle, independent of which
   specific outcome it was. This is not itself a rejection category —
   `strategy.rejected` is one *specific way* a pair can fail to become
   an ORB candidate, but a pair that qualifies for a *legacy* strategy
   (not rejected at all, proceeding normally to Risk) equally counts as
   "reached a terminal front-half outcome" for ADR-037's completeness
   purposes. ADR-031's existing early-exit vocabulary and ADR-037's
   completeness vocabulary are **orthogonal axes**, not the same
   concept under two names — conflating them would be a governance
   error either document's own text would need to guard against.
3. **An incomplete opportunity-selection scan** — the *consequence*,
   scoped to an opportunity *window* (potentially spanning many pairs),
   of category 2 failing for even one tracked pair. This is not a
   per-pair early exit at all; it is an aggregate-level failure mode
   with no analogue anywhere in ADR-031's current, exclusively
   per-pair-scoped §3/§7/§8 text.

**This is reported as a genuine, currently-unaddressed vocabulary gap,
not silently solved here.** Per the task's own instruction, no softer
policy (e.g., dynamically removing an unavailable pair from the
expected universe before scan start) is proposed or implied — ADR-037's
own §5.D already explicitly declined that softening and left it to a
separately-authorized future decision if the operational cost proves
too high. This Research's finding is narrower and purely definitional:
**ADR-031's amendment must introduce vocabulary for concepts 2 and 3
above, cleanly distinguished from concept 1's existing vocabulary,**
or the amendment will be incomplete regardless of how §3's diagram is
redrawn. No architectural contradiction was found between ADR-031 and
ADR-037 on this point — only a vocabulary gap requiring new, additive
text, which is squarely within the "minimum amendment surface" this
Research is scoped to identify.

---

## 7. Coexistence during ADR-036 migration

Traced directly against ADR-037 §5.C/§5.G and ADR-031's own capital-
preservation/determinism requirements:

- **Some pair results continue immediately through Risk → Compliance →
  Bridge:** confirmed as the *default*, unmodified case (ADR-037 §5.G)
  — a legacy-strategy winner's `StrategySnapshot.winning_strategy.
  strategy_id` is not `OPENING_RANGE_BREAKOUT`, so §5.B's classification
  never routes it toward any barrier; it proceeds exactly as
  `run_cycle_for_pair()` already does today, unmodified, with the same
  reservation-lifecycle discipline (`risk.reservation_id` created and
  released exactly as today) ADR-031 §3's `TradeCommand` section and
  this project's own reservation-leak history already require.
- **Enabled-window ORB candidates wait behind the cross-pair barrier:**
  confirmed as the narrowly-scoped, additive case (ADR-037 §5.C) — only
  a pair whose *own* result is an enabled-window ORB candidate is ever
  held.
- **Rejected pairs terminate:** unaffected — an ORB rejection or a
  session-rule/Evidence/MI early exit both terminate exactly as today
  (the former counts as a terminal front-half outcome per §5.D; the
  latter does not, per §6 of this Research).
- **After completeness is established, one ORB winner may enter Risk:**
  confirmed (§5.E.2–§5.E.4) — exactly one reservation is ever created
  per opportunity window per cycle, eliminating the reservation-
  multiplicity risk class this project's own prior `ReservationLedger`
  leak history (session record: `S415`/`2173`/`2184`) makes a first-
  order capital-preservation concern, not a stylistic one.
- **ORB non-winners terminate without Risk reservations:** confirmed
  (§5.E.5) — Risk, Compliance, and Bridge are never invoked for a
  non-winning candidate, so no reservation for it is ever created in
  the first place; there is nothing to release.

**This coexistence model is compatible with ADR-031's capital-
preservation and deterministic-orchestration requirements**, on the
evidence gathered in this Research: no additional reservation is
created for any non-winning pair; every legacy-strategy pair's behavior
is provably unchanged (same code path, same reservation lifecycle);
and determinism is preserved provided the barrier's candidate-set
assembly inherits the existing sorted-iteration discipline (§5, §11 of
this Research). No contradiction was found; the open item is purely the
vocabulary gap in §6 above, required so this coexistence can be
*described* in ADR-031's own text, not a defect in the coexistence
design itself.

---

## 8. Failure and restart boundaries

Scoped strictly to what ADR-031 must *acknowledge as an orchestration
consequence* — not a redesign of ADR-037's own persistence contract,
which is out of this Research's scope and already Accepted:

- **Incomplete front-half collection:** already covered by §6's
  vocabulary-gap finding — this is exactly category 3 above, requiring
  a new fail-closed table row (§5 of this Research) pointing to
  ADR-037, not a restatement.
- **Opportunity Selection Engine exception/timeout:** ADR-037 §12
  already requires this to result in zero pairs proceeding for the
  affected window/cycle. ADR-031's own §8 Fail-Closed table's existing
  "Unknown engine state (an engine raises...)" row is *almost* general
  enough to cover this by analogy, but is written in per-pair singular
  terms ("that pair's cycle records a failure outcome; other
  pairs/cycles unaffected") — the amendment should extend or add a row
  clarifying that an engine-raises fault in the *new* engine has an
  aggregate blast radius (the whole window, not one pair), consistent
  with the same new table row identified above.
- **Selector-store corruption/unavailability:** this is squarely
  ADR-037's own persistence contract (§9, already Accepted) — ADR-031
  does not need its own text for this; ADR-031's only obligation is the
  same pointer-style acknowledgment already identified for the
  aggregate fail-closed category, not a duplicate of ADR-037's storage
  design.
- **Runtime failure while candidates are waiting:** not a new category
  — this is the general "Runtime process fails mid-cycle" case ADR-031
  §8 already treats as fail-closed by construction (no `TradeCommand`
  is ever built from an incomplete chain); a waiting candidate is, by
  definition, mid-chain, so the existing guarantee already covers it
  without new text.
- **Restart before winner selection / restart after winner persistence
  but before Risk / stale results crossing cycle or window
  boundaries:** all three are ADR-037's own persistence/idempotency
  contract (§9, restart-safe, fail-closed-on-corruption, `range_start`-
  keyed so a new day/window is always a new key) — already Accepted,
  already analyzed and confirmed sound in this ADR's own governance
  chain. ADR-031 does not need new text for any of these three; they
  are the new engine's own state-ownership responsibility, analogous to
  how ADR-031 does not itself describe `ReservationLedger`'s internal
  persistence contract (owned by ADR-027) even though Runtime
  orchestrates around it.

**No ADR-037 persistence redesign is proposed or implied here.** The
only ADR-031 consequence identified is the single new fail-closed table
row already named in §5 of this Research — everything else in this
category is either already covered by ADR-031's existing, general
fail-closed guarantee, or is correctly the new engine's own governed
responsibility under ADR-037, not Runtime's.

---

## 9. Architecture enforcement (inspected, not modified)

`tests/titan_protocol/runtime/test_architecture.py` (102 lines, read in
full for this Research) currently enforces, mechanically:

1. **`test_no_forbidden_identifier_anywhere_in_package_source`** — AST-
   walks every `.py` file under `titan_protocol/runtime/` for a fixed
   set of decision-shaped identifiers (`select_strategy`,
   `choose_strategy`, `select_direction`, `choose_direction`,
   `calculate_evidence`, `calculate_risk`, `make_compliance_decision`,
   `override_engine`, `generate_signal`). **Remains fully valid and
   satisfiable under ADR-037**, since the winner-selection *decision*
   is implemented inside the new engine's own package — not inside
   `titan_protocol/runtime/`, which this test's scope is limited to.
   No change to this test is required or implied.
2. **`test_no_public_method_resembles_a_decision_api`** — checks
   `RuntimeOrchestrator`'s public method names against the exact set
   `{"select", "score", "decide", "approve", "reject", "override"}`.
   **Remains satisfiable**: Runtime's new orchestration methods (barrier
   sequencing, completeness counting, invoking the selector) need not
   be named anything resembling these five words; this is a naming
   discipline constraint on the eventual implementation, not a
   governance defect requiring ADR-031 or test modification.
3. **`test_no_import_of_phantom_pipeline_or_validation_engine`** —
   unaffected; ADR-037 introduces no such dependency.
4. **`test_only_permitted_upstream_packages_are_imported`** — this is
   the one test with a genuine, disclosed consequence. It hard-codes
   `ALLOWED_UPSTREAM_PREFIXES = ("titan_protocol.evidence_engine",
   "titan_protocol.market_intelligence", "titan_protocol.strategy_engine",
   "titan_protocol.risk_engine", "titan_protocol.compliance_engine",
   "titan_protocol.bridge")` — exactly ADR-031 §3's current six-engine
   list, mirrored into a mechanical enforcement. **If the new
   Opportunity Selection Engine lives in a new top-level
   `titan_protocol.*` package (the natural consequence of ADR-037 §4's
   "new, dedicated component" ownership decision), Runtime importing it
   would fail this exact test as written today.** This is not a defect
   in the test — it is doing exactly its job, mirroring §3's own list —
   and it is exactly the kind of "authorized consequence of the
   amendment" the task asked this Research to identify rather than
   silently work around. Updating this test's tuple would be a required
   implementation-time consequence of the ADR-031 amendment (once
   Accepted), not something to change now.
5. **`TestWatchdogRestartBoundary`** — unaffected; whether the new
   engine is ever added to `APPROVED_RESTART_COMPONENTS` is Plan-level,
   independent of this test's own two assertions (Compliance/Bridge
   never in the allow-list), neither of which ADR-037 touches.

**No test was modified during this Research.** The one identified
consequence (item 4) is reported as a downstream implementation fact
the future ADR-031 amendment's own Acceptance would authorize, not a
gap in today's enforcement and not something requiring action now.

---

## 10. Adversarial Research matrix

| Scenario | Finding |
|---|---|
| One, two, and >2 enabled windows | No ADR-031 amendment scales differently by window count — the amendment concerns the *existence* of a barrier/new-stage concept, not its cardinality, which ADR-037 §5.F already confirms is uniform across any window count using the same shared front-half data |
| Zero enabled windows | Confirmed no distinct ADR-031 concern — with zero enabled windows, no pair is ever classified as an enabled-window candidate (§B), so every pair's cycle is identical to today's unmodified path; the amendment's new clauses are simply inert |
| Legacy and ORB winners in the same Runtime cycle | Directly traced in §7 above — no contradiction found; both paths coexist using entirely disjoint code paths after Strategy |
| ORB candidates across several pairs | This is the barrier's core case — correctly requires the new §6 (`RuntimeContext`)/§3 (pipeline) amendment content identified above |
| Tracked pair exits before Strategy | This is exactly §6 of this Research's category-3 finding (incomplete scan) — reported as a vocabulary gap, not silently resolved |
| Complete scan with zero ORB candidates | Confirmed safe and distinct from an incomplete scan by ADR-037 §5.D's own case-1/case-2 split, re-verified against source in the prior governance chain and not reopened here; ADR-031's amendment needs only to acknowledge this distinction exists (via the new fail-closed table row's pointer), not restate it |
| Incomplete scan | Same as above — the headline vocabulary gap this Research identifies |
| Selector exception/timeout | Covered by §8 of this Research — an aggregate-scoped fail-closed consequence, needing a pointer-style ADR-031 table row, not a restatement of ADR-037's own contract |
| Persisted winner followed by Runtime restart | ADR-037's own §9 persistence contract already covers this; no ADR-031 text needed beyond the general "no `TradeCommand` from an incomplete chain" guarantee already in §8 |
| Non-winning ORB pair accidentally reaching Risk | Prevented by ADR-037 §5.E.4/§5.E.5's own equality-check design (Runtime continues the back half *only* for the pair matching the selector's returned value); ADR-031's amendment must state this equality-check discipline explicitly enough that a future implementation cannot satisfy the amended §3 text while accidentally admitting a non-winner — this is a wording-quality requirement for whoever drafts the amendment, not a new open question |
| Legacy pair accidentally held behind ORB barrier | Prevented by §5.C's classification discipline (only an enabled-window ORB candidate is ever added to a window's barrier); confirmed no ADR-031 clause today would either authorize or prevent this misimplementation — the amendment's new early-exit-vs-barrier-participation clause (§6 of this Research) is exactly what closes this gap at the governance level |
| Duplicated Evidence/MI/Strategy computation | Directly prevented by §5.A's "exactly once per cycle" requirement, independently re-confirmed against source (§3 of this Research: no existing mechanism runs a pair's front half more than once per cycle, and ADR-037's design does not introduce one) |
| Per-session duplicate front-half evaluation | This was the original F1/G1 defect ADR-037's own governance chain already found and corrected before Acceptance; not reopened here; confirmed the corrected model (§5.A/§5.F) contains no residual duplication |
| Runtime accidentally becoming ranking/qualification owner | Prevented by §2's Hard Rules (unaffected, byte-for-byte) and independently re-traced in §5 of this Research; the architecture test in §9 (`test_no_forbidden_identifier_anywhere_in_package_source`) provides a second, mechanical backstop scoped to Runtime's own package |
| Stale candidate data crossing cycles | ADR-037 §9's `range_start`-keyed persistence (a full datetime, day-inclusive) already prevents this; no new ADR-031 text required |
| Deterministic ordering differences caused by pair iteration | Identified in §5 of this Research as a narrow, required addition to §14's determinism criterion — the barrier's candidate-set assembly must inherit `evaluate_batch()`'s existing sorted-by-symbol discipline |
| Architecture-test weakening | Identified in §9 of this Research (`test_only_permitted_upstream_packages_are_imported`) as an authorized, disclosed consequence of the amendment, not a weakening performed now or without governance |
| Silent fallback to today's unrestricted per-pair ORB execution | Explicitly forbidden by ADR-037 §12's absolute requirement, unaffected by anything in this Research; no ADR-031 clause currently permits or would newly permit this, and the amendment's new fail-closed table row (§5, §8 above) exists specifically to make this prohibition traceable in ADR-031's own text as well |

No new correctness defect was found in this adversarial pass beyond the
already-identified, purely definitional early-exit/completeness
vocabulary gap (§6) and its downstream consequences (§8's table row,
§12's enum additions, §9's disclosed test consequence). Capital
preservation was treated as taking priority over opportunity capture
throughout, consistent with `CLAUDE.md` §2.

---

## 11. Unresolved governance questions (explicitly not decided here)

The following remain open, correctly out of this Research's scope, and
are not resolved, invented, or implied by anything above:

- The exact wording of the ADR-031 amendment itself (drafting is the
  next gate, not this one).
- Whether the new engine is formally named "Opportunity Selection
  Engine" in the amendment, or renamed at Plan time (ADR-037 §4 already
  flags its own name as provisional).
- The exact new `CycleStage`/`CycleOutcome` enum member names/values.
- The exact new §8 fail-closed table row's wording.
- Whether the new engine is ever added to Watchdog's restart allow-list
  (Plan-level, per §9 above).
- Ranking formula, ranking weights, or any liquidity-scoring policy.
- Tie-handling policy.
- The exact number of enabled sessions, exact session identities, exact
  Gate A pairs, or exact Gate B anchor clock values. London and New York
  remain intended initial production-policy content only, never an
  architectural constant, and the architecture continues to support an
  arbitrary configurable number of enabled opportunity windows —
  nothing in this Research narrows that.
- Any Risk/Compliance runner-up fallback policy (ADR-037 §10 already
  leaves this as a distinct, separate future decision).
- Gate A/Gate B activation.
- ADR-036 legacy-strategy retirement sequencing, beyond the coexistence
  analysis in §7 above, which is strictly about understanding today's
  coexistence requirement, not about deciding retirement's own
  sequencing.
- The ADR-035 Phase 5 anchor hour/minute validation follow-up — entirely
  untouched, unrelated, and unauthorized in this Research.

---

## 12. Recommendation for the next gate

The evidence gathered in this Research supports drafting a dedicated
ADR-031 amendment — the incompatibility is real, multi-clause (not
confined to §3), definitionally precise (a vocabulary gap, not a
logical contradiction), and fully scoped by the analysis above. No
finding in this Research suggests ADR-037's architecture itself needs
reopening, and no finding suggests the amendment can be skipped or
deferred by a smaller fix. The recommended next gate is drafting the
amendment itself (a separate, dedicated governance task), constrained
by exactly the surface identified in §5 of this Research: §3 (pipeline
diagram + early-exit discipline), §6 (`RuntimeContext` addition), §7
(observability category), §8 (one fail-closed table row), §12 (two enum
member additions reflected in the audit-record description), and §14
(two acceptance-criteria refinements) — with §0, Pipeline position, §1,
§2, §4, §5, §9, §10, §11, and §13 left untouched.

---

*This document is a read-only Research artifact. It does not amend
ADR-031, does not implement ADR-037, does not activate Gate A or Gate
B, does not retire any legacy strategy, and does not touch the ADR-035
Phase 5 anchor hour/minute validation follow-up.*
