# Plan: ADR-035 Phase 3 — FVG (Fair Value Gap) Confirmation for ORB

Status: **FINALIZED — READY FOR INDEPENDENT IMPLEMENTATION-READINESS
REVIEW.** The Research phase (commit `2dddac2`) is complete and is
carried forward unchanged below. This pass adds the Plan section only —
no production code, no test code, per this task's own instruction.
Implementation remains prohibited until an independent
implementation-readiness review of this Plan accepts it (mirrors the
Step 2A/2B precedent exactly: Research → Plan → independent Plan review
→ Implement, never Research → Implement directly).

Owner (Plan phase): Software Architect (ADR-035/ADR-024/ADR-026 owner precedent, unchanged)
Touched components (confirmed, unchanged from Research): `titan_protocol/strategy_engine/strategies/orb_breakout.py`, `titan_protocol/strategy_engine/config.py`, `tests/titan_protocol/strategy_engine/test_orb_breakout_foundation.py`. No other package. No Evidence Engine change (re-confirmed below, §8). No new structural-boundary allowlist entries (re-confirmed below, §8).

**Fixed inputs this Plan does not revisit** (per this task's own explicit instruction): the Accepted ADR-035 §5/§13/§17 text, and the completed, independently-accepted Phase 2 `OrbBreakoutStrategy.qualify()`/`OrbQualificationStore` implementation (commit `6cb235c`) — including its exact score-formula literals (`0.4`/`0.3`/`0.3`), its 16-step breakout algorithm, and its lockout/persistence/concurrency behavior. Phase 3 is additive to this fixed baseline, never a revision of it.

---

## Research

### 0. Governance gate (verified against current HEAD, not assumed)

- Branch: `claude/phantom-ea-visibility-cjjf3a`. HEAD: `6cb235c18618f5227c9933968730c1e0aaa67e1c`, working tree clean.
- `ADR-035-orb-strategy.md`: **Accepted** (2026-07-25, §§0-16 and §17). Phase 3 is explicitly item 3 of the Accepted §17 roadmap: *"Phase 3 — FVG confirmation: §5's weighted scoring addition, including the corrected index-based temporal comparison, with unit tests covering direction matching, age, size, overlap, and expiration."*
- Phase 2 (both steps) is fully implemented and independently accepted: Step 2A (`post_range_bars`, commit `dcf9b58`) and Step 2B (breakout qualification + persistent lockout, commit `b28ac3f`, conformance-reviewed with required minor revisions applied in commit `6cb235c`). No open Phase 2 item remains.
- **Unlike Phase 2, §17's Phase 3 entry names no further-Accepted-ADR precondition.** Phase 2's entry explicitly required a proposed ADR-024 Amendment 4 to reach Accepted status before implementation could begin (a gap discovered mid-roadmap: `EvidenceSnapshot` had no bar-level OHLC field). This Research phase's own job (§1-§2 below) was to check whether Phase 3 has an equivalent hidden gap. It does not — see §1.
- CLAUDE.md §1.10 ("no implementation begins on a pipeline stage until that stage's ADR is Accepted") is satisfied: ADR-035 is Accepted, and Phase 3 requires no companion ADR amendment (§1 below). **This Research phase does not authorize implementation** — only Plan finalization and, after that, its own independent implementation-readiness review, per this project's established Phase 2 precedent.

### 1. Evidence contract completeness — confirmed sufficient, no Evidence Engine amendment required

Direct read of `titan_protocol/evidence_engine/models.py` (current HEAD):

- `FairValueGap` (Amendment 2, pre-existing) already carries every field ADR-035 §5 needs: `direction: StructureDirection`, `start_index: int`, `end_index: int`, `gap_high: float`, `gap_low: float`, `filled: bool`, `fill_index: Optional[int]`.
- `OpeningRangeState.range_start_index` (Phase 0, pre-existing) is the field §5's temporal comparison (`gap.start_index >= opening_range.range_start_index`) needs.
- `EvidenceSnapshot.fair_value_gaps: Tuple[FairValueGap, ...]` (already a field, default `()`) is exactly what `BosFvgStrategy` already consumes today (see §3).

**Index-space consistency independently verified, not assumed:** `titan_protocol/evidence_engine/engine.py::_analyze()` calls `detect_fair_value_gaps(bars)` and `compute_opening_ranges(bars, now, self.config)` with the **identical** `bars` argument in the same call (lines 84-85 of `engine.py`). `FairValueGap.start_index`/`end_index` and `OpeningRangeState.range_start_index`/`range_end_index` are therefore guaranteed to share one index space within a single `evaluate_snapshot()` call — confirming ADR-035 §5's own claim ("comparing two integers Evidence Engine already computes from the same internal bar sequence") by direct code read, not by trusting the ADR's prose.

**Conclusion: Phase 3 requires zero Evidence Engine changes.** This is the first ORB phase that does not need a companion Evidence Engine amendment — a real, checked difference from Phase 2, not an assumption carried over from it.

### 2. Exact insertion point in `OrbBreakoutStrategy.qualify()` — confirmed, does not disturb Step 2B's algorithm

Current `titan_protocol/strategy_engine/strategies/orb_breakout.py` (commit `6cb235c`) ends its qualification algorithm in this exact order (line numbers as currently committed):
1. Eligibility gate → range presence/count/formed/valid → post-range-bars presence → degenerate geometry → strict direction determination (close only) → momentum (`is_expansion`) → ATR-distance → body/wick ratio → confirmation count → confirmation direction-consistency (lines 78-131).
2. **Score/confidence computed** (lines 133-137): `score = clamp(0.4*session_value + 0.3*mi_session_score + 0.3*evidence.volatility.volatility_score)`; `confidence = session_component.confidence if session_component else 0.5`.
3. `qualified_result` built (lines 140-149).
4. Lockout `try_consume()` as the sole terminal gate (lines 151-153).

Per ADR-035 §5 ("Optional, weighted — never mandatory, never ignored... FVG absence never disqualifies, only fails to add the bonus"), FVG confirmation introduces **no new `NOT_QUALIFIED` return path**. The only correct insertion point is **between step 2 and step 3 above**: after `score`/`confidence` are computed from the existing three terms, before `qualified_result` is constructed, look up a qualifying FVG (if any) and fold its bonus into `score` (and optionally into `strengths`) before building the same `qualified_result` object. Lockout semantics (step 4), the breakout algorithm (step 1), and every existing `_not_qualified()` return in step 1 are untouched by this description — confirmed by inspection, not assumed.

### 3. No duplicate FVG detector — existing precedent confirmed

`titan_protocol/strategy_engine/strategies/bos_fvg.py` (`BosFvgStrategy`, pre-existing, unmodified by any ORB phase) already consumes `evidence.fair_value_gaps` directly (`unfilled_gaps = [g for g in evidence.fair_value_gaps if not g.filled]`) and already converts a `StructureDirection` to a `TradeIntent` via the shared helper `trade_intent_from_structure_direction()` in `titan_protocol/strategy_engine/strategies/_helpers.py`. ORB's Phase 3 direction-matching (`gap.direction` against ORB's own already-determined `trade_intent`) is the exact inverse of that same helper's mapping (`TradeIntent.BUY ⇔ StructureDirection.BULLISH`, `TradeIntent.SELL ⇔ StructureDirection.BEARISH`) — reusable as-is, requiring no new helper and no second FVG interpretation. No second FVG detector exists or is proposed anywhere in the repository; `structure.py::detect_fair_value_gaps()` remains the sole computation, confirmed by grep.

