# Plan: ADR-035 Phase 7 — Formation-Time News-Blackout Closure

Status: **RESEARCH ONLY — Plan and Validation sections intentionally
empty.** This artifact records the Research phase of the RPI gate
(`.claude/agents/TEAM.md` §9) for ADR-035 Phase 7, as authorized by
Accepted ADR-035 Amendment 1. No implementation decision is made here;
several genuine design questions are deliberately left open for the
Plan phase.

Owner (Research phase): Software Architect (ADR-035/ADR-025/ADR-026
owner precedent, unchanged from Phases 0-6).

Touched components: **none — read-only research.** No production file,
ADR, or the separate Phase 5 anchor hour/minute validation follow-up is
touched by this artifact.

---

## Research

### 0. Governance gate (verified against current HEAD, not assumed)

- Branch `claude/phantom-ea-visibility-cjjf3a`, HEAD `2e4803c` at the
  start of this research (Phase 6 implementation, independently
  reviewed and accepted). Working tree clean.
- ADR-035: `Status: Accepted` (2026-07-25). Amendment 1: `Status:
  Accepted (2026-07-26)` — both re-confirmed by direct read of
  `docs/adr/ADR-035-orb-strategy.md`, not assumed from prior session
  summaries.
- Phase 7 is explicitly named in ADR-035 §17 as "not yet scheduled; no
  RPI Research performed" prior to this artifact, and in Amendment 1 as
  "deferred, not designed here, not yet scheduled." This is the first
  Research pass against it.
- Re-verified this pass: no Phase 7 code exists anywhere in the
  repository (no new store, no new Evidence Engine field, no new
  Strategy Engine import touching Market Intelligence).

### 1. The exact Accepted-ADR obligation (quoted directly from source)

ADR-035 §2's "News restrictions" row (re-read directly,
`docs/adr/ADR-035-orb-strategy.md`):

> Reuses Market Intelligence's existing `pair_safety.news.blackout_active`
> exactly as `SessionBreakoutStrategy` does today — NOT_QUALIFIED if
> active, **both during range formation and at breakout evaluation**.

Amendment 1 records the gap this creates and its resolution path,
quoted directly:

> **Authorization:** for Phase 4 only, evaluation-time-only
> news-blackout enforcement... is explicitly authorized as a staged
> limitation. This narrows §2/§14's news-blackout requirement for Phase
> 4 specifically; it does not alter §2/§14 for any other gate, and it
> does not authorize omitting the evaluation-time check itself.
>
> **Closing the gap (deferred, not designed here, not yet scheduled):**
> a future, dedicated RPI Research pass must scope one of — (i) a new,
> small, per-`(pair, range_start)` persisted history mechanism, in
> convention analogous to `OrbQualificationStore`, that accumulates "was
> `blackout_active` ever `True`" across the cycles spanning a range's
> own formation window, queried by `OrbBreakoutStrategy` at evaluation
> time; or (ii) a reviewed, explicit Evidence-Engine dependency on
> Market Intelligence's news output. Neither design is chosen here.

**Obligation, stated precisely:** Phase 7 must make ORB return
`NOT_QUALIFIED` if a news blackout was active **at any point during**
`[range_start, range_end)` for the specific opening range a breakout
candidate belongs to — not only at the instant the breakout candidate
itself is evaluated (already enforced, unchanged since Phase 4). Two
named candidate mechanisms exist in the Accepted ADR text; neither is
chosen. Per Amendment 1's own rejection of path (a) (re-quoted in full
in §5 below), any design that reconstructs this fact inside Strategy
Engine by duplicating Market Intelligence's blackout-window arithmetic
is already rejected by the Accepted ADR itself — this is not an open
design question, it is a settled constraint this Research must respect.

### 2. Architecture reconstruction (read directly this pass)

**Evidence Engine — `titan_protocol/evidence_engine/opening_range.py`,
read in full:**
- `compute_opening_ranges(bars, now, config)` is a **pure, fully
  stateless function** — every `OpeningRangeState` is recomputed from
  scratch, every cycle, from `bars`/`now`/`config` alone. There is no
  persistence anywhere in this module; the returned `OpeningRangeState`
  objects are not the same Python objects across cycles, and nothing
  in Evidence Engine remembers what happened on a prior cycle for the
  "same" range.
