# Plan: ADR-035 Phase 4 — Market Intelligence / Eligibility Integration for ORB

Status: **REVISED (2026-07-26) — PHASE 4 REMAINS BLOCKED, PENDING
ADR-035 AMENDMENT 1 INDEPENDENT REVIEW AND ACCEPTANCE.** This revision
responds to an independent implementation-readiness review of the prior
finalized Plan (commit `b550a97`), which returned **PHASE 4 PLAN
REQUIRES MAJOR REVISION** on three findings. Two are resolved directly
in this revision, within the existing Accepted contract (§3's `is_holiday`
gate addition; §2/§9/§6's tie-record correction). The third —
formation-time news-blackout enforcement — cannot be resolved within
Phase 4's existing scope without either violating this project's
Evidence-Engine/Strategy-Engine/Market-Intelligence ownership boundaries
or inventing unavailable historical state (see §9 and the newly-drafted
`ADR-035-orb-strategy.md` Amendment 1, **Proposed**, not yet Accepted).
Implementation of this Plan remains prohibited until Amendment 1 is
independently reviewed and formally Accepted, and this revised Plan then
receives its own independent implementation-readiness re-review — no
step of that sequence may be skipped or compressed.

Owner (Plan phase): Software Architect (ADR-035/ADR-025/ADR-026 owner precedent, unchanged)
Touched components (confirmed, expanded by one file from Research's anticipation — see §11): `titan_protocol/strategy_engine/strategies/orb_breakout.py`, `titan_protocol/strategy_engine/config.py`, `tests/titan_protocol/strategy_engine/test_orb_breakout_foundation.py`, `tests/titan_protocol/strategy_engine/_fixtures.py`. No other package. No Evidence Engine change, no Market Intelligence Engine change (both re-confirmed unnecessary below). No new structural-boundary allowlist entries (re-confirmed below, §10).

**Plan finalization — resolves both Research-flagged open questions with evidence, not invention (§§1-2 below):** (1) the exact "currently relevant" opening-range selection formula, derived from `compute_opening_ranges()`'s actual recomputation behavior and ADR-035 §3/§15's own words, not assumed; (2) explicit fail-closed behavior for a genuine multi-match — retained as defense-in-depth; **corrected this revision: the anchor-overlap guarantee this decision references already exists in production (§2, §9), it is not a still-open Phase 5 gap as originally claimed.** Also finalizes the Market Intelligence eligibility gate set (§3, **revised this pass to add an `is_holiday` gate**), an explicit predicate order (§4, renumbered), and disclosed, evidence-grounded scope limitations (§9) that this Plan does not silently paper over.

**Revision record (2026-07-26):** an independent implementation-readiness
review of the prior Plan (commit `b550a97`) found three issues, addressed
here: (1) formation-time news-blackout enforcement was silently narrowed
to evaluation-time-only with no ADR-level authorization — resolved by
drafting `ADR-035-orb-strategy.md` Amendment 1 (Proposed), see §9; (2)
`is_holiday` was excluded from the MI eligibility gate set on a
misreading of ADR-035 §2's "Holiday handling" row — resolved by adding
the gate, see §3/§4/§6/§10/§11; (3) the tie/multi-match Risk Register
entry incorrectly claimed the anchor-overlap guarantee "does not yet
exist" — resolved by correcting the record against directly re-verified
source, see §2/§9/§6 Example D. Every other section of the prior Plan
was independently re-confirmed unaffected by this revision and is
carried forward unchanged.

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

### 1. Resolved design decision 1: the exact "currently relevant" selection formula

**Decision: among all `opening_ranges` where `is_formed` is `True`, select the one with the greatest `range_end`. `is_valid` is checked afterward, on the selected range only — it plays no role in selection itself.**

Derivation, grounded in repository behavior, not invented:

1. `compute_opening_ranges()` (re-read again this pass) recomputes `range_start = now.replace(hour=..., minute=...)` fresh every cycle against `now`'s own calendar date. Within one trading day, once an anchor's window has been reached, that anchor's `range_start`/`range_end` stay **fixed for the rest of that calendar day**. Two anchors (e.g. London 07:00, New York 12:00) therefore both remain present in `opening_ranges`, both `is_formed=True`, simultaneously, for potentially many hours — confirmed in Research §2, re-verified here.
2. Because `is_formed = now >= range_end` never reverts to `False` once flipped, **"formed" alone cannot be the whole selection criterion** — under "formed" alone, both of the above ranges would stay eligible all day with no way to prefer one over the other. Something in ADR-035's own words must discriminate between them.
3. ADR-035 §3 states selection means "comparing the evaluation cycle's `now` against each `OpeningRangeState.range_start`/`range_end` directly." The only comparison of `now` against `range_end` that is already available, requires no new data, and yields a single deterministic answer among multiple formed ranges is: **which range's `range_end` is closest to (at or before) `now`** — i.e., the most recently completed range. This is also the only reading consistent with ORB's own stated purpose (§1: "capturing the volatility expansion that follows a session's opening consolidation") — a breakout confirmation concerns the most recently formed range's own post-range bars, not a stale range from many hours earlier in the same day.
4. Concretely: `max(r.range_end for r in formed_ranges)` requires no comparison against "now" at all once the `is_formed` filter has already been applied — `range_end` values are compared to each other, not re-derived from a fresh `now`. This avoids re-implementing Evidence Engine's own `is_formed` computation a second time in Strategy Engine (CLAUDE.md §1.3 — no duplicate logic) and needs no new parameter on `Strategy.qualify()` (Research §2's `now`-availability finding is therefore not even required by the final algorithm; recorded here for completeness only).
5. **`is_valid` is checked only after selection**, mirroring the existing single-range code's own sequential structure exactly (`is_formed` check, then `is_valid` check, both against the one range in play). Folding `is_valid` into the selection criterion itself (e.g. "prefer the most recent *valid* range, skipping invalid ones") would be new cascading-fallback policy this Plan has no ADR authority to invent — ADR-035 §15's "no ambiguity, no closest guess" framing argues directly against adding a fallback search. If the most recently formed range is invalid, ORB fails closed exactly as it already does today for the single-range case — it does not fall back to an older, valid range.

**This is the maximal formula ADR-035's own text supports without invention.** No stricter, more specific rule (e.g. an explicit staleness cutoff after which a formed range stops being "relevant") is stated anywhere in §3/§12/§15, and none is needed for determinism given non-overlapping windows — "greatest formed `range_end`" is already unique by construction once windows don't collide, with no additional threshold to invent.

### 2. Resolved design decision 2: genuine multi-match — explicit fail-closed behavior (record corrected this revision)

**Decision, unchanged: if more than one range shares the maximal qualifying `range_end` (a tie), return `NOT_QUALIFIED` unconditionally. Tuple order, arbitrary choice, or any other tie-break is explicitly rejected.**

**Correction (2026-07-26, this revision):** the prior text below claimed the anchor-overlap guarantee "does not yet exist at the config-validation layer" and was "Phase 5, not Phase 4" scope, citing ADR-035 §17's Phase 5 cross-field-validation entry. **This claim was independently re-verified against source this pass and found to be wrong.** `titan_protocol/evidence_engine/config.py`'s `EvidenceEngineConfig.__post_init__` (line 123) already calls `_validate_no_overlapping_anchors(self.opening_range_anchors, self.opening_range_duration_minutes)` (lines 126-145) — a check that **already exists in current production code** (implemented as part of Phase 0, not deferred to Phase 5) and rejects, at config-construction time, any two anchors whose `[range_start, range_end)` windows coincide or overlap. Direct execution confirms this:

```
EvidenceEngineConfig(opening_range_anchors=((SessionName.LONDON, 7, 0), (SessionName.EARLY_NEW_YORK, 7, 0)))
→ ValueError: opening_range_anchors[0] and opening_range_anchors[1] produce coincident or overlapping windows
```

Since `range_end = range_start + duration` with one shared `duration_minutes` across all anchors (re-confirmed below, unchanged from the prior analysis), and this validation already forbids any two anchors from sharing a `(start_hour_utc, start_minute_utc)` or an overlapping window, **it is not possible, under any config that has passed `EvidenceEngineConfig.__post_init__`, for two distinct formed ranges to ever share a `range_end`.** ADR-035 §15 states exactly this ("Startup validation (§13) rejects any two configured anchors whose windows would coincide or overlap, so at most one match is ever possible") — that guarantee is **already true today**, not a Phase 5 aspiration. The prior text's error was reading ADR-035 §17's Phase 5 entry ("cross-field checks... duplicate/overlapping anchors") as still-outstanding without re-checking whether the anchors' actual home (`EvidenceEngineConfig`, not `StrategyEngineConfig` — Research §1's own finding) already implements it independently of that Phase 5 entry's original, `StrategyEngineConfig`-scoped assumption.