### 4. Config precedent — confirmed pattern, one unresolved cross-field question

`titan_protocol/strategy_engine/config.py`'s Step 2B fields (`orb_min_breakout_distance_atr_multiple`, `orb_min_body_to_range_ratio`, `orb_min_confirmation_candles`, `orb_max_qualifications_per_range`) establish the exact pattern Phase 3's three new fields (`orb_fvg_max_age_bars`, `orb_fvg_min_size_atr_multiple`, `orb_fvg_score_weight`, per ADR-035 §13) will follow: a defaulted dataclass field with an inline comment naming its purpose, validated in the single existing `__post_init__`.

**Open question requiring an explicit Plan-phase decision (not a silent implementer choice):** ADR-035 §13's cross-field validation clause states config loading must fail closed if *"the weighted-scoring components in §5 (`orb_fvg_score_weight` and any sibling weights in the same weighted sum) do not sum to ≤ 1."* Direct inspection of the **already-shipped** Step 2B score formula shows it does not use named, configurable weights at all — `0.4`, `0.3`, `0.3` are inline literals in `orb_breakout.py`, not `StrategyEngineConfig` fields (this was an accepted deviation from ADR-035 §5's own drafted formula, which used `w1/w2/w3` and a `range_quality` term that was never implemented that way — Step 2B instead reused `SessionBreakoutStrategy`'s literal formula verbatim, already independently reviewed and accepted). Adding `orb_fvg_score_weight` as a fourth, genuinely configurable term therefore raises a question ADR-035's own text does not resolve and this Research phase will not silently decide: **does §13's "≤ 1" cross-field check apply only to `orb_fvg_score_weight` in isolation (bounded 0-1, checked alone), or does implementing it correctly require promoting the existing three literals to named config fields as well so the full sum can be validated?** Either answer is defensible; the Plan phase must state and justify one, not leave it for the implementer to invent (CLAUDE.md §1.9, §7).

