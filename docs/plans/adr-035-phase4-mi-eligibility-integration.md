# Plan: ADR-035 Phase 4 — Market Intelligence / Eligibility Integration for ORB

Status: **Research**
Owner (Plan phase): Software Architect (ADR-035/ADR-025/ADR-026 owner precedent, unchanged)
Touched components (anticipated, confirmed below): `titan_protocol/strategy_engine/strategies/orb_breakout.py`, `titan_protocol/strategy_engine/config.py`, `tests/titan_protocol/strategy_engine/test_orb_breakout_foundation.py`. No other package.

---

## Research

### 0. Governance gate (verified against current HEAD, not assumed)

- HEAD: `bf2285bf8fb001aeccbe9d9327c9d69b9eab470e`, working tree clean, matches remote.
- `ADR-035-orb-strategy.md`: **Accepted** (2026-07-25, §§0-16 and §17). Phase 4 is explicitly item 4 of the Accepted §17 roadmap: *"Phase 4 — Market Intelligence/eligibility integration: session anchor matching (using §3's corrected identification rule), news/liquidity/holiday gates, eligibility hard gate, with unit tests for each gate."*
- Phase 3 (FVG confirmation) is fully implemented (commit `bf2285b`) and independently conformance-reviewed with no findings. No open Phase 3 item remains.
- **§17's Phase 4 entry names no further-Accepted-ADR precondition**, unlike Phase 2's Amendment-4 gate. This Research phase's job was to check whether Phase 4 has an equivalent hidden gap. It does not for Evidence Engine or Market Intelligence Engine (§1/§3 below) — every field Phase 4 needs already exists. It does surface two genuine open design questions (§5/§6 below) that gate Plan finalization, not this disposition.
- `python3 scripts/check_architecture.py`: PASS (scans `phantom_pipeline/`, the reference-only legacy tree — not evidence about this `titan_protocol` change, run only because TEAM.md §9 names it as the mandatory check; `tests/titan_protocol/strategy_engine/test_architecture.py` is this change's actual governing check, re-confirmed clean in §7 below).

### 1. Session-anchor configuration — already exists, but in Evidence Engine, not Strategy Engine

ADR-035 §13's config table lists `orb_session_anchors` as a `StrategyEngineConfig`-scoped field. Direct inspection of the current repository shows this is **already implemented**, but as `EvidenceEngineConfig.opening_range_anchors: Tuple[Tuple[SessionName, int, int], ...] = ()` (Phase 0, `titan_protocol/evidence_engine/config.py`) — the multi-anchor mechanism ADR-035 §3 describes was built as part of Phase 0's Evidence Engine amendment, not deferred to a later Strategy Engine field. `titan_protocol/strategy_engine/config.py` (re-grepped in full at current HEAD) has **zero** `orb_session_anchors`-equivalent field.

**Consequence: Phase 4 needs no new session-anchor config field.** Its "session anchor matching" scope (§17) is pure consumption logic inside `OrbBreakoutStrategy.qualify()` against the already-plural `EvidenceSnapshot.opening_ranges`, not a new configuration surface.

### 2. The exact placeholder Phase 4 must replace — confirmed by direct code read

`titan_protocol/strategy_engine/strategies/orb_breakout.py` (current HEAD) contains, verbatim:
```python
if len(opening_ranges) > 1:
    return _not_qualified(pair, "Multiple opening ranges configured, cannot disambiguate before Phase 4")
```
This is the exact, explicitly-named placeholder Step 2B's own Plan left for Phase 4 to resolve. Phase 4's "session anchor matching" scope is precisely: replace this blanket rejection with ADR-035 §3's "Identification" rule — select whichever configured range's `range_start`/`range_end` window is currently relevant to the evaluation cycle, never matching by `session` alone (`SessionName` cannot disambiguate two anchors sharing the same coarse session).

**`compute_opening_ranges()` (Evidence Engine, re-read in full) confirms multiple simultaneously-formed ranges is an everyday occurrence, not a rare edge case:** `range_start = now.replace(hour=..., minute=...)` is recomputed fresh every cycle against `now`'s own calendar date, so with two anchors configured (e.g. London 07:00 UTC, New York 12:00 UTC), any cycle after both anchors' `range_end` has elapsed will have **both** ranges present in `opening_ranges`, both `is_formed=True`. This is not hypothetical — it is the normal, expected state for any multi-anchor configuration during the trading day.

**`now` availability inside `qualify()`, confirmed:** `Strategy.qualify()`'s interface (`titan_protocol/strategy_engine/strategies/base.py`) has no `now` parameter. But `EvidenceReport.generated_at` (already on `evidence.report`) carries the exact same `now` Evidence Engine used to compute `opening_ranges` in the same cycle. No interface change to `Strategy.qualify()` is needed — confirmed by direct model inspection, not assumed.

### 3. Market Intelligence contract — every field ADR-035 §2 needs already exists

Direct read of `titan_protocol/market_intelligence/models.py` in full confirms `MarketIntelligenceSnapshot.pair_safety` already exposes every field §2's table names:
- `pair_safety.news.blackout_active` (`PairNewsIntelligence`) — news restrictions.
- `pair_safety.liquidity.liquidity_score` and `pair_safety.liquidity.current_spread` (`LiquidityIntelligence`) — low-liquidity handling and maximum-spread checks, both on the same object.
- `pair_safety.market_safety.market_closed` / `.is_holiday` (`MarketSafetyStatus`) — holiday/market-closed handling.
- `pair_safety.session.session_score` (`SessionIntelligence`) — already consumed since Step 2B for scoring, not eligibility.

**Conclusion: Phase 4 requires zero Market Intelligence Engine changes** — the second consecutive ORB phase (after Phase 3's zero-Evidence-Engine-change finding) needing no companion engine amendment.

### 4. Existing precedent — reuse confirmed for news, genuinely new field access for spread/liquidity/holiday

`SessionBreakoutStrategy` (re-read in full) already checks `market_intelligence.pair_safety.news.blackout_active` exactly as ADR-035 §2 says ORB should — direct, reusable precedent, no new pattern needed for the news gate.

**No existing strategy checks `pair_safety.liquidity.liquidity_score`, `pair_safety.liquidity.current_spread`, or `pair_safety.market_safety.market_closed`/`.is_holiday`.** Grepped all five legacy strategies directly. This is genuinely new field access for Strategy Engine, though mechanically trivial (the same well-established "if condition: return NOT_QUALIFIED" shape every other gate in this codebase already uses) — flagged here so the Plan doesn't overstate this as pure copy-paste reuse.

**Naming collision to flag explicitly, so no implementer confuses the two:** `LiquiditySweepMssStrategy` already has a check named `liquidity_value < config.liquidity_sweep_min_liquidity_score` — but `liquidity_value` there is `component(evidence.report, "liquidity")`, **Evidence Engine's own structural liquidity-pool quality score**, an entirely different concept from **Market Intelligence's `pair_safety.liquidity.liquidity_score`** (a broker/market external-liquidity condition, spread-derived). ADR-035 §2 explicitly names the Market Intelligence one. The Plan must be unambiguous about which "liquidity" ORB's new `orb_min_liquidity_score` field gates against.

### 5. Open design question 1 (safety-relevant, flagged, not decided here): ambiguous multi-match before Phase 5's overlap guarantee exists

ADR-035 §15's own "Multiple ranges" edge-case row states: *"Startup validation (§13) rejects any two configured anchors whose windows would coincide or overlap, so at most one match is ever possible."* This is the ADR's own stated basis for why the Identification rule's selection is unambiguous.

**But §17's own Phase 5 entry assigns that exact cross-field validation ("duplicate/overlapping anchors") to Phase 5, not Phase 4** — independently re-confirmed at the same location this Research phase used to resolve Phase 3's analogous weight-sum question. **Consequence: if Phase 4 is implemented (as instructed) before Phase 5, the guarantee §15 relies on to claim "at most one match is ever possible" does not yet exist at the config-validation layer.** An operator could, today, configure two anchors whose windows genuinely overlap, and Phase 4's selection logic would then face a real ambiguity the ADR's edge-case table assumes cannot occur.

This is not an architectural conflict requiring an ADR amendment — CLAUDE.md's own fail-closed/never-guess discipline and ADR-035's own repeated "no ambiguity, no closest guess" framing point toward an available, safe resolution (e.g., treat a genuine multi-match as itself a fail-closed `NOT_QUALIFIED` condition, pending Phase 5's own overlap-prevention validation). But this Research phase will not silently choose that resolution — **the Plan phase must explicitly state and justify the exact behavior when more than one opening range is simultaneously "currently relevant," not leave it to be invented at implementation time.**

### 6. Open design question 2 (narrower, flagged, not decided here): exact "currently relevant" selection formula

Even in the ordinary (non-overlapping) case, ADR-035's text ("comparing the evaluation cycle's `now` against each `OpeningRangeState.range_start`/`range_end` directly") states the comparison's *inputs* but not the exact selection rule when, e.g., one range is already formed and a second range's `range_end` is more recent. The natural reading — select the range with the greatest `range_end <= now` among formed, valid ranges (i.e. the most recently completed one, since a breakout confirmation concerns "the most recent closed bar," not a stale range from hours ago) — is not stated as such anywhere in ADR-035 §3/§12/§15. **The Plan phase must specify this exact formula**, the same way Phase 3's Plan had to specify the exact `age_bars` reference index ADR-035 §5 left unstated.

### 7. Config and test precedent — confirmed pattern, no surprises

`titan_protocol/strategy_engine/config.py`'s existing 7 `orb_*` fields (Step 2B's 4, Phase 3's 3) establish the exact pattern Phase 4's two new fields (`orb_max_spread_pips`, `orb_min_liquidity_score`, per ADR-035 §13) will follow: a defaulted dataclass field with an inline comment, validated in the single existing `__post_init__`. Neither field is a weight in a scoring formula (they are independent floor/ceiling gates), so neither raises the cross-field-validation question Phase 3 had to resolve for `orb_fvg_score_weight`.

`tests/titan_protocol/strategy_engine/test_orb_breakout_foundation.py` (currently 60 tests, all green after Phase 3) already establishes every fixture pattern Phase 4 needs: `_make_opening_range()` (will need a second, differently-anchored range for multi-range tests), `_evidence_with_ranges()` (already accepts `*ranges`, i.e. already supports multiple `OpeningRangeState` arguments — confirmed by re-reading its signature, no helper extension needed for that part), and `make_mi_snapshot()` (will need inspection for how to override `pair_safety.news/liquidity/market_safety` fields per test — to be confirmed in the Plan phase, not assumed here).

### 8. Architecture-boundary check — clean, zero new entries anticipated

- `tests/titan_protocol/strategy_engine/test_architecture.py`: `ALLOWED_UPSTREAM_PREFIXES` already includes `titan_protocol.market_intelligence` (used since Step 2B) — no new prefix required, since Phase 4 introduces no new upstream package.
- Both `test_structural_boundary.py` files: `_LATER_AUTHORIZED_EXCEPTIONS` already contain `titan_protocol/strategy_engine/config.py` and `titan_protocol/strategy_engine/strategies/orb_breakout.py` — the only two production files Phase 4 is expected to touch. **Zero new entries anticipated**, matching the pattern Phase 3 already established (a real difference from Phase 2, which needed a first-time entry).

### 9. Duplicate-logic / regression check

No duplicate MI-consumption logic — `pair_safety.news.blackout_active` reuses `SessionBreakoutStrategy`'s exact pattern; the spread/liquidity/holiday checks are new field access but not new mechanisms (same `if condition: NOT_QUALIFIED` shape every strategy already uses). No duplicate session/opening-range computation — Phase 4 consumes `evidence.opening_ranges` as-is, adds no second range-selection mechanism elsewhere. The five legacy strategies remain read-only precedent. `git status --porcelain` at this Research pass's own HEAD is clean.

---

## Plan

(Not started — next phase. Must explicitly resolve §5 and §6's open questions with evidence, not invent them silently, before finalization.)

## Validation

(Not started — next phase.)

---

**Disposition: PHASE 4 RESEARCH COMPLETE — READY FOR PLAN FINALIZATION** (ADR-035 Phase 4, Market Intelligence / Eligibility Integration).

Two open design questions are explicitly flagged for the Plan phase to resolve with evidence, not invent during implementation: (1) exact behavior when more than one opening range is simultaneously "currently relevant" — a real possibility before Phase 5's own anchor-overlap validation exists — including whether to fail closed as `NOT_QUALIFIED` pending that guarantee; (2) the exact selection formula (most likely "greatest `range_end <= now` among formed, valid ranges," but not yet ADR-stated precisely enough to implement without inventing). Neither is an architectural conflict requiring an ADR amendment; both are Plan-finalization-scoped decisions in the same class as Phase 3's three resolved open questions.

Recommend proceeding to `/rpi:plan` for this document.