**Consequence for this decision:** the tie-detection logic below remains correct and is retained, but as **defense-in-depth against an unreachable-today condition** — not because operators can, today, misconfigure two coincident/overlapping anchors (they cannot; `EvidenceEngineConfig` construction itself fails closed first). It guards against a future regression (e.g., if `_validate_no_overlapping_anchors` were ever weakened or bypassed) or a hand-constructed `EvidenceSnapshot` that did not originate from a validated `EvidenceEngineConfig` (as this file's own test fixtures already do via `_evidence_with_ranges()`). The underlying derivation (single shared duration ⇒ a tie requires identical `range_start`) is unchanged and still correct — only the claim that this state is "reachable via operator misconfiguration today" is retracted.

- This remains **not** an arbitrary choice among equally-plausible candidates — it is the direct, minimal consequence of ADR-035's own repeated "no ambiguity, no closest guess" language (§15) and its "never guess" fail-closed discipline (§14), applied the same way every other unresolvable-input case in this file already fails closed (e.g. `"No breakout: close within range"`, `"Insufficient volatility evidence"`) — now understood as belt-and-suspenders rather than a live gap.
- **Explicitly rejected as a resolution:** picking `currently_relevant[0]` (first in tuple order) — tuple order reflects `config.opening_range_anchors`' own declaration order, an accident of configuration, not a decision about which range is "more relevant." Using it as a tie-break would be exactly the "closest guess" ADR-035 forbids.
- **Explicitly rejected as a resolution:** silently disqualifying by falling through to the next-most-recent range — this would fabricate a selection the tie itself proves is ambiguous, and would silently mask a misconfiguration an operator needs to see and fix.
- **Reason string, corrected:** `"Multiple opening ranges are simultaneously relevant (unreachable under current anchor-overlap validation; retained as defense-in-depth)"` — the prior string ("ambiguous pending Phase 5 anchor-overlap validation") is retracted because it misstates that the validation is still pending.

No ADR amendment is required for this decision — this is a Plan-level, disclosed fail-closed policy choice for an input state that is already prevented by existing production validation, retained defensively, applying the same "never guess" discipline CLAUDE.md and ADR-035 already mandate everywhere else in this file.

**Explicit Plan decision — `trading_halted` and `broker_maintenance_active` (new this revision, resolving a gap the independent review flagged):** neither field is named anywhere in ADR-035 §2's eligibility table or §14's fail-closed list (both name only "Market closed / holiday" and, separately, spread/news/liquidity — no separate bullet for a broker halt or maintenance window). Repository-wide check, re-confirmed this pass: zero existing strategies (`grep -rn "trading_halted\|broker_maintenance" titan_protocol/strategy_engine/strategies/*.py` — no matches) check either field; both are left to downstream layers today. **Decision: Phase 4 does not gate on `trading_halted` or `broker_maintenance_active` directly**, consistent with this established, repository-wide precedent and with the absence of any ADR-035 text requiring it — ownership remains with whichever downstream layer (Compliance/Runtime/Bridge) already handles a halted/maintenance-mode broker. This is a disclosed Plan decision grounded in repository evidence, not a silent omission; §9 records it in the Risk Register.

### 3. Market Intelligence eligibility gate set — revised this pass (adds `is_holiday`)

Five gates (was four — `is_holiday` added this revision), all reusing already-existing `MarketIntelligenceSnapshot` fields (Research §3), no MI Engine change:

| Gate | Field checked | Operator | Reason string |
|---|---|---|---|
| Market closed | `pair_safety.market_safety.market_closed` | `if market_closed:` | `"Market closed"` |
| Holiday **(new this revision)** | `pair_safety.market_safety.is_holiday` | `if is_holiday:` | `"Holiday"` |
| News blackout | `pair_safety.news.blackout_active` | `if blackout_active:` | `"News blackout active"` |
| Maximum spread | `pair_safety.liquidity.current_spread` | `if current_spread > config.orb_max_spread_pips:` | `f"Spread {current_spread:.1f} exceeds maximum {config.orb_max_spread_pips}"` |
| Minimum liquidity | `pair_safety.liquidity.liquidity_score` | `if liquidity_score < config.orb_min_liquidity_score:` | `f"Liquidity score {liquidity_score:.1f} below minimum {config.orb_min_liquidity_score}"` |

**Field-name decision, corrected this revision:** the prior text excluded `is_holiday`, reasoning that ADR-035 §2's "Holiday handling" row names only `market_closed` "by its exact identifier." **This was a misreading, identified by independent review and confirmed against source this pass.** §2's row actually names *two* things: `MarketSafetyInputs.holidays` **and** `market_closed`. `MarketSafetyInputs` is never visible to Strategy Engine — only its derived `MarketSafetyStatus` is (via `MarketIntelligenceSnapshot.pair_safety.market_safety`) — and the only field on `MarketSafetyStatus` that corresponds to the `.holidays` mechanism the ADR names is `is_holiday`. Direct re-read of `titan_protocol/market_intelligence/market_safety.py` (lines 39, 45-46, 66-73) confirms `is_holiday = now.date() in inputs.holidays` and `market_closed = inputs.market_closed` are **structurally independent, externally-supplied facts with no derivation relationship between them** — a date being in the operator's `holidays` set does not imply `market_closed=True`, and vice versa (`MarketSafetyInputs` are, by that dataclass's own docstring, "externally-supplied facts this engine never derives itself"). Checking `market_closed` alone therefore does **not** fulfill the "Holiday handling" mechanism ADR-035 §2 names by citing `.holidays` — a holiday correctly recorded in `MarketSafetyInputs.holidays` but not redundantly also flagged `market_closed=True` would previously have passed through Phase 4's gates unnoticed, contrary to §2's row and §14's "Market closed / holiday" fail-closed pairing.

