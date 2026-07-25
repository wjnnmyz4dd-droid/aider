# Plan: ADR-035 Phase 0 — Evidence Engine Amendment (OpeningRangeState)

Status: Planned
Owner (Plan phase): Software Architect (per ADR-035's own Owner field — this Plan executes that ADR's Research artifact for Phase 0 only)
Touched components: `titan_protocol/evidence_engine/` only

---

## Research

- **Affected files and their dependencies:** `titan_protocol/evidence_engine/models.py`, `config.py`, `engine.py`, plus one new file, `opening_range.py`. All dependencies (`Bar`, `FairValueGap`, `EvidenceEngineConfig`, `_analyze()`'s existing pass) confirmed by direct read this session (see §3 of this plan).
- **Touched stage's ADR status:** ADR-024 (Evidence Engine) — Accepted. ADR-035 — Accepted (this Plan exists because it is). CLAUDE.md §1.10 satisfied: Phase 0 is this ADR's own first stage, already reviewed.
- **Duplicate logic / potential regressions found:** none — Phase 0 adds one new computation reusing the exact `bars`/`now` inputs `_analyze()` already receives; no existing function is modified in place, no existing field is removed or renamed.
- **`python3 -m unittest tests.titan_protocol.evidence_engine.test_architecture` result:** not yet re-run for this change (nothing implemented); this is the actual `titan_protocol`-aware architectural check for this package (verifies no forbidden import of `phantom_pipeline`/`titan_protocol.bridge`, no trade-decision vocabulary, no randomness/ML import, no network/file I/O import) — confirmed passing against the current, pre-Phase-0 source this session, and not expected to change, since Phase 0 introduces no forbidden import (§4, §6 below). (`scripts/check_architecture.py` is not used as a verification gate for this change: direct read confirms its `PACKAGE_ROOT` is hardcoded to `phantom_pipeline`, with zero reference to `titan_protocol` anywhere in the script — it validates the legacy namespace only and cannot observe anything this Phase changes.)

## Plan

(Sections 1-18 below constitute the Plan in the detail this task requires; the terse template fields above are filled for consistency with `docs/plans/`'s existing convention and are not a substitute for them.)

---

## 1. Phase Objective

Phase 0 exists to give Evidence Engine — and only Evidence Engine — the capability to compute and expose a fixed-width "opening range" fact (`OpeningRangeState`) as part of the `EvidenceSnapshot` it already produces. Today, Evidence Engine can describe a session's broad hour-boundary window (`SessionName`, `session.py`) and an unbounded running session high/low (`SupportResistanceContext.session_high`/`session_low`, `support_resistance.py`), but nothing in the repository computes a narrow, fixed-duration range anchored to a specific configured start time — confirmed absent by direct grep of `evidence_engine/config.py` and `models.py` (zero `Timeframe`/fixed-range concept found). Every later ADR-035 phase (1 through 6) depends on this fact existing on `EvidenceSnapshot` before any strategy code can be written — Phase 1 cannot "consume `opening_ranges`" (ADR-035 §17) if the field doesn't exist yet. This is strictly an Evidence Engine capability addition; it introduces no strategy, no qualification logic, and no new package.

## 2. Repository Evidence Summary

Verified directly this session:

- `EvidenceEngine._analyze(bars, now)` (`engine.py`) is the **single shared computation pass** behind both `evaluate()` and `evaluate_snapshot()` — it already calls `analyze_market_structure`, `analyze_liquidity`, `recognize_patterns`, `analyze_volatility`, `classify_trend`, `analyze_session`, and `detect_fair_value_gaps`, all against the same `bars: Sequence[Bar]` and `now: datetime`. This is the one place a new computation must be added so it is never recomputed twice and never diverges between `evaluate()`/`evaluate_snapshot()` (ADR-024 Amendment 1 Hard Rule 9).
- `EvidenceSnapshot` (`models.py`) is assembled in `evaluate_snapshot()` from exactly the values `_analyze()` returns, plus `support_resistance` (computed separately, also from the same pass's outputs). `fair_value_gaps: Tuple[FairValueGap, ...] = ()` is the most recent precedent for adding a new, defaulted, additive field to this type.
- `FairValueGap.start_index`/`end_index` (`models.py`) are plain integer positions into the **same** `bars` argument passed to `_analyze()` — confirmed directly in `structure.py::detect_fair_value_gaps()` (`start_index=i - 2, end_index=i`, `i` being a loop index over `bars`). This is why `OpeningRangeState.range_start_index`/`range_end_index`, computed the same way, are directly comparable to them with no conversion.
- `EvidenceEngineConfig` (`config.py`) already carries plain, engine-owned integer-hour fields for its own session concept (`asian_session_start_hour`, `london_session_start_hour`, `new_york_session_start_hour`, etc.) — the established precedent for where new, Evidence-Engine-owned time-boundary configuration belongs, as opposed to `StrategyEngineConfig` (a different package, which ADR-035 §13 already scopes its own `orb_session_anchors`/`orb_range_duration_minutes` fields to — see §8 of this plan for how the two relate).
- `support_resistance.py::session_high_low(bars, now, config)` is the closest existing function signature precedent for a new "range from bars" computation — same three-argument shape, same module-per-concern pattern as `session.py`'s own separation from it despite conceptual overlap (ADR-035 §18.A item 1's own stated assumption, adopted here).
- Test convention (`tests/titan_protocol/evidence_engine/`): one test file per concern (`test_structure.py`, `test_support_resistance.py`, `test_trend_volatility_session.py`, ...) — Phase 0's tests belong in a new `test_opening_range.py`, matching this pattern exactly, not appended to an existing file.

## 3. Current Architecture Assessment

Evidence Engine's pipeline, as it exists today, in the order `_analyze()` calls it: market structure → liquidity → candlestick patterns → volatility → trend → session → component scores → evidence score → fair value gaps. `evaluate_snapshot()` additionally computes `support_resistance` from those same outputs. `OpeningRangeState` computation belongs as one more step inside `_analyze()`, positioned after `detect_fair_value_gaps()` (no dependency on it, order otherwise doesn't matter) and requires no output from any other step — it needs only `bars` and `now`, exactly like `detect_fair_value_gaps(bars)` itself needs only `bars`. It must be threaded into `EvidenceSnapshot` alongside `fair_value_gaps`; `evaluate()` (which returns a plain `EvidenceReport`, not a snapshot) is unaffected and requires no change, since `EvidenceReport` doesn't carry structural facts at all (confirmed — `evaluate()`'s return value construction, `build_evidence_report(symbol, now, evidence_score)`, uses none of the raw structural values).

