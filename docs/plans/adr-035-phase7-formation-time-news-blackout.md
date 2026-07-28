# Plan: ADR-035 Phase 7 — Formation-Time News-Blackout Closure

Status: **PLAN REVISED — READY FOR FOCUSED IMPLEMENTATION-READINESS
RE-REVIEW.** This revision resolves the two required findings from the
independent implementation-readiness review of Plan commit `34cbe5c`:
**F2 (algorithm-placement defect, now fixed):** the formation-blackout
observation loop is now specified to run immediately after
`check_eligibility()` and before the `market_closed`/`is_holiday`/
evaluation-time-blackout early-returns (§P4), so a genuine formation-
window blackout co-occurring with a market-closed or holiday cycle is
no longer silently unobserved. **F1 (reachability analysis, now
expanded):** §P3 now discloses **two independently verified default
gates**, not one — Gate A (`OPENING_RANGE_BREAKOUT` absent from
`DEFAULT_APPROVED_PAIRS_BY_STRATEGY`) and Gate B
(`EvidenceEngineConfig.opening_range_anchors` defaulting to `()`, the
shipped example config preserving that empty default) — and explicitly
analyzes and rejects relocating the observation point to Runtime or
Evidence Engine as a way to bypass ORB's eligibility gate. Candidate C
(a new, Strategy-Engine-owned, `OrbQualificationStore`-analogous
persisted store) remains selected and independently proven sufficient
(§P2), unchanged by either revision. Implementation is **not
authorized** by this revision — it requires its own focused
independent implementation-readiness re-review first.

Owner (Research phase): Software Architect (ADR-035/ADR-025/ADR-026
owner precedent, unchanged from Phases 0-6).
Owner (Plan phase): Software Architect (same precedent, unchanged).

Touched components (final, per §P12's file-impact matrix): a new
sibling module inside `titan_protocol/strategy_state_store/`,
`titan_protocol/strategy_engine/strategies/orb_breakout.py`,
`deployment_windows/start.py`, new tests, this Plan document. **Not in
scope:** any Evidence Engine or Market Intelligence file, `strategy_engine/config.py`'s
`DEFAULT_APPROVED_PAIRS_BY_STRATEGY`, the existing `OrbQualificationStore`
files, `install.py`, any ADR, the five legacy strategy files, and the
separate Phase 5 anchor hour/minute validation follow-up.

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

**Status of this section: FINALIZED.** Resolves all seven Research-phase
open questions with direct repository evidence, plus the additional
reachability/persistence/identity questions this Plan-finalization task
itself raised. One finding below is disclosed prominently, not hidden,
and its disposition impact is stated explicitly rather than assumed
(§P3).

### P0. Owner and scope

Owner (Plan phase): Software Architect (ADR-035/ADR-025/ADR-026/ADR-031
owner precedent, unchanged). Touched components (final, per §P12):
`titan_protocol/strategy_state_store/` (one new sibling module),
`titan_protocol/strategy_engine/strategies/orb_breakout.py`,
`deployment_windows/start.py`, new tests, this Plan document. No ADR
file, no Phase 5 anchor-validation file, no legacy strategy file.

### P1. Governing contract (re-derived directly, §1 of Research
re-confirmed, not re-litigated)

ADR-035 §2's "News restrictions" row requires ORB `NOT_QUALIFIED` on
blackout "both during range formation and at breakout evaluation."
Amendment 1 authorized Phase 4's evaluation-time-only enforcement as a
**staged limitation**, explicit that this "does not authorize omitting
the evaluation-time check itself." Phase 7 must therefore **add** a
formation-time check **without removing, weakening, or restructuring**
the existing evaluation-time check (`orb_breakout.py` line 87,
unchanged since Phase 4). The two checks test **different temporal
conditions** — "is blackout active right now" (unchanged, evaluation-
time) vs. "was blackout ever active at any point during this specific
range's own formation" (new, formation-time) — and both must
independently gate `QUALIFIED`.

### P2. Architecture/design decision — Candidate C selected, proven, not assumed

Research (§4) identified five candidates. This Plan independently
re-derives, rather than assumes, that Candidate C — a new,
Strategy-Engine-owned, `OrbQualificationStore`-analogous persisted
store — is sufficient and correct, by proving each element Research
flagged as unproven:

1. **Does the chosen owner (Strategy Engine, via `OrbBreakoutStrategy.qualify()`)
   receive the necessary information at the necessary time?** Re-read
   `qualify()` in full this pass. The existing evaluation-time blackout
   check (`if pair_safety.news.blackout_active: return _not_qualified(...)`,
   line 87) executes **before** `evidence.opening_ranges` is even
   inspected — it is unconditional on formation state. This means
   `qualify()` already reads the live, current-cycle
   `pair_safety.news.blackout_active` value on **every cycle it runs**,
   whether or not any range has finished forming yet. The information
   Candidate C needs is therefore already present, at the exact point
   Candidate C needs it, with **zero new dependency** — the new
   mechanism reads the same field the existing check already reads,
   once more, for a different purpose. No duplication of Market
   Intelligence's blackout-window arithmetic occurs, since nothing
   re-derives `blackout_active` — it is read, not recomputed, exactly
   the same distinction Research's §5 already established as the
   dispositive one.
2. **Does `evidence.opening_ranges` expose still-forming ranges, not
   only the formed one `qualify()` currently uses for breakout logic?**
   Re-read `compute_opening_ranges()`/`_compute_single_range()`
   (`opening_range.py`) directly this pass: a range is included in the
   returned tuple as soon as `bars[-1].timestamp >= range_start` — its
   own `is_formed` field (`now >= range_end`) is computed independently
   and does **not** gate whether the state appears in
   `evidence.opening_ranges` at all. **Confirmed: still-forming ranges
   (`is_formed=False`) are already present in `evidence.opening_ranges`
   every cycle**, alongside any already-formed one. `qualify()`'s
   current code only ever filters to `formed_ranges = [r for r in
   opening_ranges if r.is_formed]` for its *breakout* logic — it never
   currently inspects the still-forming entries at all. Candidate C
   requires a **new** loop, in addition to the existing `formed_ranges`
   filter, over the still-forming entries — a genuine, disclosed
   implementation addition (§P4), not something "free."
3. **Can the owner persist the fact without duplicating MI's
   interpretation?** Yes — per (1), it persists the *already-computed*
   boolean, never re-deriving it, exactly the same non-duplication
   argument the Accepted ADR itself already uses to distinguish
   `OrbQualificationStore`'s own precedent from a forbidden
   reimplementation (Research §5, re-affirmed, not reopened).

**Conclusion: Candidate C is proven sufficient and architecturally
correct under the current runtime/data flow — a new dependency is not
required, and the information timing genuinely lines up**, contingent
on the reachability finding in §P3 immediately below, which this Plan
treats as a disclosed consequence, not a design defect.