**This Plan now checks `market_closed` and `is_holiday` both.** `is_early_close`, `broker_maintenance`, and `trading_halted` remain deliberately **not** checked, on grounds independently re-verified this pass (not merely re-asserted): `is_early_close` is explicitly covered by ADR-035 §15's own edge-case row ("no further bars exist... fails closed by absence of data, not a special case to code for") — ORB needs no explicit gate because a range past an early close simply never receives further bars. `trading_halted`/`broker_maintenance_active` are addressed as an explicit Plan decision in §2 above (repository-wide precedent: no existing strategy checks either field; neither is named in §2/§14's ORB-specific text), not a silent omission.

**Operator convention, grounded in this file's own established pattern (Phase 2/3 precedent, re-verified against the current `__post_init__`):** minimum thresholds reject via strict `<` (exactly-at-minimum passes, e.g. `orb_min_breakout_distance_atr_multiple`'s existing check); by exact structural symmetry, the one new maximum threshold (`orb_max_spread_pips`) rejects via strict `>` (exactly-at-maximum passes). Not a new convention — the mirror image of one already in this file.

**"Liquidity" naming — kept unambiguous per Research §4:** `orb_min_liquidity_score` gates exclusively against `MarketIntelligenceSnapshot.pair_safety.liquidity.liquidity_score` (broker/market external-liquidity condition). It has no relationship to `LiquiditySweepMssStrategy`'s `liquidity_value` (Evidence Engine's structural liquidity-pool quality score) — a different strategy, a different engine, a different concept, never conflated in the implementation or its naming.