## 4. Files Affected Matrix

| File | Classification | Reason |
|---|---|---|
| `titan_protocol/evidence_engine/models.py` | **MODIFIED** | Add `OpeningRangeState` dataclass; add `opening_ranges: Tuple[OpeningRangeState, ...] = ()` to `EvidenceSnapshot`; add both to `__all__`. Every other type in the file is untouched. |
| `titan_protocol/evidence_engine/config.py` | **MODIFIED** | Add the new anchor-list and expected-bar-interval fields (§8, §6 below) to `EvidenceEngineConfig`, following the existing plain-field, no-nested-object convention already used for session hours. No existing field changes value or meaning. |
| `titan_protocol/evidence_engine/opening_range.py` | **NEW** | Houses the range-computation function(s) — mirrors `support_resistance.py`/`session.py` as separate, single-concern modules (ADR-035 §18.A item 1). |
| `titan_protocol/evidence_engine/engine.py` | **MODIFIED** | `_analyze()` gains one more call (opening-range computation); `evaluate_snapshot()`'s `EvidenceSnapshot(...)` construction gains `opening_ranges=...`. `evaluate()` is **not** modified — it never returns a snapshot and has no use for this fact. |
| `titan_protocol/evidence_engine/__init__.py` | **MODIFIED** | Export `OpeningRangeState` (and any newly-public helper, if `opening_range.py` exposes one beyond the main computation function) the same way `FairValueGap`/`detect_fair_value_gaps` are already exported, if that is this package's existing export convention (verify against current `__init__.py` before implementation; do not assume). |
| `titan_protocol/evidence_engine/structure.py` | **READ ONLY** | `FairValueGap`'s index convention is read to ensure `opening_range.py`'s indices match it; nothing in this file changes. |
| `titan_protocol/evidence_engine/support_resistance.py`, `session.py` | **READ ONLY** | Precedent only — confirms module-separation and function-signature conventions; neither file is touched, per ADR-035 §18.A item 1's own assumption. |
| `titan_protocol/market_data_ingestion/*` | **READ ONLY** | Confirms (again) that no gap signal or `Timeframe` concept is imported from this package — Phase 0 must not create this cross-package dependency (§6 below). |
| `titan_protocol/strategy_engine/*` | **READ ONLY** | Out of scope entirely (§12) — read only to confirm no Phase 0 change is needed there. |
| `tests/titan_protocol/evidence_engine/test_opening_range.py` | **NEW** | Phase 0's own test suite (§10). |
| `tests/titan_protocol/evidence_engine/test_architecture.py` | **READ (existing coverage)** | The package's actual `titan_protocol`-aware architectural check (forbidden `phantom_pipeline`/`titan_protocol.bridge` imports, trade-decision vocabulary, randomness/ML imports, network/file I/O imports) — re-run unmodified as part of validation (§11, §14); not itself changed by Phase 0. |
| `tests/titan_protocol/evidence_engine/test_engine.py`, `test_boundary.py`, `test_regression.py`, `test_determinism.py`, `test_property.py` | **MODIFIED or READ, TBD at implementation time** | Existing snapshot/regression/determinism/property tests construct `EvidenceSnapshot` and/or call `evaluate_snapshot()`; since `opening_ranges` defaults to `()`, these should continue to pass unmodified unless a test asserts an exhaustive field list, in which case it needs the new field added to its expectations — verify, don't assume, at implementation time. |
| Any file outside `titan_protocol/evidence_engine/` and its own tests | **DELETE** | None expected — Phase 0 touches no other package (§12). |