### P3. Critical reachability question — resolved, with a disclosed, non-blocking consequence

**Direct trace, this pass, of the real production path:**
- `StrategyEngine.evaluate()` (`engine.py`, unchanged, re-read this
  pass) calls `strategy.qualify(...)` for **every** strategy in
  `self.registry.all()`, unconditionally — the engine itself never
  skips a strategy based on eligibility; eligibility is checked
  *inside* each strategy's own `qualify()`.
- `deployment_windows/start.py` (Phase 6, unchanged, re-confirmed empty
  diff since `2e4803c`) unconditionally constructs
  `build_default_registry(orb_qualification_store)` and passes the
  resulting **six-strategy** registry into the real `StrategyEngine` —
  ORB **is** registered, and its `qualify()` **is** invoked every cycle
  for every pair the live-cycle loop evaluates.
- `OrbBreakoutStrategy.qualify()`'s **first** action is
  `check_eligibility(StrategyId.OPENING_RANGE_BREAKOUT, pair, config)`
  (line 78, unchanged). `DEFAULT_APPROVED_PAIRS_BY_STRATEGY`
  (`strategy_engine/config.py`, re-confirmed empty diff since Phase 6,
  no ORB entry) makes `approved_pairs_for(OPENING_RANGE_BREAKOUT)`
  return `()` for every pair, so `check_eligibility()` returns
  `NOT_ELIGIBLE` **unconditionally, for every pair, every cycle**, and
  `qualify()` returns at line 80 — **before** reaching the blackout
  check, before reaching `evidence.opening_ranges` at all. This is
  **Gate A**.

**Gate B (newly added this revision, independently verified, compounds
Gate A):** even setting Gate A aside entirely — e.g. imagining a
hypothetical future world where `OPENING_RANGE_BREAKOUT` were pair-
eligible — a **second, fully independent** default gate would still
block any live opening range from existing at all:
- `titan_protocol/evidence_engine/config.py`, re-read directly this
  pass: `EvidenceEngineConfig.opening_range_anchors: Tuple[Tuple[SessionName,
  int, int], ...] = ()` — the field defaults to an **empty tuple**, not
  merely unset.
- `compute_opening_ranges()` (`opening_range.py`, re-read directly,
  §2/§P2 above) iterates `config.opening_range_anchors` to produce
  `evidence.opening_ranges` — an empty anchor tuple means the loop body
  never executes, so `evidence.opening_ranges` is `()` for every pair,
  every cycle, regardless of ORB's own eligibility status.
- `deployment_windows/config/titan_protocol_config.example.json`,
  re-read directly this pass, line 77: `"opening_range_anchors": []` —
  the **shipped example deployment configuration preserves the empty
  default** rather than populating it. The file's own adjacent `_note`
  (line 76) already documents this: opening ranges are "inert (fails
  closed) until an operator configures at least one anchor."
- **Consequence:** even if Gate A were separately, independently lifted
  by some future authorized decision, `OrbBreakoutStrategy.qualify()`
  would still return `_not_qualified(pair, "No opening range configured
  for this evaluation cycle")` (line 100) for every pair, every cycle,
  under the shipped default configuration — and, load-bearing for
  Phase 7 specifically, the new formation-blackout accumulation loop
  (§P4) iterates exactly this same, empty `evidence.opening_ranges`
  tuple, so it has **nothing to iterate over and observes nothing**,
  independently of Gate A.

**Finding, stated precisely and without softening:** under the current,
unchanged, already-Accepted production defaults, `qualify()` **never**
reaches the point where it could observe
`pair_safety.news.blackout_active` during formation, for any pair, in
the real running system, today — for **two independent reasons**, not
one: Gate A (pair ineligibility, blocks before `evidence.opening_ranges`
is even read) and Gate B (empty anchor configuration, blocks
`evidence.opening_ranges` from ever being non-empty regardless of
eligibility). This is not unique to Phase 7 — it is already true of the
**existing, already-accepted** evaluation-time check (Phase 4), of
breakout-distance/body-ratio/FVG/lockout logic (Phase 2/3), and of
Phase 6's own registration itself. Phase 6's own Plan and its
independent implementation-readiness review both already stated this
explicitly and in identical terms: *"registration alone creates no live
ORB trading impact... until pair-eligibility is separately and
explicitly authorized by a future phase."* Gate B was not named by
Phase 6's own disclosure (Phase 6 concerned registration, not anchor
configuration) and is disclosed here for the first time, as an
independent, compounding fact, not a restatement of Gate A.

**Rejected alternative: relocating formation-blackout observation to
Runtime or Evidence Engine, specifically to bypass ORB's eligibility
gate.** Considered explicitly this revision, in direct response to the
independent review's challenge, and rejected for four concrete reasons:
1. **Gate B blocks it regardless of where observation happens.** Moving
   the observation point out of `OrbBreakoutStrategy.qualify()` and
   into Runtime or Evidence Engine does not change the fact that
   `evidence.opening_ranges` is itself empty under the shipped
   `opening_range_anchors: []` default — there is no opening-range
   state of any kind, still-forming or formed, for any relocated
   observer to observe. Relocation solves nothing about Gate B, since
   Gate B is a property of the anchor configuration, not of which
   component happens to read `evidence.opening_ranges`.
2. **Enforcement must ultimately occur in ORB qualification, which
   remains eligibility-gated regardless of where observation happens.**
   Even if some other component (Runtime, Evidence Engine) observed and
   persisted the fact independently, the fact is only ever *consulted*
   by `OrbBreakoutStrategy.qualify()` at evaluation time (§P1/§P4) — and
   that call site is, and must remain, downstream of
   `check_eligibility()` (§1.10/§14 of the Accepted ADR; eligibility is
   the absolute first gate for every strategy, not negotiable per
   strategy). Relocating *observation* earlier in the pipeline does not
   and cannot relocate *enforcement* earlier than eligibility — it would
   only add a second place the same Gate-A-gated dormancy shows up.
3. **Relocation would create additional ownership/dependency/state
   complexity without making the production-default ORB path
   operational.** Moving observation to Evidence Engine would require
   Evidence Engine to gain a new, persistent, cross-cycle memory it does
   not have today (§2/Research, re-affirmed, unaffected by this
   revision) purely to observe a fact that — per points 1 and 2 above —
   still could not become operationally meaningful under current
   defaults. Moving observation to Runtime would require Runtime
   (ADR-031, not ADR-035) to gain new ADR-035-specific persisted state
   of its own (Research §8, re-affirmed) for the same non-benefit. Both
   would be strictly more invasive than Candidate C for zero gain in
   production reachability.