**Gate order, a disclosed Plan decision (ADR-035 does not mandate one):** market-closed → news blackout → spread → liquidity, running immediately after the existing `check_eligibility()` pair-whitelist gate and before the opening-range/session-anchor logic. Rationale: these are pair/market-level facts independent of any specific range's state ("is this pair tradeable in this market condition at all right now"), logically prior to "which range, if any, is currently relevant" — matching ADR-035 §2's own framing of both as "Market eligibility" facts, and matching §17's own listing order ("news/liquidity/holiday gates, eligibility hard gate" as one grouped concern preceding the breakout-specific logic named separately in §4/§5, already implemented).

### 4. Exact algorithm and predicate order

Full ordering inside `OrbBreakoutStrategy.qualify()`, from the top (unchanged code in plain text, new code in **bold** markers):

1. `check_eligibility()` pair-whitelist gate — **unchanged**.
2. **NEW** — market-closed gate (§3).
3. **NEW (added this revision)** — holiday gate (§3): `if is_holiday: return _not_qualified(pair, "Holiday")`.
4. **NEW** — news-blackout gate (§3).
5. **NEW** — maximum-spread gate (§3).
6. **NEW** — minimum-liquidity gate (§3).
7. `if not opening_ranges: return _not_qualified(pair, "No opening range configured for this evaluation cycle")` — **unchanged, exact string preserved** (existing test `TestOpeningRangeAbsence` asserts this exact path with no override needed).
8. **NEW** — `formed_ranges = [r for r in opening_ranges if r.is_formed]`; `if not formed_ranges: return _not_qualified(pair, "No opening range currently relevant (none yet formed)")`.
9. **NEW** — `latest_range_end = max(r.range_end for r in formed_ranges)`; `currently_relevant = [r for r in formed_ranges if r.range_end == latest_range_end]`; `if len(currently_relevant) > 1: return _not_qualified(pair, "Multiple opening ranges are simultaneously relevant (unreachable under current anchor-overlap validation; retained as defense-in-depth)")` — **reason string corrected this revision, see §2.**
10. `opening_range = currently_relevant[0]` (single element at this point, since step 9 has already ruled out ties).
11. `if not opening_range.is_valid: return _not_qualified(pair, "Opening range invalidated by a data gap or insufficient bar count")` — **unchanged code, now applied to the selected range** rather than `opening_ranges[0]`.
12. Post-range-bars presence, degenerate geometry, direction determination, momentum, ATR-distance, body/wick ratio, confirmation count, confirmation direction-consistency (Phase 2, steps unchanged, unreachable code touched).
13. Score/confidence computation, FVG-selection block, `strengths` construction (Phase 3, unchanged).
14. `qualified_result` construction (unchanged).
15. `try_consume()` lockout — **unchanged**, still the sole terminal side-effecting gate, still consuming `(pair, opening_range.range_start)` for whichever range was selected in step 9-10.

**No new `NOT_QUALIFIED` return is inserted after step 11** — every Phase 4 addition is either a pre-range-state eligibility gate (steps 2-6) or part of range *selection* (steps 8-9), never a change to Phase 2's breakout algorithm or Phase 3's FVG logic, both of which remain byte-for-byte as implemented in commit `bf2285b`.

**Formation-time news-blackout enforcement remains out of scope for this algorithm, per Amendment 1 (Proposed):** step 4's news-blackout gate is evaluation-time-only, on every cycle — it is not a change from the prior revision's design, only its governance status changed (§9).

### 5. Config contract and validation

