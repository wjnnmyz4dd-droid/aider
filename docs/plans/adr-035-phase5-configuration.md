# Plan: ADR-035 Phase 5 — Configuration Wiring and Cross-Field Validation

Status: **RESEARCH COMPLETE — READY FOR PLAN FINALIZATION.**
Owner (Plan phase): Software Architect (ADR-035/ADR-025/ADR-026 owner precedent, unchanged)
Touched components (tentative — final list depends on the score-weight
decision flagged in Research §6/§12, which the Plan phase must resolve
before the file-impact matrix can be finalized): `titan_protocol/evidence_engine/config.py`,
`titan_protocol/strategy_engine/config.py`, `deployment_windows/config_loader.py`,
`deployment_windows/config/titan_protocol_config.example.json`,
`tests/titan_protocol/evidence_engine/test_opening_range.py`,
`tests/titan_protocol/strategy_engine/test_orb_breakout_foundation.py`,
`tests/deployment_windows/test_config_loader.py`. Possibly
`titan_protocol/strategy_engine/strategies/orb_breakout.py` and both
Strategy-Engine structural-boundary allowlists — conditional on the
score-weight decision (§6).

---

## Research

### 0. Governance gate (verified against current HEAD, not assumed)

- Branch `claude/phantom-ea-visibility-cjjf3a`, HEAD `92d8c95`, working
  tree clean, matches remote (`git status --porcelain` empty).
- `ADR-035-orb-strategy.md`: **Accepted** (2026-07-25). Amendment 1:
  **Accepted** (commit `9b7d255`).