**Second open question, same category:** ADR-035 §5 says a qualifying FVG "adds a bounded scoring bonus" but does not specify `fvg_bonus`'s own value formula (a fixed constant when a qualifying gap is found vs. a graduated value derived from gap quality/size/age). The Plan phase must specify this exactly, the same way it specified the exact ATR-distance/body-ratio formulas for Phase 2.

**Third, narrower open question:** §5's `orb_fvg_max_age_bars` needs one reference index against which "age" is measured (candidate bar's own `index`, `opening_range.range_end_index`, or the qualifying gap's own `end_index` relative to one of those) — ADR-035's text states the *existence* of an age limit but not which index anchors it. Confirmed by re-reading §5 in full; not an oversight in this Research pass.

None of these three items are architectural objections or missing ADR amendments — they are the same class of implementation-detail decision ADR-035 §17 explicitly delegates to each phase's own Plan document (mirroring how Phase 2's Plan resolved its own write-failure-handling ambiguity at Plan-finalization time, not by returning to the ADR). They gate Plan finalization, not this Research disposition.

### 5. Architecture-boundary check — run and confirmed clean, zero new allowlist entries anticipated

- `tests/titan_protocol/strategy_engine/test_architecture.py`: `ALLOWED_UPSTREAM_PREFIXES` already includes `titan_protocol.evidence_engine` — the only upstream package Phase 3 needs (`evidence.fair_value_gaps` is already an `EvidenceSnapshot` field). No new prefix required.
- `tests/titan_protocol/compliance_state_store/test_structural_boundary.py` and `tests/titan_protocol/news_ingestion/test_structural_boundary.py`: both `_LATER_AUTHORIZED_EXCEPTIONS` allowlists already contain `titan_protocol/strategy_engine/config.py` and `titan_protocol/strategy_engine/strategies/orb_breakout.py` (added for Step 2B) — the only two production files Phase 3 is expected to touch. **Zero new entries anticipated in either allowlist**, a real difference from every prior ORB phase, each of which required at least one new entry.
- `python3 scripts/check_architecture.py` (owned by Integration Engineer, TEAM.md §9): PASS — no circular imports, no cross-package private-state access, no pipeline-stage-imports-observer violation. Note for the record: this script scans `phantom_pipeline/` (the reference-only legacy tree, CLAUDE.md §2), not `titan_protocol/` — it is run here only because TEAM.md §9 names it as the mandatory Research-phase check; it is not evidence about the `titan_protocol` change itself. `tests/titan_protocol/strategy_engine/test_architecture.py` (run directly, full pass) is the actual governing check for this change, per ADR-001's single-authority supersession of §2's original component list.

### 6. Test precedent — confirmed structure, no new test file needed

`tests/titan_protocol/strategy_engine/test_orb_breakout_foundation.py` (currently 41 tests, all green) already establishes: `_OrbTestCase` base class (fresh temp-dir-backed `OrbQualificationStore` per test), `_bar()`/`_make_opening_range()`/`_evidence_with_ranges()`/`_breakout_evidence()` helpers, and per-rule test classes (`TestAtrDistance`, `TestBodyWickRatio`, etc., each with bullish + bearish coverage as of the most recent commit). Phase 3's own required test coverage (ADR-035 §17: "direction matching, age, size, overlap, and expiration") fits this same file and these same helpers — no new test file, no new fixture pattern needed. `_breakout_evidence()` will need extending to accept an optional `fair_value_gaps` tuple (currently it only threads `opening_ranges`/`volatility` into `EvidenceSnapshot`); this is a test-helper extension, not new architecture.

### 7. Duplicate-logic / regression check

No duplicate FVG logic (§3). No duplicate ATR/body/lockout logic — Phase 3 adds no new gating rule, only a scoring term, so none of Step 2B's `_not_qualified()` paths, the lockout store, or its concurrency/persistence guarantees are touched. The five legacy strategies and `BosFvgStrategy` are read-only precedent here, not modified. `git status --porcelain` at this Research pass's own HEAD is clean — no stray edits exist to regress against.

---

## Plan

### 1. Approach

Add FVG confirmation as a pure, score-only enhancement inserted between
Phase 2's existing score/confidence computation and its existing
`qualified_result` construction (Research §2's identified insertion
point, re-confirmed here). No new `NOT_QUALIFIED` return path, no
change to any of Phase 2's 16 gating steps, no change to
`OrbQualificationStore` or its lockout semantics. One new private
helper function in `orb_breakout.py` selects at most one qualifying FVG
deterministically; its presence contributes a bounded, configurable
scoring bonus. Exactly one new config field is added
(`orb_fvg_score_weight`); the three fields ADR-035 §13 also lists for
Phase 3 (`orb_fvg_max_age_bars`, `orb_fvg_min_size_atr_multiple`) are
added alongside it as eligibility thresholds for the FVG-selection
predicate itself, not as score weights.