- `_compute_single_range()` computes `is_formed`/`is_valid`/`range_high`/
  `range_low`/`post_range_bars` purely from the bar window
  `[range_start, range_end)` and the post-range bar-continuity rule —
  no news-related field exists on `OpeningRangeState` today (confirmed
  by reading `models.py`'s `OpeningRangeState` definition, unchanged
  since Phase 0).
- **Consequence for candidate design (load-bearing):** because Evidence
  Engine recomputes `OpeningRangeState` fresh every cycle rather than
  maintaining one persistent object per range across its formation
  window, Evidence Engine **cannot itself be the accumulator** of a
  "was blackout ever active during formation" fact using only its
  current architecture — it has no cross-cycle memory of its own to
  accumulate into. Any design that wants Evidence Engine to *expose*
  this fact (as opposed to merely *carry* an externally-accumulated
  one) would need Evidence Engine to gain a new, persistent,
  cross-cycle memory of its own — a materially larger change than
  adding a field to an already-stateless computation.

**Market Intelligence — `titan_protocol/market_intelligence/news.py`,
read in full:**
- `compute_blackout(pair, events, now, config) -> (bool, Optional[str])`
  is also a **pure, stateless function** of its four arguments — `now`
  is an explicit parameter, not read from the wall clock internally.
  It is not "the current instant's blackout status" in any way baked
  into the function itself; it is "blackout status as of whatever `now`
  the caller supplies," evaluated against whatever `events` the caller
  supplies.
- This means `compute_blackout` **could**, in principle, be invoked
  retroactively for a past `now` (e.g., some instant during an already-
  formed range's formation window) — **provided the caller has access
  to an `events` sequence that still contains whatever `NewsEvent`s were
  relevant at that past instant.**
- **Retention caveat (verified from source, not assumed):**
  `titan_protocol/news_ingestion/config.py`'s `NewsIngestionConfig` has
  `cache_max_entries: int = 200` — a bounded, size-based cache with no
  provision for "retain until every currently-forming range has closed
  its formation window." Events can be evicted for capacity reasons
  unrelated to whether some in-flight opening range still needs them.
  This is a concrete reason a *retroactive* re-invocation of
  `compute_blackout` (as opposed to accumulating its *live* result each
  cycle, before eviction is a factor) is fragile — flagged in §7 below,
  not adopted as a design.
- `PairNewsIntelligence.blackout_active`/`.blackout_reason` (the fields
  `OrbBreakoutStrategy` already reads at evaluation time, unchanged
  since Phase 4) are themselves already the *live, current-cycle*
  output of `compute_blackout` called with the current cycle's own
  `now` — Market Intelligence does not itself retain a history of past
  cycles' `blackout_active` values anywhere either. **Direct answer to
  Research objective 6: no, current Market Intelligence snapshots/
  history do not retain enough information to answer "was blackout
  active at any point during this range's formation?" without either
  new persisted state or a retroactive re-computation subject to the
  eviction caveat above — verified from `news.py`'s and
  `news_ingestion/config.py`'s actual code, not inferred.**

**Strategy Engine — `titan_protocol/strategy_engine/strategies/orb_breakout.py`,
current blackout gate re-read directly (line 87, unchanged since
Phase 4/6):**
```python
if pair_safety.news.blackout_active:
    return _not_qualified(pair, "News blackout active")
```
This is the sole existing blackout check — evaluation-time-only,
exactly as Amendment 1 describes. It runs after the market-closed/
holiday gates and before the opening-range/breakout logic, unchanged by
Phase 6.

**Runtime ordering — `titan_protocol/runtime/engine.py`, read directly
(lines ~211-231):**
```python
evidence = self.evidence_engine.evaluate_snapshot(pair, bars, now)
...
market_intelligence = self.market_intelligence_engine.evaluate(...)
...
strategy = self.strategy_engine.evaluate(pair, evidence, market_intelligence, now)
```
**Evidence Engine evaluates strictly before Market Intelligence, every
cycle.** This is a load-bearing fact for candidate (ii)/B: if Evidence
Engine were to consume Market Intelligence's news output *within the
same cycle*, the current call order makes that data unavailable at the
point Evidence Engine runs — only the *prior* cycle's Market
Intelligence output would exist yet, introducing a one-cycle lag, or
Runtime's own call order would need to change (Market Intelligence
before Evidence Engine), which is a Runtime-level change Amendment 1's
text does not discuss and this Research does not resolve (see §9, open
question 3).

