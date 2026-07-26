# ADR-024 — Evidence Engine

Status: **Accepted**

**Amendment 1 (2026-07-10):** expands the engine's output with a new,
additive `EvidenceSnapshot` type carrying the raw structural/liquidity/
candlestick facts already computed internally (previously discarded
after being folded into `ComponentScore`s) plus a new
`SupportResistanceContext` (Previous Day/Week/Month High/Low, Session
High/Low, Psychological Levels, Confluence Score, Break Quality Score,
False Break Probability — concepts this engine never computed before).
Triggered by Phase 2C (Strategy Engine): that phase's own spec requires
consuming raw structural/liquidity/candlestick facts and several S/R
concepts Evidence Engine didn't expose, while simultaneously forbidding
both modifying Evidence Engine and building a second, duplicate analyzer
inside Strategy Engine. Put to the user directly; the explicit answer,
given twice, was **"expand the EvidenceSnapshot, not create a second
analyzer"** — the same resolution `ADR-002` Amendment 1 already
established as this project's precedent for exactly this situation
("resolved as an amendment to this ADR rather than a new pipeline
stage... to avoid creating a second authority over facts this ADR
already owns"). **This supersedes the "Do NOT modify Evidence Engine"
line in the Phase 2C prompt** — the user's direct clarification is a
more specific, later instruction than that prompt's blanket prerequisite,
per normal instruction precedence. Purely additive: `EvidenceReport`,
`evaluate()`, and every existing type/field/test are byte-for-byte
unchanged — verified by re-running the full pre-amendment test suite
unmodified. Additions appear in §2, §3 (new Hard Rule 9), and Testing,
each marked "Amendment 1."

**Amendment 2 (2026-07-10, same trigger):** while implementing the
"BOS + Fair Value Gap" strategy, Strategy Engine needs Fair Value Gap
(FVG) detection -- a 3-candle price-imbalance concept this engine never
computed, and (per Amendment 1's same resolution) not something
Strategy Engine may derive itself from raw bars, since its declared
inputs are the two snapshots only, never raw bars. Resolved identically
to Amendment 1, under the same explicit user direction ("expand the
EvidenceSnapshot, not create a second analyzer") already given for this
exact class of gap: adds `detect_fair_value_gaps()` to `structure.py`
and a new `fair_value_gaps` field on `EvidenceSnapshot` (not on
`MarketStructureResult`, which stays byte-for-byte unchanged) computed
from the same single analysis pass. Purely additive; the full
pre-amendment-2 suite passes unmodified.

**Amendment 3 (2026-07-25, bookkeeping correction -- this document was
never updated at the time, ADR-035 §3 flagged the gap): documents the
already-implemented `OpeningRangeState`/`opening_ranges` addition
(ADR-035 §3, ADR-035 Phase 0, commit `ee976f4`).** Same trigger class as
Amendments 1-2 (a downstream consumer -- ADR-035's Opening Range
Breakout strategy -- needing a market-evidence fact this engine did not
yet compute), same resolution ("expand the `EvidenceSnapshot`, not
create a second analyzer"), same additive-only discipline: adds
`OpeningRangeState` to `models.py` and a new `opening_range.py` module
(`compute_opening_ranges()`), plus the `opening_ranges` field on
`EvidenceSnapshot` (default `()`), computed from the same single
analysis pass inside `_analyze()`. Purely additive; the full
pre-amendment-3 suite passed unmodified at the time of Phase 0's
original implementation. **This entry records history that was already
Accepted and already implemented at the time ADR-035 itself was
Accepted (2026-07-25) -- it is not a new decision, only the missing
bookkeeping entry ADR-035 §3/§19 already identified as owed to this
document.** ADR-035's own text previously mislabeled this addition
"Amendment 2" in three places before a clerical-numbering correction
made this session; this is the corresponding, previously-missing entry
in *this* document, not a new one.

**Amendment 4 (2026-07-26, Proposed -- not yet Accepted, requires
independent review before any implementation; revised 2026-07-26 to
resolve findings from the independent "ADR-024 Amendment 4 -- Independent
Evidence-Contract Architecture & Acceptance Review," disposition
**REQUIRES MAJOR REVISION** on the original text's closed-bar claim --
this revision replaces that claim, not merely restates it): adds a
bounded, per-opening-range post-range bar-observation fact, closing the
evidence-contract gap discovered during ADR-035 Phase 2 RPI planning.**
See `docs/plans/adr-035-phase2-orb-breakout-lockout.md` for the full
research record. In summary: ADR-035 §4's breakout-qualification rule
(close beyond the opening range, body/wick ratio, confirmation-candle
count) requires each qualifying bar's own OHLC, and no field on
`EvidenceSnapshot` today exposes any bar's OHLC after `evaluate_snapshot()`
discards `bars` at the end of `_analyze()` -- confirmed by direct
tracing, not assumed. Proposed addition: `OpeningRangeState` gains a new
field, `post_range_bars: Tuple[OpeningRangeBarObservation, ...] = ()`,
bounded to a new `EvidenceEngineConfig.opening_range_post_range_bar_window`
(default 5, validated `>= 1` in `__post_init__`, following this config's
own existing validation convention). `OpeningRangeBarObservation` remains
opening-range-specific (not a generic bar-evidence type, to avoid
inviting `EvidenceSnapshot` to become a raw-market-data transport
mechanism), carrying `index` (the same bar-sequence index space as
`range_start_index`/`range_end_index`/`FairValueGap.start_index`/
`end_index`), `timestamp`, `open`, `high`, `low`, `close` -- no `volume`
(not required by any ADR-035 §4 rule). This is a pure, objective,
direction-agnostic fact -- it does not compute "is this a breakout,"
does not pick a direction, and does not apply any of ADR-035 §13's
Strategy-Engine-owned thresholds; those decisions remain entirely
Strategy Engine's, in Phase 2's own, still-separate implementation.
Evidence Engine remains sole owner; Strategy Engine continues to
receive interpreted evidence, never a raw `Bar` sequence, never a
`market_data_ingestion` import, never Evidence Engine internals.

**Completion semantics (revised -- this is the load-bearing correction).**
The original text justified omitting a closed/completed indicator by
citing `market_data_ingestion.normalization.normalize()`'s docstring
("never called for a forming bar"). Independent review found this
insufficient: nothing in `EvidenceEngine`, `Bar`, or this amendment's own
proposed model structurally verifies that guarantee -- `EvidenceEngine.
evaluate()`/`evaluate_snapshot()` accept `bars: Sequence[Bar]` with no
provenance check, and existing test code (`tests/titan_protocol/e2e/
test_stress_scenarios.py`, `test_news_validation.py`) already constructs
`Bar` objects directly, bypassing `normalize()` entirely -- proving the
guarantee is a caller convention, not a structural one. **This amendment
no longer relies on upstream provenance, normalization convention, caller
discipline, or an upstream completion flag of any kind.** Instead,
Evidence Engine independently proves each candidate bar's completion
itself, from data it already has, mirroring `OpeningRangeState.is_formed`'s
own existing self-contained pattern (`is_formed = now >= range_end`) and
`opening_range.py::_has_temporal_gap()`'s own existing precedent of never
trusting another package's flag. The rule: a candidate bar is eligible
only when

```
bar.timestamp + timedelta(seconds=config.expected_bar_interval_seconds) <= now
```

where `bar.timestamp` is the bar's **open** timestamp (confirmed:
`normalization.normalize()` sets `timestamp=raw.bar_open_time`) -- so a
bar is provably complete once its own expected close time (open time plus
one expected interval) has already elapsed relative to `now`, computed
entirely from `bar.timestamp`, `config.expected_bar_interval_seconds`, and
`now` -- three values already in scope inside `_compute_single_range()`,
nothing borrowed from upstream. A bar exactly at the boundary
(`bar.timestamp + expected_bar_interval_seconds == now`) is eligible (`<=`,
not `<`). **`OpeningRangeBarObservation` still carries no `is_closed`
field** -- the field would be redundant (every observation that survives
this filter is complete by the filter's own construction) and would
invite exactly the false confidence the original text mistakenly rested
on; completion is a computed admission criterion, not a stored, trustable
flag.

**Contiguous post-range semantics (new -- resolves a gap independent
review found unaddressed).** `post_range_bars` is precisely: *the
bounded, chronological, contiguous prefix of completed bars immediately
following `range_end_index`, with no gap-skipping.* The range remains
`[range_start, range_end)`, and `range_end_index` is already defined
(Phase 0, unchanged) as the exclusive upper sequence index of the range
-- the first bar not included in the range. Therefore **the first
post-range candidate is `bars[range_end_index]`, never `bars[range_end_index
+ 1]`** (`range_end_index` already points one past the last in-range bar).
Processing proceeds bar-by-bar in chronological order starting there,
and for each candidate, in order:

1. Verify temporal continuity from the immediately preceding boundary
   (`range_end` for the first candidate, or the prior accepted
   observation's own `timestamp + expected_bar_interval_seconds` for
   every subsequent one) -- reusing the exact continuity test
   `_has_temporal_gap()` already applies inside the opening range itself,
   never trusting an upstream gap flag.
2. Verify completion per the rule above.
3. Accept the candidate into `post_range_bars` only if both checks
   succeed.
4. **Stop at the first incomplete bar or the first detected temporal
   gap** -- do not skip the invalid or missing point and resume
   collecting from later, otherwise-valid bars.

This guarantees `post_range_bars` can never represent a non-contiguous
confirmation history assembled around a hole -- a gap or an incomplete
bar truncates the sequence at that point, exactly the same fail-closed
posture `is_valid` already applies to the opening range itself.

**Index contract (clarified -- stated explicitly, not left inferable).**
`OpeningRangeBarObservation.index` is **sequence-relative, not a globally
stable bar identity**: it is a position within the specific `bars`
sequence supplied to that one `EvidenceEngine.evaluate_snapshot()` call,
identical in kind to the pre-existing, unchanged limitation already true
of `range_start_index`/`range_end_index`/`FairValueGap.start_index`/
`end_index` (`Bar` carries no persistent identity anywhere in this
system). Index comparisons are therefore valid only among evidence
produced by the same snapshot call, never across separate calls;
`timestamp` is what supplies the observation's own independent temporal
identity outside that scope. This is sufficient for ADR-035 Phase 2,
which only ever compares indices within one snapshot.

**Multiple opening ranges (clarified -- stated explicitly).** A single
physical bar may simultaneously be post-range evidence for one configured
opening range and formation/in-range evidence for a different configured
opening range -- each `OpeningRangeState` (and its own `post_range_bars`)
is derived independently from the same immutable `bars` sequence, so this
is a correct, harmless factual outcome, not corruption or ambiguity in the
data itself. It creates no qualification ambiguity in Phase 2 because
Phase 1's existing multi-range handling (carried forward unchanged) already
fails closed to `NOT_QUALIFIED` whenever more than one `OpeningRangeState`
is present, regardless of any such overlap.

**Bounded-history rationale (clarified -- the derivation, not just the
number).** The fixed bound of 5 is a **safety margin over ADR-035 §13's
currently recommended `orb_min_confirmation_candles` range of 1-2** --
comfortably wider than the recommended range without exposing an
unbounded window of session bars. A future Phase 5 configuration
requiring more confirmation candles than this window can supply does
**not** create a capital-safety failure: insufficient post-range evidence
can only ever cause a downstream consumer to fail closed to
`NOT_QUALIFIED` (§4/§14's own fail-closed doctrine), never to fabricate a
false `QUALIFIED`. It is a **capability/configuration incompatibility**,
not a safety defect -- and one that would require revisiting this bound
at that time, not one this amendment must solve now.

**Testing (planned, added to this amendment's own scope -- not yet
written, no test file is touched by this proposal):** model shape and
immutability of `OpeningRangeBarObservation`; `post_range_bars` defaults
to `()`; the first post-range observation begins at `range_end_index`
(not `+1`); exact OHLC/timestamp/index preservation; chronological
ordering; window-bound enforcement; a genuinely completed candidate is
included; a candidate with `bar.timestamp + expected_bar_interval_seconds
> now` is excluded; a candidate exactly at
`bar.timestamp + expected_bar_interval_seconds == now` is eligible; a
temporal gap between `range_end` and the first candidate prevents that
candidate and every later bar from forming a false contiguous
confirmation sequence; a temporal gap inside the post-range sequence
truncates evidence at the gap; later, otherwise-valid bars after a
detected gap are never resumed into the same `post_range_bars` sequence;
`evaluate()` remains behaviorally unchanged; `evaluate_snapshot()` exposes
the additive evidence; existing `OpeningRangeState` construction
(`opening_range.py`, `tests/titan_protocol/evidence_engine/
test_opening_range.py`, `tests/titan_protocol/strategy_engine/
test_orb_breakout_foundation.py` -- all keyword-argument construction,
confirmed by direct search, none positional) remains backward compatible;
no `market_data_ingestion` dependency is introduced into Strategy Engine;
no raw bars reach `Strategy.qualify()`; no Phase 2 qualification
semantics are implemented by this amendment.

Computed inside the existing `compute_opening_ranges()`/
`_compute_single_range()` pass (Phase 0's own module), reusing the same
`bars`/`range_end_index`/`config.expected_bar_interval_seconds` already
in scope -- one bounded forward scan, no second traversal, no unbounded
scan. `evaluate()` is unaffected; only `evaluate_snapshot()`'s existing
`opening_ranges` output gains the new, defaulted field.

**Governance:** this amendment remains **Proposed**, not Accepted.
Acceptance criterion "closed-bar semantics are proven" is satisfied only
once Evidence Engine's own self-derived completion proof (above) is what
implementation actually builds -- restating this proposal's text is not,
by itself, sufficient to consider that criterion met; the revised design
must still pass its own independent re-review before Acceptance. Requires
its own independent review and Acceptance before ADR-035 Phase 2
implementation may begin (CLAUDE.md §1.10); this entry documents the
revised proposal, not an acceptance.

Owner: Software Architect (per `.claude/agents/TEAM.md`'s precedent for
cross-cutting evaluation components — same accountable role as
ADR-002/ADR-004)

Accepted By: User direction, this session (explicit, full specification:
7 responsibility categories — market structure, liquidity, candlestick
intelligence, trend, volatility, session awareness, indicator framework
— plus scoring/ranking/explainability requirements, architecture rules,
performance targets, and an 8-category testing mandate) — the same
in-session approving authority already used to accept `ADR-020` through
`ADR-023`.

Reviewed by: (post-hoc, this session) — confirmed against
`ADR-001`'s "no duplicate scoring" rule and `ADR-002` Amendment 1's
precedent before acceptance; see §0 below.

Date: 2026-07-10

Depends on: none. This ADR deliberately does not depend on
`ADR-001-single-authority-architecture.md` or any of its per-stage
successors (`ADR-002` onward) — see §0.

---

# 0. Relationship to the existing `phantom_pipeline/` pipeline

This is the decision this ADR exists to record, made explicitly with the
user before any code was written (three direct questions, three direct
answers):

1. **Location:** `titan_protocol/evidence_engine/` — a new, independent package
   alongside `titan_protocol/bridge/`, not `phantom_pipeline/evidence_engine/`.
2. **Relationship to `ADR-002-scanner.md` (Accepted, implemented in
   `phantom_pipeline/scanner/`) and `ADR-004-scoring-engine.md`
   (Accepted, implemented in `phantom_pipeline/scoring_engine/`):**
   fully fresh, clean-room implementation. **No code, module, or class is
   ported or imported from `phantom_pipeline/`.** This mirrors the
   relationship `titan_protocol/bridge/` already has to
   `phantom_pipeline/ea_bridge/` (ADR-023) — a second, independent
   implementation track under `titan_protocol/`, built and hardened
   turn-by-turn this session, deliberately not reusing the
   `phantom_pipeline/` codebase.
3. **ADR gate:** this document — drafted and marked Accepted in the same
   session as the implementation, per the established precedent of
   `ADR-020` through `ADR-023`, satisfying the Titan Protocol Protocol's rule
   that no pipeline-stage implementation begins without an Accepted ADR
   for that stage (CLAUDE.md §1.10).

**This is a real scope overlap, acknowledged, not hidden:** `ADR-002`
Scanner already computes market structure (BOS/CHOCH/swing/S-R),
liquidity concepts, and session detection; `ADR-004` Scoring Engine
already computes a weighted, explainable composite score with
reason/weight/confidence per component, plus ranking. `ADR-002`
Amendment 1 explicitly rejected building a *separate* pipeline stage for
overlapping market-structure scope, to avoid a second authority over the
same facts — this ADR takes the opposite resolution, per explicit user
direction, because `Evidence Engine` is not extending `phantom_pipeline/`'s
single authority; it is part of a **separate, independent track**
(`titan_protocol/`) that does not participate in `phantom_pipeline/`'s pipeline
at all. There is exactly one authority for each fact **within each
track**; the two tracks are not wired together by this ADR, and nothing
in `titan_protocol/evidence_engine/` calls, imports, or is called by anything in
`phantom_pipeline/`.

---

# Pipeline position

**The Evidence Engine is not wired into any execution pipeline. It is a
standalone measurement/scoring component with no consumer yet.** Per the
user's own stated ordering (given at Bridge-freeze time), the intended
future sequence for this track is:

Evidence Engine → Strategy Engine → Portfolio Statistical Risk Engine →
Market Intelligence Engine → Prop Firm Compliance Engine → Research &
Learning Engine → Validation

Each of those later stages is out of scope here and requires its own
Accepted ADR before implementation, per CLAUDE.md §1.10. This ADR defines
only the Evidence Engine.

---

# 1. Mission

**The Evidence Engine answers exactly one question: "How strong is the
observable market evidence for a given pair, right now?"**

It **never** answers: should we buy, should we sell, what size, is this
compliant, is a news event blocking this, should we execute. It produces
a deterministic, explainable, bounded score (0–100) per pair from
independently-computed evidence components — nothing more.

---

# Hard Rules

1. **No trade decision anywhere in this package.** No `BUY`/`SELL`
   enum, no position size, no stop loss / take profit, no order,
   anywhere in `titan_protocol/evidence_engine/`. A structural test enforces
   this (see Testing).
2. **No duplicate scoring.** Every one of the seven component scores
   (structure, liquidity, candlestick, trend, volatility, session,
   indicator) is computed from independent inputs; no signal is counted
   twice within a single Evidence Score.
3. **No hidden calculations.** Every component score carries a `reason`
   (human-readable), a `weight` (its contribution to the composite), and
   a `confidence` (0–1). The composite `EvidenceScore` is a fully
   reproducible weighted function of its components — nothing computed
   off-band.
4. **No randomness, no ML, no AI.** Every function in this package is a
   pure, deterministic transform of its Bar/OHLC input. Same input bars
   always produce the same `EvidenceReport`, byte-for-byte comparable
   field by field.
5. **No news, no risk, no compliance, no execution.** This package
   imports nothing from `risk_engine`, `compliance_engine`,
   `execution_validator`, `mt5_bridge`, `position_manager`, or any
   `phantom_pipeline/` package. It has no network calls, no file I/O
   beyond its own logging sink.
6. **One responsibility only.** Given a symbol's recent bars, produce an
   `EvidenceReport`. Given several pairs' reports, rank them by score.
   That is the entire public surface.
7. **Indicator framework is an interface only in this phase.** `EMA`,
   `RSI`, `ADX`, `MACD`, `Stochastic`, `Bollinger`, `Volume`, `VWAP` are
   named as future indicators this framework must support, but none are
   implemented as concrete indicators in Phase 2A — only the `Indicator`
   ABC, a registry, and a caching layer are built now.
8. **Thread safety without duplicate work.** Evaluating N pairs
   concurrently must not corrupt shared state and must not recompute the
   same indicator twice for the same symbol/bar-set/parameters within one
   evaluation cycle (caching, keyed by content, not by wall-clock time).
9. **(Amendment 1) Additive only, one computation per fact.**
   `EvidenceSnapshot` carries the *exact same* structure/liquidity/
   candlestick results `evaluate()` already computes internally for the
   `EvidenceReport` — `evaluate_snapshot()` never runs
   `analyze_market_structure`/`analyze_liquidity`/`recognize_patterns`
   a second time for the same bars; it computes once and populates both
   the existing `EvidenceReport` and the new raw fields from that one
   pass. The new `support_resistance.py` module is new logic (nothing
   in `structure.py` computed Previous Day/Week/Month High/Low, Session
   High/Low, Psychological Levels, Confluence, Break Quality, or False
   Break Probability before this amendment) — not a duplicate of
   anything pre-existing.

---

# 2. Architecture

```
titan_protocol/evidence_engine/
    models.py          Bar, SwingPoint, StructureEvent, LiquidityPool,
                        LiquiditySweep, CandlestickMatch, TrendState,
                        VolatilityState, SessionState, IndicatorResult,
                        ComponentScore, EvidenceScore, EvidenceReport,
                        PairRanking
    config.py           EvidenceEngineConfig -- every threshold/weight
                        named, no magic numbers
    structure.py         swings, BOS, CHOCH (internal/external), trend
                        leg detection, support/resistance levels
    liquidity.py         equal highs/lows, liquidity pools, sweeps, stop
                        hunts, liquidity-trap filter, displacement
    candlesticks.py       1/2/3-candle pattern recognition with quality/
                        context/confidence
    trend.py            trending-up/down/range/compression/expansion/
                        reversal classification
    volatility.py        ATR, expansion/compression, volatility score
    session.py          London/overlap/early-NY/late-NY/Asian + quality
    indicators.py         Indicator ABC + registry + cache (interface
                        only -- no concrete indicators yet)
    scoring.py          per-component ComponentScore -> composite
                        EvidenceScore (0-100)
    ranking.py           rank enabled pairs by EvidenceScore
    explainability.py    EvidenceReport assembly (strengths/weaknesses/
                        confidence narrative)
    engine.py            EvidenceEngine.evaluate()/evaluate_batch() --
                        orchestrates the above, thread-safe, caches
                        indicator results per (symbol, bar signature)
    logging_sink.py       structured logging (same conventions as
                        titan_protocol/bridge/logging_sink.py)
    metrics.py           counters/gauges (same conventions as
                        titan_protocol/bridge/metrics.py)
    __init__.py          public exports
```

No file here imports anything from `phantom_pipeline/`. No file in
`phantom_pipeline/` is modified by this ADR.

**(Amendment 1) New/changed files:**

```
    models.py            + EvidenceSnapshot, SupportResistanceContext,
                        PsychologicalLevel, ConfluenceZone (additive --
                        every pre-existing type/field unchanged)
    support_resistance.py  (new) Previous Day/Week/Month High/Low,
                        Session High/Low, Psychological Levels,
                        Confluence Score, Break Quality Score, False
                        Break Probability
    engine.py            + EvidenceEngine.evaluate_snapshot() (new
                        method; evaluate() itself is untouched)
```

---

# 3. Testing (mandatory before Accepted → Done)

Per the user's 8-category mandate: unit, property, boundary, performance
(28+ pairs simultaneously), determinism (same input → same output, run
twice), explainability (every score traces to a reason), regression, and
architecture (no forbidden imports, no trade-decision types, no
randomness).

**(Amendment 1):** the full pre-amendment suite (110 tests) must pass
unmodified, proving zero regression, plus new tests for
`support_resistance.py` and `evaluate_snapshot()` covering the same 8
categories.

---

# Success Criteria

- Evidence Score is bounded [0, 100] for all valid inputs, for every
  pair, always.
- Every `ComponentScore` and the composite `EvidenceScore` carries a
  `reason`, `weight`, and `confidence`.
- Two calls with identical input bars produce identical
  `EvidenceReport`s (determinism test).
- 28+ pairs evaluated in one `evaluate_batch()` call with no duplicate
  indicator computation and no shared-state corruption under concurrent
  use.
- `scripts/check_architecture.py` (extended for this package) confirms
  no import from any `phantom_pipeline/` package and no import of
  trade-decision vocabulary (`BUY`/`SELL`/order/position-size types).
- No trade is ever placed, sized, or approved by this package — it is
  physically incapable of it (no such method exists in its public
  surface).