### 2. Resolved design decisions (the three Research-phase questions)

#### 2.1 Score weights / cross-field validation

**Decision: do not promote Phase 2's existing `0.4`/`0.3`/`0.3` score
literals into config fields. Add exactly one new field,
`orb_fvg_score_weight: float = 0.15`, validated only against its own
per-field range `[0.0, 1.0]`. No cross-field sum check is implemented,
and this is not an omission — it is the correct reading of §13 given
this Plan's fixed inputs, for the following reasons, in order:**

1. This task explicitly instructs treating "the completed Phase 2 ORB
   implementation as fixed inputs." Phase 2's score formula (including
   its three literal coefficients) is part of that implementation,
   already independently accepted (conformance review, commit
   `b28ac3f`/`6cb235c`). Rescaling those literals to make room for a
   fourth weighted term would be a behavior change to already-accepted,
   already-shipped code — not an addition — and is out of this Plan's
   authorized scope.
2. The Step 2B Plan (`docs/plans/adr-035-phase2-orb-breakout-lockout.md`
   §13, its own Plan-finalization note) already recorded, explicitly,
   that "ADR-035 §13's cross-field validation clause does not apply to
   any of Step 2B's 4 fields" — an acknowledgment, made at the time,
   that the session/MI/volatility weights were not configurable fields
   and therefore had no "sibling weights" for any future FVG weight to
   sum against. This Plan does not silently re-open that already-decided
   point; it inherits it.
3. §13's cross-field clause reads: *"the weighted-scoring components in
   §5 (`orb_fvg_score_weight` **and any sibling weights in the same
   weighted sum**) do not sum to ≤ 1."* With zero sibling weights
   existing as configurable fields (by #1/#2 above), this clause is not
   violated by omission — it degenerates to, and is fully satisfied by,
   `orb_fvg_score_weight`'s own per-field bound. A cross-field check with
   only one field to check is not a cross-field check; nothing is lost
   by not writing one.
4. ADR-035 §18.B item 3 (Future design considerations, explicitly
   non-blocking) states: *"Exact default values in §13 are proposed,
   reasonable starting points, not empirically validated... before
   Phase 5, not before."* This confirms the ADR itself treats §13's
   numeric defaults, including `orb_fvg_score_weight`'s `0.15`, as
   provisional — supporting (not requiring) exactly the reading above:
   the binding requirement is the *structural* one (bounded, weighted,
   never disqualifying), which this design satisfies; the specific
   numbers are not frozen by the ADR.
5. **Consequence, stated plainly:** the existing three terms can already
   sum to 100 at their own maximum (`0.4+0.3+0.3=1.0` against inputs
   each bounded `[0,100]`); adding `orb_fvg_score_weight * fvg_bonus`
   (max `0.15*100=15`) on top can push the pre-clamp value to at most
   115, absorbed by the existing `clamp(value, 0.0, 100.0)` call that
   already wraps this formula today. This is intentional, not a defect:
   ADR-035 §5 itself calls the FVG contribution "a bounded scoring
   bonus," not a fourth weighted-average term requiring renormalization
   — "bonus" language is consistent with additive headroom absorbed by
   an existing ceiling, not with a strict weighted-average identity.
   **Recorded as a non-blocking open item for a possible future,
   separately-scoped follow-up** (§6 below): promoting all four weights
   to config fields with a real cross-field sum check remains available
   if a later phase wants it; Phase 3 does not need it and does not
   invent it now.

#### 2.2 FVG bonus formula

**Decision: `fvg_bonus` is binary — `100.0` if at least one qualifying
FVG is found, else `0.0`.** Gates score only, never qualification,
exactly per ADR-035 §5's own words ("weights configurable, sum-bounded
so FVG absence never disqualifies, only fails to add the bonus" —
confirmed, not paraphrased). No existing code in this repository
converts an FVG into a graduated numeric score (`BosFvgStrategy`, the
one other FVG-consuming strategy, uses gap width only in a descriptive
`strengths` string, never in its own score formula — checked directly).
A graduated formula (age-weighted, size-weighted) would require
inventing additional coefficients with zero ADR or repository grounding
— exactly the kind of implementer-invented rule this task instructs
against. Binary presence is the minimal, deterministic, bounded design
that satisfies §5's literal text with no invented sub-formula.

