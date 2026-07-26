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
independent review before any implementation; revised twice, 2026-07-26:
first to resolve the closed-bar finding from the independent "ADR-024
Amendment 4 -- Independent Evidence-Contract Architecture & Acceptance
Review" (disposition **REQUIRES MAJOR REVISION**); second, this
revision, to resolve the first-candidate continuity finding from the
independent "ADR-024 Amendment 4 Revised Proposal -- Independent
Acceptance Re-Review" (disposition again **REQUIRES MAJOR REVISION**:
the prior text's suggestion to reuse `_has_temporal_gap()`'s tolerance
test against `range_end` was proven wrong -- that test only flags a gap
exceeding one full interval, so a bar missing exactly at the range
boundary would have gone undetected). Each revision replaces the
defective claim it targets, never merely restates it): adds a
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
**First-candidate continuity (corrected -- this is the load-bearing fix
in this revision).** The prior text suggested reusing
`opening_range.py::_has_temporal_gap()`'s existing test (`later.timestamp
- earlier.timestamp > expected_interval_seconds`) against `(range_end,
first candidate)`. Independent review proved this wrong by direct
arithmetic: for `range_end=10:00`, `expected_interval=5min`, a first
candidate at `10:05` (the true 10:00 bar missing entirely) computes
`10:05 - 10:00 = 5min`, which is **not** `> 5min` -- so `_has_temporal_gap()`'s
own tolerance would silently accept a bar that is one full missing
interval away from the range boundary. That test is correct for
comparing two real, already-adjacent bars; it is the wrong comparison
when one side is the `range_end` boundary itself, because the boundary
is not a bar -- the true first legitimate post-range bar is defined to
open **exactly** at `range_end` (§3 above, `range_end_index` already
points at the first bar not in the range). The corrected, exact rule,
with no tolerance of any kind:

```
FIRST CANDIDATE:  candidate.timestamp == range_end
```

If `bars[range_end_index].timestamp != range_end` -- whether earlier,
later, one expected interval later, or several intervals later --
`post_range_bars = ()` for that `OpeningRangeState`, unconditionally.
There is no searching forward for a later bar that happens to match;
the first post-range bar must begin exactly at the boundary or no
post-range evidence is exposed at all for that range in that
evaluation cycle.

**Subsequent-candidate continuity (kept separate from the first-candidate
rule -- distinct anchor, distinct check).** Only once the first
candidate has passed the exact-equality check above does the earlier
`_has_temporal_gap()`-style comparison apply, and only between two real,
already-accepted bars:

```
SUBSEQUENT CANDIDATES:  candidate.timestamp == previous.timestamp + expected_bar_interval_seconds
```

(stated here as exact equality, tighter than `_has_temporal_gap()`'s own
`>`-only check, since a contiguous confirmation sequence must never
admit a candidate that arrived either early/duplicated or with any gap,
not merely one exceeding a full interval).

Processing proceeds bar-by-bar in chronological order starting at
`bars[range_end_index]`, and for each candidate, in order:

1. Verify continuity: the first-candidate exact-equality rule for the
   very first candidate, or the subsequent-candidate exact-equality rule
   (relative to the immediately preceding **accepted** observation) for
   every candidate after it.
2. Verify completion per the rule above.
3. Accept the candidate into `post_range_bars` only if both checks
   succeed, in that order.
4. **Stop at the first failed continuity check or the first incomplete
   bar** -- do not skip the invalid or missing point and resume
   collecting from later, otherwise-valid bars. A first-candidate
   continuity failure yields `post_range_bars = ()` directly (there is
   no "later" bar to fall back to, per the exact rule above); a
   subsequent-candidate failure or an incomplete bar truncates the
   already-accepted prefix at that point.

This guarantees `post_range_bars` can never represent a non-contiguous
confirmation history assembled around a hole, at the range boundary or
anywhere inside the sequence -- a gap or an incomplete bar truncates (or,
at the very first candidate, empties) the sequence at that point, exactly
the same fail-closed posture `is_valid` already applies to the opening
range itself.

**Index contract (clarified -- stated explicitly, not left inferable).**
`OpeningRangeBarObservation.index` is **sequence-relative, not a globally
stable bar identity**: it is a position within the specific `bars`
sequence supplied to that one `EvidenceEngine.evaluate_snapshot()` call,
identical in kind to the pre-existing, unchanged limitation already true
of `range_start_index`/`range_end_index`/`FairValueGap.start_index`/
`end_index` (`Bar` carries no persistent identity anywhere in this
system). Index comparisons are therefore valid only among evidence
produced by the same snapshot call, never across separate calls. This
is sufficient for ADR-035 Phase 2, which only ever compares indices
within one snapshot.

**Timestamp identity (tightened -- scoped explicitly, not left
overstated).** `timestamp` is not a globally stable bar identity either;
it supplies the observation's own temporal identity only within the
enclosing symbol/evaluation context -- practically, uniqueness holds at
the scope of `(symbol, timestamp)` for one evaluation call, matching
this same, pre-existing scope every other bar-derived fact in
`EvidenceSnapshot` already has. `OpeningRangeBarObservation` intentionally
does not duplicate `symbol` on the observation itself -- `symbol` is
already supplied once by the enclosing `EvidenceEngine.evaluate_snapshot()`
call's own context, matching `OpeningRangeState`'s and `FairValueGap`'s
existing convention of never repeating it. Neither `index` nor
`timestamp`, alone or together, should be treated as a repository-wide
or globally durable bar identifier -- both are scoped to one evaluation
call for one symbol.

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

**Snapshot freshness (clarified -- explicitly out of this amendment's
scope, not silently ignored).** This amendment proves completion and
continuity only for bars actually supplied to `EvidenceEngine` in a
given call; it does not, and is not required to, establish that the
overall `bars` input itself is fresh relative to `now` (i.e., that no
newer bar exists that simply wasn't supplied). Snapshot/input freshness
remains `market_data_ingestion.freshness.is_stale()`'s own, pre-existing,
upstream responsibility (ADR-033, unchanged) -- this amendment introduces
no new freshness mechanism, and never fabricates an observation for a bar
that was never supplied.

**Testing (planned, added to this amendment's own scope -- not yet
written, no test file is touched by this proposal):**

- model shape and immutability of `OpeningRangeBarObservation`;
- `post_range_bars` defaults to `()`;
- **A.** first candidate's `timestamp` exactly equals `range_end` ->
  eligible for the subsequent completion check;
- **B.** first candidate's `timestamp` is later than `range_end`
  (including exactly one, or several, expected intervals later -- the
  §3 boundary-missing-bar case) -> `post_range_bars == ()`;
- **C.** first candidate's `timestamp` is earlier than `range_end` ->
  `post_range_bars == ()`;
- exact OHLC/timestamp/index preservation for every accepted
  observation;
- chronological ordering; window-bound enforcement (`opening_range_post_range_bar_window`);
- a genuinely completed candidate is included;
- a candidate with `bar.timestamp + expected_bar_interval_seconds > now`
  is excluded (extraction stops there);
- a candidate exactly at `bar.timestamp + expected_bar_interval_seconds
  == now` is eligible;
- **D.** an internal subsequent-candidate gap (`candidate.timestamp !=
  previous.timestamp + expected_bar_interval_seconds`) stops extraction,
  keeping only the already-accepted prefix;
- **E.** an incomplete candidate stops extraction the same way;
- **F.** later, otherwise-valid bars after a detected gap or incomplete
  bar are never resumed into the same `post_range_bars` sequence (no
  skip-and-resume, tested explicitly by asserting the tuple length/content
  after the stop point);
- the concrete boundary-missing-bar scenario named in the required
  revision -- `range_end=10:00`, `expected_interval=5min`, final in-range
  bar `09:55`, `10:00` bar absent, next available bar `10:05` (otherwise
  complete) -> `post_range_bars == ()`, the `10:05` bar must not be
  accepted;
- `evaluate()` remains behaviorally compatible (see below); `evaluate_snapshot()`
  exposes the additive evidence;
- existing `OpeningRangeState` construction (`opening_range.py`,
  `tests/titan_protocol/evidence_engine/test_opening_range.py`,
  `tests/titan_protocol/strategy_engine/test_orb_breakout_foundation.py`
  -- all keyword-argument construction, confirmed by direct search, none
  positional) remains backward compatible;
- no `market_data_ingestion` dependency is introduced into Strategy
  Engine; no raw bars reach `Strategy.qualify()`; no Phase 2
  qualification semantics are implemented by this amendment.

Computed inside the existing `compute_opening_ranges()`/
`_compute_single_range()` pass (Phase 0's own module), reusing the same
`bars`/`range_end_index`/`config.expected_bar_interval_seconds` already
in scope -- one bounded forward scan, no second traversal, no unbounded
scan.

**`evaluate()` compatibility (corrected wording -- behavioral, not
computational, identity).** `compute_opening_ranges()` already runs
unconditionally inside the shared `_analyze()` pass today, and `evaluate()`
already discards its result (assigned to `_opening_ranges`); this
amendment makes that same, already-discarded computation marginally
larger for callers of `evaluate_snapshot()`. The precise claim is
therefore: `evaluate()` remains **behaviorally compatible** -- its
returned `EvidenceReport` contract and semantics, and every field on it,
are byte-for-byte unchanged -- not that zero additional computation
occurs. Only `evaluate_snapshot()`'s existing `opening_ranges` output
gains the new, defaulted `post_range_bars` field.

**Governance:** this amendment remains **Proposed**, not Accepted. It
introduces no ORB breakout qualification, direction, body/wick or
confirmation-threshold decision, `QualificationResult`, `TradeIntent`,
lockout, persistence, FVG confirmation, Market Intelligence integration,
production ORB registration, legacy-strategy modification, or ADR-036
retirement work -- evidence only. Acceptance criterion "closed-bar and
continuity semantics are proven" is satisfied only once Evidence
Engine's own self-derived completion-and-continuity proof (above,
including the corrected first-candidate rule) is what implementation
actually builds -- restating this proposal's text is not, by itself,
sufficient to consider that criterion met; the revised design must still
pass its own independent re-review before Acceptance. Requires its own
independent review and Acceptance before ADR-035 Phase 2 implementation
may begin (CLAUDE.md §1.10); this entry documents the revised proposal,
not an acceptance, and does not itself unblock Phase 2.

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
