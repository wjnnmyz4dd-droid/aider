# Plan: Session-Scoped Cross-Pair ORB Selection — Research

Status: Research
Owner (Research phase): Software Architect
Touched components: none (read-only this phase — no production, config,
or test file anywhere is created, modified, or deleted by this Research)

---

## 0. Scope of this document

This is the Research-phase RPI artifact for the capability first
identified as a scoped-out architectural finding in
`docs/plans/adr-036-legacy-strategy-retirement.md` §P16 (commit
`ecaa415`): ORB ultimately scanning multiple candidate pairs for each
configured session and selecting the best qualifying opportunity for
that session independently, with no automatic carryover between
sessions.

**This document does not design or implement the solution.** It
reconstructs the current architecture from source, answers the twelve
questions the governing task specified, performs the required
adversarial capital-preservation review, and states explicitly which
governance decisions remain open. No pair, no anchor, no ranking
formula, no weight, and no routing behavior is chosen here.

**Explicitly out of scope, untouched throughout:** legacy-strategy
retirement, Gate A/Gate B activation, any ADR-036 implementation, Phase
7 formation-blackout behavior, and the separate Phase 5 anchor
hour/minute validation residual risk.

## 1. Repository state (fresh, verified this pass)

- Branch: `claude/phantom-ea-visibility-cjjf3a`
- HEAD at start of this pass: `ecaa415` (ADR-036 Plan §P16 scoped-out
  finding)
- Working tree: clean throughout
- `docs/plans/adr-036-legacy-strategy-retirement.md` §P16 re-read in
  full as the governing statement of this Research's trigger.

## 2. Current architecture, reconstructed fresh from source

**Per-pair independence is total and consistent across every layer of
the live pipeline — confirmed by direct read of every engine's own
orchestration entry point, not assumed:**

- **`RuntimeOrchestrator.run_cycle(pairs, profile, inputs, now,
  cycle_id)`** (`titan_protocol/runtime/engine.py`) iterates `for pair
  in sorted(pairs): ... run_cycle_for_pair(pair, ...)` — each pair gets
  its own complete, independent Evidence → Market Intelligence →
  Strategy → Risk → Compliance → Bridge cycle. Runtime's own governing
  ADR (ADR-031) states this explicitly as a Hard Rule, confirmed by
  direct read of `runtime/engine.py`'s own module docstring:
  `RuntimeOrchestrator` "owns ZERO trading logic — every conditional
  branch below is an equality/membership check against a value another
  engine's public interface already returned, never a threshold,
  weight, or rule computed inline." Runtime never compares one pair's
  outcome against another's, anywhere.
- **Every engine exposes an `evaluate_batch()` convenience method
  (`StrategyEngine`, `RiskEngine` confirmed by direct read; likely
  others), and every one of them is the identical shape**: a
  deterministic, sorted, per-item loop calling the same engine's own
  singular `evaluate()` — e.g. `StrategyEngine.evaluate_batch()`:
  `results = tuple(self.evaluate(pair, evidence, market_intelligence,
  now) for pair, (evidence, market_intelligence) in
  sorted(pairs.items()))`. **Zero cross-item aggregation, comparison, or
  ranking logic exists in any `evaluate_batch()` anywhere** — "batch" in
  this codebase means "the same per-item work done for several items,"
  never "compare the items to each other."
- **`RuntimeOrchestrator` never calls any engine's own
  `evaluate_batch()`** — confirmed by repository-wide grep: the only
  reference to `evaluate_batch` outside its own defining modules and
  their test suites is a single, unrelated comment in
  `deployment_windows/start.py:800`. Runtime's `run_cycle()` performs
  its **own** per-pair loop, calling each engine's **singular**
  `evaluate()` once per pair, itself.
- **`selection.py`'s 6-step cascade** (`strategy_engine/selection.py`,
  re-confirmed fresh this pass) selects among **strategies** competing
  for the **same pair** — `select_winning_strategy(qualifications:
  Sequence[QualificationResult], ...)` operates on qualification results
  that are all, by construction, for one `pair` (they come from
  `StrategyEngine.evaluate(pair, ...)`'s own single-pair loop over
  `self.registry.all()`). It has never compared candidates from
  **different** pairs, and nothing about its design generalizes to doing
  so without a different input shape entirely.