4. **Changing pair eligibility or anchor defaults is a separate
   governance decision, not authorized by Phase 7.** The only way to
   make either gate's dormancy operationally live is to change
   `DEFAULT_APPROVED_PAIRS_BY_STRATEGY` (Gate A) and/or
   `opening_range_anchors`'s configured value (Gate B) — both explicitly
   out of this Plan's authorized scope (§P0, §P9, §P12), and neither
   ADR-035 nor Amendment 1 authorizes Phase 7 to make either change.
   Relocating observation could never substitute for that separate,
   unauthorized decision; it would only obscure that the real blocker is
   configuration, not architecture.

**Disposition of this finding — reasoned, not assumed:**
- This Plan does **not** treat either gate as a blocker to Phase 7's own
  finalization, for four concrete reasons, extended to cover both gates:
  (a) neither is introduced by Phase 7 and neither is a defect in Phase
  7's own design — both are pre-existing, already-accepted (Gate A) or
  independently-verified-and-newly-disclosed-but-still-pre-existing
  (Gate B) characteristics of the whole ORB strategy's current
  deployment state, unrelated to which specific gate is under
  discussion; (b) ADR-035/Amendment 1 nowhere authorizes or requires
  Phase 7 to also resolve pair eligibility or anchor configuration —
  doing so would be scope creep this Plan is instructed not to commit,
  and the task instructions explicitly forbid changing either default
  without independent ADR authorization, which does not exist for
  either; (c) blocking Phase 7 specifically on these pre-existing facts
  would be inconsistent with this project's own established precedent —
  Phases 2 through 6 were each individually Planned, Implemented, and
  independently Accepted despite being equally inert under the same
  pair-eligibility default throughout, and Gate B is simply a second,
  equally pre-existing instance of the same class of dormancy; (d) the
  *safety* consequence Amendment 1 worried about (a stale
  evaluation-time-only check permitting an unsafe `QUALIFIED` result)
  **cannot currently occur in the live system at all**, since ORB
  cannot produce a live `QUALIFIED` result of any kind today under
  either gate individually, let alone both — the residual exposure
  Amendment 1 named is itself currently dormant, which is a reassuring
  fact, not a reason to leave the gap permanently unclosed.
- This Plan **does** treat this as a **named, tracked, capital-relevant
  dependency that must be surfaced to every future reader**, not
  silently absorbed: Phase 7's mechanism, once implemented, has **zero
  live effect until two separate, still-unscheduled future governance
  decisions both occur** — `OPENING_RANGE_BREAKOUT` being made
  pair-eligible (Gate A), and an operator configuring at least one
  `opening_range_anchors` entry (Gate B) — at which point Phase 7's
  closure becomes load-bearing for the first time. **Phase 7 therefore
  installs a correctly designed but currently dormant formation-
  blackout mechanism under current production defaults** — this exact
  framing is recorded as **Finding F1** in §P14's adversarial review and
  is repeated in this Plan's own final disposition text (§P16), not
  left to be discovered only by inspecting test code or configuration.
- **Verification strategy given this constraint:** every test proving
  the mechanism's *logic* is correct must use the same test-only
  eligibility override mechanism Phase 6 established and had
  independently accepted for exactly this reason, **plus an explicit
  test-only `opening_range_anchors` configuration** (since Gate B is
  independent of Gate A and neither override alone is sufficient) —
  proving the mechanism will function correctly *once both gates are
  separately, independently lifted*, since production reachability
  cannot itself be demonstrated while either production default remains
  unchanged. No test may claim to prove *live* reachability under
  current defaults; this Plan does not permit that claim to be made
  (§P10 sharpens this distinction explicitly).

**This is not marked "PHASE 7 PLAN BLOCKED"** — see §P16 for the
reasoning restated at the point of final disposition.

### P4. Runtime ordering and exact mechanism specification

Current cycle order (`runtime/engine.py`, re-confirmed unchanged):
`evidence = evidence_engine.evaluate_snapshot(...)` →
`market_intelligence = market_intelligence_engine.evaluate(...)` →
`strategy = strategy_engine.evaluate(pair, evidence, market_intelligence, now)`.
Unchanged by this Plan.

**Exact mechanism:**
- **Origin:** `pair_safety.news.blackout_active`, produced by Market
  Intelligence's existing `compute_blackout()` (unchanged,
  `market_intelligence/news.py`), exactly the same field the existing
  evaluation-time check already reads.
- **Availability:** every cycle, the instant `StrategyEngine.evaluate()`
  is called with that cycle's `market_intelligence` snapshot — no
  timing change from today.
- **Observer:** `OrbBreakoutStrategy.qualify()`, the same and only
  component that already observes it today.
- **When the monotonic fact is updated (corrected this revision — see
  Finding F2):** the Plan finalized at commit `34cbe5c` specified this
  loop as running immediately *after* the existing evaluation-time
  blackout check (line 87). The independent implementation-readiness
  review correctly identified this as defective: `market_closed`
  (line 83) and `is_holiday` (line 85) both `return` **before** line
  87 is ever reached, so on any cycle where the market is closed or a
  holiday is in effect, the accumulation loop would never run at
  all — silently missing a genuine formation-window blackout that
  happened to coincide with a market-closed or holiday cycle. This
  Plan now specifies the loop's insertion point as **immediately after
  `check_eligibility()` and before `market_closed`** — i.e., the new
  first statement of the eligibility-cleared branch, strictly before
  every one of `market_closed`, `is_holiday`, the existing
  evaluation-time blackout check, and the spread/liquidity/
  range-selection/breakout logic that follows. Eligibility itself
  remains the absolute first gate (ADR-035 §14; unmoved, unmodified) —
  this revision does not and must not place formation-blackout
  observation before `check_eligibility()`. The existing
  evaluation-time blackout check (line 87) itself is **not modified**
  by this change — it keeps its own position and behavior exactly as
  today; only the new accumulation loop moves earlier, ahead of it and
  ahead of `market_closed`/`is_holiday`:
  ```python
  ineligible = check_eligibility(StrategyId.OPENING_RANGE_BREAKOUT, pair, config)
  if ineligible is not None:
      return ineligible

  pair_safety = market_intelligence.pair_safety
  for r in evidence.opening_ranges:
      if not r.is_formed:
          formation_blackout_store.record_cycle_observation(
              pair, r.range_start, pair_safety.news.blackout_active,
          )

  if pair_safety.market_safety.market_closed:
      return _not_qualified(pair, "Market closed")
  if pair_safety.market_safety.is_holiday:
      return _not_qualified(pair, "Holiday")
  if pair_safety.news.blackout_active:
      return _not_qualified(pair, "News blackout active")
  ...
  ```
  Iterates every still-forming range this cycle (not only the
  eventually-relevant one), recording this cycle's already-computed
  `blackout_active` boolean under each range's own `(pair, range_start)`
  key — now observed **unconditionally on every cycle that clears
  eligibility**, regardless of `market_closed`/`is_holiday`/
  evaluation-time-blackout state, so a genuine formation-window
  blackout is recorded even when it co-occurs with a market-closed or
  holiday cycle. `record_cycle_observation()` is idempotent-OR: it only
  ever transitions a key from "not observed" to "observed," never the
  reverse (§P6). **Downstream qualification is unaffected by this
  reordering:** a cycle where `market_closed`/`is_holiday` is `True`
  still returns `NOT_QUALIFIED` via those existing, unmoved gates
  immediately afterward — moving the observation loop earlier changes
  only *what gets recorded*, never *what gets qualified* on that cycle.
