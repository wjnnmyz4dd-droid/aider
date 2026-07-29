# Research: ADR-037 §8/§9 Persistence-Semantics Amendment — Minimum Governance Correction

Status: Research (read-only). No ADR-037 edit, no implementation-Plan
edit, no code, no Gate A/Gate B activation, no legacy-strategy
retirement, no deployment-profile values, no runner-up fallback, no
ADR-035 Phase 5 work.

Owner (Research phase): Principal Software Architect, consulting the
Risk/Compliance-adjacent capital-preservation lens directly (no delegated
subagent review was judged to add evidence beyond direct source reading
for this narrow, text-comparison question).

Touched components: none (documentation-only artifact).

---

## 0. Scope and instruction compliance

This document performs the Research pass the independent implementation-
Plan re-review of `docs/plans/adr-037-implementation-plan.md` at
`0388595` named as the required next governance gate: it does not amend
ADR-037, does not revise the implementation Plan, writes no code, and
does not touch Gate A/Gate B, legacy-strategy retirement, deployment
profile values, runner-up fallback, or ADR-035 Phase 5. It answers one
narrow question — does ADR-037 §8/§9's Accepted persistence text need
amendment now that source proves a single `range_start` can legitimately
produce zero candidates on cycle N and a valid candidate on cycle N+1 —
and, if so, what is the *smallest* correction that preserves ADR-037's
safety/cardinality/restart guarantees without inventing an unsupported
terminal-window policy.

---

## 1. Repository and governance state (independently verified)

- Branch `claude/phantom-ea-visibility-cjjf3a`, HEAD `0388595` at the
  start of this Research — re-verified by direct `git rev-parse HEAD`
  and `git fetch` + comparison against `origin/claude/phantom-ea-
  visibility-cjjf3a` (identical SHA, no divergence either direction).
  Working tree clean (`git status --short`, empty) both before and
  after this Research.
- `docs/adr/ADR-037-orb-cross-pair-session-opportunity-selection.md`
  Status: `**Accepted**`, re-read in full for this Research (§8, §9,
  §10, §12, §14, §17 read with particular attention, per the task's own
  instruction; §1–§7, §11, §13, §15, §16 also re-read for whole-document
  dependent-language inspection, §6 below).