- **`OrbBreakoutStrategy.qualify()`** (`orb_breakout.py`, re-confirmed
  fresh) already restricts evaluation, per pair per cycle, to only the
  most-recently-formed opening range: `latest_range_end = max(r.range_end
  for r in formed_ranges)`; `currently_relevant = [r for r in
  formed_ranges if r.range_end == latest_range_end]`. Once a later
  session's anchor produces a new range for a pair, that pair's earlier
  session's range is automatically superseded. This is genuine,
  already-existing, zero-new-code "no carryover between sessions" — but
  it is a **per-pair** guarantee, not a cross-pair one (§4 below).
- **Risk Engine already has genuine cross-pair awareness, for a
  different purpose**: `ReservationLedger` (`risk_engine/reservation.py`)
  tracks `pending_total_r()`/`pending_for_pair_r()` across the whole
  portfolio; `correlation.py`'s `compute_correlation_status()`/`_cluster()`
  groups pairs by estimated correlation to cap simultaneous correlated
  exposure. Both exist to **limit** how much of the portfolio a set of
  already-approved candidates may simultaneously occupy — neither
  chooses **which** candidate to prefer among competing opportunities.
  `RiskEngine.evaluate(pair, ...)` reserves risk_r for **whichever** pair
  is being evaluated, independent of whether a "better" pair exists
  elsewhere in the same cycle.
- **`InFlightCommandRegistry`** (`runtime/in_flight_commands.py`) is
  pair-keyed (`has_unresolved(pair, now)`) and already prevents
  re-submitting for a pair with an unresolved in-flight command —
  orthogonal to, and unaffected by, which pair a future selection
  mechanism might prefer.
- **`EvidenceEngineConfig.__post_init__`** already rejects, at
  config-load time, any two `opening_range_anchors` whose windows would
  coincide or overlap (`_validate_no_overlapping_anchors`) — genuinely
  overlapping session **range-formation windows** are already
  structurally impossible today, independent of this Research.
- **`QualificationResult`** (`strategy_engine/models.py`, re-confirmed)
  carries `score: float` (0–100), `confidence: float` (0–1), `trade_intent`,
  `strengths`/`weaknesses` — per-pair, per-strategy outputs already
  computed today, with no cross-pair meaning attached to them by any
  existing code.

## 3. Answers to the twelve governing questions

### 3.1 Where could cross-pair comparison correctly live?

Four candidates exist; none is a clean, ADR-permitted fit without a new
governance decision:

- **Inside Runtime** — Runtime is the only component that already
  iterates every pair in one cycle, but ADR-031's own Hard Rule
  (quoted §2 above) explicitly forbids Runtime from computing "a
  threshold, weight, or rule... inline." A cross-pair ranking is
  precisely that. Placing it here would require an ADR-031 amendment
  reopening a Hard Rule this project has otherwise treated as
  foundational.
- **Inside Strategy Engine** — has the qualification data, but is
  currently strictly single-pair by construction (`evaluate(pair,
  ...)`); extending it to accept and compare multiple pairs is a new
  capability for the package, and ADR-036 §9's own Non-Goals already
  state `selection.py`'s cascade is "already strategy-count-agnostic"
  and must not be modified — a cross-pair analog would very likely
  touch that boundary, requiring an ADR-026 amendment and probably an
  ADR-036 Amendment 2.
- **Inside Risk Engine** — the only engine with existing genuine
  cross-pair plumbing (reservation, correlation), but its own role is
  sizing/reserving capital against an *already-chosen* candidate, not
  choosing which candidate to consider in the first place — an
  ownership mismatch, not just a governance one. Would require an
  ADR-027 amendment.