- **When it is read at breakout evaluation:** once `opening_range` (the
  `currently_relevant`, `is_formed=True` range) is resolved — i.e.,
  immediately after the existing `if not opening_range.is_valid:` check
  and before the ATR/breakout-distance logic — a new gate:
  ```python
  if formation_blackout_store.was_blackout_observed(pair, opening_range.range_start):
      return _not_qualified(pair, "News blackout observed during range formation")
  ```
- **Across restart:** per §P7, the store reloads its persisted
  `(pair, range_start) -> bool` map at construction; a range whose
  formation began before the restart continues to accumulate
  observations from its remaining, post-restart formation cycles into
  the same key.

No duplication of Market Intelligence's blackout-window arithmetic
occurs anywhere in this design — confirmed directly by inspection: the
new code only ever reads `pair_safety.news.blackout_active`, already
computed by Market Intelligence, never recomputing anything from raw
`NewsEvent` data.

### P5. Temporal semantics — resolved where evidence permits, flagged where it does not

**Re-verified this revision against the corrected §P4 insertion point
(Finding F2 fix):** moving the write-side accumulation loop earlier —
from "after the existing evaluation-time blackout check" to
"immediately after `check_eligibility()`, before `market_closed`" —
does not change any of the boundary semantics stated below; it only
changes *which cycles* the loop runs on. Every example in this section
was re-checked against the corrected ordering and requires no
restatement of its own conclusion, with one addition made explicit for
the first time this revision (the `market_closed`/`is_holiday`
co-occurrence case, new bullet below):

- **Formation blackout co-occurring with `market_closed=True` or
  `is_holiday=True` (new this revision, the exact scenario Finding F2
  concerned):** under the corrected insertion point, the accumulation
  loop runs *before* the `market_closed`/`is_holiday` checks, so a
  cycle where `pair_safety.news.blackout_active` is `True` **and**
  `market_closed`/`is_holiday` is also `True` still records the
  formation-blackout observation for every still-forming range that
  cycle. The cycle's own qualification outcome is unaffected — it still
  returns `NOT_QUALIFIED` via the existing, unmoved `market_closed`/
  `is_holiday` gates immediately afterward, exactly as it would without
  Phase 7 present. A later, market-open, non-holiday, blackout-clear
  cycle does not erase the earlier observation (§P6's monotonicity
  contract, unaffected by the reordering). This scenario is explicitly
  covered by new test rows in §P10.
- **Formation interval:** `[range_start, range_end)`, adopting the same
  half-open convention §3 already establishes for bar inclusion, for
  consistency. **Disclosed as this Plan's own reasoned choice, not an
  ADR-mandated one** — the Accepted ADR text does not itself specify
  this boundary (Research §6 finding, re-affirmed). The independent
  Plan review should scrutinize this choice specifically.
- **Blackout at `range_start` (`now == range_start`):** counted (start
  of the half-open window).