- Phase 2 (breakout/lockout): implemented, independently accepted.
  Phase 3 (FVG confirmation, commit `bf2285b`): implemented, independently
  accepted. Phase 4 (MI eligibility/range-quality, commit `92d8c95`):
  implemented, independently accepted this session (disposition "PHASE 4
  IMPLEMENTATION CONFORMS — ACCEPTED").
- Phase 5 implementation is **not authorized** — this document is the
  Research artifact only. Phase 6 (registration) and Phase 7
  (formation-time blackout closure) remain unscheduled and out of scope.
- `python3 scripts/check_architecture.py`: PASS (scans `phantom_pipeline/`,
  reference-only — not evidence about this `titan_protocol` change, run
  only because `TEAM.md` §9 names it as the mandatory check).
- Baseline test run, this pass: `python -m unittest discover -s
  tests/titan_protocol` → **1370/1370 pass**. `python -m unittest
  tests.deployment_windows.test_config_loader` → **19/19 pass**. Both
  establish the Phase 5 starting baseline — any regression during
  Implement must be diffed against these exact counts.

### 1. ADR-035 §13/§17 evidence — the exact Phase 5 mandate

§17's own Phase 5 entry, verbatim: *"Phase 5 — Configuration: §13's
fields wired through `StrategyEngineConfig`, `config_loader.py`, and the
example config, each with startup fail-closed validation and the
cross-field checks named in §13 (duplicate/overlapping anchors,
bar-count feasibility, weight-sum bound), with unit tests for every
validation path."*

§13's own cross-field-validation clause (verbatim): config loading must
fail closed if:
1. any two `orb_session_anchors` entries produce coincident/overlapping
   `[range_start, range_end)` windows;
2. `orb_min_range_bars` is infeasible for `orb_range_duration_minutes`
   given the configured bar timeframe;
3. the weighted-scoring components in §5 (`orb_fvg_score_weight` and
   "any sibling weights in the same weighted sum") do not sum to ≤ 1.

### 2. Configuration inventory — every ADR-035 §13 field, traced to its real owner

`StrategyEngineConfig` (`titan_protocol/strategy_engine/config.py`,
current HEAD, re-read in full) — 10 `orb_*` fields, **all already
implemented** across Phases 2-4:

| Field | Default | Validation | Phase |
|---|---|---|---|
| `orb_min_breakout_distance_atr_multiple` | 0.15 | `> 0` | 2 |
| `orb_min_body_to_range_ratio` | 0.5 | `[0,1]` | 2 |
| `orb_min_confirmation_candles` | 1 | `>= 1` | 2 |
| `orb_max_qualifications_per_range` | 1 | `>= 1` | 2 |
| `orb_fvg_max_age_bars` | 10 | `>= 1` | 3 |
| `orb_fvg_min_size_atr_multiple` | 0.1 | `> 0` | 3 |
| `orb_fvg_score_weight` | 0.15 | `[0,1]` (no cross-field sum check — explicitly deferred to Phase 5, see §6) | 3 |
| `orb_min_range_atr_ratio` | 0.5 | `> 0` | 4 |
| `orb_max_spread_pips` | 3.0 | `> 0` | 4 |
| `orb_min_liquidity_score` | 60.0 | `[0,100]` | 4 |

`EvidenceEngineConfig` (`titan_protocol/evidence_engine/config.py`,
re-read in full) — the opening-range fields §13's table names under
different `StrategyEngineConfig`-scoped names (a mapping Phase 4
Research already established and this pass re-confirmed by direct
re-read, not assumed):

| §13 name | Real field | Owner | Default | Validation |
|---|---|---|---|---|
| `orb_session_anchors` | `opening_range_anchors` | `EvidenceEngineConfig` | `()` | per-anchor: none; cross-field: **anchor-overlap check already implemented** (`_validate_no_overlapping_anchors`, §4 below) |
| `orb_range_duration_minutes` | `opening_range_duration_minutes` | `EvidenceEngineConfig` | 30 | `(0, 1440]` |
| `orb_min_range_bars` | `opening_range_min_bars` | `EvidenceEngineConfig` | 3 | `>= 1` (no feasibility cross-check yet — §4 below) |
| n/a (Evidence-Engine-internal, not in §13's table) | `expected_bar_interval_seconds` | `EvidenceEngineConfig` | 300 | `> 0` |
| n/a | `opening_range_post_range_bar_window` | `EvidenceEngineConfig` | 5 | `>= 1` |

`orb_approved_pairs` (§13's remaining field): **not a distinct field
anywhere** — ORB's pair eligibility is expressed through the generic
`StrategyEngineConfig.approved_pairs_by_strategy` /
`DEFAULT_APPROVED_PAIRS_BY_STRATEGY` mechanism every strategy already
uses (confirmed: `DEFAULT_APPROVED_PAIRS_BY_STRATEGY` has zero
`StrategyId.OPENING_RANGE_BREAKOUT` entry today, correctly, since ORB is
unregistered until Phase 6). This is unchanged from Phase 4 Research's
own finding, re-confirmed by direct re-read this pass.

**Consequence: every field §13 lists already exists, with correct
per-field validation, somewhere in the repository.** Nothing is
"missing" in the sense of needing a brand-new dataclass field (except
possibly score-weight fields, §6). What is missing is (a) two of
three cross-field checks (§4), and (b) any JSON-config wiring
whatsoever (§3).

### 3. Config-loading architecture — the real, current gap

`deployment_windows/config_loader.py` (563 lines, read in full) wires
exactly these dataclasses from JSON: `BridgeConfig`, `RuntimeConfig`,
`RiskEngineConfig`, `ComplianceEngineConfig` (+ named rule-profile
override), `MarketIntelligenceConfig`, `NewsProviderSettings`,
`ReliabilityConfig`. **`StrategyEngineConfig` and `EvidenceEngineConfig`
appear nowhere in this file — no import, no section, no field mapping.**

Confirmed by direct grep across `titan_protocol/` and `deployment_windows/`
(excluding tests): `StrategyEngineConfig()` and `EvidenceEngineConfig()`
are constructed with **pure Python defaults**, unconditionally, in
`deployment_windows/start.py` (lines 1126, 1194), `health_check.py`
(line 190), and `install.py` (lines 301, 303) — every single call site,
no exceptions.

**This is not an ORB-specific gap — it is total.** Every field on both
dataclasses (not just the `orb_*`/`opening_range_*` ones) is
JSON-unconfigurable today; the five legacy strategies' own thresholds
(`session_breakout_min_session_score`, etc.) are equally hardcoded.
`config/titan_protocol_config.example.json`'s own `trading_profile`
section comment states this explicitly and accurately as today's design:
*"Session windows and strategy eligibility are governed by the selected
profile itself... and by `titan_protocol/strategy_engine/config.py` — not
independently overridable from this file."* This is a disclosed,
pre-existing deployment-layer design choice, not an ADR-level constraint
— nothing in any Accepted ADR mandates it, and ADR-035 §17 explicitly
authorizes changing it for ORB's own fields. But it means Phase 5 is
**establishing JSON wiring for these two engines' configs for the first
time ever**, not extending an existing pattern the way Phase 5 extends
`config_loader.py`'s own established `dataclasses.replace()`-on-a-named-
profile idiom (already used for `compliance_config`, §5).

**Safety-relevant fact surfaced by this Research, not previously
documented anywhere:** because `EvidenceEngineConfig()` always defaults
`opening_range_anchors=()` in production, and `()` means "fail closed
until an operator configures one" (the field's own docstring), **ORB's
entire opening-range mechanism is inert in production today, independent
of ORB's registration status.** This has zero live consequence before
Phase 6 (ORB isn't registered, so nothing consumes `opening_ranges`
anyway) but is worth flagging as a fact Phase 5 will make operationally
real for the first time, and a candidate for a `KNOWN_GAPS.md` note
(Plan-phase decision, §12).

### 4. Cross-field validation — exact status of each of §13's three named checks

1. **Duplicate/overlapping anchors — already implemented and correct.**
   `EvidenceEngineConfig.__post_init__` calls
   `_validate_no_overlapping_anchors(self.opening_range_anchors,
   self.opening_range_duration_minutes)` (lines 123, 126-145), which
   rejects any two anchors producing coincident/overlapping windows.
   Tested directly: `tests/titan_protocol/evidence_engine/test_opening_range.py::TestNegativeCases::test_overlapping_anchors_raise_value_error_at_construction`.
   **Phase 5's only remaining work here is plumbing** — ensuring
   `config_loader.py` actually constructs `EvidenceEngineConfig(opening_range_anchors=...)`
   from parsed JSON so this already-correct check has real input to
   validate. No new validation logic needed.
2. **Bar-count/duration feasibility — not implemented anywhere.**
   `__post_init__` validates `opening_range_min_bars >= 1`,
   `opening_range_duration_minutes` range, and
   `expected_bar_interval_seconds > 0` independently, but never
   cross-checks that `opening_range_min_bars` bars can actually form
   within `opening_range_duration_minutes` given
   `expected_bar_interval_seconds` (confirmed by re-reading
   `__post_init__` line-by-line and confirming no such check exists;
   confirmed by `test_opening_range.py`'s own
   `test_invalid_min_bars_raises_value_error`, which only tests
   `min_bars=0`, never an infeasible-combination case). **This is a
   genuine, new Phase 5 production-code task.** Concrete worked
   examples for the Plan phase: `duration_minutes=30`,
   `expected_bar_interval_seconds=300` (5-minute bars) → 6 complete bars
   fit the window; `min_bars=3` is feasible, `min_bars=10` is not and
   must fail closed at construction.
3. **Weight-sum bound — not implemented; genuinely open, see §6.**

### 5. Config-loading pattern precedent (for the Plan phase to reuse, not invent)

`config_loader.py` already establishes the exact idiom Phase 5 needs:
`compliance_config = dataclasses.replace(_base_compliance_config,
rule_profiles=tuple(dataclasses.replace(p, ...) if p.name == ... else p
for p in ...))` — i.e., construct the dataclass with its own defaults,
then `dataclasses.replace()` in only the JSON-supplied overrides, so any
field absent from the JSON silently keeps its existing engine default
(backward compatible with every operator's existing config file with no
"strategy"/"evidence" section at all). The same `_get_float`/`_get_int`/
`_get_bool` helpers with a `default=<engine's own dataclass default>`
argument already handle "missing key falls back to engine default,
wrong type fails closed" for every other section — no new parsing
primitive is needed.

### 6. Score-weight analysis — the primary open question (not resolved here)

**Actual formula** (`orb_breakout.py`, unchanged since Phase 3, re-read
directly this pass):
```python
score = clamp(0.4 * session_value + 0.3 * mi_session_score + 0.3 * evidence.volatility.volatility_score + config.orb_fvg_score_weight * fvg_bonus)
```
Four coefficients participate: `0.4`, `0.3`, `0.3` are **hardcoded
Python literals**, never `StrategyEngineConfig` fields; `orb_fvg_score_weight`
(default `0.15`) is the **only** one that is a configurable field.

**This is not a newly discovered contradiction — it is an already-known,
already-litigated, already-accepted deviation, re-confirmed by this
pass's direct re-read of both the Phase 3 Plan (`docs/plans/adr-035-phase3-fvg-confirmation.md`
§2.1, already Accepted) and ADR-035 §5 itself:**

- ADR-035 §5's own drafted formula is `w1*range_quality + w2*mi_session_score
  + w3*volatility_score + w4*fvg_bonus`, "weights configurable,
  sum-bounded." Phase 2 (already independently accepted, commits
  `b28ac3f`/`6cb235c`) instead reused `SessionBreakoutStrategy`'s literal
  formula verbatim, substituting `session_value` for the undrafted
  `range_quality` term and leaving three of four weights hardcoded — an
  **already-reviewed-and-accepted deviation**, not a new finding.
- Phase 3's own Plan (§2.1, already Accepted) explicitly traced this
  exact question — "does `orb_fvg_score_weight` alone satisfy §13's
  weight-sum bound, or must the three literals be promoted to config
  fields first?" — and **explicitly, textually deferred both the
  cross-field check itself and the promotion decision to Phase 5**,
  citing ADR-035 §17's own phase-assignment text as the reason no ADR
  amendment or escalation was needed at Phase 3 time.

**Consequence for this Research: there is no Accepted-ADR contradiction
requiring a fresh amendment** — ADR-035's own accepted roadmap already
assigns exactly this decision to Phase 5. But it **is** a genuine,
two-sided, undecided implementation choice this Research will not invent
a resolution for (per this task's explicit instruction), and it is
**the single decision that determines Phase 5's actual file-impact
matrix**:

- **Option A — treat the existing single configurable weight as already
  satisfying §13.** `orb_fvg_score_weight`'s own `[0, 1]` per-field bound
  (already validated) is, for a single-term sum, already a "sum ≤ 1"
  check. No new fields, no change to `orb_breakout.py`'s score line. The
  cross-field "weight-sum bound" requirement is satisfied by documenting,
  in code and in this Plan, why it degenerates to the existing per-field
  check for the one weight that is actually configurable today.
- **Option B — promote the three literals to named `StrategyEngineConfig`
  fields** (e.g. `orb_session_score_weight=0.4`, `orb_mi_session_score_weight=0.3`,
  `orb_volatility_score_weight=0.3`), add a genuine four-way sum-≤-1
  cross-field check mirroring `EvidenceEngineConfig`'s own
  `structure_weight + ... == 1.0` pattern, and change `orb_breakout.py`'s
  score line to read all four from config. Defaults chosen to equal
  today's literals would preserve current behavior exactly, but this
  touches `orb_breakout.py` for the first time since Phase 3 (a file
  three independent reviews have now signed off on unchanged) and would
  require new entries in both Strategy-Engine structural-boundary
  allowlists (§9).

`config.py`'s own module docstring ("every threshold and weight used
anywhere in this package is named here... no magic numbers") arguably
favors Option B; Minimal-Change-Engineer discipline (§6, smallest correct
diff, no scope expansion) and "don't touch already-accepted code without
a concrete reason" arguably favor Option A. **Both are defensible; the
Plan phase must state and justify one, not have it invented here or at
Implement time.**

### 7. Anchor-overlap validation — precisely what remains (re-derived, not duplicated)

Re-confirmed by direct read: the existing `_validate_no_overlapping_anchors()`
correctly implements §13's first cross-field rule and needs no
Strategy-Engine-side duplicate. Phase 5 must **not** add a second,
`StrategyEngineConfig`-scoped anchor-overlap check — ADR-035 §13's table
originally assumed this check would live on `StrategyEngineConfig`
(since that's where `orb_session_anchors` was drafted to live), but
Phase 4 Research already established the real field lives on
`EvidenceEngineConfig`, where the check already correctly runs. Adding a
second copy on `StrategyEngineConfig` would be exactly the duplicate
logic CLAUDE.md §1.3/§1.4 forbid, with zero evidentiary basis — no ADR
text requires two copies, only one functioning check.

### 8. File-impact matrix (proposed; final shape gated on §6's decision)

| File | Change | Conditional on §6? |
|---|---|---|
| `titan_protocol/evidence_engine/config.py` | Add bar-count/duration feasibility cross-field check to `__post_init__` (§4 item 2) | No — needed either way |
| `titan_protocol/strategy_engine/config.py` | If Option A: no field changes, only a comment documenting why the existing `orb_fvg_score_weight` bound satisfies §13. If Option B: 3 new fields + 1 new cross-field `__post_init__` check | Yes |
| `titan_protocol/strategy_engine/strategies/orb_breakout.py` | Unchanged if Option A; score line rewritten to read 4 config fields if Option B | Yes |
| `deployment_windows/config_loader.py` | New wiring: parse JSON sections for `StrategyEngineConfig`'s `orb_*` fields and `EvidenceEngineConfig`'s `opening_range_*` fields, using the existing `dataclasses.replace()`-over-defaults idiom (§5) | No |
| `deployment_windows/config/titan_protocol_config.example.json` | New JSON section(s) documenting every wired field; update/remove the now-partially-stale `trading_profile` comment (§3) | No |
| `tests/titan_protocol/evidence_engine/test_opening_range.py` | New feasibility-check tests (exact examples, §4 item 2) | No |
| `tests/titan_protocol/strategy_engine/test_orb_breakout_foundation.py` | New weight-sum-bound tests, shape depends on §6 | Yes |
| `tests/deployment_windows/test_config_loader.py` | New tests: each field's JSON→dataclass mapping, missing-section-defaults-preserved, invalid-value-fails-closed | No |
| `deployment_windows/KNOWN_GAPS.md` | Possibly a new/updated entry disclosing the "opening_range_anchors defaults empty in production" fact (§3) — Plan phase to decide, not required by any ADR text | No (independent of §6) |
| `docs/adr/*` | **None anticipated** — §6 is already ADR-authorized to Phase 5, no contradiction found requiring amendment | No |
| Structural-boundary allowlists (`compliance_state_store`, `news_ingestion`) | **None needed** if Option A — `evidence_engine/config.py` and `strategy_engine/config.py` are already-authorized exceptions in both files (re-confirmed by direct read); `config_loader.py`/example JSON are outside the `titan_protocol/` prefix these checks scan entirely. **New entries needed for `orb_breakout.py`** if Option B, since it is not currently listed as touchable beyond Phase 2's original authorization | Yes |
| `build_default_registry()` / legacy strategies | **None** — Phase 5 does not register ORB (Phase 6) and does not touch any of the five legacy strategies | No |

### 9. Architecture/boundary implications

`test_architecture.py` (Strategy Engine) and the evidence_engine
equivalent scan for forbidden imports/vocabulary/randomness — a pure
arithmetic feasibility check and JSON-wiring code introduce none of
these; no new entries anticipated there regardless of §6. The
structural-boundary allowlist consequence is captured in §8's table.
`deployment_windows/config_loader.py` and the example JSON are outside
`titan_protocol/` entirely and are not scanned by either
`test_structural_boundary.py` file's frozen-prefix check — confirmed by
direct read of both files' `_FROZEN_PREFIXES` tuples (both start with
`"titan_protocol/..."` only).

### 10. Proposed test matrix

- **Per-field parsing/default/validation** (config_loader.py, new): for
  every wired `orb_*`/`opening_range_*` field — JSON value honored;
  section/key absent falls back to the engine's own existing default
  (zero behavior change for an operator's pre-Phase-5 config file);
  out-of-safe-range value raises `ConfigError` at startup, never at
  evaluation time (mirrors every existing `config_loader.py` field).
- **Anchor-overlap** (integration-level, new): a JSON config with two
  overlapping anchors fails closed via `load_settings()`, proving the
  already-correct `EvidenceEngineConfig` check is actually reachable
  from the JSON path (the check itself needs no new unit test — already
  covered).
- **Bar-count feasibility** (new, `EvidenceEngineConfig` unit level):
  exactly-feasible boundary passes; one-bar-short fails closed; multiple
  duration/interval combinations (per §4 item 2's worked example).
- **Weight-sum bound** (new; exact shape depends on §6's resolution):
  Option A — a test/comment confirming the existing per-field `[0,1]`
  bound is documented as satisfying §13 for the single real weight.
  Option B — boundary-exact sum tests (`== 1.0` passes, `> 1.0` fails
  closed) mirroring `EvidenceEngineConfig`'s own weight-sum test
  precedent.
- **Preservation** (regression): full `titan_protocol` suite (1370
  baseline, this pass); `build_default_registry()` still exactly 5,
  ORB excluded; no legacy-strategy file touched (`git diff --name-only`);
  Phase 2/3/4 `OrbBreakoutStrategy` test file fully green with zero
  reason-string changes (unless Option B changes the score line, in
  which case only score-related assertions, never gate/reason-string
  assertions, may need updating — Plan phase to state explicitly if so).

### 11. Capital-preservation risks

- **Low blast radius today:** ORB remains unregistered (Phase 6 not yet
  authorized), so no Phase 5 change has any live-trading effect yet —
  Phase 5's risk is entirely about not introducing a defect that
  surfaces once Phase 6 registers ORB, not about immediate capital
  exposure.
- **Backward compatibility is the main safety property to preserve:** an
  operator's existing `titan_protocol_config.json` (no "strategy"/
  "evidence" section) must continue to produce byte-identical
  `StrategyEngineConfig`/`EvidenceEngineConfig` objects to today's
  hardcoded defaults — provable via the `dataclasses.replace()`-over-
  defaults idiom already used elsewhere in this file, not a new risk.
- **The one genuinely new safety-relevant fact:** production's
  `opening_range_anchors` has always defaulted to `()` — Phase 5 makes
  this configurable for the first time, meaning a badly-configured
  anchor could now actually affect ORB's future (post-Phase-6) behavior
  where today it structurally cannot. The already-existing anchor-
  overlap check and the new bar-count-feasibility check are exactly the
  fail-closed guards that keep this addition safe; both must be proven
  correct with boundary-exact tests before Implement is considered done.

### 12. Open questions / blockers for Plan finalization

1. **(Primary, blocking Plan finalization) Score-weight promotion —
   Option A vs. Option B (§6).** Must be explicitly decided and
   justified by the Plan phase; determines the file-impact matrix,
   whether `orb_breakout.py` and the structural-boundary allowlists are
   touched, and the shape of the weight-sum test matrix.
2. **Should `orb_approved_pairs`/pair-eligibility wiring be attempted in
   Phase 5 at all?** ORB has zero registry presence until Phase 6, and
   no precedent exists for ANY strategy's approved-pairs list being
   JSON-configurable (confirmed: `config_loader.py` never touches
   `approved_pairs_by_strategy` for any of the five legacy strategies
   either). Recommendation for the Plan phase to state and justify:
   **exclude from Phase 5**, defer to Phase 6 if ever needed — but this
   is a Plan-phase decision, not decided here.
3. **JSON section naming/shape** for the new `StrategyEngineConfig`/
   `EvidenceEngineConfig` wiring (e.g. `"strategy_engine"` /
   `"evidence_engine"` / `"opening_range"`) — unconstrained by any ADR
   text; a Plan-phase naming decision.
4. **Whether to update the `trading_profile` section's now-partially-
   stale comment** ("not independently overridable from this file") and
   whether `KNOWN_GAPS.md` should gain an entry for the
   always-empty-anchors production fact (§3) — neither is ADR-mandated;
   Plan phase to decide.

None of these four items is an Accepted-ADR contradiction blocking
Research itself — every one is a legitimate implementation choice
ADR-035 §17 itself assigns to Phase 5 to resolve. Research therefore
does not halt; it hands all four forward as explicit, unresolved
decisions for Plan finalization, per this task's instruction not to
invent them here.

---

## Plan

(Not started. This Research artifact authorizes no implementation.)

## Validation

(Not started.)

---

**Disposition: PHASE 5 RESEARCH COMPLETE — READY FOR PLAN FINALIZATION.**

Every ADR-035 §13 field has been traced to its real, existing owner and
validation state; the config-loading architecture's actual current gap
(total absence of `StrategyEngineConfig`/`EvidenceEngineConfig` JSON
wiring, not an ORB-specific one) has been established from source, not
assumed; two of three required cross-field checks have been precisely
scoped (one already correct and only needing plumbing, one entirely new);
the third (weight-sum bound) has been traced to an already-accepted,
already-disclosed Phase 3 deferral and is presented as the primary open
question for Plan finalization, with both defensible options stated
rather than one invented. No Accepted-ADR contradiction was found that
requires a fresh amendment — ADR-035's own roadmap already authorizes
Phase 5 to resolve every open item listed in §12.

**Phase 5 implementation remains prohibited** until a Plan artifact
explicitly resolves §12's open questions (primarily the score-weight
decision) and receives its own independent implementation-readiness
review. **Phase 6 and Phase 7 remain unauthorized regardless of this
Research's outcome.**