**Existing type-only dependency, re-confirmed:**
`titan_protocol/market_intelligence/models.py` imports `SessionName`
from `titan_protocol.evidence_engine.models` — a real, existing,
one-directional dependency, **Market Intelligence depending on Evidence
Engine**, not the reverse. No import in the opposite direction exists
anywhere today (`grep` of `titan_protocol/evidence_engine/*.py` for any
cross-package import returns nothing at all — Evidence Engine currently
imports from no other `titan_protocol` package whatsoever).

**Structural-boundary allowlists — read directly:**
- `tests/titan_protocol/strategy_engine/test_architecture.py`'s
  `ALLOWED_UPSTREAM_PREFIXES` = `("titan_protocol.evidence_engine",
  "titan_protocol.market_intelligence", "titan_protocol.strategy_state_store")`
  — Strategy Engine importing from Market Intelligence is **already
  allowed** (it already does, for `pair_safety.news.blackout_active`
  via the `MarketIntelligenceSnapshot` type). A new
  `titan_protocol.strategy_state_store`-based mechanism (candidate C/
  option (i)) needs no allowlist change.
- `tests/titan_protocol/evidence_engine/test_architecture.py`'s own
  check is a **blocklist, not an allowlist**:
  `FORBIDDEN_IMPORT_PREFIXES = ("phantom_pipeline", "titan_protocol.bridge")`.
  It does **not** explicitly forbid `titan_protocol.market_intelligence`.
  **Concrete consequence:** the existing architecture test, as written
  today, would **not catch** a new Evidence Engine → Market
  Intelligence import if one were introduced — it is not an
  affirmative allowlist the way Strategy Engine's is. This is a real
  gap in the test's current design (pre-existing, not introduced by
  this Research) that the Plan phase must account for explicitly if
  candidate (ii)/B is ever chosen: either a new, narrow allowlist entry
  documenting the reviewed exception, or an explicit negative test
  proving the dependency was NOT introduced, depending on which
  direction the Plan resolves.

**`strategy_state_store/` precedent, re-confirmed (already the
ORB-lockout mechanism, unchanged by this research):**
`OrbQualificationStore`/`StrategyStateStoreConfig` (Phase 2, extended
into the real deployment path by Phase 6) is a restart-safe,
concurrency-safe, per-key JSON-persisted store, already
Strategy-Engine-owned, already wired into `deployment_windows/start.py`
at `settings.state_dir / "orb_qualifications.json"`. This is the direct
architectural precedent Amendment 1's option (i) explicitly invokes
("in convention analogous to `OrbQualificationStore`").

### 3. The fact that must survive formation → evaluation

**Semantics:** for a given `(pair, range_start)` — the same identity
already used by the existing lockout (§6 of the ADR, unchanged) — the
fact is: *"was `pair_safety.news.blackout_active` observed `True` at
any evaluation cycle whose `now` fell within `[range_start, range_end)`
for this range, before the range's own `is_formed` became `True`?"*