- **A new, dedicated pipeline component** ("Opportunity Selection" or
  similar), sitting between Strategy Engine and Risk Engine (or, per
  §3.5, later) — the architecturally cleanest fit (violates no existing
  engine's own Hard Rules), but is a genuinely new pipeline stage under
  ADR-001's own stage-per-Accepted-ADR discipline (`CLAUDE.md` §1.10) —
  requiring a brand new ADR, not an amendment.

**No existing component is simultaneously (a) already positioned with
the necessary multi-pair visibility and (b) already permitted by its own
Accepted Hard Rules to make this kind of decision.** This is itself a
finding, not an oversight to route around.

### 3.2 What existing outputs could legitimately participate vs. what is new policy?

Available today, per pair, with no new computation: `QualificationResult.score`,
`.confidence`, `.trade_intent`; Market Intelligence's `liquidity_score`/
`news_score`/`session_score` (already read by `selection.py`'s own
steps 5–6 for strategy tie-breaking — the same facts, reusable in
principle for pair tie-breaking).

**Not determinable from existing outputs, and squarely new policy**: the
actual *definition* of "best." `selection.py`'s existing 6-step cascade
order (score → confidence → placeholders → liquidity → news) was itself
a deliberate, disclosed ADR-026 Hard Rule 6 design decision — a
cross-pair analog needs the same order of deliberate, disclosed design,
not silent reuse of the same steps for a different comparison axis. Tie
handling is likewise policy: `selection.py`'s own precedent is "still
tied after every step: reject, never randomize" (confirmed from source)
— a defensible default for a cross-pair analog, but not automatically
inherited without an explicit design decision saying so.

### 3.3 How would a session-scoped candidate set be formed?

The natural, no-new-config answer is: the candidate universe **is**
whatever pair set `OPENING_RANGE_BREAKOUT` is approved for in
`approved_pairs_by_strategy` (ADR-036 Gate A) — scanning "the candidate
universe" and "the pairs ORB is eligible for" are the same list, if the
intended design is "the same universe applies to every configured
session." Re-confirmed this pass: no session-*specific* pair-eligibility
authority exists anywhere (`market_intelligence/session_intelligence.py`
computes a session-**wide** preference/quality score, entirely
pair-agnostic; `liquidity_intelligence.py` computes real-time per-pair
liquidity from live spread/broker data, not a static per-session
eligibility table). If the actual intent is a genuinely *different*
candidate subset per session (e.g. certain pairs only scanned during
London, others only during New York), that eligibility rule does not
exist today in any form and would have to be invented — this Research
does not invent it, consistent with the instruction not to.

### 3.4 Session identity, boundaries, anchors, resets, no-carryover

Per-pair "no carryover between sessions" is already free (§2). The
subtlety a cross-pair mechanism introduces: comparing pair A's
"currently relevant" range against pair B's requires both to actually be
evaluating **the same session's** range — i.e., keyed by the same
`(session, range_start)` identity from the configured anchor, not merely
"whichever range `qualify()` currently treats as relevant for that
pair." If pair A has a data gap and its own most-recently-formed range
is still London's while pair B's has already advanced to New York's
(both per-pair-correct individually, per §2's existing logic), a
naive cross-pair comparison that simply reads "the most recent
`QualificationResult` per pair" would silently compare a London
opportunity against a New York one — comparing across sessions by
accident. **A correct design must explicitly key candidates by
`(session_anchor_identity, range_start)`, not merely by "whatever the
per-pair qualify() call currently returns."** This is a genuine adversarial
finding, not a solved problem (§5).

### 3.5 Before or after Risk/Compliance? Capital-preservation consequences of each

**Option A — compare immediately after Strategy Engine, before Risk/Compliance:**
only the chosen winner proceeds; every other candidate's cycle ends at a
new, distinct outcome ("qualified, not selected this session").
*Consequence*: cheaper (Risk Engine reserves risk_r for exactly one
candidate, not several), and avoids wasting correlation/portfolio-heat
computation on discarded candidates. *Cost*: if Risk Engine or
Compliance Engine subsequently rejects the chosen winner (portfolio
heat, daily-loss lock, etc.), the session's opportunity is lost even if
a second-best candidate would have cleared every gate — the selection
was made on qualification quality alone, without knowing whether the
winner would actually survive downstream.

**Option B — run every qualifying pair through the full, unmodified,
existing per-pair pipeline (Risk → Compliance) independently first, and
select only at the final Bridge-submission step, among whichever
candidates independently passed every existing gate:** *Consequence*:
the eventual winner is provably a fully-vetted candidate, not merely the
best-looking one on paper. *Cost, concrete and serious*: Risk Engine
already reserves risk_r **before** Compliance ever runs, per pair
(`ReservationLedger.reserve_if()`, confirmed from source and from this
project's own prior, hard-won reservation-lifecycle bug-fix work this
session's memory recalls). If three candidate pairs all independently
qualify and pass Risk + Compliance in the same cycle, **three
simultaneous reservations exist**, and only one pair will actually be
submitted — the other two reservations must be correctly, explicitly
released once the cross-pair winner is chosen. Getting this wrong
reproduces exactly the reservation-leak defect class this codebase has
already spent real engineering effort fixing once. Option B is not
simply "safer" than Option A — it trades a lost-opportunity risk for a
reservation-lifecycle-correctness risk of a kind this project has direct,
recent, first-hand experience being bitten by.

**This is a genuine, unresolved, capital-preservation-relevant design
tradeoff.** This Research does not choose between them.

### 3.6 Zero/one/multiple qualify; ties; delayed/missing data; different evaluation times; reconnects; incomplete scans

- **Zero qualify**: no selection needed, equivalent to today's
  `NO_STRATEGY`-shaped outcome, no new logic.
- **Exactly one qualifies**: trivial winner, but still requires having
  scanned the *whole* candidate universe first to know only one
  qualified — not a distinct code path, just the N=1 case of a full
  scan.
- **Multiple qualify**: genuinely requires the new ranking/tie-break
  policy (§3.2) — unresolved by design, pending governance.
- **Exact ties**: this codebase's own established precedent
  (`selection.py`: "still tied after every step: reject, never
  randomize") is the natural default for a cross-pair analog, but must
  be an explicit decision, not silently inherited.
- **Delayed or missing pair data**: a scan that waits for every
  candidate pair's data before deciding risks unbounded latency (a pair
  whose data never arrives that cycle); a scan that proceeds with
  whichever pairs' data happened to arrive risks silently selecting "the
  best of an incomplete subset" while an operator reasonably believes
  the system considered the full universe. Neither is free; which one
  (and how the gap is surfaced/logged) is an unresolved design question.
- **Pairs evaluated at genuinely different wall-clock moments within a
  cycle**: comparing `QualificationResult`s computed from
  meaningfully different-aged snapshots is comparing facts of differing
  freshness as if they were contemporaneous — a real "ranking
  incomparable/stale snapshots" hazard (§5).
- **Reconnects mid-cycle**: if a winner is chosen but Bridge submission
  then fails and the connection is later restored, does the mechanism
  retry with the *same* previously-chosen winner, or re-scan and
  potentially choose a *different* one? Unresolved without a persisted,
  idempotent winner record (§3.7).
- **Incomplete session scans** (a time-budget cutoff reached before all
  candidate pairs are evaluated): the same "best of a partial subset,
  presented as if it were the whole" hazard as delayed data.

### 3.7 Suppression of otherwise-qualified pairs; state/persistence/idempotency

Selecting one pair per session necessarily means every other
otherwise-`QUALIFIED` pair for that session must be **suppressed** — new
behavior, since today every qualifying pair proceeds independently. This
requires, at minimum:

- A new, distinct outcome (analogous to `CycleOutcome.NO_STRATEGY`, but
  meaning "qualified, a different pair was selected for this session,"
  not "nothing qualified at all") for audit-record completeness — this
  project already treats `RuntimeAuditRecord` completeness as a serious,
  explicitly-tracked concern (its own prior "Final Release Hardening"
  work), so a silent suppression with no distinct, recorded reason would
  be a regression against that established standard.
- **Idempotency across repeated cycles within the same session window**:
  without a persisted "session S, range_start R → winner is pair X"
  record — analogous in shape to `OrbQualificationStore`'s own
  per-`(pair, range_start)` lockout, but keyed differently (by session
  identity, across pairs, not by pair alone) — a naively-recomputed
  "best pair" could flip mid-session if candidate scores fluctuate
  cycle-to-cycle (pair A wins one cycle, pair B "wins" the next purely
  because A's score dipped slightly), producing genuinely contradictory
  winners across cycles for what should be one session's one decision.
  **This is real new persisted state, not a config value** — a new
  store, designed with the same restart-safe, fail-closed-on-corruption
  discipline already established by `OrbQualificationStore`/
  `FormationBlackoutStore`, would very likely be required.

### 3.8 Interaction with portfolio limits, correlation, in-flight state, concurrent sessions

- **Portfolio limits** (`max_open_positions`, `max_positions_per_pair`)
  and **correlation clustering** already exist in Risk Engine and would
  continue to apply unchanged to whichever single pair wins a session —
  a single-winner-per-session model is, if anything, a *smaller* risk
  surface against these existing controls than today's
  every-qualifying-pair-proceeds-independently behavior, provided the
  new mechanism routes its single winner through the existing,
  unmodified Risk → Compliance → Bridge path (not a new, parallel one).
- **`InFlightCommandRegistry`** is already pair-keyed and orthogonal to
  which pair is "selected" — no new logic needed there.
- **Genuinely overlapping session *range-formation* windows** are
  already structurally prevented by Evidence Engine's own existing
  config validation (§2). **Overlapping *position-holding* periods**
  (a position opened during London still open when New York's own
  window begins) are a distinct, unaddressed concern — CLAUDE.md's own
  "No duplicate trades. No uncontrolled pyramiding" principle bears
  directly here. The existing Risk Engine/Compliance Engine
  position-limit and correlation gates, run downstream of whichever pair
  a future mechanism selects, are the natural place this would continue
  to be caught — **provided** the new selection step does not attempt to
  duplicate or bypass that check itself, which this Research does not
  design.

### 3.9 Can this be added while preserving the existing per-pair pipeline, or does it need a new stage?

Every individual per-pair engine (Evidence Engine's own per-pair
evaluation, Strategy Engine's own `qualify()`, Risk/Compliance's own
per-pair gates) can remain entirely unmodified — this capability
consumes their **outputs** across pairs, it does not need to change how
any single pair is individually evaluated. But **some new, genuinely
cross-cutting aggregation step must exist somewhere** in the pipeline
(§3.1) — the "per-pair pipeline stays untouched end-to-end with zero new
architecture" reading is not available; a new component is required
regardless of which of §3.1's four candidates is eventually chosen.

### 3.10 Which Accepted ADR contracts would change?

| Candidate (§3.1) | ADR(s) requiring amendment or creation |
|---|---|
| Extend Runtime | ADR-031 amendment (reopens its own "Runtime owns zero trading logic" Hard Rule) |
| Extend Strategy Engine | ADR-026 amendment; very likely ADR-036 Amendment 2 (§9 Non-Goals currently forbid modifying `selection.py` and forbid new ORB-specific coupling outside Strategy Engine) |
| Extend Risk Engine | ADR-027 amendment |
| New dedicated pipeline stage | A brand new ADR (per ADR-001's stage-per-Accepted-ADR discipline, `CLAUDE.md` §1.10) — not an amendment; plus, in every case above, likely ADR-035 amendment (changes how ORB's own qualification output is consumed in production) and ADR-036 Amendment 2 (changes what "Gate A" and retirement completion mean) |

This Research does **not** choose among these — doing so would be
resolving an ADR-level decision inside a Research document, which the
governing task explicitly prohibited.

### 3.11 What becomes of ADR-036 Gate A and Gate B?

- **Gate B (opening-range anchors) is entirely independent of this
  architecture question** and can be resolved as an ordinary
  deployment-profile value decision at any time — §3.4 already confirms
  multiple session anchors are structurally supported today with zero
  new code. Unchanged conclusion from the prior Plan pass.
- **Gate A (approved pairs) is where the dependency actually bites.** A
  *narrow* Gate A (one, or a small fixed handful, of pairs) remains
  resolvable today as an ordinary deployment-profile value, entirely
  independent of this Research — every qualifying pair in a narrow set
  would simply proceed independently through the existing, unmodified
  pipeline, bounded by today's existing portfolio/correlation limits,
  exactly as ORB already behaves for any single pair today. A *wide*
  Gate A, configured with the intent that the system will automatically
  select only the best opportunity per session, **does not produce that
  behavior under the current architecture** — it would instead mean
  every qualifying pair in that wide universe proceeds independently
  (today's existing behavior, just with more pairs turned on), which is
  a materially different, and materially less selective, outcome than
  what was actually requested. Configuring a wide Gate A today, before
  this capability exists, would silently misrepresent what the system
  does. **This Research does not choose Gate A's width or membership** —
  it establishes that the choice of width is now coupled to whether the
  new selection architecture exists, and flags that coupling precisely
  for whoever makes that deployment-profile decision next.

### 3.12 Smallest plausible candidate architectures

| Candidate | Ownership fit | Primary failure mode | Observability need | Rollout/rollback | Testability |
|---|---|---|---|---|---|
| Extend Runtime | Poor — conflicts with ADR-031's own explicit Hard Rule | Runtime silently becomes a decision-maker, not a sequencer, undermining ADR-031's own audit/determinism guarantees | New Runtime-level metrics/logging for "selected vs. suppressed" per session | Reverting restores today's per-pair-independent behavior cleanly | Runtime's existing test suite already exercises full-cycle behavior; a new cross-pair scenario matrix would need to be added there |
| Extend Strategy Engine | Moderate — has the data, lacks the multi-pair shape; touches ADR-036 §9's own Non-Goals | A new multi-pair entry point diverging in behavior from the single-pair `evaluate()` every existing test assumes | New Strategy-Engine-level explainability output naming the suppressed candidates and why | Reverting restores single-pair-only `evaluate()`; existing single-pair tests unaffected if the new entry point is additive | Strategy Engine's existing fixture/registry patterns extend naturally to a new, additive test file |
| New dedicated pipeline stage | Best structural fit — no existing Hard Rule conflict | A wholly new component's own correctness (persistence, idempotency, fail-closed behavior) is unproven by any existing precedent beyond analogy | A new stage needs its own logging_sink/metrics pair, per this project's own established per-package convention | Cleanest rollback (a new stage can be structurally bypassed/disabled without touching existing engines) but is the largest single addition | Requires an entirely new test suite from scratch, no existing suite to extend |
| Extend Risk Engine | Poor — ownership mismatch (sizing an already-chosen candidate vs. choosing the candidate) | Conflates two distinct responsibilities (risk sizing and opportunity selection) inside one engine, the kind of duplicate-responsibility this project's own charter (`CLAUDE.md` §1.4) warns against | Existing Risk Engine metrics would need new fields distinguishing "sized" from "selected" | Reverting risks entangling with Risk Engine's own existing, carefully-hardened reservation-lifecycle code | Risk Engine's existing reservation-lifecycle tests are already intricate (per this project's own prior bug-fix history); adding selection logic here raises the risk of regressing that hardened surface |

**No recommendation is made.** Existing governance and evidence are
insufficient to prefer one candidate over another — §3.5's pre/post-Risk
placement question and §3.10's ADR-level implications differ materially
by candidate, and choosing among them is itself the governance decision
this Research surfaces rather than resolves.

## 4. Adversarial capital-preservation review

| # | Risk | Assessment |
|---|---|---|
| 1 | Selecting a winner from an incomplete candidate set (delayed/missing data, time-budget cutoff) | Confirmed real, unresolved (§3.6) — a partial scan silently presented as a full one is a capital-preservation-relevant transparency failure, not merely a data-quality nuisance |
| 2 | Executing multiple winners (reservation-lifecycle failure under Option B, §3.5) | Confirmed real and serious — directly analogous to a defect class this project has already had to fix once; any future design choosing Option B must treat multi-reservation release with at least the same rigor as the existing fix |
| 3 | Stale winners surviving session boundaries or restarts | Confirmed real, unresolved without a new idempotent persisted store (§3.7) — without one, a restart mid-session could either re-select a different winner (contradicting the prior cycle's own decision) or fail to resolve at all |
| 4 | Ranking incomparable/stale snapshots (candidates evaluated at different effective times, or across different session identities per §3.4) | Confirmed real — both a data-freshness hazard (§3.6) and a session-identity-alignment hazard (§3.4); a correct design must key comparisons by `(session_anchor_identity, range_start)`, not merely by "whatever qualify() currently returns" |
| 5 | Accidentally converting a selection failure into unrestricted per-pair execution (fail-open instead of fail-closed) | **The single most severe risk this Research identifies.** If the future mechanism cannot decide (exception, timeout, tie with no tie-break) and its fallback is "let every qualifying pair proceed as before," that is a silent, fail-open reversion to today's exact pre-selection behavior — precisely when the new mechanism was supposed to be constraining exposure. Any future design must fail closed here (no pair proceeds that session on a selection failure), mirroring this project's own consistent, established fail-closed philosophy (Evidence Engine, `validate_profile()`, both persisted ORB stores). This must be an explicit, tested requirement of whatever Plan eventually designs this, not an incidental default. |

## 5. Preservation constraints (reaffirmed)

Nothing in this Research changes: ORB's own `qualify()` logic;
`selection.py`'s existing cascade; `RuntimeOrchestrator`'s existing
per-pair cycle; Risk Engine's, Compliance Engine's, or Bridge's existing
behavior; Evidence Engine's opening-range computation; the Phase 7
formation-blackout mechanism; or any ADR-036 Plan content (§P1–§P16 of
the Legacy Strategy Retirement Plan remain exactly as previously
finalized). No `StrategyId`, no registry entry, no config default, no
approved pair, and no opening-range anchor was touched by this pass.

## 6. File-impact hypotheses (explicitly conditional — no architecture chosen)

Genuinely hypothetical, contingent on a future governance decision among
§3.1's four candidates — **not a commitment, not a Plan**:

- **If a new pipeline stage** (§3.1, best structural fit): a new
  top-level package (e.g. `titan_protocol/opportunity_selection/`) with
  its own `models.py`, `config.py`, `engine.py`, `logging_sink.py`,
  `metrics.py`, and a new persisted store (§3.7) — mirroring this
  project's own established per-package convention; `runtime/engine.py`
  would gain a new call site between Strategy Engine and Risk Engine (or
  later, per §3.5); `scripts/check_architecture.py` would need a new
  package boundary rule.
- **If extending Strategy Engine**: `strategy_engine/selection.py` or a
  new sibling module; `strategy_engine/engine.py` gains a new multi-pair
  entry point; ADR-026/ADR-036 documentation updates.
- **If extending Runtime**: `runtime/engine.py`'s own `run_cycle()`
  gains new inline comparison logic — the candidate this Research
  regards as the poorest fit (§3.1).
- **In every candidate**: `docs/adr/ADR-035-orb-strategy.md`,
  `docs/adr/ADR-036-orb-strategy-consolidation.md`, and very likely
  `docs/adr/ADR-026-strategy-engine.md` and/or
  `docs/adr/ADR-031-runtime-orchestrator.md` would need an amendment
  (§3.10) — none of that is performed here.

## 7. Validation baseline (fresh, confirming this Research changed nothing)

- `git status`/`git diff --name-only`: expect no changes outside this
  new Research document.
- `python3 -m compileall -q titan_protocol tests deployment_windows scripts`
- `python3 scripts/check_architecture.py` — expect PASS, unchanged
  package count.
- `python3 -m unittest discover -s tests/titan_protocol/strategy_engine`
- `python3 -m unittest discover -s tests/titan_protocol/runtime`
- Live confirmation: `StrategyId` membership, `DEFAULT_APPROVED_PAIRS_BY_STRATEGY`,
  and `EvidenceEngineConfig.opening_range_anchors` all unchanged from
  their current production defaults.

## 8. Final disposition

This capability is **not ready for governance resolution as a single
ADR decision** — the Research above surfaces multiple, materially
different candidate architectures (§3.1/§3.12) whose ownership fit,
ADR impact (§3.10), and a load-bearing, unresolved capital-preservation
tradeoff (§3.5's pre- vs. post-Risk placement) have not converged on one
answer, and this Research correctly does not manufacture that
convergence. At the same time, one part of the originally-requested
behavior — session-based, non-carrying-over opening ranges — **is
already satisfied by the existing, unmodified architecture** and
requires no new work at all (§2, §3.4); this should not be
re-litigated or redesigned in any future governance pass.

**Recommended next step** (not authorized by this Research, stated only
as a recommendation): a dedicated ADR-level Research/proposal — most
likely framed as a new ADR for a dedicated pipeline stage, per §3.12's
own structural-fit assessment, though this Research does not mandate
that outcome — should resolve §3.1's placement question and §3.5's
pre/post-Risk tradeoff before any Plan for this capability is written.
Gate B may be decided independently of this at any time; Gate A's exact
membership and width remain coupled to this decision per §3.11 and
should not be finalized as "wide" until the selection mechanism exists.

**SESSION-SCOPED CROSS-PAIR ORB SELECTION — RESEARCH COMPLETE —
GOVERNANCE-LEVEL ARCHITECTURE DECISION REQUIRED BEFORE PLAN WORK
BEGINS**

Standing reminders:

- No implementation, design commitment, or ADR change has been made.
- The session-based (non-carrying-over) half of the original request is
  already satisfied by existing code and does not require this
  decision to proceed being true — but no config change (Gate B) is
  authorized by this Research either.
- ADR-036 Gate A and Gate B remain exactly as `docs/plans/adr-036-legacy-strategy-retirement.md`
  §P15/§P16 left them: unresolved.
- The separate Phase 5 anchor hour/minute validation residual risk was
  not performed, referenced as authority, or folded into this work.