- `docs/adr/ADR-031-runtime-orchestrator.md` Amendment 1: `Accepted`
  (`5e6bbea`), re-read for its own persistence-adjacent language (none
  found beyond pointing to ADR-037 §9 as the new engine's own
  responsibility — confirmed in the prior `adr-031-pipeline-amendment-
  research.md` Research artifact, §8, and independently re-confirmed
  here by re-reading Amendment 1's own text fresh).
- `docs/plans/adr-037-implementation-plan.md` at `0388595`: re-read §1
  (`store.py` bullet), §6 (Persistence contract), §11 row 18, §13.
- `docs/plans/adr-037-ranking-tie-session-policy-decision.md` and its
  Research predecessor: re-confirmed as settled product-policy inputs
  this Research does not reopen (three initial windows: London,
  London–New York Overlap, Early New York — descriptive content only,
  irrelevant to the persistence-semantics question).
- Gate A: `OPENING_RANGE_BREAKOUT` confirmed absent from
  `DEFAULT_APPROVED_PAIRS_BY_STRATEGY` (`titan_protocol/strategy_engine/
  config.py`) — closed.
- Gate B: `EvidenceEngineConfig().opening_range_anchors == ()` — empty.
- `grep -rl "OpportunitySelectionEngine\|opportunity_selection"
  titan_protocol/ tests/` — no matches. No implementation of ADR-037's
  architecture exists anywhere in the repository.
- `StrategyId` has exactly 6 members; `build_default_registry()`
  registers only the 5 legacy strategies by default — legacy-strategy
  retirement status unchanged.
- `python3 -m compileall -q titan_protocol tests` — clean.
  `tests/titan_protocol/runtime` 158/158, `tests/titan_protocol/
  strategy_engine` 180/180, `runtime.test_architecture` 6/6 — all green,
  unmodified, re-run fresh for this Research (read-only validation; no
  file was changed by these commands).

---

## 2. Source-backed lifecycle findings (independently re-derived, not assumed)

Re-read directly from source for this Research, not carried over from
the prior Plan revision's own claims:

- **`range_start` construction and stability**
  (`titan_protocol/evidence_engine/opening_range.py:128-152`,
  `compute_opening_ranges()`): for each configured anchor,
  `range_start = now.replace(hour=start_hour_utc, minute=start_minute_
  utc, second=0, microsecond=0)`. This expression is a function of
  `now`'s **date** and the anchor's fixed hour/minute only — it does
  not depend on how far `now` has advanced intra-day. Confirmed: for a
  fixed anchor, every cycle evaluated on the same calendar day computes
  the **identical** `range_start` value. This is the same identity
  ADR-037 §8 itself already cites and adopts (`range_start` alone, not
  `(SessionName, range_start)`), re-verified directly against this file
  rather than taken on the ADR's own word.
- **Formation versus formed-range behavior**
  (`opening_range.py:72-125`, `_compute_single_range()`): `range_end =
  range_start + timedelta(minutes=duration_minutes)`; `is_formed = now
  >= range_end`. Before `range_end`, `is_formed` is `False` for every
  cycle, unconditionally, regardless of how many bars exist or what
  they contain — a range in formation cannot be `is_formed=True` no
  matter what its bars show.
- **NOT_QUALIFIED → QUALIFIED transition across cycles sharing the same
  `range_start`** (`titan_protocol/strategy_engine/strategies/
  orb_breakout.py:84-237`, `qualify()`): `formed_ranges = [r for r in
  opening_ranges if r.is_formed]`; `if not formed_ranges: return
  _not_qualified(pair, "No opening range currently relevant (none yet
  formed)")` (lines 121-123) — confirmed every cycle during formation
  returns `NOT_QUALIFIED`, unconditionally, for every pair. Once
  `is_formed` becomes `True` (same `range_start`, later cycle),
  `qualify()` proceeds to inspect `post_range_bars` (line 147 onward) —
  a sequence that **grows every cycle** as new bars close
  (`_compute_post_range_bars()`, `opening_range.py:32-69`, bounded by
  `now`). A cycle whose `post_range_bars` does not yet contain a genuine
  breakout returns `NOT_QUALIFIED` (`"No breakout: close within range"`,
  line 162, or any of the several other named rejection reasons below
  it); a **later** cycle, same `range_start`, whose newest closed bar
  finally closes beyond `range_high`/`range_low` with sufficient ATR
  distance, body quality, and confirmation-candle count returns
  `QUALIFIED`. **This transition is not hypothetical — it is `qualify()`'s
  designed, intended behavior**: a genuine breakout is expected to arrive
  on some cycle strictly later than the range's own formation cycle,
  since post-range bars accumulate only after `range_end`.
- **No authoritative "window is over" point in source.** Searched
  `opening_range.py`, `orb_breakout.py`, and `EvidenceEngineConfig`
  (`titan_protocol/evidence_engine/config.py`) for any field or
  computation representing "this opportunity can no longer produce a
  qualification." None exists. The only thing resembling a boundary is
  `orb_breakout.py`'s own `currently_relevant` filter (lines 125-133):
  `latest_range_end = max(r.range_end for r in formed_ranges)`;
  `currently_relevant = [r for r in formed_ranges if r.range_end ==
  latest_range_end]`. This is a **selection-among-simultaneously-formed-
  ranges** mechanism (picking the newest, for defense-in-depth against
  the anchor-overlap case ADR-037 §8 already confirms cannot occur under
  `_validate_no_overlapping_anchors`) — not a termination policy. A given
  `range_start` remains the unique formed range for its anchor, and
  therefore remains `currently_relevant`, until a **newer** range for
  that same anchor forms — for a once-daily anchor (the only kind
  `opening_range_anchors` currently supports; no intraday-repeating
  anchor concept exists in `EvidenceEngineConfig`), this is effectively
  the remainder of the calendar day. This is a *calendar-day-rollover
  artifact of anchor reconstruction*, not a designed "opportunity is
  concluded" signal — re-confirmed by inspecting every other use of
  `range_end` in both files; none of them encode a policy decision about
  when a window's trading opportunity ends.
- **What `opening_range_duration_minutes` actually marks.** Grepped
  every use of `opening_range_duration_minutes` in
  `titan_protocol/evidence_engine/` and `titan_protocol/strategy_engine/`.
  It is read in exactly two places: `_compute_single_range()`'s
  `range_end` computation (marking **formation completion** only — the
  point at which the range's own high/low become fixed and post-range
  bar collection begins) and `EvidenceEngineConfig._validate_no_
  overlapping_anchors()` (a **startup-time anchor-spacing** validation,
  confirming two anchors' formation windows don't overlap — again about
  formation, not about opportunity termination). **No source location
  reads this field to mean "the opportunity to trade this range has
  ended."** The Plan's own stale-window check (`range_start +
  timedelta(minutes=duration_minutes) < now`) uses it only as a
  should-never-happen defense-in-depth guard against Runtime somehow
  presenting an already-superseded `range_start` — not as a claim that
  this is when the *opportunity* legitimately ends.
- **Existing precedent for "provisional/negative outcomes need not be
  durably recorded"** — found directly in this codebase's own already-
  Accepted design, not invented for this Research:
  `titan_protocol/strategy_state_store/formation_blackout_store.py`
  (`FormationBlackoutStore`, ADR-035 §2/§14 Amendment 1, Phase 7).
  Its own docstring (lines 11-23) and `record_cycle_observation()`
  (lines 152-171) establish: the store records only a **monotonic
  positive transition** (`blackout_active` observed `True` for a
  `(pair, range_start)` key); a cycle whose observation does **not**
  change the recorded value — the common case, a range whose formation
  never sees a blackout — **"skips the persist entirely... therefore
  never touches disk"** (line 156-160, its own words). `was_blackout_
  observed()` (lines 173-180) returns `False` for a key that was never
  written, and this is documented as "exactly matching 'nothing has been
  observed yet' as the correct initial state." **This is a direct,
  already-Accepted, in-repository precedent for the identical shape of
  design decision this Research is evaluating**: the negative/nothing-
  notable-happened outcome is never persisted at all; the positive,
  durability-worthy fact is the only thing ever written; key-absence
  correctly and permanently means "nothing has happened yet," not "a
  negative decision was made." The winner-only design under evaluation
  (Model A, §4 below) is structurally the same shape, applied to a
  different fact (a selected winner vs. an observed blackout) and a
  different store (`OpportunityWinnerStore` vs. `FormationBlackoutStore`).
  `titan_protocol/runtime/in_flight_store.py` (lines 1-30) supplies a
  second, weaker precedent for the same general principle — this
  codebase already documents deliberate persistence-scope limits
  ("Persists only... never the original `TradeCommand`... a deliberate
  scope limit, not an oversight") as a normal, accepted design practice,
  not something requiring special justification each time.

**Summary of lifecycle facts:** a single `range_start` legitimately
produces `NOT_QUALIFIED` on every cycle during formation (not a defect,
an intended consequence of `is_formed`'s definition), may continue to
produce `NOT_QUALIFIED` for an arbitrary number of cycles after formation
(no breakout yet), and may transition to `QUALIFIED` on any later cycle
whose newest post-range bar finally satisfies every gate — this is
`qualify()`'s designed purpose, not an edge case. No source location
anywhere defines a point before calendar-day rollover at which this
transition becomes impossible. This directly confirms the finding
`docs/plans/adr-037-implementation-plan.md` §11 row 18 already reached,
now independently re-derived rather than taken on faith.

---

## 3. Challenging the original persistence rationale — what did §9 actually intend?

ADR-037 §9's text: *"Persistence: the winner (or the fact that no winner
was selected) must be recorded in a new, dedicated, restart-safe,
persisted store..."* Re-read in full, alongside §8's *"the winning `pair`
(or its absence) is what is stored for that key"* and §12's list of
required **observability** signals (distinct section, distinct
mechanism — logging/metrics, not the persisted store).

The task's own three candidate readings, tested against the ADR's actual
text and its surrounding sections:

1. **"This cycle produced no winner"** (a cycle-scoped, non-final fact).
   Nothing in §8 or §9 qualifies "the fact that no winner was selected"
   with "this cycle" or any per-evaluation scoping language — both
   clauses speak of the store recording a value *for the key*
   (`range_start`), the same singular, keyed-value framing used for the
   winner case. If reading 1 were intended, the natural phrasing would
   parallel §9's own idempotency clause ("re-evaluating... after a
   winner is already persisted" — explicitly scoped to a *specific
   cycle relationship*); no such scoping appears for the absence case.
2. **"This opportunity window has permanently concluded with no
   winner"** (a final, immutable, terminal fact). This reading is
   consistent with §9's key/value framing (one persisted value per
   `range_start`, implying a single, settled fact) and with §8's
   "descriptive value for that key" language. But **no clause in ADR-037
   defines when a window "permanently concludes."** §5.D (completeness)
   defines when a *single cycle's scan* is complete or incomplete —
   an entirely different question from when a *window's entire multi-
   cycle lifetime* is over. Reading 2 requires a terminal-window
   boundary the ADR does not supply anywhere (confirmed by the whole-
   document re-read in §6 below) — meaning if reading 2 was intended,
   ADR-037 itself never actually defined the one fact that reading
   would require, and any implementation following reading 2 literally
   would have to invent that boundary unilaterally, which is exactly
   what the original (pre-`e139076`) Plan revision did by treating
   "persist unconditionally" as safe, and exactly what the independent
   Plan re-review found unsafe (`docs/plans/adr-037-implementation-plan.md`
   §11 row 18).
3. **"Winner-selection outcomes must be restart-safe"** (a property of
   the *store's mechanism*, not a mandate that *every* outcome —
   including negative ones — be durably written). This reading is
   consistent with §9's own explicit statement that "the exact
   re-evaluation policy... is left to the implementation Plan" for the
   post-winner case, suggesting the ADR's authors were already thinking
   in terms of *mechanism properties* (restart-safety, at-most-one-
   winner, fail-closed) rather than dictating every value that must be
   written to disk. Under this reading, "the fact that no winner was
   selected must be recorded" is satisfiable by *any* mechanism that
   makes the overall decision process restart-safe and auditable —
   which the winner-only design (never persisting absence, but logging
   every negative cycle via §12) already achieves, just via a different
   sub-mechanism (durable store for the one immutable fact; observability
   log for the recurring provisional facts) than a literal reading of
   §9's sentence structure suggests.

**Finding: ADR-037 does not itself establish which of these three
readings was intended.** §9's literal sentence structure most naturally
supports reading 2 (a single persisted value per key, paralleling the
winner case's own single persisted value) — but reading 2 requires a
terminal-window boundary the ADR never defines, and applying it literally
(as the pre-`e139076` Plan did) reproduces the exact capital-preservation
defect this whole research chain exists to correct. Reading 1 and reading
3 are both defensible from the surrounding text (§9's winner-scoped
idempotency language; §12's separate observability channel) but are not
unambiguously *established* by it either. **This ambiguity is reported
here, not retroactively resolved by inventing authorial intent** — the
ADR's own text is underspecified on exactly the axis this Research was
asked to test.

---

## 4. Comparison: winner-only persistence (Model A) vs. persisted provisional absence (Model B)

Both models share, unconditionally: `range_start` alone as the store's
key; a genuine, single winner is the only value that is ever immutable;
`decide_once()`'s check-then-persist sequence executes under one
`threading.Lock`; a stale-window defense-in-depth check runs first,
unconditionally; construction-time corruption fails closed (uncaught);
runtime persist-failure is caught/logged, in-memory decision stands for
the process's remaining lifetime (mirroring `OrbQualificationStore`'s and
`FormationBlackoutStore`'s own established, Accepted precedent in both
cases).

**Model A — winner-only durable persistence** (the design in the current
implementation Plan at `0388595`): a "no winner this cycle" outcome
(empty candidate set, or an unresolved tie) is never written to the
store at all. The key remains absent until a genuine winner exists.
Once a key exists, its value is always a real winning pair — never a
persisted `None`.

**Model B — persisted provisional absence**: every evaluated cycle may
write a value for the key, but an absence-marker (`{"pair": null, ...}`
or equivalent) is explicitly **provisional and replaceable** — a later
cycle observing an absence-marker (not a winner) is free to recompute
and overwrite it, including with a winner. Only a genuine winner value
is immutable; an absence-marker value is not.

| Criterion | Model A | Model B |
|---|---|---|
| At most one selected pair per opportunity window (ADR-037's core purpose) | Satisfied — a winner, once written, is never overwritten; §9's own idempotency clause is scoped only to "after a winner is already persisted," which both models satisfy identically | Satisfied identically — the only immutable state in either model is the winner value |
| Restart safety before a winner exists | Satisfied — key absent on restart resumes with "freely re-decidable," the correct fact | Satisfied — an absence-marker or an absent key both resume with "freely re-decidable"; functionally identical outcome, differing only in whether a disk write occurred |
| Restart safety after a winner exists | Satisfied — winner value loaded once at construction, returned unchanged forever after | Satisfied identically |
| Idempotency (ADR-037 §9's own explicit scoping: "after a winner is already persisted") | Satisfied — literally the only case §9 constrains | Satisfied — literally the only case §9 constrains; Model B's extra absence-marker writes are additional behavior §9 neither requires nor forbids |
| Concurrent selectors attempting different winners | Prevented identically in both — the entire check-then-persist sequence executes under one lock; whichever thread acquires the lock first either finds no key/an absence-marker (computes, persists only a genuine winner) or a winner (returns it unchanged); the second thread re-checks under the same lock before computing anything of its own | Prevented identically — the lock discipline is the same regardless of whether an absence-marker is also written |
| Selector/store failures | Both fail closed identically: a selector exception or incomplete scan never persists anything (Model A) or persists/leaves-unchanged an absence-marker (Model B), and in both cases zero pairs proceed that cycle (Runtime's own termination logic, unaffected by either model) | (same) |
| Ties | Both treat a tie as "no winner this cycle" — cycle-local and non-binding in Model A; a provisional, overwritable absence-marker in Model B | (same practical effect) |
| Zero-candidate cycles | Same as ties, in both models | (same) |
| Observability/audit requirements (ADR-037 §12) | Identical in both — §12's "No candidates available," "Tie / no-winner produced" signals are emitted by `logging_sink.py`/`metrics.py` on every negative cycle regardless of which persistence model is chosen; §12 is a distinct mechanism from the winner store in either model | (same) |
| Stale state / calendar-day identity | Identical in both — `range_start`'s day-inclusive construction already makes a new calendar day a new key in either model; the stale-window defense-in-depth check is unaffected by which model is chosen | (same) |
| Atomicity before Risk reservation | Identical in both — Runtime's `run_cycle()` calls `evaluate_window()` synchronously and only invokes `_run_back_half` for the pair equal to the returned winner; this ordering does not depend on whether absence outcomes are persisted | (same) |
| Unnecessary state complexity | Simpler: no absence-marker schema, no "is this marker still provisional or should it be treated as final" question ever arises, no extra disk writes for the overwhelming-majority negative-cycle case | Adds an absence-marker value shape, a provisional-vs-immutable distinction inside the *same* store (something to get right in code and tests), and disk writes on every negative cycle for the store's entire pre-winner life — for **no additional safety property**, per the row below |
| **Does persisting provisional absence supply any safety property Model A's fail-closed cycle behavior plus durable winner persistence does not already provide?** | — | **No.** Every adversarial scenario in §5 below produces an identical durable-state outcome and an identical "who may proceed into Risk" answer under both models. The only observable difference is whether a disk write occurs for a fact (the negative outcome) that is, by construction, always superseded or irrelevant the moment a winner appears, and is already independently observable via §12's logging in both models. |
| Literal conformance with ADR-037 §8/§9 text as currently written | **No** — §8/§9's plain language ("the winning pair, **or its absence**, is what is stored for that key"; "the fact that no winner was selected **must be recorded**... in a ... persisted store") describes a value being written for the key on a negative outcome; Model A never writes one | **Yes** — Model B writes a value (the absence-marker) for every evaluated key, literally satisfying §8/§9's plain sentence structure, while the *separate* idempotency clause (scoped only to "after a winner is already persisted") is left unconstrained for the absence-marker case, exactly as its own wording permits |

**Conclusion of this comparison:** the two models are functionally
identical on every safety, cardinality, restart, concurrency, and
observability dimension tested. They differ only in (a) literal textual
conformance with ADR-037 §8/§9 as currently worded, and (b) implementation
simplicity, where Model A is strictly simpler with no compensating safety
benefit forfeited. This is not a case where "more persistence" buys more
safety — per this Research's own adversarial matrix (§5), persisting a
provisional absence-marker is inert with respect to every capital-
preservation property ADR-037 actually cares about; its sole effect is
making the current implementation Plan's design literally match ADR-037's
current sentence structure without requiring that sentence structure to
change.

---

## 5. Adversarial lifecycle matrix

For each scenario: durable state under Model A, durable state under
Model B, and whether any candidate may enter Risk.

| Scenario | Durable state — Model A | Durable state — Model B | May any candidate enter Risk? |
|---|---|---|---|
| Formation-period, no candidate → later candidate | No key after cycle N; genuine winner key after cycle N+1 | Absence-marker after cycle N; overwritten with genuine winner after cycle N+1 | Only the eventual winner, only after N+1, in both models |
| Formed range, no breakout yet → later breakout | Same shape as above | Same shape as above | Same |
| Tie → later unique winner | No key after the tie cycle; winner key after the later cycle | Absence-marker after the tie cycle; overwritten with winner later | Only the eventual unique winner, in both models |
| Repeated no-winner cycles | No key persists across any of them | Absence-marker re-written (or left as-is) each cycle; never becomes immutable | No candidate proceeds in either model, for as long as no winner exists |
| Restart during those cycles | Key absent before and after restart — freely re-decidable | Absence-marker (or absent key, if the last negative cycle happened to skip a write) present before and after restart — still freely re-decidable, since it is not immutable | No candidate has ever proceeded in either model prior to a winner |
| Winner selected → restart | Winner key loaded at construction, returned unchanged | Winner key (having overwritten any prior absence-marker) loaded at construction, returned unchanged | Only the already-selected winner, in both models — identical to today's `OrbQualificationStore`/`FormationBlackoutStore` restart precedent |
| Winner selected → later different/better candidate | Key present ⇒ persisted winner returned unchanged, `select_winner()` never even invoked on the new candidates | Winner value is immutable in Model B too (only absence-markers are provisional) ⇒ identical behavior | Only the original winner, in both models — never the later candidate |
| Concurrent attempts to establish different winners | Single `threading.Lock` around the entire check-then-persist sequence in both models: whichever thread acquires the lock first computes and persists (if a genuine winner); the second thread re-checks the key under the same lock before computing anything of its own | Identical lock discipline; the only difference is whether the "no key yet" branch also writes an absence-marker when neither thread found a winner | Never two different winners in either model — structurally impossible under the shared-lock discipline, not merely unlikely |
| Persistence failure during winner establishment | In-memory decision stands for the process's remaining lifetime (mirrors `OrbQualificationStore._persist()`'s own already-Accepted, documented risk shape); a restart before the failed write is retried could re-select a different winner — an existing, disclosed, pre-existing residual risk shared by every store in this codebase's established pattern, not introduced or worsened by either model | Identical — the same persist-failure/in-memory-stands contract applies equally to a winner write in Model B | Identical residual risk in both models; not a discriminator between them |
| Corrupt/unavailable winner store | Construction-time corruption fails closed (uncaught), identical in both models — mirrors `OrbQualificationStore`'s/`FormationBlackoutStore`'s own documented "refusing to silently treat this as 'nothing decided yet'" precedent | Identical | No candidate proceeds if the store cannot be trusted, in either model |
| Stale prior-day state | `range_start`'s day-inclusive construction makes a new day a new key in both models; the stale-window defense-in-depth check in `decide_once()` is identical in both | Identical | No candidate proceeds via a stale key in either model |
| Multiple independent `range_start` windows | Each `range_start` is an independent key in both models — no cross-window interaction in either | Identical | Each window's own winner (if any) proceeds independently in both models; no model introduces cross-window coupling |

**No scenario in this matrix distinguishes the two models on any
safety-relevant dimension.** The only distinguishing property across the
whole matrix is textual: Model B writes an extra, functionally-inert
value to disk on negative cycles; Model A does not.

---

## 6. Affected ADR-037 clauses — whole-document inspection

Per the task's own instruction not to assume only §8/§9 are affected,
every section of ADR-037 was re-read for persistence-adjacent language:

| § | Clause | Affected? | Why |
|---|---|---|---|
| §1–§4 | Problem statement, product requirement, governance vehicle, ownership | No | No persistence-specific language |
| §5 | Pipeline placement/control flow (A–G) | No | §5.E.2 says "consult the winner store" and §5.E.3/.4 describe consuming its returned value — none of this text specifies *what* the store persists for a negative outcome; both models satisfy §5 identically |
| §6 | Cross-pair selection contract (`select_winner`'s pure-function contract) | No | Concerns the selector function, not the store |
| §7 | Candidate-set completeness (§5.D cross-reference) | No | Concerns scan completeness, an orthogonal concept to whether a negative *selection* outcome is persisted |
| **§8** | Session identity/lifecycle — *"the winning `pair` (or its absence) is what is stored for that key"* | **Yes** | Directly the clause under evaluation; needs either a Model-A-consistent rewording ("a genuine winner is the only value ever durably stored for a key; a negative outcome is cycle-local, observable via §12, not persisted") or confirmation that Model B is intended (in which case this clause is already accurate and needs only the "provisional/overwritable" qualifier added) |
| **§9** | Winner cardinality/persistence/fail-closed — *"the fact that no winner was selected must be recorded... in a ... persisted store"* | **Yes** | The core clause under evaluation, per §3 of this Research's three-reading analysis |
| §10 | Risk/Compliance/Bridge interaction, no-fallback contract | No | Independent of which persistence model is chosen; both models produce identical "no candidate proceeds without a durable winner" behavior |
| §11 | Gate A/B / structural-readiness invariant | No | Unrelated to per-window persistence semantics |
| **§12** | Observability — *"Tie / no-winner produced despite candidates existing"* signal | **Consequence, not a defect** | §12 already treats this as a **logging** signal, distinct from the persisted store — both models already satisfy §12 identically; no wording change needed here, but §9's own cross-reference to "recorded" should not be read as implicitly meaning §12's logging already discharges §9's persisted-store obligation, since they are and remain textually distinct requirements until §9 itself is amended |
| §13 | Relationship to ADR-036 | No | Unrelated |
| §14 | Governance status / next gate | No | Unaffected by this question; still correctly names the ADR-031 amendment as the next-required precondition (already independently researched, see the existing `adr-031-pipeline-amendment-research.md`) — this persistence-semantics question is a *second*, independent, additive amendment need, not a substitute for that one |
| §15 | Capital-preservation adversarial review | **Indirectly, row-level** | Should be re-checked once §8/§9 are amended, to confirm no row's disposition was written assuming literal persisted-absence recording — a scan of §15's existing rows (not reproduced here in full, out of this Research's narrow scope) found no row whose disposition text specifically depends on the absence case being durably persisted rather than cycle-local; this is a confirmatory note for the amendment drafter, not a new finding requiring action here |
| §16 | Preservation constraints | No | Unrelated |
| §17 | Preconditions for next phase | **Consequence, procedural** | Item 3 already names a *separate*, required ADR-031 amendment as a precondition; this Research's finding adds a **second**, independent ADR-037-internal amendment (§8/§9, self-amending, not ADR-031) to the precondition list before implementation may proceed — see §7 below |

**Summary: the incompatibility is confined to §8 and §9's own text**,
with §12 and §15 requiring only confirmatory/cross-reference attention
(no wording change), and §17 requiring a procedural update naming this
as an additional, independent precondition alongside the already-known
ADR-031 amendment.

---

## 7. Minimum amendment surface

If governance chooses to proceed with an amendment (this Research's own
recommendation, §10 below):

- **§8**: replace *"the winning `pair` (or its absence) is what is
  stored for that key"* with language stating a genuine, single winner
  is the only value ever durably stored for a `range_start` key; a
  cycle producing no winner (zero candidates or an unresolved tie) does
  not write to the store at all, and the key's absence is the correct,
  permanent representation of "no winner yet," never distinguished from
  "not yet evaluated."
- **§9**: replace *"the winner (or the fact that no winner was selected)
  must be recorded in a ... persisted store"* with language stating only
  the winner must be durably recorded; the fact that a given cycle
  produced no winner is satisfied by §12's own observability signals,
  not by the persisted store, and is never itself a durable, immutable
  fact. The existing idempotency clause ("after a winner is already
  persisted... never produces a second concurrent winner") needs no
  wording change — it already, correctly, scopes immutability to the
  winner case only.
- **§12**: no wording change required — already correctly scoped as a
  logging/metrics requirement, distinct from persisted state; the
  amendment may add one clarifying sentence noting that these signals
  are what discharges "the fact that no winner was selected" being
  observable, now that §9 no longer requires it to also be durably
  stored.
- **§14/§17**: a status/precondition update recording that this
  amendment (a second, independent, ADR-037-self-contained amendment,
  not the already-known ADR-031 amendment) exists and its own governance
  disposition (Proposed → independent review → Accepted), mirroring the
  established amendment pattern this same ADR's own §17 already cites
  (ADR-036 Amendment 1's draft → independent review → revision → final
  acceptance review → acceptance-recorded sequence).
- **Revision-history treatment**: per this repository's established
  pattern (ADR-031 Amendment 1, ADR-036 Amendment 1), the amendment
  should be recorded as "ADR-037 Amendment 1," with its own dated
  status line and a summary paragraph citing the source evidence this
  Research gathered (formation-period `NOT_QUALIFIED`, day-stable
  `range_start`, no source-derivable terminal-window boundary,
  `FormationBlackoutStore`'s own precedent for the same design shape) —
  not a silent in-place edit of §8/§9's existing text without a visible
  amendment marker, consistent with how ADR-031 and ADR-036 both
  recorded their own corrections.

**Everything else in ADR-037 (§1–§7, §10, §11, §13, §16) requires no
textual change.**

---

## 8. Concurrency proof required of the eventual Plan (Research note only — not a Plan edit)

The independent Plan re-review's MEDIUM observation asked what
concurrency proof the eventual Plan must require to demonstrate that
different concurrent candidate sets cannot result in different callers
releasing different local winners. On direct inspection of the existing,
already-Accepted `OrbQualificationStore.try_consume()` precedent
(`titan_protocol/strategy_state_store/store.py:123-141`) and the
`decide_once()` contract both models above share: the entire read-decide-
persist sequence executes under one `threading.Lock`, so two threads can
never simultaneously observe an absent key and both proceed to compute
independently — the second thread's lock acquisition happens strictly
after the first's release, at which point it re-observes whatever the
first thread left behind. **This is already structurally sufficient**
regardless of which persistence model is chosen. What the existing test
specification (`test_concurrent_decide_once_calls_never_produce_two_
winners`, described only as "mirroring `OrbQualificationStore`'s own
concurrency test convention") does not make explicit is whether the
concurrent threads in that test are given **differing** candidate sets
(such that, absent the lock, they would compute different winners) —
`OrbQualificationStore`'s own precedent test races threads against the
*same* counter-increment operation, not against operations that would
diverge without synchronization. **This Research recommends** (as a
finding for the eventual Plan revision, not performed here) that the
test specification be tightened to state explicitly that concurrent
calls pass candidate sets whose respective locally-computed winners
would differ absent the lock, so the proof demonstrates convergence on
one persisted winner rather than merely "the same deterministic
computation run twice never disagrees with itself." This finding is
independent of, and does not depend on the resolution of, the Model
A/B persistence-semantics question — it applies identically to both.

---

## 9. Findings register

| # | Severity | Finding | Blocks amendment recommendation? |
|---|---|---|---|
| 1 | HIGH | ADR-037 §8/§9's literal text ("the fact that no winner was selected must be recorded... in a ... persisted store") is underspecified as to intent (§3) and, read literally without a terminal-window boundary the ADR never supplies, would reproduce the exact permanent-early-lockout defect the independent Plan review found — confirming the implementation Plan's Model-A design cannot be reconciled with ADR-037's current text without either an ADR amendment or a switch to Model B | No — this is the finding that motivates the recommended amendment |
| 2 | — (informational, resolves finding 1's design question) | Model A (winner-only persistence, as already chosen by the implementation Plan) and Model B (persisted provisional absence) are functionally identical on every capital-preservation, cardinality, restart, concurrency, and observability dimension tested (§4, §5); Model A is strictly simpler, and this codebase already has an Accepted, in-production-shape precedent for exactly Model A's design pattern (`FormationBlackoutStore`, §2) | No |
| 3 | LOW | §15 (capital-preservation adversarial review) and §17 (preconditions) both require confirmatory/procedural attention once the amendment lands, but neither contains language contradicting the recommended amendment as written today | No |
| 4 | LOW (test-specification precision, not a persistence-model defect) | The existing (pre-dating this revision chain) concurrency test specification for `OpportunityWinnerStore` does not explicitly require differing per-thread candidate sets, leaving the strongest form of the "competing calls converge on the persisted winner rather than their locally computed winner" proof unstated; recommended as a tightening for the eventual Plan revision, applies identically regardless of which model is adopted | No |

---

## 10. Consequences for the current implementation Plan (`0388595`)

The implementation Plan's Model-A design (§1/§6 of `docs/plans/adr-037-
implementation-plan.md`) is **not** found to be unsafe, incorrect, or in
need of a different underlying design by this Research — every
adversarial scenario tested produces the correct, capital-preserving
outcome under Model A. The defect identified by the independent Plan
review is **governance-textual, not architectural**: the Plan implements
a persistence contract ADR-037's current §8/§9 text does not, as
written, authorize. This Research's recommendation is to bring ADR-037's
text into conformance with the Plan's already-correct design (via a
dedicated ADR-037 Amendment), rather than to change the Plan's design to
match ADR-037's current, literal-but-unworkable text. The implementation
Plan itself is **not to be revised in this task** — that is the
reconciliation step that follows the amendment's own independent
governance review and Acceptance, per the chain restated below.

---

## 11. Authorization boundaries and unresolved questions (explicitly not decided here)

Not performed, decided, or implied by this Research:

- The exact final wording of the ADR-037 Amendment itself (drafting is
  the next gate, not this one).
- Whether the amendment is captured as "ADR-037 Amendment 1" or folded
  into a renumbered Accepted revision — a drafting-time, not a Research-
  time, decision, though this Research's own recommendation (§7) favors
  the Amendment pattern already established twice in this repository
  (ADR-031 Amendment 1, ADR-036 Amendment 1).
- Any change to the implementation Plan (`docs/plans/adr-037-
  implementation-plan.md`) — untouched by this task.
- Any ADR-037 text outside §8/§9/§12(clarifying-sentence-only)/§14/§17.
- The separately-already-identified, separately-tracked ADR-031
  amendment (`docs/plans/adr-031-pipeline-amendment-research.md`) —
  unrelated to and not a substitute for this persistence-semantics
  question; both amendments are independently required before
  implementation.
- Gate A/Gate B activation.
- ADR-036 legacy-strategy retirement sequencing.
- Any runner-up fallback policy.
- The ADR-035 Phase 5 anchor hour/minute validation follow-up.
- Ranking formula, tie-tolerance value, or exact session/pair/anchor
  production values — all previously settled or explicitly out of
  scope, untouched here.

---

## 12. Recommendation for the next gate

The evidence gathered in this Research supports drafting a dedicated
ADR-037 Amendment (the smallest correction: §8/§9 reworded to match
Model A, a clarifying sentence in §12, procedural updates to §14/§17;
§1–§7, §10, §11, §13, §15 (substance), §16 untouched), following the
same draft → independent review → revision (if needed) → final
acceptance review → acceptance-recorded sequence this repository already
established for ADR-031 Amendment 1 and ADR-036 Amendment 1. No finding
in this Research supports abandoning the implementation Plan's winner-
only design — the design is correct; only ADR-037's own text needs to
catch up to it. The reconciliation of `docs/plans/adr-037-implementation-
plan.md` against the amendment's own text is the gate *after* the
amendment's independent review and Acceptance, not this one.

---

**ADR-037 PERSISTENCE SEMANTICS RESEARCH COMPLETE — GOVERNANCE AMENDMENT DRAFT REQUIRED**

---

*This document is a read-only Research artifact. It does not amend
ADR-037, does not revise the implementation Plan, does not implement
code, does not activate Gate A or Gate B, does not retire any legacy
strategy, does not change any deployment-profile value, does not
authorize runner-up fallback, and does not touch the ADR-035 Phase 5
anchor hour/minute validation follow-up.*