## 5. Model Changes

**`OpeningRangeState`** (new, `models.py`):

| Field | Type | Purpose |
|---|---|---|
| `session` | `SessionName` | Descriptive only (ADR-035 §3's "Identification" correction) — which broad session window this anchor falls within. Never used to disambiguate one range from another. |
| `range_start` | `datetime` | First included closed bar's `timestamp` (`Bar.timestamp`). |
| `range_end` | `datetime` | `range_start + configured duration`. |
| `range_start_index` | `int` | Position of the first included bar within the `bars` sequence `_analyze()` received. |
| `range_end_index` | `int` | Exclusive upper bound of included bars, in the same index space as `FairValueGap.start_index`/`end_index`. |
| `range_high` | `float` | Max high of included closed bars. |
| `range_low` | `float` | Min low of included closed bars. |
| `range_midpoint` | `float` | `(range_high + range_low) / 2`. |
| `is_formed` | `bool` | `True` once `range_end` has fully elapsed relative to `now`. |
| `is_valid` | `bool` | `False` on insufficient bar count or a detected temporal gap (§6). |

- **Owner:** Evidence Engine (`titan_protocol/evidence_engine/`), per ADR-035 §3 — generic market evidence, not Strategy-Engine-owned.
- **Relationships:** produced independently per configured anchor; held in `EvidenceSnapshot.opening_ranges: Tuple[OpeningRangeState, ...]` (plural, additive, defaulted to `()` exactly like `fair_value_gaps`). No relationship to `FairValueGap` beyond the shared index space (`range_start_index`/`range_end_index` vs. `start_index`/`end_index`) that lets a *future* phase (Phase 3, out of scope here) compare them.
- **Lifecycle:** computed fresh every `evaluate_snapshot()` call, from that call's own `bars`/`now` — never cached or persisted across calls, exactly like every other `EvidenceSnapshot` field. No cross-call state.
- **Visibility:** public, exported from the package (mirrors `FairValueGap`).
- **Serialization:** none of `EvidenceSnapshot`'s existing fields are serialized to JSON/disk anywhere in the current pipeline (confirmed — `EvidenceSnapshot` flows in-process only, from `EvidenceEngine` to `StrategyEngine`, never through `compliance_state_store`-style persistence or the Bridge wire format); `OpeningRangeState` introduces no new serialization requirement.
- **Dataclass style:** **frozen dataclass**, matching every other type in `models.py` without exception (`Bar`, `FairValueGap`, `SupportResistanceContext`, `EvidenceSnapshot` itself are all `@dataclass(frozen=True)`) — this is the repository's only pattern for this kind of value type; a `NamedTuple` would be a deviation with no precedent and no justification.

**No other new model is introduced.** No change to `Bar`, `FairValueGap`, `EvidenceReport`, or any existing type's fields (per ADR-035's own revised §5, `FairValueGap` is explicitly left untouched — the comparison is one-directional, `OpeningRangeState` adopting `FairValueGap`'s index convention, not the reverse).

## 6. Evidence Pipeline Plan

- **Input:** the same `bars: Sequence[Bar]` and `now: datetime` already available inside `_analyze()` — no new input source.
- **Processing stage:** one new call inside `_analyze()`, after `detect_fair_value_gaps(bars)` (position chosen for readability/proximity to the other "raw fact" computations near the end of the pass; it has no dependency on anything computed earlier, so its exact position among the independent steps is not architecturally significant — this plan fixes it at the end of the existing sequence to minimize the diff).
- **Dependencies:** `EvidenceEngineConfig`'s new anchor-list and expected-interval fields (this phase adds them, §8/§9). No dependency on `structure_result`, `liquidity_result`, or any other step's output.
- **Output:** `Tuple[OpeningRangeState, ...]`, one entry per configured anchor whose window's start falls within the bars available (an anchor whose window hasn't started yet for this symbol/cycle simply produces no entry — not an error, not a placeholder).
- **`EvidenceSnapshot` integration:** `_analyze()`'s return tuple gains one more element; `evaluate_snapshot()`'s `EvidenceSnapshot(...)` call gains `opening_ranges=opening_ranges`. `evaluate()` discards this new value exactly as it already discards `fair_value_gaps` (it destructures `_analyze()`'s full return tuple but only uses `evidence_score` to build its `EvidenceReport`).
- **Circular dependency check:** none introduced — `opening_range.py` depends only on `models.py` (for `Bar`, `OpeningRangeState`, `SessionName`) and `config.py` (for the new fields), the same dependency shape as `support_resistance.py` and `session.py`. Nothing in `models.py`/`config.py` depends back on `opening_range.py`.

## 7. Gap Validation Plan

Confirms and implements ADR-035 §3's corrected fail-closed rule.

- **Required interval concept:** a new `EvidenceEngineConfig` field, e.g. `expected_bar_interval_seconds: int`, engine-wide (matching the existing pattern of engine-wide, not per-symbol, thresholds — e.g. `indicator_cache_max_entries`). This is a **new concept for Evidence Engine**, confirmed absent today by direct grep; it must not be imported from `market_data_ingestion`'s `Timeframe`/`TIMEFRAME_SECONDS`, since Evidence Engine has no existing dependency on that package and creating one would be a new cross-package coupling this Phase does not need (the value only needs to be *a number*, not a shared enum).
- **Gap detection responsibility:** a pure function in `opening_range.py` (name TBD at implementation time, e.g. `_has_temporal_gap(bars_in_window, expected_interval_seconds)`) checking that consecutive closed bars' `timestamp` values differ by no more than the configured expected interval (allowing exact equality, flagging anything larger) — operating only on the `Bar.timestamp` values already present in the `bars` argument, never touching `market_data_ingestion`.
- **Failure behavior:** any detected gap, or a bar count below the configured minimum, sets `is_valid=False` on that anchor's `OpeningRangeState` — never raises, never drops the entry from `opening_ranges` (a strategy consuming it needs to see *that* a configured range exists and is invalid, not have it silently vanish).
- **Output semantics:** `is_valid` is the only signal a consumer needs; it carries no further detail (no distinct "which kind of invalidity" enum) — matching the granularity `FairValueGap.filled` already uses for a comparable pass/fail fact, not over-engineering a taxonomy nothing downstream asks for yet.

## 8. Index Model Plan

- **`range_start_index`/`range_end_index`:** integer positions within the exact `bars` sequence `_analyze()` received for this call — computed by the same loop that determines `range_high`/`range_low`, at zero extra cost (the subset of bars within `[range_start, range_end)` is already being iterated).
- **Ownership:** Evidence Engine, alongside the rest of `OpeningRangeState` — not a separate model, not owned by Strategy Engine.
- **Purpose:** lets a future consumer (Phase 3, out of scope here) compare `FairValueGap.start_index`/`end_index` against these bounds directly, with no datetime-to-index translation, since `EvidenceSnapshot` exposes no raw bar sequence a strategy could perform that translation with itself (confirmed absent from `EvidenceSnapshot`'s field list).
- **Relationship to `FairValueGap` indices:** same index space, same `bars` argument, same per-call scope — confirmed by direct read of `detect_fair_value_gaps()`'s own index assignment (`start_index=i - 2, end_index=i` against the same `bars` parameter `_analyze()` passes it).
- **Why this preserves architecture:** no new field is added to `FairValueGap` (a type multiple existing/future strategies already depend on unmodified); no raw bar sequence is newly exposed on `EvidenceSnapshot` (which would let a strategy bypass Evidence Engine's "sole interpreter" role, ADR-024 Hard Rule); the fix is entirely contained within the one new type this phase already introduces.

## 9. Session Model Plan

- **How configured anchors relate to `SessionName`:** an anchor is `(SessionName, start_hour_utc, start_minute_utc)`-shaped (per ADR-035 §13's own field description) — `SessionName` remains descriptive metadata on the resulting `OpeningRangeState`, never the disambiguating key (§3's correction).
- **Configuration ownership (a mechanical detail this Plan resolves, not a new architectural decision):** the anchor list Evidence Engine's `opening_range.py` consumes to know *which* ranges to compute must live in `EvidenceEngineConfig` itself — mirroring the existing `london_session_start_hour`-style fields — since `EvidenceEngine.evaluate_snapshot()`'s signature has no path to receive a `StrategyEngineConfig` (a different package) at all, and ADR-035 §3 itself frames `opening_ranges` as generic output any future strategy can read, not something gated by one strategy's own config. ADR-035 §13's `StrategyEngineConfig.orb_session_anchors` is therefore, precisely, ORB's own *selection* of which Evidence-Engine-computed ranges it qualifies against — reconciling the two lists (by matching `session`/`range_start`) is Phase 4's concern ("Market Intelligence/eligibility integration," ADR-035 §17), explicitly out of Phase 0's scope (§12 below). Phase 0 needs only its own `EvidenceEngineConfig`-side list to exist and be computed against.
- **How `OpeningRangeState` identifies a range:** by its own `range_start`/`range_end` window (§3's correction), never by `session` alone.
- **Duplicate-anchor prevention:** ADR-035 §13 already specifies this as a **Strategy Engine** config-loading concern (Phase 5, `config_loader.py`-level `ConfigError`), scoped to `StrategyEngineConfig.orb_session_anchors`. Phase 0's own `EvidenceEngineConfig`-side anchor list is a separate, engine-owned list; **this Plan recommends the identical validation rule be applied to it at Evidence Engine's own config-construction time** (rejecting two configured anchors whose windows would coincide/overlap), for the same reason ADR-035 §3 gives — but implementing it is still a Phase 0 task (it validates *this phase's own* new config fields), not deferred to Phase 5, which only covers Strategy Engine's config file. This is the one place this Plan adds a validation step ADR-035's text doesn't spell out verbatim for the Evidence-Engine side specifically — justified directly by extending §3's own stated rule to the config surface Phase 0 actually introduces.

## 10. Fail-Closed Analysis

| Condition | Result | Engine responsibility | Later-phase impact |
|---|---|---|---|
| Insufficient bars in window | `is_valid=False` | Evidence Engine | ORB (Phase 1+) treats as `NOT_QUALIFIED` |
| Temporal gap detected (§6) | `is_valid=False` | Evidence Engine | Same |
| Duplicate/overlapping configured anchors | Startup `ValueError` (§9) — matches `EvidenceEngineConfig.__post_init__`'s existing, verified pattern (`config.py`'s weight-sum check); `ConfigError` is not this file's exception type, only `deployment_windows/config_loader.py`'s | Evidence Engine (config construction) | Prevents ambiguous `opening_ranges` entries reaching any later phase |
| Invalid duration (≤ 0, or exceeding a sane upper bound) | Startup `ValueError` | Evidence Engine (config construction) | Same |
| Timestamp discontinuity within the window | Covered by the gap check (§6) — not a distinct case | Evidence Engine | Same |
| Unknown/unmapped session for an anchor | Not applicable — `SessionName` is a closed enum; an anchor's `session` value is supplied directly by config, not derived, so there is no "unknown" state to fail on at this layer | Evidence Engine (config typing) | None |
| Partial window (evaluated before `range_end` has elapsed) | `is_formed=False` (not `is_valid=False` — this is not a failure, just "not yet") | Evidence Engine | ORB (Phase 1+) treats as `NOT_QUALIFIED`, distinctly from an invalid range |
| Zero bars supplied to `evaluate_snapshot()` at all | Already fails closed today — `evaluate_snapshot()` raises `ValueError` before `_analyze()` is ever called (existing behavior, unchanged by this phase) | Evidence Engine (existing) | None — Phase 0 adds no new zero-bar path |

## 11. Testing Plan

New file: `tests/titan_protocol/evidence_engine/test_opening_range.py`, matching this package's one-file-per-concern convention.

- **Unit tests:** range_high/low/midpoint calculation from a known bar set; `range_start_index`/`range_end_index` correctness against a known `bars` list; `is_formed` transitions (before/at/after `range_end`); descriptive-only role of `session` (two different anchors sharing a `SessionName` still produce two distinct, independently valid `OpeningRangeState` entries).
- **Boundary tests:** exactly the minimum bar count (valid) vs. one fewer (invalid); a bar exactly at `range_start`/`range_end`'s boundary (`[start, end)` — inclusive/exclusive edge behavior); the expected-interval gap check at exactly the threshold vs. one unit beyond it.
- **Negative tests:** a bar missing inside the window (`is_valid=False`); zero configured anchors (`opening_ranges == ()`, no error); a config with two overlapping anchors (`ValueError` at construction, §9).
- **Regression tests:** existing `test_engine.py`/`test_determinism.py`/`test_property.py`/`test_boundary.py` re-run unmodified (or updated only if they assert an exhaustive `EvidenceSnapshot` field list — verify at implementation time, per §4's file matrix) to confirm zero behavior change for every symbol/bar-set that has no configured opening-range anchor at all (the overwhelmingly common case pre-ORB, since `orb_approved_pairs` defaults to empty, ADR-035 §13).
- **Serialization tests:** not applicable (§5 — no serialization path exists for this type today).
- **Model integrity tests:** `OpeningRangeState` is frozen (attempting mutation raises, matching every other model in the package — a one-line test mirroring existing coverage for `FairValueGap`, if such coverage exists; add it if it doesn't).
- **Snapshot tests:** `evaluate_snapshot()` with a configured anchor produces a non-empty `opening_ranges` tuple with correct values; with none configured, produces `()`, byte-identical to today's behavior otherwise.
- **Architecture test:** `tests/titan_protocol/evidence_engine/test_architecture.py` (existing, unmodified) re-run to confirm `opening_range.py` introduces no forbidden import and no trade-decision vocabulary — this is the package's actual architectural verification gate (§4, §14).

## 12. Risk Assessment

| Risk | Classification | Note |
|---|---|---|
| Config-ownership split between `EvidenceEngineConfig` (Phase 0) and `StrategyEngineConfig` (§13) is implicit in ADR-035's text, not spelled out verbatim | Architectural | Resolved in this Plan (§9) via existing config-precedent, not a new decision; flagged so implementation doesn't rediscover it independently |
| New `expected_bar_interval_seconds` concept has no natural default validated against real market data yet | Configuration | Same category as ADR-035 §18.B's provisional-defaults item — a reasonable starting value is chosen, not empirically tuned, consistent with that already-accepted open item |
| Existing snapshot/regression tests may assert an exhaustive field list and need updating | Testing | Identified in §4/§11; verified, not assumed, at implementation time |
| None of the changes affect trading behavior (no strategy consumes `opening_ranges` until Phase 1) | Operational | Confirms this phase carries no live-trading risk at all — pure additive data availability |

No High or Critical risk identified — every item above is a bounded, foreseeable implementation detail, not an open architectural question.

## 13. Out-of-Scope Confirmation

Phase 0 does **not** implement, and this Plan does not describe:

- The ORB strategy itself, or any `Strategy` interface implementation.
- Strategy registration or the selection cascade.
- Qualification logic, breakout rules, FVG scoring, or the `range_boundary`/body-size calculations (ADR-035 §4/§5 — Strategy Engine's concern, Phase 2/3).
- `StrategyEngineConfig`'s own fields (`orb_approved_pairs`, `orb_min_range_atr_ratio`, etc., ADR-035 §13) or their `config_loader.py` wiring (Phase 5).
- Market Intelligence integration or eligibility gating (Phase 4).
- Runtime, Bridge, Risk Engine, Compliance Engine, or execution — untouched, unreferenced beyond the read-only architectural boundary confirmations in §4.
- Reconciling `EvidenceEngineConfig`'s anchor list against `StrategyEngineConfig.orb_session_anchors` (Phase 4, noted in §9).
- Tests for any later phase.

## 14. Acceptance Criteria

- `OpeningRangeState` exists in `titan_protocol/evidence_engine/models.py` as a frozen dataclass with exactly the fields in §5.
- `EvidenceSnapshot.opening_ranges: Tuple[OpeningRangeState, ...] = ()` exists, additive, default-empty.
- `EvidenceEngineConfig` exposes the new anchor-list and `expected_bar_interval_seconds` fields (§6, §9), each with a stated default and startup validation (including the overlap/duplicate check, §9).
- `opening_range.py` computes range high/low/midpoint/indices/`is_formed`/`is_valid` correctly against `test_opening_range.py`'s unit and boundary tests — all passing.
- Gap validation (§6) correctly sets `is_valid=False` on a detected missing bar, verified by a dedicated negative test.
- `_analyze()`/`evaluate_snapshot()` correctly wire the new computation through — verified by a snapshot test with at least one configured anchor.
- `evaluate()` (non-snapshot path) is unmodified in behavior — verified by re-running its existing tests unchanged.
- **Every pre-existing Evidence Engine test passes unmodified**, except any identified in §4/§11 as needing a field-list update, each such update reviewed individually — no unexplained regression.
- `python3 -m compileall titan_protocol/evidence_engine tests/titan_protocol/evidence_engine` clean.
- `python3 -m unittest tests.titan_protocol.evidence_engine.test_architecture` still PASS (no forbidden `phantom_pipeline`/`titan_protocol.bridge` import introduced, no trade-decision vocabulary, no randomness/ML import, no network/file I/O import) — the actual `titan_protocol`-aware architectural check for this package. (`scripts/check_architecture.py` is not used as a gate here: confirmed by direct read to validate only the legacy `phantom_pipeline/` namespace, with zero reference to `titan_protocol` anywhere in the script.)
- `git diff --stat` shows changes confined to the files in §4's matrix — no file outside `titan_protocol/evidence_engine/` and its own tests is touched.

## 15. Rollback Strategy

Deterministic and low-risk, since every change is additive:

- Revert `models.py`, `config.py`, `engine.py`, `__init__.py` to their pre-Phase-0 committed state (a single `git revert` of Phase 0's commit(s) is sufficient — no other file depends on the new type or fields, confirmed by §4's matrix showing zero touches outside Evidence Engine).
- Delete `opening_range.py` and `test_opening_range.py`.
- `OpeningRangeState` and `EvidenceSnapshot.opening_ranges` disappear entirely; `EvidenceSnapshot` reverts to its exact pre-Phase-0 shape.
- Repository behavior returns to today's state: Evidence Engine computes no opening-range fact, exactly as before this Plan.
- No data migration, no persisted state, no downstream consumer to unwind (Phase 1+ does not exist yet) — rollback has no cascading effect by construction.

## 16. Engineering Checklist

- [ ] `OpeningRangeState` added to `models.py`, frozen, matching §5's field list exactly.
- [ ] `EvidenceSnapshot.opening_ranges` added, additive, default `()`.
- [ ] Both added to `models.py`'s `__all__`.
- [ ] `EvidenceEngineConfig` gains the anchor-list field and `expected_bar_interval_seconds`, each with a stated default.
- [ ] Startup validation added for: anchor overlap/duplication, invalid duration, invalid interval value (§9, §10).
- [ ] `opening_range.py` created with the range-computation function and the gap-check helper (§6, §7).
- [ ] `_analyze()` calls the new computation; both return-tuple sites updated.
- [ ] `evaluate_snapshot()`'s `EvidenceSnapshot(...)` construction includes `opening_ranges=...`.
- [ ] `evaluate()` confirmed unmodified and still correct.
- [ ] `__init__.py` exports `OpeningRangeState` (verify existing export convention first).
- [ ] `test_opening_range.py` written covering §11's full list.
- [ ] Every pre-existing Evidence Engine test re-run; any needing a field-list update identified and fixed individually.
- [ ] `compileall` clean.
- [ ] `tests/titan_protocol/evidence_engine/test_architecture.py` re-run and PASS (the `titan_protocol`-aware architectural check for this package).
- [ ] `git diff --stat` confined to §4's file matrix.
- [ ] CHANGELOG entry drafted (per this project's established per-phase convention).

## 17. Final Readiness Assessment

This Plan is grounded entirely in code read directly this session (`engine.py`, `models.py`, `config.py`, `structure.py`, `support_resistance.py`, existing test directory listing) and in ADR-035's own already-Accepted, already-corrected text. The one mechanical detail ADR-035 does not spell out verbatim — where the anchor-list configuration actually lives — is resolved here (§9) using existing, precedented config ownership (`EvidenceEngineConfig`'s own session-hour fields), not a new architectural decision, and is flagged explicitly as such rather than silently assumed. No further architectural question needs to be reopened before implementation begins.

## Validation

(To be completed during/after Phase 0 implementation, per this project's standing convention — recorded here as the expected checklist, not yet executed, since no implementation exists.)

- `python3 -m compileall titan_protocol/evidence_engine tests/titan_protocol/evidence_engine`:
- `python3 -m unittest discover -s tests/titan_protocol/evidence_engine`:
- `python3 -m unittest tests.titan_protocol.evidence_engine.test_architecture`:
- Code Reviewer sign-off:
- Test Results Analyzer sign-off:
- Software Architect sign-off (mandatory per `TEAM.md` §3 for an Evidence Engine change):
