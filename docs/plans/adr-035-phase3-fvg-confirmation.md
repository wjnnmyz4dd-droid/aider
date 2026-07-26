# Plan: ADR-035 Phase 3 — FVG (Fair Value Gap) Confirmation for ORB

Status: **Research**
Owner (Plan phase): Software Architect (ADR-035/ADR-024/ADR-026 owner precedent, unchanged)
Touched components (anticipated, confirmed below): `titan_protocol/strategy_engine/strategies/orb_breakout.py`, `titan_protocol/strategy_engine/config.py`, `tests/titan_protocol/strategy_engine/test_orb_breakout_foundation.py`. No other package.

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

(Not started — next phase.)

## Validation

(Not started — next phase.)

---

**Disposition: STEP/PHASE RESEARCH COMPLETE — READY FOR PLAN FINALIZATION** (ADR-035 Phase 3, FVG Confirmation).

Recommend proceeding to `/rpi:plan` for this document. The Plan phase must explicitly resolve the three items in §4 above (weight-sum cross-field validation scope, `fvg_bonus`'s exact value formula, and the age reference-index) rather than leaving them to be invented during implementation.