Two new `StrategyEngineConfig` fields, following the exact pattern of all 7 existing `orb_*` fields (defaulted dataclass field, inline comment, validated in the single existing `__post_init__`, no cross-field check — neither field is a weight, so Phase 3's weight-sum deferral question does not apply here):

| Field | Type | Default | Validation |
|---|---|---|---|
| `orb_max_spread_pips` | `float` | `3.0` | `> 0` (ADR-035 §13 safe range) |
| `orb_min_liquidity_score` | `float` | `60.0` | `0.0 <= x <= 100.0` (ADR-035 §13 safe range) |

No change to `approved_pairs_for()`, `DEFAULT_APPROVED_PAIRS_BY_STRATEGY`, or `_ORB_APPROVED_CONFIG` — these two fields have no interaction with pair eligibility.

### 6. Worked adversarial examples

Shared fixture convention: two anchors, London (`range_start=07:00Z`, `range_end=07:30Z`) and New York (`range_start=12:00Z`, `range_end=12:30Z`), both `is_valid=True` unless stated otherwise. `orb_max_spread_pips=3.0`, `orb_min_liquidity_score=60.0` (defaults).

| # | Scenario | Outcome |
|---|---|---|
| A | Both London and NY formed, `now` well past both | `latest_range_end = 12:30Z` (NY) — NY selected; London ignored entirely, not merely deprioritized |
| B | Only London formed (before NY's 12:00Z start — NY absent from `opening_ranges` per `compute_opening_ranges()`'s own skip-if-not-started behavior, not merely `is_formed=False`) | `formed_ranges = [London]` — London selected, single-range path, identical to pre-Phase-4 behavior |
| C | Neither anchor's window has completed yet (e.g. `now` = 07:15Z, mid-formation) | `formed_ranges = []` → `NOT_QUALIFIED`, `"No opening range currently relevant (none yet formed)"` |
| D | **Corrected this revision — not operator-reachable.** Two anchors hand-constructed with the identical `(start_hour_utc, start_minute_utc)` (e.g. both "configured" for 07:00 UTC under different `SessionName` labels) — this can only be tested by directly constructing `OpeningRangeState` tuples (as this file's existing fixtures already do via `_evidence_with_ranges()`, bypassing `EvidenceEngineConfig`), never via a real `EvidenceEngineConfig(opening_range_anchors=...)`, which raises `ValueError` for this exact input (§2) | `currently_relevant` has 2 entries → `NOT_QUALIFIED`, `"Multiple opening ranges are simultaneously relevant (unreachable under current anchor-overlap validation; retained as defense-in-depth)"` — never tuple-order-selects either one; documented as a defense-in-depth test, not an operator-reachable scenario |
| E | NY selected (most recent) but `is_valid=False` (data gap) | `NOT_QUALIFIED`, `"Opening range invalidated by a data gap or insufficient bar count"` — London (formed, valid, but older) is never considered as a fallback |
| F | `market_safety.market_closed=True`, otherwise a fully qualifying breakout | `NOT_QUALIFIED`, `"Market closed"` — checked before any range logic runs |
| F′ | **New this revision.** `market_safety.is_holiday=True`, `market_closed=False`, otherwise a fully qualifying breakout | `NOT_QUALIFIED`, `"Holiday"` — checked immediately after the market-closed gate, before news blackout; confirms `is_holiday` gates independently of `market_closed` |
| G | `news.blackout_active=True`, otherwise qualifying | `NOT_QUALIFIED`, `"News blackout active"` |
| H | `current_spread=3.0` exactly (== `orb_max_spread_pips`) | passes (inclusive boundary, `>` is strict) |
| H′ | `current_spread=3.5` | `NOT_QUALIFIED`, `"Spread 3.5 exceeds maximum 3.0"` (chosen deliberately clear of `.1f`-rounding ambiguity — a value like `3.01` would display as `"3.0"`, cosmetically appearing not to exceed `3.0`, even though the underlying `>` comparison is exact and correct) |
| I | `liquidity_score=60.0` exactly (== `orb_min_liquidity_score`) | passes (inclusive boundary, `<` is strict) |
| I′ | `liquidity_score=59.9` | `NOT_QUALIFIED`, `"Liquidity score 59.9 below minimum 60.0"` |
| J | All four MI gates pass, single relevant range, otherwise-qualifying breakout with a qualifying FVG present | `QUALIFIED` — confirms Phase 2's breakout algorithm and Phase 3's FVG/score logic are fully preserved end-to-end with Phase 4's gates layered in front, and the lockout still consumes `(pair, opening_range.range_start)` for the selected range |
| K | Same as J, second `qualify()` call on the identical selected range | `NOT_QUALIFIED`, `"Already qualified for this opening range"` — lockout behavior unaffected by multi-range selection |

### 7. Boundaries — what this Plan explicitly does NOT do

- Does not add a new Strategy Engine session-anchor config field — `EvidenceEngineConfig.opening_range_anchors` (Phase 0) already owns this, confirmed sufficient (Research §1).
- Does not modify Evidence Engine or Market Intelligence Engine in any way — every field needed already exists (Research §3).
- Does not implement ADR-035 §13's anchor-overlap cross-field validation — that is explicitly Phase 5's scope (§17), unchanged by this Plan; §2 above specifies Phase 4's own required fail-closed behavior for the window before that validation exists, which is not the same thing as implementing the validation itself.
- Does not modify any of Phase 2's breakout-qualification steps, Phase 3's FVG-confirmation logic, or `OrbQualificationStore`'s persistence/concurrency semantics.
- Does not register `OrbBreakoutStrategy` in `build_default_registry()` — registration remains no earlier than Phase 6 (ADR-035 §17).
- Does not touch any of the five legacy strategies.
- **Revised this pass:** does check `is_holiday` (§3, added this revision). Does not check `is_early_close` (ADR-035 §15 explicitly covers this via bar absence — no gate needed), `broker_maintenance`, or `trading_halted` (§2's new explicit Plan decision — no ADR-035 text names either as an ORB gate, and no existing strategy checks them).
- **Does not implement formation-time news-blackout enforcement** — evaluation-time-only enforcement for Phase 4 requires `ADR-035-orb-strategy.md` Amendment 1 (Proposed, drafted this pass) to be independently reviewed and Accepted before this Plan may proceed to implementation (§9). Closing the underlying gap is out of scope for Phase 4 entirely — deferred to a new, unscheduled Phase 7 (Amendment 1).
- Does not add a fallback mechanism that selects an older, valid range when the most-recently-formed range is invalid, or when a tie is detected — both are explicit, disclosed "no closest guess" decisions (§§1-2), not omissions.

### 8. Architectural-compliance confirmation (re-verified this pass, not merely carried from Research)

- Against ADR-001's pipeline: unchanged — Strategy Engine remains the sole stage touched.
- Against ADR-035 itself: §2's five eligibility facts (pairs, sessions/anchors, spread, news, liquidity) and §3's Identification rule are now both fully specified (§§1-4 above); §17's Phase 4 scope ("session anchor matching... news/liquidity/holiday gates, eligibility hard gate, with unit tests for each gate") is fully covered.
- Against ADR-026 (Strategy Engine) Hard Rules: no trade-decision vocabulary added, no position sizing/price level introduced, no new randomness, no shared mutable eligibility state, no interface change to `Strategy.qualify()` (§1 confirms the `now`-parameter question is moot — the final algorithm needs no fresh `now`).
- `tests/titan_protocol/strategy_engine/test_architecture.py`: `titan_protocol.market_intelligence` already an allowed upstream prefix (used since Step 2B) — no new prefix needed, since Phase 4 introduces no new upstream import at all (re-confirmed: no new `import` line is required in `orb_breakout.py` for this phase, unlike Phase 3's `StructureDirection` addition).
- Both `test_structural_boundary.py` files: `_LATER_AUTHORIZED_EXCEPTIONS` already contain `titan_protocol/strategy_engine/config.py` and `titan_protocol/strategy_engine/strategies/orb_breakout.py` — the only two production files this Plan touches. **Re-confirmed, not assumed: zero new allowlist entries required.**

### 9. Risk register / disclosed limitations (revised this pass)

- **News-blackout timing gap — escalated to governance this revision, no longer a Plan-level disclosure alone.** ADR-035 §2 states news restrictions apply *"both during range formation and at breakout evaluation."* `OrbBreakoutStrategy.qualify()` is stateless (ADR-026) and only observes the *current* cycle's `MarketIntelligenceSnapshot` — there is no repository mechanism to record "was a blackout active while this specific range was forming" retroactively on `OpeningRangeState` (confirmed: the model has no news-related field). An independent implementation-readiness review of the prior Plan found that disclosing this gap in a Risk Register entry alone is insufficient governance action for a deviation from explicit Accepted-ADR text — recording a Plan-level limitation does not authorize it. **Resolution this revision:** two candidate closures were independently evaluated and both rejected as being outside Phase 4's own scope without further architectural review — (a) reconstructing formation-time blackout status inside Strategy Engine from `pair_safety.news.{active_events,recent_events,upcoming_events}`, rejected because it requires duplicating Market Intelligence's own blackout-window arithmetic inside Strategy Engine (an ownership-boundary violation) and is unreliable regardless (the bucket windows are sized independently of, and often narrower than, the actual blackout windows, so a formation-time-relevant event can silently age out of view before evaluation); (b) an Evidence-Engine dependency on Market Intelligence's news output to persist a formation-time flag on `OpeningRangeState`, rejected for this Plan's scope because Evidence Engine and Market Intelligence have no dependency relationship today and creating one is new architecture requiring its own review. **`ADR-035-orb-strategy.md` Amendment 1 (Proposed, drafted this pass, not yet Accepted) formally authorizes evaluation-time-only enforcement for Phase 4 as a staged limitation**, states the safety consequence in the ADR's own text, and assigns closing the gap to a new, explicitly unscheduled **Phase 7** — not folded into Phase 4, Phase 5, or Phase 6. **This Plan's implementation remains blocked until Amendment 1 receives its own independent review and formal Acceptance.**
- **Genuine multi-match — corrected this revision, no longer characterized as a live risk.** The prior text here claimed multi-match was "a real, reachable pre-Phase-5 state, not merely theoretical." Independent review found this claim factually wrong: `EvidenceEngineConfig.__post_init__` already validates no anchor overlap/coincidence (current production code, not Phase 5 — re-verified in §2, including a direct, executed reproduction). The tie-handling logic is retained as defense-in-depth against an unreachable-today condition (a possible future regression, or a hand-constructed `EvidenceSnapshot` bypassing config validation), not because operators can, today, trigger it through misconfiguration.
- **`trading_halted`/`broker_maintenance_active` — new explicit Plan decision this revision (§2):** neither is checked by Phase 4, grounded in repository-wide precedent (no existing strategy checks either field) and the absence of either from ADR-035 §2/§14's ORB-specific text. Ownership remains with downstream layers. Disclosed here, not silently omitted.
- **Gate ordering (§3) is a disclosed Plan decision**, not an ADR mandate — a future amendment could reorder these five gates without contradicting ADR-035's own text, since it does not specify an order.

### 10. File-impact matrix

| File | Change | Structural-boundary status |
|---|---|---|
| `titan_protocol/strategy_engine/config.py` | Add 2 fields + 2 `__post_init__` checks | Already allowlisted (both boundary tests) |
| `titan_protocol/strategy_engine/strategies/orb_breakout.py` | Add 5 MI eligibility gates (was 4 — `is_holiday` added this revision) + multi-range selection logic (§4); no new imports | Already allowlisted (both boundary tests) |
| `tests/titan_protocol/strategy_engine/test_orb_breakout_foundation.py` | Update `TestMultipleRanges`'s expected reason string (its existing fixture is already a genuine tie under the new rule — see below, reason string corrected this revision); add new test classes for range-selection (examples A-E, D corrected this revision) and MI eligibility gates (examples F-K, plus new F′ for `is_holiday`) | Not a frozen-prefix file |
| `tests/titan_protocol/strategy_engine/_fixtures.py` | Extend `make_liquidity_intelligence()` with two new optional parameters, `current_spread: float = 1.0` and `average_spread: float = 1.0`, defaulting to today's hardcoded values (zero behavior change for every existing caller) — needed because no existing fixture exposes spread as an override, only `liquidity_score`. **New this revision:** also extend `make_market_safety_status()` with one new optional parameter, `holiday: bool = False`, threading into `MarketSafetyStatus.is_holiday` (currently hardcoded `False` with no override — confirmed by direct re-read), zero behavior change for every existing caller | Not a frozen-prefix file; disclosed here as a small, backward-compatible, shared-fixture addition |
| Evidence Engine (any file) | **None** — confirmed sufficient as-is (§8, Research §3) | N/A |
| Market Intelligence Engine (any file) | **None** — confirmed sufficient as-is (§8, Research §3) | N/A |
| `docs/adr/*` | **None** | N/A |
| Any structural-boundary allowlist | **None** | Re-confirmed §8 |

**Important existing-test note:** `TestMultipleRanges.test_multiple_opening_ranges_returns_not_qualified_regardless_of_state`'s current fixture already constructs two `_make_opening_range()` calls with the *same default* `range_start` (neither call overrides it) — under the Phase 4 rule, this is exactly a **genuine tie** (identical `range_end`), not merely "more than one range." Its assertion must be updated from the old placeholder string to the new tie-specific reason string (§2); its setup requires no change.

**Disclosed, non-breaking reason-string changes (no assertion update required, noted for transparency):** `TestUnformedRange.test_unformed_range_returns_not_qualified` and `TestInvalidRange.test_invalid_range_returns_not_qualified` each assert only `status` and `trade_intent`, never the exact `reason` string — re-verified directly against the current test file. Under Phase 4, the single-range case in each test now passes through the new `formed_ranges`/`currently_relevant` selection logic before reaching the unchanged `is_formed`/`is_valid` checks, and `TestUnformedRange`'s specific reason string changes from `"Opening range not yet formed"` to `"No opening range currently relevant (none yet formed)"` (a more precise message for the generalized multi-range case). Both tests continue to pass unmodified; this is recorded so the Implement phase does not mistake the changed diagnostic text for a regression.

### 11. Test / validation matrix (for the Implement phase — Implement remains blocked, see Disposition)

- Update `TestMultipleRanges`'s expected `reason` to the corrected tie message (§2/§10).
- New test class (name deferred to Implement phase, e.g. `TestRangeSelection`) covering examples A-E from §6: NY-selected-over-London, single-range-unaffected, none-yet-formed, genuine-tie (D, documented as defense-in-depth, not operator-reachable), selected-range-invalid.
- New test class (e.g. `TestMarketIntelligenceEligibility`) covering examples F, F′ (new — `is_holiday`), G-K from §6: market-closed, holiday, news-blackout, spread-boundary (both sides), liquidity-boundary (both sides), full-pass-through-to-QUALIFIED, lockout-unaffected.
- Config validation: `orb_max_spread_pips <= 0` and `orb_min_liquidity_score` outside `[0, 100]` each raise `ValueError` (mirrors `TestConfigValidation`'s existing pattern); extend `test_defaults_match_adr_035` for both new fields' defaults (`3.0`, `60.0`).
- Full regression: all 60 currently-passing tests in this file must remain green; only `TestMultipleRanges`'s one reason-string assertion is expected to change — no other existing test's outcome should change, to be proven by running the suite, not assumed.
- Full suite: `python -m unittest discover -s tests/titan_protocol` (1352/1352 baseline) plus the new tests, zero failures.
- `python -m compileall` on all four touched files.
- `tests/titan_protocol/strategy_engine/test_architecture.py` and both `test_structural_boundary.py` files re-run green with zero new allowlist entries.
- `build_default_registry()` re-confirmed at exactly 5 `.register()` calls — ORB still absent.
- **Deferred, not this Plan's scope:** formation-time news-blackout closure (Phase 7, Amendment 1) will need its own dedicated test coverage once that phase is Researched, Planned, and its own governing amendment Accepted — not enumerated here.

## Validation

(Not started — Implement phase. This Plan authorizes no implementation.
Beyond the prior requirement of an independent implementation-readiness
review accepting this Plan, implementation is additionally blocked on
`ADR-035-orb-strategy.md` Amendment 1 receiving its own independent
review and formal Acceptance — see Disposition.)

---

## Adversarial re-read (this revision)

Performed against the complete, revised governance/Plan text (this
document plus the new ADR-035 Amendment 1) for contradictions:

- §2's corrected tie narrative and §9's corrected Risk Register entry
  now agree with each other and with the executed verification
  (`ValueError` on overlapping anchors) — no remaining reference in this
  document still claims the anchor-overlap guarantee is Phase 5 scope or
  "not yet enforced." Checked every occurrence of "Phase 5" and
  "overlap" in this file.
- §3's `is_holiday` gate, §4's renumbered predicate order, §6's new F′
  example, §10's fixture-extension entry, and §11's test-matrix entry
  are mutually consistent (same field, same reason string `"Holiday"`,
  same position — immediately after market-closed, before news-blackout
  — in all four places).
- §7's boundaries list no longer claims `is_holiday` is out of scope
  (corrected to reflect it is now checked), while continuing to
  correctly exclude `is_early_close`/`trading_halted`/`broker_maintenance`
  with source-grounded reasons, not a blanket restatement of the old
  claim.
- Confirmed no change anywhere in this revision touches Phase 2's
  breakout-qualification steps, Phase 3's FVG-confirmation logic, or the
  lockout's terminal/unconditional `try_consume()` semantics — §4's
  renumbering only shifts step *positions*, not their content or order
  relative to each other (post-range-bars through `qualified_result`
  remain in the same relative sequence, now steps 12-14 instead of
  11-13).
- Confirmed MI-rejection-cannot-consume-lockout is unaffected: the new
  `is_holiday` gate (like every eligibility gate) returns before
  `try_consume()` is ever reached, identical in structure to the
  existing market-closed/news/spread/liquidity gates.
- Confirmed no Phase 5, ORB registration, ADR-036, or legacy-strategy
  work was pulled into this revision — `build_default_registry()`,
  `DEFAULT_APPROVED_PAIRS_BY_STRATEGY`, and all five legacy strategy
  files remain unmentioned and untouched by any edit in this pass;
  re-verified via `git status --porcelain` showing only
  `docs/adr/ADR-035-orb-strategy.md` and this Plan file changed.

No contradiction found. This revision resolves findings 2 and 3 from
the independent implementation-readiness review directly; finding 1
(formation-time news-blackout) is escalated to Amendment 1 (Proposed),
not resolved within this Plan's own text, per the review's explicit
instruction not to silently weaken the ADR's requirement.

---

**Disposition: PHASE 4 REMAINS BLOCKED — ADR-035 AMENDMENT PROPOSED FOR INDEPENDENT REVIEW.**

Two of the three findings from the independent implementation-readiness
review (commit `b550a97`) are resolved directly within the existing
Accepted contract: the `is_holiday` gate is added (§3/§4/§6/§10/§11),
and the tie/multi-match record is corrected against independently
re-verified source (§2/§9/§6 Example D), including an explicit,
evidence-grounded Plan decision on `trading_halted`/`broker_maintenance_active`
(§2/§9). The third finding — formation-time news-blackout enforcement —
cannot be resolved within Phase 4's existing scope without either
violating this project's Evidence-Engine/Strategy-Engine/Market-Intelligence
ownership boundaries or inventing unavailable historical state (§9); it
is addressed by drafting `ADR-035-orb-strategy.md` Amendment 1
(**Proposed**, not Accepted), which explicitly authorizes evaluation-time-only
enforcement for Phase 4 as a staged limitation, states its safety
consequence, and assigns closing the gap to a new, unscheduled Phase 7.

**Phase 4 implementation remains prohibited** until Amendment 1
receives its own independent review and is formally Accepted, after
which this revised Plan must itself receive a fresh independent
implementation-readiness re-review before `/rpi:implement` may begin.
**Phase 5 remains unauthorized regardless of this revision's outcome.**