- **When it becomes true:** the first cycle, during formation, where
  the live `MarketIntelligenceSnapshot.pair_safety.news.blackout_active`
  is `True` for the pair and the range's own `range_start <= now <
  range_end` holds for that cycle's `now`.
- **Monotonic for a given range:** yes, if defined as "was true at any
  point" — once `True`, it should never become `False` again for that
  same `(pair, range_start)` identity, since the fact concerns
  something that already happened during a window that, once passed,
  cannot be revisited. This mirrors the lockout's own append-only,
  never-decrement semantics.
- **Restart persistence:** required. A range's formation window
  (default 30 minutes, per `EvidenceEngineConfig.opening_range_duration_minutes`)
  spans multiple live-cycle iterations (default cycle interval 15s per
  `_LIVE_CYCLE_INTERVAL_SECONDS`, ~120 cycles per formation window) —
  a process restart mid-formation must not silently lose whatever
  blackout observations already occurred before the restart, exactly
  the same restart-safety rationale ADR-035 §18.A item 2 already
  established for the qualification lockout itself.
- **Existing model or new contract:** `OpeningRangeState` (Evidence
  Engine) has no field for this today, and — per §2's finding above —
  cannot itself accumulate it without gaining new cross-cycle memory it
  doesn't currently have. This is therefore a **new contract**
  regardless of which candidate design is chosen; the only open
  question is which component owns it and how ORB reaches it at
  evaluation time (§4, §9).

### 4. Candidate designs

**Candidate A — persist the fact directly on `OpeningRangeState`
(Evidence-Engine-owned field, populated each cycle).**
Not explicitly named by Amendment 1, but a natural-seeming extension of
"the fact lives where the range itself lives." Rejected as
**infeasible without a larger, undisclosed change**: per §2's finding,
`compute_opening_ranges()` recomputes every `OpeningRangeState` from
scratch each cycle from `bars`/`now`/`config` alone — it has no
persistent object identity across cycles to accumulate into, and no
existing input parameter through which "was blackout observed in an
earlier cycle for this same range" could even be threaded in without
Evidence Engine either (a) gaining its own new persisted store (a
genuinely new architectural element, not a field addition), or (b)
receiving the accumulated fact as an input parameter from some external
accumulator — at which point the real design is actually candidate C or
D below, with Evidence Engine merely as a pass-through consumer, not the
owner. **Verdict: not a standalone candidate; collapses into C/D
depending on where the actual accumulation happens.**

**Candidate B / ADR option (ii) — a reviewed Evidence Engine dependency
on Market Intelligence's news output.**
- *Ownership/dependency direction:* would require Evidence Engine to
  import from `titan_protocol.market_intelligence` for the first time
  ever — reversing the only precedent that exists today (MI → Evidence
  Engine, type-only, for `SessionName`). Whether this is a type-only or
  data dependency depends entirely on what's consumed: reading
  `blackout_active`/`blackout_reason` off a `PairNewsIntelligence`
  instance is a **data** dependency (a runtime value, not merely a
  type), a materially heavier dependency than MI's existing
  `SessionName` import.
- *Restart/ordering:* per §2's Runtime-ordering finding, Evidence Engine
  currently evaluates strictly before Market Intelligence each cycle —
  this dependency cannot be satisfied same-cycle without either
  accepting a one-cycle staleness or restructuring Runtime's call order
  (itself out of ADR-035's stated scope and a Runtime-engine change,
  ADR-031, not an ADR-035 change).
- *Structural-boundary consequence:* `test_architecture.py`'s current
  blocklist-style check for Evidence Engine would not catch this
  dependency being introduced — a Plan choosing this candidate would
  need to explicitly design either a new allowlist entry or accept an
  unenforced boundary, a governance question in its own right.
- *Persistence:* Evidence Engine still has no persistent memory across
  cycles (§2) — this candidate alone does not solve "did blackout occur
  at some earlier cycle during this range's formation," only "is
  blackout active in Market Intelligence's *current* output," unless
  *also* paired with new cross-cycle accumulation somewhere — meaning
  candidate B, taken alone, does not actually close the gap; it would
  need to be combined with a persistence mechanism resembling C anyway.
  **This is a significant, previously-unstated finding:** Amendment 1's
  option (ii) as literally written ("a reviewed Evidence-Engine
  dependency on Market Intelligence's news output") does not by itself
  specify *where* the resulting fact is accumulated across the
  formation window — it only addresses the dependency-direction/
  ownership question, not the persistence question. The Plan phase
  must treat this as two separable questions, not one.

**Candidate C / ADR option (i) — a new, small, `OrbQualificationStore`-
analogous persisted store, Strategy-Engine-owned, accumulating "was
blackout ever true" per `(pair, range_start)`, queried by
`OrbBreakoutStrategy` at evaluation time.**
- *Ownership:* Strategy Engine, following the exact precedent Amendment
  1 itself names. `OrbQualificationStore`'s existing design (atomic
  JSON write, `.bak` rotation, schema-versioned, fail-closed on
  corruption, restart-safe, `try_consume()`-style single entry point)
  is a proven, already-accepted, already-implemented convention this
  candidate would mirror, not invent from nothing.
- *Who writes to it and when:* this is the central open design question
  (§9, item 1) — the natural candidate is `OrbBreakoutStrategy.qualify()`
  itself, on every cycle (whether or not the range has formed yet),
  recording an observation for `(pair, range_start)` whenever
  `pair_safety.news.blackout_active` is `True` and the range is still
  forming. This requires `qualify()` to run — and therefore be
  reachable — every cycle during formation, not only after formation,
  which is a behavioral question the current `qualify()` early-returns
  do not obviously support without inspection (`qualify()` today
  returns `NOT_QUALIFIED` immediately once `opening_range.is_formed` is
  `False`, per the existing "No opening range currently relevant (none
  yet formed)" path (single-range case) — but it does still *run* every
  cycle up to that point, meaning it already *has* access to
  `pair_safety.news.blackout_active` on every cycle regardless of
  formation state, it just doesn't currently persist anything from it).
- *Dependency direction:* no new cross-engine dependency at all —
  Strategy Engine already depends on Market Intelligence (allowed,
  already used for the same field). This candidate requires zero new
  structural-boundary consideration beyond a new module within
  `titan_protocol/strategy_state_store/` (already an allowed upstream
  import for Strategy Engine) or a new sibling package following the
  same convention.
- *Persistence/restart:* directly solved by the same convention already
  proven correct and accepted for the qualification lockout.
- *Failure modes:* would need its own fail-closed contract decision —
  most likely mirroring `OrbQualificationStore`'s own (corrupt state
  fails closed at construction; write failures logged and contained,
  never escaping `qualify()`) — but this is a Plan-phase design
  decision, not resolved here.
- **Verdict: the most directly evidence-grounded, lowest-new-dependency
  candidate — closes the gap using only mechanisms and precedents that
  already exist and are already accepted, at the cost of Strategy
  Engine now needing to be invoked (or at least have `qualify()` run)
  every cycle during formation, not only at evaluation, which needs
  explicit confirmation from Runtime's actual cycle behavior (open
  question, §9).**

**Candidate D — any simpler mechanism already supported by repository
architecture.**
No fourth, simpler mechanism was found beyond A/B/C above. The
"reuse Market Intelligence's already-bucketed `recent_events`/
`active_events` fields directly" idea (distinct from re-invoking
`compute_blackout` itself) was considered and is **the exact mechanism
Amendment 1's own rejected path (a) already describes and rejects** —
not a new candidate, restated for completeness in §5.

**Candidate E (newly surfaced this pass, not named by the ADR) —
retroactive re-invocation of Market Intelligence's own
`compute_blackout()` function, called from wherever the fact is needed,
against historical `NewsEvent` data and a historical `now`.**
Distinct from Amendment 1's rejected path (a): path (a) rejected
*reimplementing*/*reconstructing* blackout logic from already-bucketed,
present-tense snapshot fields; this candidate would instead *call the
same function Market Intelligence itself already uses*, with a past
`now`, requiring access to the underlying `NewsEvent` history rather
than derived buckets. This is architecturally different from (a) (reuse
vs. reimplementation) but independently discouraged by this Research
(§2's retention-caveat finding: `cache_max_entries=200`, a capacity-
bounded cache with no retention guarantee tied to in-flight ranges'
formation windows) and by a genuine sampling-gap risk (approximating
"at any point during formation" by checking discrete past cycles could
miss a blackout that both started and ended between two sampled
instants, whereas an accumulator recorded live every cycle as it
happens has no such gap). **Not adopted; recorded for completeness and
explicitly not recommended, given C's freedom from both of these
specific risks.**

### 5. Explicitly rejected: reconstructing blackout state in Strategy
Engine by duplicating Market Intelligence's arithmetic

This is not this Research's own finding — it is the Accepted ADR's own
settled position, re-quoted here in full because Research objective 5
requires it be explicitly addressed, not merely cross-referenced:

> reconstructing formation-time blackout status inside Strategy Engine
> from the current snapshot's `pair_safety.news.{active_events,
> recent_events,upcoming_events}` — rejected. **The load-bearing reason
> is an ownership-boundary violation, not a data-availability one:**
> doing this requires duplicating Market Intelligence's own
> blackout-window arithmetic... inside Strategy Engine, violating the
> "Market Intelligence owns event interpretation" ownership split this
> codebase already enforces elsewhere...

Candidate C (§4) does **not** violate this — it does not reimplement or
reconstruct MI's blackout-window arithmetic anywhere; it persists the
*already-computed, already-owned* `blackout_active` boolean MI itself
produces each cycle, exactly as `OrbQualificationStore` persists an
already-computed *qualification* fact rather than recomputing anything
strategy-owned logic depends on. This distinction — persisting an
upstream engine's own already-correct output vs. re-deriving that
output's logic locally — is the same distinction ADR-026 Hard Rule 5
and the existing structural-boundary tests already draw for every other
engine boundary in this codebase, re-applied here rather than invented.

### 6. Temporal semantics — ADR/source-derived, with explicit "not
specified" flags

- **Blackout at any instant during formation invalidates the range:**
  directly required by §2's own row text ("both during range formation
  and at breakout evaluation") — not an inference.
- **Blackout beginning/ending exactly at range boundaries
  (`range_start`/`range_end`):** **the Accepted ADR does not specify**
  whether a blackout active at the exact instant `now == range_start`
  or `now == range_end` counts as "during formation." No half-open vs.
  closed convention is stated for this specific fact (distinct from
  §3's own explicit half-open `[range_start, range_end)` convention for
  bar inclusion, which is unrelated to blackout timing). **Flagged as
  an open question for Plan, not invented here** (§9, item 4).
- **Blackout status unavailable or stale:** the ADR does not name a
  behavior for this fact specifically. Existing precedent elsewhere in
  this codebase (`ComplianceStateStore`'s `CorruptStateError`,
  `OrbQualificationStore`'s identical convention, ADR-035 §14's own
  general fail-closed principle) all point toward "treat unavailable/
  unreliable historical state as if blackout occurred" (fail closed) —
  but the ADR does not say this explicitly for this new fact, and
  **this Research does not decide it** (§9, item 5).
- **Reconnect/restart during formation:** requires restart persistence
  per §3 above; the ADR names this as the reason a persisted mechanism
  is one of its two candidate closures, but does not specify recovery
  semantics for a corrupt/missing record (fail-closed-and-block vs.
  fail-closed-and-treat-as-blacked-out are both defensible and distinct
  — **not specified, flagged for Plan**, §9 item 5).
- **Multiple simultaneous opening ranges/anchors:** §3's existing
  anchor-overlap validation (unchanged, Phase 0/5) already guarantees
  at most one range per `SessionName`/window is ever concurrently
  forming without overlap — the fact's own `(pair, range_start)` key
  (identical to the lockout's) already disambiguates multiple anchors
  correctly, since `range_start` is already the unique, collision-
  checked identity. No new multi-range handling appears to be required
  beyond reusing this existing key — **but this Research does not
  treat this as settled**, since it was not independently stress-tested
  against a concrete multi-anchor scenario this pass (flagged as a
  Plan-phase verification item, not a design question).

### 7. Discouraged approach detail (Candidate E, cache-eviction risk)

Re-stated from §4/§2 for visibility: `NewsIngestionConfig.cache_max_entries=200`
is a hard capacity bound with no retention tie to any in-flight opening
range's formation window. A design that relies on retroactively
re-querying historical `NewsEvent` data at evaluation time (rather than
recording the live, already-computed `blackout_active` value each
cycle) is exposed to silent data loss under high news volume, entirely
independent of whether the underlying `compute_blackout()` arithmetic
itself is reused correctly. This is a data-availability risk, not an
ownership-boundary one — orthogonal to, and additional to, §5's
rejection.

### 8. Architecture-boundary reassessment (summary; findings integrated
into §4 above per candidate)

- Evidence Engine depending on Market Intelligence data (not just
  types) would be a first-of-its-kind reversal of the only existing
  cross-engine dependency direction in this pair (MI → Evidence Engine,
  type-only) — a type-only dependency in the new direction is not
  obviously needed (no new Evidence Engine *type* appears necessary
  under any candidate examined); any dependency candidate B would
  introduce is a **data** dependency, the heavier kind.
- Strategy Engine depending on `strategy_state_store` for a second
  purpose (an accumulator alongside the existing qualification lockout)
  introduces no new structural-boundary consideration — already an
  allowed upstream import, already exercised for exactly this kind of
  persisted, restart-safe, per-`(pair, range_start)` fact.
- Runtime coordinating the fact directly (e.g., `RuntimeOrchestrator`
  itself observing `blackout_active` each cycle and passing a derived
  value into both Evidence Engine and Strategy Engine) was considered
  briefly: this would centralize the accumulation outside either
  engine, but requires Runtime (ADR-031, not ADR-035) to gain new,
  ADR-035-specific persisted state of its own — pushing a Strategy-
  Engine-specific concern into a shared orchestration layer that today
  holds no persisted state of this kind for any single strategy.  Not
  independently pursued further this pass; noted as a Runtime-adjacent
  alternative to candidate C's Strategy-Engine ownership, for the Plan
  phase to weigh if it wishes.
- A new persisted store (candidate C, or B if paired with one) does
  introduce a new state-store requirement, following exactly the
  `strategy_state_store`/`compliance_state_store` convention already
  established twice in this codebase — no new convention would need to
  be invented.
- No structural-boundary allowlist change is required under candidate
  C. Candidate B would require an explicit decision about
  `tests/titan_protocol/evidence_engine/test_architecture.py`'s
  currently-blocklist-only design (§2 finding).

### 9. Unresolved design questions for Plan finalization (not resolved here)

1. **Which candidate (B, C, or a hybrid) does the Plan adopt?** Not
   decided by this Research. Candidate C is the most directly
   evidence-grounded given current architecture (§4), but this Research
   does not choose it — the Plan phase must state and justify the
   choice explicitly, per this project's own established practice for
   exactly this kind of decision (e.g., Phase 5's Option A/B score-
   weight decision, Phase 6's registration-mechanism decision).
2. **If candidate C: does `OrbBreakoutStrategy.qualify()` already run
   every cycle during formation (before `is_formed` becomes `True`),
   or does something upstream (Runtime, the selection cascade) skip
   invoking it until formation completes?** This Research read
   `qualify()`'s own control flow (it does not early-return before the
   opening-range checks based on `is_formed` — the checks occur inside
   `qualify()` itself, meaning `qualify()` is invoked, and reaches the
   `pair_safety.news.blackout_active` gate) but did **not** trace
   whether `RuntimeOrchestrator`/`StrategyEngine.evaluate()` itself
   ever skips calling a given strategy's `qualify()` based on any
   pre-condition — this needs explicit confirmation before Plan can
   assume "every cycle" access to the live blackout flag during
   formation.
3. **If candidate B (or a hybrid needing it): does the Plan accept
   one-cycle staleness, or does it propose reordering Runtime's
   Evidence Engine / Market Intelligence call sequence?** The latter is
   a Runtime-engine (ADR-031) change outside ADR-035's own stated
   scope and this Research explicitly does not recommend it; if Plan
   still wants candidate B, it must address this directly rather than
   silently accept staleness or silently expand into Runtime's ADR.
4. **Half-open vs. closed boundary semantics for blackout-at-
   `range_start`/`range_end`.** Not specified by the ADR (§6). Plan must
   choose and justify, likely by analogy to §3's own `[range_start,
   range_end)` bar-inclusion convention, but this Research does not
   assume that analogy is correct without Plan-phase confirmation.
5. **Fail-closed policy for corrupt/missing/stale formation-blackout
   state.** Not specified by the ADR (§6). Strong existing precedent
   favors "treat as blacked-out" (maximally conservative, consistent
   with `CorruptStateError`'s existing fail-closed convention
   elsewhere) but this Research does not decide it.
6. **Exact schema/identity for the new persisted fact under candidate
   C** (e.g., a boolean per `(pair, range_start)` vs. richer metadata
   like the specific blackout reason/timestamp) — a minimal boolean
   satisfies the ADR's stated requirement; anything richer is scope the
   Plan must justify, not assume.
7. **Whether this new mechanism shares a file with `OrbQualificationStore`
   or is a wholly separate module/package** — Amendment 1 says "in
   convention analogous to," not "reusing the same store," and ADR-026
   Hard Rule 5 (an engine never reuses another engine's persisted
   store for an unrelated fact — re-confirmed as the same reasoning
   that originally justified `OrbQualificationStore` as its own package
   rather than folding into `compliance_state_store`) argues for a
   separate module even within the same owning engine, but this
   Research does not decide file boundaries.

### 10. Preservation constraints (verified unaffected by any candidate
examined; re-confirmed, not merely restated)

- Phase 2 breakout qualification/lockout, Phase 3 FVG score-only
  behavior, Phase 4 MI eligibility gates, Phase 5 config wiring, and
  Phase 6 conditional registration are all independent of which
  formation-time-blackout candidate is eventually chosen — none of the
  candidates examined touch `orb_breakout.py`'s existing breakout-
  distance/body-ratio/confirmation-candle/FVG logic, `selection.py`,
  `eligibility.py`, or any of the five legacy strategies.
- Evaluation-time blackout enforcement (`orb_breakout.py` line 87)
  remains unchanged and additive to whatever formation-time check
  Phase 7 adds — the ADR's own text is explicit that Phase 4's
  authorization "does not authorize omitting the evaluation-time check
  itself."
  `DEFAULT_APPROVED_PAIRS_BY_STRATEGY` and Phase 6's conditional
  registration (`build_default_registry(store)`) are untouched by every
  candidate examined — none require a pair-eligibility change.
- The Phase 5 anchor hour/minute range-validation residual risk is not
  referenced by, and has no relationship to, any candidate examined —
  confirmed out of scope, not folded in.

### 11. Preliminary file-impact categories (explicitly marked
not-yet-decided — no Plan-phase commitment implied)

Depending on which candidate the Plan phase adopts, the following
categories are *plausible*, not decided:

- **If candidate C:** a new module (likely a new file within
  `titan_protocol/strategy_state_store/` or a new sibling package),
  `titan_protocol/strategy_engine/strategies/orb_breakout.py` (a new
  read/write call site, and possibly a new constructor dependency
  analogous to `OrbQualificationStore`), `deployment_windows/start.py`
  (a second store construction, if a new file/package is chosen),
  new tests, and this Plan document. `titan_protocol/strategy_engine/config.py`
  is plausibly untouched (no new config field self-evidently required,
  though the Plan may find one needed for retention/lookback bounds).
- **If candidate B (data dependency):** `titan_protocol/evidence_engine/opening_range.py`
  and/or `models.py`, `titan_protocol/evidence_engine/engine.py`
  (a new input parameter), `titan_protocol/runtime/engine.py`
  (call-order and data-threading changes), `tests/titan_protocol/evidence_engine/test_architecture.py`
  (an explicit boundary decision), new tests, and this Plan document.
  Meaningfully larger and more cross-cutting than candidate C's
  category.
- **Never touched under any candidate examined:** any ADR file, any of
  the five legacy strategy files, `titan_protocol/strategy_engine/eligibility.py`,
  `titan_protocol/strategy_engine/selection.py`,
  `titan_protocol/strategy_engine/config.py`'s `DEFAULT_APPROVED_PAIRS_BY_STRATEGY`,
  `deployment_windows/install.py` (unless a new construction-only smoke
  check is deliberately extended, which no candidate here requires),
  the Phase 5 anchor-validation files.

### 12. Baseline validation results (freshly re-run this pass)

| Check | Result |
|---|---|
| `python3 -m compileall titan_protocol deployment_windows tests` | OK |
| `tests.titan_protocol.evidence_engine` (full discover) | 176/176 OK |
| `tests.titan_protocol.market_intelligence` (full discover) | 90/90 OK |
| `tests.titan_protocol.strategy_engine` (full discover) | 164/164 OK |
| `tests.titan_protocol.strategy_engine.test_architecture` + `tests.titan_protocol.evidence_engine.test_architecture` | 11/11 OK |
| `tests.titan_protocol.compliance_state_store.test_structural_boundary` + `tests.titan_protocol.news_ingestion.test_structural_boundary` | 10/10 OK |
| `tests/deployment_windows` (`-t .`) | 162/162 OK |
| Full `tests/titan_protocol` regression | 1391/1391 OK (one `OSError: simulated disk failure` traceback is expected fault-injection logging, not a failure) |
| `scripts/check_architecture.py` | PASS |
| `build_default_registry()` (no store) | 5 strategies, ORB absent — unchanged from Phase 6 |
| `build_default_registry(store)` | 6 strategies, ORB exactly once — unchanged from Phase 6 |

All baselines match the state independently confirmed by the Phase 6
conformance review; no drift since that review.

---

## Plan

*(Intentionally left empty — Research only, per this task's
authorization. §9's seven open questions must be explicitly resolved
here, with evidence, before Implement begins.)*

## Validation

*(Intentionally left empty — Research only.)*