- **Blackout immediately before `range_start`:** not applicable — no
  accumulation occurs before a range appears in `evidence.opening_ranges`
  at all (Evidence Engine's own existing inclusion rule, unchanged).
- **Blackout during formation:** the core case; recorded every cycle
  per §P4.
- **Blackout exactly at `range_end`:** **not** counted by the formation
  accumulator under the half-open convention chosen above — but this
  creates no coverage gap: the very next cycle (the first at which
  `is_formed` can become `True`) is still covered by the **unchanged,
  existing evaluation-time check**, which independently re-evaluates
  `blackout_active` fresh every cycle `qualify()` runs, including this
  one. No instant in time is left ungated by *both* checks.
- **Blackout after `range_end` but before breakout-candidate
  evaluation:** already fully covered today, **without any Phase 7
  change** — re-confirmed this pass: the existing evaluation-time check
  re-runs on *every* cycle `qualify()` executes, including every cycle
  during the post-range-bar-window search, not merely the single cycle
  a candidate happens to qualify on. Amendment 1's own "residual
  exposure" language concerns specifically a blackout that both started
  *and cleared* before evaluation — i.e., a formation-window event — not
  this post-range window, which was never actually exposed.
- **Evaluation-time blackout:** unchanged, still gates independently
  (§P1).
- **Multiple simultaneous opening ranges/anchors:** handled by the
  `(pair, range_start)` key (§P6) — one accumulator entry per anchor,
  identical disambiguation to the existing lockout's own proven
  identity.
- **Reconnect/restart during formation:** handled by persistence
  (§P7), subject to the narrow, disclosed residual risk analyzed there.

### P6. State identity and monotonicity

**Key: `(pair, range_start)`** — identical to `OrbQualificationStore`'s
own existing key, and identical to `OpeningRangeState`'s own documented
identity ("the identifying key is this instance's own `range_start`/
`range_end` window, never `session` alone," `models.py` line 363-364,
re-confirmed this pass). `range_end`/session identity is **not**
required in the key: `range_start` alone is already the unique,
collision-checked identity the existing anchor-overlap validation
guarantees (Evidence Engine, unchanged, Phase 0/5) — re-deriving a
compound key would be redundant, not more correct.

**Monotonicity contract:** once `(pair, range_start)` has been recorded
as `blackout_active=True` for any cycle, it must never be cleared by a
later cycle observing `blackout_active=False` for the same key.
`record_cycle_observation()`'s contract is therefore: `new_value =
old_value or this_cycle_value` — an OR-accumulate, never an overwrite.

**Cleanup/retention:** not required for Phase 7 correctness. This
mirrors `OrbQualificationStore`'s own existing, accepted characteristic
(unbounded growth, one entry per `(pair, range_start)` ever observed,
never pruned) — a pre-existing, already-accepted property of this
precedent this Plan does not need to newly address, and does not
invent new pruning logic beyond what the existing precedent already
lives with.

### P7. Persistence/failure semantics — analyzed explicitly, not copied automatically

**Restart persistence is mandatory** — a formation window spans ~120
cycles (30-minute default duration ÷ 15-second cycle interval); losing
all prior observations on every restart would defeat the entire
purpose of Phase 7.

**State-file ownership/location:** a **new**, Strategy-Engine-owned
file, sibling to (not merged with) `orb_qualifications.json` — see
§P8 for why a separate file/class, not an extension of
`OrbQualificationStore`, is the correct choice. Constructed in
`deployment_windows/start.py` at `settings.state_dir /
"orb_formation_blackout.json"`, following the identical
`settings.state_dir`-relative convention already established twice
(`compliance_state.json`, `orb_qualifications.json`).

**Startup loading:** mirrors `OrbQualificationStore._load_initial()`
exactly — missing file → empty map (a genuinely correct initial state,
not a guess: nothing has been observed yet); corrupt/unreadable file
(with no usable `.bak`) → raise a `CorruptStateError`-equivalent,
**uncaught** in `start.py`, crashing startup — identical fail-closed
precedent to both existing stores.

**Persistence failure behavior — the specific question this task asks
to analyze, not assume:** should a mid-run persist failure be
contained (logged, in-memory value stands, matching
`OrbQualificationStore`) or should it be treated more strictly, given
this fact's capital-preservation relevance?

*Analysis:* the risk pattern is structurally the same class of risk
`OrbQualificationStore` already accepts for the lockout count — a
persist failure followed by a restart before any subsequent successful
persist could lose an observation. However, two properties make this
*specific* new fact's exposure **narrower**, not wider, than the
lockout count's own already-accepted exposure:
1. The lockout count is written **once**, at the single terminal moment
   a qualification is consumed — if that one write is lost, there is no
   second chance to record it. The formation-blackout fact is written
   **every cycle throughout an ongoing, multi-cycle formation window**
   (~120 opportunities) — a lost write on one cycle does not lose the
   fact if blackout is *still* active on the next cycle (which
   `record_cycle_observation()` will observe and correctly persist
   then). The **only** way this fact is truly lost is if a blackout
   both started and fully cleared within the single narrow gap between
   one failed persist and the next successful one, immediately followed
   by a restart before any intervening successful write — a materially
   narrower window than the lockout count's own single-shot exposure.
2. A blocking/retry-until-success alternative was considered and
   **rejected**: this codebase's own established fault-containment
   doctrine (`_safe_log_exception()`'s "a diagnostic must never crash
   the live-cycle loop" precedent, `deployment_windows/start.py`)
   argues strongly against introducing a new I/O-blocking or
   retry-loop inside the live-cycle path merely to strengthen a
   narrower-than-existing residual risk — doing so would trade a small,
   already-precedented persistence gap for a new, unprecedented
   live-cycle-stall risk, which is a worse trade for capital
   preservation overall (a stalled cycle blocks *every* strategy's
   evaluation for that pair, not only ORB's).

**Conclusion: mirror `OrbQualificationStore`'s exact containment
pattern** (persist failures caught/logged internally, in-memory value
authoritative for the process's own lifetime, never escaping into
`qualify()`) — **with this reasoning explicitly disclosed**, per the
task's own instruction not to copy it silently. No stricter persistence
contract is adopted; none is warranted by the analysis above.

**"Failure to persist a newly observed blackout may permit unsafe
qualification after restart":** possible, in the narrow window
described in point 1 above — an already-known, already-accepted class
of exposure this codebase already lives with for the lockout count,
now shown to apply more narrowly here. Not eliminated; bounded and
disclosed, consistent with this project's own established
capital-preservation posture of disclosing rather than silently
eliminating every conceivable residual risk at the cost of introducing
new ones.

### P8. Interaction with the existing lockout store — separate module, same package, decided and grounded

**Decision: a new, separate class/module within
`titan_protocol/strategy_state_store/` (already an allowed Strategy
Engine upstream import, §2 of Research, re-confirmed unaffected) —
neither extending `OrbQualificationStore` nor merging into a single
shared file.**

*Grounding:*
- **Different write contract.** `OrbQualificationStore.try_consume()`
  is deliberately a single atomic "read-count, compare-to-max,
  increment-if-allowed" gate — its own docstring states it is
  "deliberately never split into a `get_count()`/`increment()` pair,
  since that would reintroduce exactly the race this design must
  prevent." The new fact's write contract is structurally different:
  an idempotent, unconditional OR-accumulate with no comparison, no
  gating, no return value consulted for a pass/fail decision. Folding
  both contracts into one class would blur two genuinely different
  concurrency/write shapes into one API, the opposite of "never split
  into a get/increment pair" — it would be splitting an already-correct
  single-purpose contract to accommodate an unrelated one.
- **Different read/consumption semantics.** The lockout count is
  consumed (mutated) as the qualification's own terminal, one-time,
  side-effecting gate. The formation-blackout fact is written every
  cycle throughout formation and read (without mutation) once at
  evaluation — a materially different lifecycle.
- **No dual-authority risk.** `OrbQualificationStore` remains the sole
  authority for "how many times has this range already qualified"
  (completely unchanged). The new store becomes the sole, new authority
  for "was blackout ever observed during this range's formation" — the
  two facts are genuinely disjoint; no design decision here creates two
  competing sources of truth for the same question.
- **Consistent with Amendment 1's own wording** — "in convention
  analogous to `OrbQualificationStore`," not "reusing" it — and with
  ADR-026 Hard Rule 5's established precedent (re-applied at
  sub-engine granularity, as Research already flagged) that a genuinely
  distinct fact gets its own module even when the same engine owns
  both.

### P9. Pair eligibility — unchanged; production functioning explained precisely

`DEFAULT_APPROVED_PAIRS_BY_STRATEGY` is **not modified** by this Plan —
no ADR text authorizes it, and none of Candidate C's requirements need
it changed to be correctly *implemented and tested*. Per §P3 (Gate A):
**the mechanism cannot and does not need to function live in
production today**, because no ORB logic of any kind currently does,
under the same, already-accepted default. `opening_range_anchors` is
similarly **not modified** by this Plan — per §P3 (Gate B, expanded
this revision), the shipped empty-anchor default independently blocks
any opening range from existing at all, regardless of ORB's pair
eligibility. Both gates, and the explicit rejection of relocating
observation to bypass either, are disclosed together as **Finding F1**
(§P3, §P14), not silently assumed away, and are **not** treated as a
blocker to Plan finalization, per the reasoning in §P3. Two separate,
future, separately-scoped, separately-authorized decisions — granting
ORB pair eligibility (Gate A) and configuring at least one opening-range
anchor (Gate B) — are jointly the point at which Phase 7's closure —
already correctly implemented and tested by then — becomes live, with
no further ORB-side code change required at that time.

### P10. Test contract

All tests use the real `build_default_registry(store)` factory and the
real `StrategyEngine` — never a hand-assembled registry (established
precedent, Phase 6, re-applied).

**Category A vs. Category B, stated explicitly (sharpened this
revision, per the independent review's instruction that no test-only
configuration may be described as proof of production-default
operability):**
- **Category A — test-only-configuration tests.** These use both the
  test-only eligibility override Phase 6 established
  (`make_config(approved_pairs_by_strategy=DEFAULT_APPROVED_PAIRS_BY_STRATEGY
  + ((StrategyId.OPENING_RANGE_BREAKOUT, ("EURUSD",)),))`, lifting Gate
  A) **and** an explicit test-only `opening_range_anchors` configuration
  (lifting Gate B) — neither of which mutates the production constants,
  both scoped to the individual test's own local `config`/
  `EvidenceEngineConfig` object. Every row below marked "Category A"
  proves the mechanism's *logic* is correct **once both gates are
  independently, explicitly lifted for that test only** — it proves
  **testability under explicit test configuration**, never production
  reachability. No Category A test result may be cited, in this Plan,
  in Implement, or in any later review, as evidence that the mechanism
  operates under production defaults — the two are different claims and
  must never be conflated.
- **Category B — production-default tests.** These use the unmodified
  `DEFAULT_APPROVED_PAIRS_BY_STRATEGY` and the unmodified (empty)
  `opening_range_anchors` default, proving the mechanism's **current
  operational dormancy** (Finding F1) is real and unaffected by Phase
  7's addition — mirroring Phase 6's own
  `TestProductionEligibilityUnderDefaultPolicy` precedent, now covering
  both gates.

| Required case | Category | Proves |
|---|---|---|
| No blackout during formation + no evaluation blackout | A | `QUALIFIED` reachable when both checks are clean (baseline) |
| Blackout at evaluation only (never during formation) | A | Existing evaluation-time check alone still gates — unchanged Phase 4 behavior preserved |
| Blackout during formation, cleared by evaluation time | A | **The exact gap Phase 7 closes** — must now be `NOT_QUALIFIED`, where pre-Phase-7 behavior would have been `QUALIFIED` |
| Formation blackout active while `market_closed=True` (new this revision, Finding F2) | A | Observation is still recorded even though the cycle's own qualification is rejected via the existing, unmoved `market_closed` gate — corrected §P4 insertion point verified directly |
| Formation blackout active while `is_holiday=True` (new this revision, Finding F2) | A | Same as above, for the `is_holiday` gate — observation recorded, qualification still rejected via the existing, unmoved `is_holiday` gate |
| A later clear (non-blackout) cycle, following either of the two rows above, does not erase the earlier fact (new this revision) | A | Monotonicity holds across the market-closed/holiday co-occurrence case specifically, not only the generic case below |
| Downstream qualification on a market-closed or holiday cycle remains rejected per the existing `market_closed`/`is_holiday` gates, with or without a formation-blackout fact present (new this revision) | A | The §P4 reordering changes only what is *recorded*, never what is *qualified* — no behavioral regression introduced by moving the observation loop earlier |
| Blackout observed once, then clear for many subsequent cycles | A | Monotonicity (general case) — the fact does not clear itself |
| Restart after a formation-blackout observation, same range still forming or now formed | A | Persistence — fresh store/registry/engine objects reading the same file, mirroring Phase 6's own restart-test pattern |
| Restart during a clean (no-blackout) formation | A | Restart does not fabricate a false-positive |
| Two simultaneous anchors/ranges, blackout during only one | A | `(pair, range_start)` key isolation — no cross-range contamination |
| Same pair, two sequential (non-overlapping) range_starts, one blacked-out, one clean | A | Range-identity isolation for the same pair over time |
| Persistence (write) failure during formation, mid-cycle | A | Containment — mirrors Phase 6's `TestPersistFailureContainment`, applied to the new store |
| Corrupt persisted state at startup | A | Fail-closed construction — mirrors Phase 6's `TestStartupCorruptState` |
| Boundary: blackout observed exactly at `range_start` | A | Half-open convention (§P5) — counted |
| Boundary: blackout observed exactly at `range_end` | A | Half-open convention (§P5) — not counted by the accumulator, but still caught by the unchanged evaluation-time check on the next cycle (assert both facts together) |
| Existing lockout (`OrbQualificationStore`) still gates independently, unaffected by the new store's presence | A | Two-store non-interference — no dual-authority regression |
| Production-default eligibility unaffected by the new mechanism's presence (Gate A) | **B** | Mirrors Phase 6's own dedicated proof; using the override here would defeat this test's purpose |
| Production-default anchor configuration unaffected by the new mechanism's presence, `evidence.opening_ranges` remains empty and the formation-blackout loop observes nothing (Gate B, new this revision) | **B** | Confirms Gate B's dormancy directly, not merely by cross-reference to Gate A — closes the gap the independent review identified in the prior revision's reachability disclosure |

Additionally, per Phase 6's own established regression-proof pattern:
one test compares a five-strategy vs. six-strategy (with the new store
wired) registry's evaluation of the **five legacy strategies**, proving
their results are byte-identical regardless of the new mechanism's
presence — extending, not duplicating, Phase 6's own
`TestLegacyStrategyRegressionThroughRealEngine`.

### P11. Preservation

Explicitly unaffected by every element of this design (verified by
direct inspection this pass, restated for completeness, not merely
asserted): Phase 2 qualification gates (ATR-distance, body/wick ratio,
confirmation candles — untouched code, only two new, additive
check-points inserted around the existing logic); Phase 3 FVG
score-only behavior (untouched); Phase 4 range-selection/MI/
range-quality gates (untouched — the new checks are inserted, not
interleaved with existing ones); `OrbQualificationStore`'s own lockout
semantics (a wholly separate module, §P8, zero shared code);
Phase 6's conditional registration (`build_default_registry()`'s
zero-argument path and `build_default_registry(store)`'s six-strategy
path both unaffected — the new store is a **second**, independent
optional dependency `OrbBreakoutStrategy` would need, addressed as a
constructor-signature question for Implement, not resolved here beyond
noting it must not change `build_default_registry()`'s existing
`orb_qualification_store` parameter's own meaning);
`DEFAULT_APPROVED_PAIRS_BY_STRATEGY` (untouched, §P9); all five legacy
strategy files (never referenced by any element of this design); ADR-035
and Amendment 1 (read, not modified); the Phase 5 anchor hour/minute
validation residual risk (not referenced, not folded in, remains a
wholly separate, unauthorized follow-up).

**One open construction-shape question for Implement, not resolved
here:** whether `OrbBreakoutStrategy.__init__` gains a second
constructor parameter (`formation_blackout_store`) alongside its
existing `store: OrbQualificationStore` parameter, or whether the two
stores are bundled behind one new small container type. This Plan
states the **requirement** (two independent stores, §P8) but leaves the
exact Python constructor shape to Implement, since it is a mechanical
detail with no safety-relevant consequence either way, consistent with
this project's own practice of not over-specifying implementation
details a competent implementer can resolve correctly within the
Plan's stated constraints.

### P12. Architecture and file-impact matrix

| File | Expected change | Classification |
|---|---|---|
| `titan_protocol/strategy_state_store/` (new module, e.g. `formation_blackout_store.py` + a small config dataclass) | New file(s), following `OrbQualificationStore`'s exact conventions | Required |
| `titan_protocol/strategy_engine/strategies/orb_breakout.py` | New constructor dependency; two new call sites (accumulate immediately after `check_eligibility()`, before `market_closed`/`is_holiday`/evaluation-time-blackout — corrected this revision, Finding F2; read-gate after opening_range resolution, unchanged) | Required |
| `deployment_windows/start.py` | New store construction at `settings.state_dir / "orb_formation_blackout.json"`; threaded into `OrbBreakoutStrategy`'s construction (exact call-site shape per §P11's open question) | Required |
| New test module(s) (e.g. `tests/titan_protocol/strategy_engine/test_orb_formation_blackout.py` and/or an addition to `test_orb_full_suite_integration.py`) | Full §P10 matrix | Required |
| This Plan document | Already being finalized | Required (this artifact) |
| `titan_protocol/strategy_engine/config.py` | **No change** — `DEFAULT_APPROVED_PAIRS_BY_STRATEGY` untouched (§P9) | Explicitly excluded |
| `titan_protocol/evidence_engine/*` (any file) | **No change** — Candidate C requires no Evidence Engine change at all | Explicitly excluded |
| `titan_protocol/market_intelligence/*` (any file) | **No change** | Explicitly excluded |
| `titan_protocol/strategy_state_store/store.py` / `config.py` / `models.py` (the *existing* `OrbQualificationStore` files) | **No change** — new module is a sibling, not an edit to these | Explicitly excluded |
| `titan_protocol/strategy_engine/eligibility.py`, `selection.py` | **No change** | Explicitly excluded |
| Five legacy strategy files | **No change** | Explicitly excluded |
| `deployment_windows/install.py` | **No change** — same reasoning as Phase 6's own disposition (construction-only smoke check, never evaluates strategies) | Explicitly excluded |
| `deployment_windows/config_loader.py` / example JSON | **No change anticipated** — no new configurable field is self-evidently required; Implement should confirm no lookback/retention bound needs to be operator-tunable before treating this as final | Preliminary, low-confidence exclusion |
| Any ADR file | **No change** | Explicitly excluded |
| Phase 5 anchor hour/minute validation files | **No change** | Explicitly excluded (separate, unauthorized follow-up) |

**Structural-boundary re-check:** `tests/titan_protocol/strategy_engine/test_architecture.py`'s
`ALLOWED_UPSTREAM_PREFIXES` already includes
`titan_protocol.strategy_state_store` — the new module lives inside
that already-allowed package, so **no allowlist change is required**.
No new cross-engine dependency is introduced anywhere in this design
(re-confirmed, §P2) — `tests/titan_protocol/evidence_engine/test_architecture.py`'s
blocklist-only gap (Research §2 finding) is **not** triggered by this
Plan, since Evidence Engine is untouched; that gap remains a latent,
pre-existing characteristic this Plan does not need to close (it would
only matter for a future Candidate-B-style design, not this one).

### P13. Validation matrix (exact commands, current baselines re-stated from Research §12)

Targeted:
```
python3 -m unittest tests.titan_protocol.strategy_engine.test_orb_formation_blackout -v
python3 -m unittest tests.titan_protocol.strategy_engine.test_orb_full_suite_integration -v
python3 -m unittest tests.titan_protocol.strategy_engine.test_orb_breakout_foundation -v
```
Full, at Implement/Validation time:
```
python3 -m compileall titan_protocol deployment_windows tests
python3 -m unittest discover -s tests/titan_protocol/evidence_engine        # baseline 176/176, expect unchanged
python3 -m unittest discover -s tests/titan_protocol/market_intelligence    # baseline 90/90, expect unchanged
python3 -m unittest discover -s tests/titan_protocol/strategy_engine        # baseline 164/164, plus new Phase 7 tests
python3 -m unittest tests.titan_protocol.strategy_engine.test_architecture tests.titan_protocol.evidence_engine.test_architecture   # baseline 11/11
python3 -m unittest tests.titan_protocol.compliance_state_store.test_structural_boundary tests.titan_protocol.news_ingestion.test_structural_boundary   # baseline 10/10
python3 -m unittest discover -s tests/deployment_windows -t .               # baseline 162/162, expect unchanged unless start.py's new construction needs a new deployment-level test
python3 -m unittest discover -s tests/titan_protocol                        # baseline 1391/1391, plus new tests
python3 scripts/check_architecture.py                                      # baseline PASS
git diff --stat <phase-7-base-commit> HEAD -- <five legacy strategy files, orb_breakout.py's pre-existing lines, evidence_engine, market_intelligence, config.py, eligibility.py, selection.py, install.py>
# must show zero output for every explicitly-excluded file in §P12
```
Live registry re-check (unchanged from Phase 6, re-run to confirm no
regression): `build_default_registry()` → 5, ORB absent;
`build_default_registry(store)` → 6, ORB exactly once.

### P14. Adversarial Plan review (re-run this revision against the
corrected design)

- **Observation still occurring after another early-return gate
  (Finding F2)?** Fixed, not merely disclosed, this revision — the
  accumulation loop's insertion point moved from "after the existing
  evaluation-time blackout check" to "immediately after
  `check_eligibility()`, before `market_closed`" (§P4). Directly
  re-verified against `orb_breakout.py`'s actual gate order (lines
  78-88): `market_closed` (83), `is_holiday` (85), and the evaluation-
  time blackout check (87) all now execute **after** the accumulation
  loop, not before it — none of them can suppress the observation any
  longer. New Category A test rows (§P10) explicitly cover the
  `market_closed`/`is_holiday` co-occurrence cases this finding
  concerned.
- **Eligibility-order violation?** Checked explicitly — the
  accumulation loop is placed **after** `check_eligibility()`, never
  before it (§P4). Eligibility remains the absolute first gate (ADR-035
  §14), unmoved by this revision; this was verified directly against
  the corrected code block in §P4, not merely asserted.
- **Dormant mechanism described as operational?** Checked explicitly —
  §P3's expanded Finding F1 states, in the Plan's own words, that
  "Phase 7 therefore installs a correctly designed but currently
  dormant formation-blackout mechanism under current production
  defaults," naming both Gate A and Gate B; the header Status line and
  §P16 repeat this framing rather than letting it be inferred only from
  test code or configuration.
- **Test-only reachability confused with production reachability?**
  Guarded against explicitly and sharpened this revision — §P10 now
  names Category A (test-only-configuration) and Category B
  (production-default) tests explicitly, states that no Category A
  result may be cited as proof of production reachability, and adds a
  dedicated Category B row proving Gate B's dormancy directly (not only
  by cross-reference to Gate A).
- **Missing anchors overlooked (Finding F1, Gate B)?** Fixed this
  revision — §P3 now discloses Gate B (`opening_range_anchors`
  defaulting to `()`, the shipped example config preserving that
  default) as an independent, compounding gate alongside Gate A, with
  its own dedicated Category B test (§P10).
- **Formation fact cleared by a later clean cycle?** Prevented by
  design, unaffected by this revision's reordering —
  `record_cycle_observation()`'s OR-accumulate contract (§P6) has no
  code path that can transition `True → False`; explicitly re-tested
  this revision for the market-closed/holiday co-occurrence case
  specifically (§P10), not only the generic case.
- **Wrong range identity?** Prevented by the `(pair, range_start)` key
  (§P6), identical to the already-proven lockout identity — unaffected
  by moving the write side earlier in `qualify()`'s control flow.
- **Restart/persistence false-clean behavior?** Bounded, not
  eliminated — analyzed explicitly in §P7, not silently accepted;
  unaffected by the §P4 reordering, since persistence semantics are
  independent of which point in `qualify()` triggers a write.
- **Duplicated MI logic?** Explicitly checked and rejected as a risk —
  the design only ever reads the already-computed `blackout_active`
  boolean, confirmed by direct code-flow tracing (§P2, §P4); nothing
  recomputes anything from raw `NewsEvent` data. Unaffected by the
  reordering.
- **New unauthorized engine dependencies (including the Runtime/
  Evidence-Engine relocation considered this revision)?** None
  introduced — Strategy Engine already depends on Market Intelligence
  (unchanged, already allowed); the new store lives inside Strategy
  Engine's own already-allowed `strategy_state_store` package (§P12).
  The Runtime/Evidence-Engine relocation alternative was explicitly
  considered and rejected this revision (§P3) — rejected specifically
  because it would introduce exactly this kind of new dependency for no
  reachability benefit, not adopted and then reasoned away.
- **Accidental production eligibility or anchor-default changes?** Not
  introduced — `DEFAULT_APPROVED_PAIRS_BY_STRATEGY` and
  `opening_range_anchors` are both explicitly excluded from this Plan's
  file-impact matrix (§P12) and untouched by every element of the
  design, including the revised §P3/§P4/§P10.
- **Phase 2-6 regressions?** None identified — every existing gate,
  file, and test is either untouched or extended additively; the new
  §P10 rows explicitly assert that downstream qualification on a
  market-closed/holiday cycle is unaffected by the reordering, closing
  the one place this revision touches existing control flow.
- **Anchor-validation follow-up leakage?** Not referenced anywhere in
  this Plan; confirmed out of scope in §P11, unaffected by this
  revision.

**No new blocker was discovered in this adversarial re-read. Both
required findings — F2 (algorithm placement) and F1 (reachability
disclosure) — are resolved: F2 by an actual code-ordering correction in
§P4, F1 by an expanded, two-gate disclosure and an explicit rejected-
alternatives analysis in §P3, both carried through to §P9, §P10, and
§P16.**

### P15. Unresolved items explicitly handed to Implement (not safety-relevant, mechanical only)

1. Exact constructor shape for `OrbBreakoutStrategy`'s second store
   dependency (§P11) — a naming/signature detail, not a design
   decision, with no safety consequence either way.
2. Exact new-module filename/class name within `strategy_state_store/`
   — mechanical, following the existing file's own naming convention.
3. Whether `config_loader.py`/the example JSON eventually need a
   lookback/retention-bound field — flagged as a low-confidence,
   preliminary exclusion (§P12) for Implement to confirm, not decided
   here, since no such field is self-evidently required by anything
   this Plan's design depends on.

None of these block Implementation from beginning against this Plan;
none require a further Research or Plan pass on their own.

### P16. Final disposition reasoning (restated once more, deliberately, so it cannot be missed)

**Finding F2 (algorithm placement) is now fixed, not merely disclosed:**
the formation-blackout accumulation loop's insertion point is corrected
to run immediately after `check_eligibility()` and before
`market_closed`/`is_holiday`/the existing evaluation-time blackout check
(§P4) — a genuine formation-window blackout that co-occurs with a
market-closed or holiday cycle is now recorded, where the prior
revision (Plan commit `34cbe5c`) would have silently missed it. This
correction is verified directly against `orb_breakout.py`'s actual gate
order and covered by new, explicit test commitments (§P10).

**Finding F1 (reachability), expanded rather than merely restated: the
formation-time blackout mechanism this Plan authorizes has zero live
effect in production today, for two independent, compounding reasons —
Gate A (ORB is `NOT_ELIGIBLE` for every pair under the current,
unchanged, already-Accepted `DEFAULT_APPROVED_PAIRS_BY_STRATEGY`
default) and Gate B (`EvidenceEngineConfig.opening_range_anchors`
defaults to `()`, and the shipped example deployment configuration
preserves that empty default, so no opening range exists for any pair
regardless of ORB's eligibility).** Both are pre-existing conditions
this Plan does not change, is not authorized to change, and does not
recommend changing. Relocating the observation point to Runtime or
Evidence Engine was explicitly considered and rejected as a way to
bypass either gate (§P3) — it would neither solve Gate B nor move
enforcement earlier than the ADR-mandated eligibility gate, and would
add dependency/ownership complexity for no reachability benefit.
**Phase 7 therefore installs a correctly designed, correctly testable,
currently-dormant-by-design closure of the gap Amendment 1 named** —
consistent with, not a departure from, this project's own established
practice across Phases 2 through 6. Testability is proven under
explicit Category A test configuration (§P10); production-default
dormancy under both gates is independently proven by dedicated Category
B tests (§P10) — the two claims are never conflated anywhere in this
Plan.

**Disposition: PHASE 7 PLAN REVISED — READY FOR FOCUSED
IMPLEMENTATION-READINESS RE-REVIEW.** Both required findings from the
prior independent implementation-readiness review are resolved; no new
blocker was discovered in this revision's own adversarial re-read
(§P14). Implementation remains unauthorized until a focused re-review
of this revision explicitly approves it.

## Validation

*(Intentionally left empty — this is the Implement phase's own
responsibility, per `TEAM.md` §9. §P13 above states the exact commands
and expected baselines that phase must execute and record here.)*