**Direction handling:** `required_direction = StructureDirection.BULLISH
if trade_intent is TradeIntent.BUY else StructureDirection.BEARISH` —
the exact inverse of the existing `trade_intent_from_structure_direction()`
helper in `_helpers.py` (Research §3), reused as a direction predicate,
not a new mapping.

**Multiple eligible FVGs — deterministic selection, no aggregation
needed:** because the bonus is binary, "multiple qualifying gaps" never
needs an aggregation rule (100.0 either way). For the `strengths` text
(which names one specific gap), the first gap in
`evidence.fair_value_gaps`'s existing tuple order that passes every
predicate is used — the exact precedent already set by
`BosFvgStrategy`'s own `matching[0]` (Research §3), not a new "best gap"
search, no sorting, no additional tie-break rule invented.

**Eligibility predicate, applied in this exact order (matches §5's own
bullet order):**
1. `gap.direction == required_direction`
2. `not gap.filled`
3. `gap.start_index >= opening_range.range_start_index` (§5's own
   decided mechanism, verbatim)
4. Age filter (§2.3 below)
5. `(gap.gap_high - gap.gap_low) >= config.orb_fvg_min_size_atr_multiple
   * evidence.volatility.atr` (inclusive-at-threshold `>=`, matching this
   file's own established "minimum means inclusive-pass" convention,
   e.g. `orb_min_confirmation_candles`'s existing `<` rejection, which
   passes exactly-at-minimum)
6. Overlap: with `zone_low = min(range_boundary, candidate.close)`,
   `zone_high = max(range_boundary, candidate.close)`, the gap overlaps
   iff `gap.gap_high >= zone_low and gap.gap_low <= zone_high` (inclusive
   interval overlap — touching endpoints count; ADR text does not
   specify strict vs. inclusive here, and inclusive is the simplest,
   most standard reading of "must overlap," consistent with every other
   inclusive-minimum threshold already in this file)

`evidence.volatility.atr <= 0` is already excluded by an earlier Phase 2
check (line ~114 of the current file) that runs before this code can be
reached — no defensive re-check needed here (CLAUDE.md §7: no defensive
code for scenarios that cannot occur at this point).

#### 2.3 FVG age semantics

**Decision: `age_bars = candidate.index - gap.end_index`, where
`candidate` is the same `post_range_bars[-1]` bar Phase 2 already
selected as the breakout candidate.** `end_index` (not `start_index`) is
used because `FairValueGap`'s own docstring defines it as "candle 3" —
the index at which the 3-candle imbalance is fully formed; "age" means
bars elapsed since the gap fully existed, measured against the breakout
event itself (§5's own framing: "weak confirmation of **a fresh
breakout**" — the breakout is the reference point, not the range's own
end). `candidate.index` and `gap.end_index` are independently confirmed
(Research §1) to share one index space within a single
`evaluate_snapshot()` call, so this subtraction is always meaningful,
never a cross-call or cross-symbol comparison.

**Boundary behavior — inclusive at the limit:** reject iff `age_bars >
config.orb_fvg_max_age_bars`; an FVG exactly `orb_fvg_max_age_bars` bars
old still qualifies. This mirrors this codebase's own established
staleness convention verbatim (`tests/deployment_windows/
test_positions_staleness_observability.py`'s documented precedent:
`waited_seconds > timeout`, not `>=` — "exactly at the threshold is not
yet stale"), not an invented boundary choice.

**Future/invalid index — fail-closed, explicit:** if `age_bars < 0`
(i.e. `gap.end_index > candidate.index`, an inverted/inconsistent index
that should not occur given both indices derive from the same bar
sequence, but is not provably impossible from the type system alone),
the gap is excluded from FVG confirmation — never treated as
"maximally fresh." This is the one explicit fail-closed rule this
question required (mirrors ADR-035 §14's general fail-closed-on-
ambiguity discipline): a negative age must not silently satisfy `age_bars
<= max_age_bars` and reward a broken invariant with a bonus.

### 3. Exact algorithm and insertion point

Inserted into `OrbBreakoutStrategy.qualify()` between the existing score/
confidence computation and the existing `qualified_result` construction
(current lines ~133-140) — no other line in the file changes:

```
required_direction = StructureDirection.BULLISH if trade_intent is TradeIntent.BUY else StructureDirection.BEARISH
zone_low = min(range_boundary, candidate.close)
zone_high = max(range_boundary, candidate.close)

qualifying_fvg = None
for gap in evidence.fair_value_gaps:
    if gap.direction != required_direction:
        continue
    if gap.filled:
        continue
    if gap.start_index < opening_range.range_start_index:
        continue
    age_bars = candidate.index - gap.end_index
    if age_bars < 0 or age_bars > config.orb_fvg_max_age_bars:
        continue
    if (gap.gap_high - gap.gap_low) < config.orb_fvg_min_size_atr_multiple * evidence.volatility.atr:
        continue
    if gap.gap_high < zone_low or gap.gap_low > zone_high:
        continue
    qualifying_fvg = gap
    break

fvg_bonus = 100.0 if qualifying_fvg is not None else 0.0
score = clamp(0.4 * session_value + 0.3 * mi_session_score + 0.3 * evidence.volatility.volatility_score + config.orb_fvg_score_weight * fvg_bonus)
```

`strengths` gains one additional entry, appended only when
`qualifying_fvg is not None`, e.g. `f"unfilled {qualifying_fvg.direction.value.lower()} FVG confirmation [{qualifying_fvg.start_index}-{qualifying_fvg.end_index}]"`
— mirrors `BosFvgStrategy`'s own strengths-text pattern (Research §3).
`weaknesses` gains no corresponding entry on absence (absence is neutral,
never a weakness, per §5's "never ignored... never mandatory" framing).
`confidence` is **not** modified by this insertion — see §5 (Risks) for
why, and why that is a deliberate, disclosed reading rather than an
oversight.

`orb_breakout.py` gains exactly one new import: `StructureDirection`
added to the existing `from titan_protocol.evidence_engine.models import
EvidenceSnapshot` line (mirrors `bos_fvg.py`'s identical import line —
no new upstream package, `titan_protocol.evidence_engine` is already an
allowed prefix).

**Ordering relative to Phase 2 and the lockout, explicit:** this block
only executes on the path that has already passed every one of Phase 2's
16 gating checks (it is textually and causally after all of them); it
never executes on any `_not_qualified(...)` return path. It runs
strictly before `try_consume()` (unchanged, still the last four lines of
`qualify()`), so the lockout consumes exactly the FVG-adjusted
`qualified_result`, never a stale pre-FVG one. **"Rejected FVG
confirmation must not consume qualification state" is satisfied by
construction, not by a special-cased skip:** because FVG confirmation
has no rejection outcome (§2.2 — it is score-only), there is no
FVG-rejection code path that could reach, or need to be prevented from
reaching, `try_consume()`. The lockout remains the sole, unconditional,
terminal side-effecting gate exactly as Step 2B already established.

### 4. Config contract and validation

Three new `StrategyEngineConfig` fields, added the same way Step 2B's
four fields were added (defaulted dataclass field, inline comment,
validated in the existing single `__post_init__`, no new method):

| Field | Type | Default | Validation |
|---|---|---|---|
| `orb_fvg_max_age_bars` | `int` | `10` | `>= 1` (ADR-035 §13 safe range) |
| `orb_fvg_min_size_atr_multiple` | `float` | `0.1` | `> 0` (ADR-035 §13 safe range) |
| `orb_fvg_score_weight` | `float` | `0.15` | `0.0 <= x <= 1.0` (ADR-035 §13 safe range; no cross-field check, §2.1) |

No cross-field validation function is added (§2.1). No change to
`approved_pairs_for()` or any other existing method. No change to
`DEFAULT_APPROVED_PAIRS_BY_STRATEGY` or `_ORB_APPROVED_CONFIG` (the test
fixture) — these three fields have no interaction with pair eligibility.

### 5. Worked adversarial examples

Shared fixture values throughout: `opening_range.range_start_index = 0`,
`range_high = 1.105`, `range_low = 1.095`, bullish `candidate.index = 10`,
`candidate.close = 1.108`, `evidence.volatility.atr = 0.001`,
`config.orb_fvg_max_age_bars = 3`, `config.orb_fvg_min_size_atr_multiple
= 0.1` (min size `= 0.0001`), `config.orb_fvg_score_weight = 0.15`.

| # | Scenario | Gap fields | Outcome |
|---|---|---|---|
| A | No FVG | `fair_value_gaps = ()` | `fvg_bonus=0.0`; score identical to pre-Phase-3 Step 2B output; `QUALIFIED` iff Phase 2 alone would qualify |
| B | Wrong-direction FVG | `direction=BEARISH`, otherwise fully eligible | excluded at predicate 1; `fvg_bonus=0.0` |
| C | Exact age boundary | `end_index=7` → `age_bars=10-7=3` | `3 > 3` is `False` → **passes** age filter (inclusive) |
| D | One bar too old | `end_index=6` → `age_bars=4` | `4 > 3` is `True` → excluded |
| E | Future/invalid index | `end_index=11` → `age_bars=-1` | excluded by the explicit `age_bars < 0` rule, never "maximally fresh" |
| F | Multiple FVGs | tuple order `[gap1 (wrong direction), gap2 (fully qualifies, end_index=8), gap3 (also qualifies, end_index=9)]` | `gap2` selected (first qualifying in tuple order); `gap3` never inspected after selection; `fvg_bonus=100.0` |
| G | Valid bullish FVG | `direction=BULLISH, filled=False, start_index=2, end_index=8, gap_high=1.107, gap_low=1.1065` | size `0.0005 >= 0.0001` ✓; zone `[1.105,1.108]`, gap `[1.1065,1.107]` overlaps ✓; **qualifies**, `fvg_bonus=100.0` |
| H | Valid bearish FVG (mirror) | `trade_intent=SELL, candidate.close=1.092`, `direction=BEARISH`, gap `[1.0925,1.0935]` | zone `[1.092,1.095]`, gap overlaps ✓; **qualifies** |
| I | Weight boundary, low | `orb_fvg_score_weight=0.0` | config accepts (boundary); qualifying FVG contributes `0.0` — feature effectively inert, never an error |
| I′ | Weight boundary, high | `orb_fvg_score_weight=1.0` | config accepts (boundary); max FVG contribution `1.0*100=100`; combined with the existing three terms' own max (`0.4+0.3+0.3=1.0` against 100-scale inputs, i.e. up to `100`), pre-clamp total can reach `200`, capped by the existing `clamp(value, 0.0, 100.0)` call to `100` — never invalid, never an exception |
| I″ | Weight out of range | `orb_fvg_score_weight=1.01` or `-0.01` | `ValueError` at `StrategyEngineConfig.__post_init__` — fails closed at startup, never at evaluation time |
| J | Otherwise-valid qualification + lockout interaction | genuine bullish breakout, qualifying FVG present, `orb_max_qualifications_per_range=1` | 1st `qualify()`: `QUALIFIED`, score boosted, `try_consume()` → `True` → returns `QUALIFIED`. 2nd `qualify()` on the identical `(pair, range_start)`: Phase 2 checks and FVG bonus computation are identical, `qualified_result` is rebuilt, but `try_consume()` → `False` → final result is `NOT_QUALIFIED` / `"Already qualified for this opening range"`, exactly Step 2B's existing behavior, **completely unaffected by FVG presence or absence** |

### 6. Risks / open questions (non-blocking, disclosed)

- **§2.1's degenerate cross-field check** (no sibling weights exist) is
  a deliberate reading, not an evasion — recorded here as the one place
  a future phase could revisit if all four weights are ever promoted to
  config fields together. Not required for Phase 3, not invented now.
- **`confidence` is not adjusted by FVG confirmation**, despite ADR-035
  §10's more general framing ("confidence... from range-quality/
  FVG-confirmation strength"). §5 — the section specifically titled "FVG
  confirmation" and the one with the actual algorithmic "Weighting"
  bullet — describes a score-only mechanism with no confidence term
  anywhere in its text. §10 is a higher-level risk-management framing
  section, not itself a second, competing mechanism spec. This Plan
  treats §5 as authoritative for the mechanism (it is the section
  ADR-035 §17's own Phase 3 roadmap entry names: "§5's weighted scoring
  addition") and §10's mention as already satisfied transitively
  (`confidence` continues to come from `session_component.confidence`,
  unchanged from Step 2B). Flagged here for the independent
  implementation-readiness reviewer to confirm or challenge — not
  silently buried.
- **Existing test regression risk:** none anticipated. Every existing
  test that does not pass `fair_value_gaps` to `_breakout_evidence()`
  will see `evidence.fair_value_gaps == ()` (the field's own existing
  default), so `qualifying_fvg` stays `None` and `fvg_bonus == 0.0` —
  numerically identical to today's score output for every one of the 41
  currently-passing tests. This must be verified, not merely asserted,
  during Implement-phase validation.

### 7. Boundaries — what this Plan explicitly does NOT do

- Does not modify `OrbQualificationStore`, its persistence format, or
  its concurrency guarantees in any way.
- Does not modify any of Phase 2's 16 existing gating checks or their
  order.
- Does not modify Evidence Engine, `FairValueGap`, or
  `detect_fair_value_gaps()` — confirmed sufficient as-is (§8).
- Does not register `OrbBreakoutStrategy` in `build_default_registry()`
  — registration remains no earlier than Phase 6 (ADR-035 §17),
  unchanged by this Plan.
- Does not touch any of the five legacy strategies.
- Does not add a graduated/weighted FVG-quality score — binary presence
  only (§2.2), by explicit decision, not oversight.
- Does not promote Phase 2's existing score-formula literals to config
  fields (§2.1).

### 8. Architectural-compliance confirmation (re-verified this pass, not merely carried from Research)

- Against ADR-001's pipeline: unchanged — Strategy Engine remains the
  sole stage touched; no cross-stage reach.
- Against ADR-035 itself: §5's mechanism, §13's three named fields
  (values as specified, cross-field clause resolved per §2.1), and §17's
  Phase 3 scope ("§5's weighted scoring addition... unit tests covering
  direction matching, age, size, overlap, and expiration" — all five
  covered in §5 of this Plan).
- Against ADR-026 (Strategy Engine) Hard Rules: no trade-decision
  vocabulary added, no position sizing/price level introduced, no new
  randomness, no shared mutable eligibility state — `test_architecture.py`
  re-run this pass (unchanged from Research §5, still PASS; `titan_protocol.evidence_engine`
  already covers the one new import).
- `tests/titan_protocol/compliance_state_store/test_structural_boundary.py`
  and `tests/titan_protocol/news_ingestion/test_structural_boundary.py`:
  both `_LATER_AUTHORIZED_EXCEPTIONS` allowlists already contain
  `titan_protocol/strategy_engine/config.py` and
  `titan_protocol/strategy_engine/strategies/orb_breakout.py` — the only
  two production files this Plan touches. **Re-confirmed, not assumed:
  zero new allowlist entries required for either file.**

### 9. File-impact matrix

| File | Change | New/Existing | Structural-boundary status |
|---|---|---|---|
| `titan_protocol/strategy_engine/config.py` | Add 3 fields + 3 `__post_init__` checks | Existing file | Already allowlisted (both boundary tests) |
| `titan_protocol/strategy_engine/strategies/orb_breakout.py` | Add `StructureDirection` import + FVG-selection block + `strengths` entry | Existing file | Already allowlisted (both boundary tests) |
| `tests/titan_protocol/strategy_engine/test_orb_breakout_foundation.py` | Extend `_breakout_evidence()` with an optional `fair_value_gaps` parameter; add one new test class | Existing file | Not a frozen-prefix file (tests are never in `_FROZEN_PREFIXES`) |
| `docs/plans/adr-035-phase3-fvg-confirmation.md` | This Plan | This document | N/A |
| Evidence Engine (any file) | **None** | — | N/A — confirmed sufficient as-is (§8, Research §1) |
| `docs/adr/ADR-024-evidence-engine.md` | **None** | — | N/A |
| Any structural-boundary allowlist | **None** | — | Re-confirmed §8 |

### 10. Test / validation matrix (for the Implement phase)

New test class in `test_orb_breakout_foundation.py` (exact name deferred
to Implement phase, e.g. `TestFvgConfirmation`), covering, at minimum,
examples A-J from §5 above, plus:
- Config validation: `orb_fvg_max_age_bars < 1`, `orb_fvg_min_size_atr_multiple
  <= 0`, and `orb_fvg_score_weight` outside `[0,1]` each raise
  `ValueError` (mirrors `TestConfigValidation`'s existing pattern).
- `test_defaults_match_adr_035`-style assertion extended for the three
  new fields' defaults (`10`, `0.1`, `0.15`).
- Full regression: all 41 currently-passing tests in this file must
  remain green with numerically unchanged `score` values wherever no
  `fair_value_gaps` are supplied (§6's disclosed non-regression claim,
  to be proven, not merely asserted).
- Full suite: `python -m unittest discover -s tests/titan_protocol`
  (1333/1333 baseline) plus the new tests, zero failures.
- `python -m compileall` on both touched production files plus the test
  file.
- `tests/titan_protocol/strategy_engine/test_architecture.py` and both
  `test_structural_boundary.py` files re-run green with zero new
  allowlist entries (proving §8/§9's claims empirically, not just by
  inspection).

## Validation

(Not started — Implement phase. This Plan authorizes no implementation;
an independent implementation-readiness review of this Plan must accept
it first, per this project's established Phase 2 precedent.)

---

**Disposition: PHASE 3 PLAN FINALIZED — READY FOR INDEPENDENT IMPLEMENTATION-READINESS REVIEW** (ADR-035 Phase 3, FVG Confirmation).

The three Research-phase questions (§4 of Research) are resolved with evidence in Plan §2.1-§2.3 above, not invented: score-weight cross-field validation (§2.1), the `fvg_bonus` formula (§2.2), and the FVG age reference index (§2.3). The adversarial re-read (this pass) found and corrected two defects before this disposition was set: a stale disposition line inherited from the Research pass, and an arithmetic error in worked example I′ — both fixed in place, not left standing.

**Implementation is not authorized by this document.** Per this project's established Phase 2 precedent, an independent implementation-readiness review of this finalized Plan must accept it before `/rpi:implement` may begin.
