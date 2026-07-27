# Plan: ADR-035 Phase 5 — Configuration Wiring and Cross-Field Validation

Status: **PLAN FINALIZED — READY FOR INDEPENDENT IMPLEMENTATION-READINESS REVIEW.**
Owner (Plan phase): Software Architect (ADR-035/ADR-025/ADR-026 owner precedent, unchanged)
Touched components (final — resolved below, §13): `titan_protocol/evidence_engine/config.py`
(new cross-field feasibility check only, zero new fields), `titan_protocol/strategy_engine/config.py`
(comment-only clarification, zero new fields), `deployment_windows/config_loader.py`,
`deployment_windows/start.py`, `deployment_windows/health_check.py`, `deployment_windows/install.py`,
`deployment_windows/config/titan_protocol_config.example.json`,
`tests/titan_protocol/evidence_engine/test_opening_range.py`,
`tests/deployment_windows/test_config_loader.py`. **`titan_protocol/strategy_engine/strategies/orb_breakout.py`
and both Strategy-Engine structural-boundary allowlists are explicitly OUT OF SCOPE** —
the score-weight decision (§13) resolved to Option A, which requires no
change to either.

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

Re-derived directly from ADR-035 §5/§13/§17/§18.B, the already-accepted
Phase 2/3/4 Plans, and current repository state (re-read this pass, not
taken solely from the Research summary above).

### 13. Score-weight contract — resolved: Option A

**Decision: retain the three fixed coefficients (`0.4`, `0.3`, `0.3`) as
hardcoded literals in `orb_breakout.py`. Do not add new
`StrategyEngineConfig` fields for them. Formally specify that ADR-035
§13's weight-sum bound is satisfied, for the one config-declared weight
that exists in the ADR's own authorized field set, by
`orb_fvg_score_weight`'s already-implemented `[0.0, 1.0]` per-field
bound — for a single term, "value ≤ 1" and "sum of the set ≤ 1" are the
same statement.** No production code changes to `orb_breakout.py` or new
fields on `StrategyEngineConfig`; one clarifying comment added next to
the existing `orb_fvg_score_weight` validation in `config.py`.

**Evidence trail (re-derived from source this pass, not carried over
unchecked):**

1. **§13's own Configuration table — the ADR's authoritative field list
   — has never named a config field for any of the three coefficients,
   across all three ADR revisions.** Re-read directly: the table's 14
   rows include exactly one score-related weight,
   `orb_fvg_score_weight`. No `orb_session_score_weight`,
   `orb_mi_session_score_weight`, `orb_volatility_score_weight`, or any
   equivalent has ever appeared in §13.
2. **§17's own Phase 5 mandate is to wire "§13's fields"** — the fields
   *already in* §13's table — "through `StrategyEngineConfig`,
   `config_loader.py`, and the example config." It does not say "extend
   §13's field set." Reading Phase 5 as authorized to invent three new
   fields §13 never named would require Phase 5 to expand the ADR's own
   configuration surface on its own initiative — a bigger step than
   "wiring," and one no ADR text authorizes.
3. **This is not a new question — it was already litigated and resolved
   the same way, twice, in already-Accepted Plans.** Phase 2's Plan
   (`docs/plans/adr-035-phase2-orb-breakout-lockout.md` §6, re-read in
   full this pass) explicitly chose the interim `0.4`/`0.3`/`0.3`
   formula "rather than inventing new Phase-2-only config fields
   ADR-035 §13 never named" — the exact same textual ground reproduced
   here. Phase 3's Plan (`docs/plans/adr-035-phase3-fvg-confirmation.md`
   §2.1, re-read in full this pass) re-examined this same question
   under direct challenge from an independent review and reaffirmed it,
   citing §17's Phase-5 assignment as the reason no amendment was
   needed at Phase 3 time — and left the specific question "should the
   three literals be promoted" open for Phase 5, not pre-decided either
   way. Nothing in the repository or any Accepted ADR text has changed
   since that would flip this reasoning.
4. **§5's own prose ("weights configurable, sum-bounded") is
   descriptive framing for the mechanism's shape, not itself an
   operative field list** — and it was already established, at Phase 2
   time, as non-literal in a different respect (the formula's own first
   term is `session_value`, not the `range_quality` term §5's draft
   text names — an already-accepted deviation, re-confirmed this pass
   by direct comparison of §5's text against the shipped code). Reading
   §5's "weights configurable" as silently overriding §13's own,
   narrower, actually-authoritative field table would mean §13's table
   was never really authoritative for this formula at all — a stronger
   claim than either already-accepted Plan made when they left `w1`'s
   own naming mismatch unresolved as "interim."
5. **`config.py`'s docstring** ("every threshold and weight used
   anywhere in this package is named here... no magic numbers") is a
   real, genuine tension with leaving `0.4`/`0.3`/`0.3` as literals —
   acknowledged, not dismissed. But it is a general package-level
   aspiration, not itself an ADR-035 requirement, and it was already
   weighed against the "§13 never named these fields" argument at Phase
   3 time and did not change that Plan's own conclusion. Nothing in this
   Research changes that balance.
6. **Consequence: no Accepted-ADR contradiction, no amendment
   required.** ADR-035's own text (§13's authoritative table + §17's
   "wire §13's fields" framing) is internally consistent with Option A
   once §5's looser prose is read as descriptive rather than as a
   silent field-table amendment — which is exactly how it was already
   read, without objection, through two independent implementation-
   readiness reviews (Phase 2, Phase 3). This Plan does not invent that
   reading; it applies the same one a third time, now that Phase 5 is
   the phase ADR-035 itself designated to close the question.

**What Phase 5 actually does for this item:** add one comment in
`titan_protocol/strategy_engine/config.py`, directly above
`orb_fvg_score_weight`'s existing `if not (0.0 <= self.orb_fvg_score_weight
<= 1.0)` check, recording this resolution — e.g. *"Satisfies ADR-035
§13's weight-sum-bound requirement: this is the only score-formula
weight ADR-035 §13's own Configuration table ever names as a config
field (Phase 2/3 Plans, already Accepted, explicitly declined to invent
additional fields for the formula's other three literal coefficients);
for the one weight the ADR's authorized field set contains, this
per-field bound is the sum bound."* No other code change.

### 14. Configuration-loader scope and per-field contract

**Narrow scope statement:** Phase 5 wires exactly the `orb_*`/
`opening_range_*` fields ADR-035 §13 already names (mapped to their real
owners per Research §2), using the exact `dataclasses.replace()`-over-
defaults idiom `config_loader.py` already established for
`compliance_config` (`deployment_windows/config_loader.py` lines
401-416) — no new parsing primitive, no new config-loading mechanism, no
change to any other engine's section. `orb_approved_pairs` is
**explicitly excluded** (§16).

Two new top-level JSON sections, each documented with a `_maps_to` note
exactly like the existing partial `"risk"` section already is ("(partial
— the fields most operators tune...)"):

**`"strategy_engine"`** → `StrategyEngineConfig` (partial: only the 10
`orb_*` fields listed below; the five legacy strategies' own thresholds
remain unwired, unchanged from today, out of this Plan's scope):

| JSON key | Field | Default when key/section absent | Parse/type | Validation path | Fail-closed behavior |
|---|---|---|---|---|---|
| `orb_min_breakout_distance_atr_multiple` | same | `0.15` | float | `StrategyEngineConfig.__post_init__` (existing) | `ConfigError` wrapping the dataclass's `ValueError`, at startup |
| `orb_min_body_to_range_ratio` | same | `0.5` | float | existing | same |
| `orb_min_confirmation_candles` | same | `1` | int | existing | same |
| `orb_max_qualifications_per_range` | same | `1` | int | existing | same |
| `orb_fvg_max_age_bars` | same | `10` | int | existing | same |
| `orb_fvg_min_size_atr_multiple` | same | `0.1` | float | existing | same |
| `orb_fvg_score_weight` | same | `0.15` | float | existing (now documented as satisfying §13's weight-sum bound, §13 above) | same |
| `orb_min_range_atr_ratio` | same | `0.5` | float | existing | same |
| `orb_max_spread_pips` | same | `3.0` | float | existing | same |
| `orb_min_liquidity_score` | same | `60.0` | float | existing | same |

**`"evidence_engine"`** → `EvidenceEngineConfig` (partial: only the 4
opening-range fields below; every other `EvidenceEngineConfig` field —
scoring weights, session hours, S/R tolerances, etc. — remains unwired,
unchanged, out of scope):

| JSON key | Field | Default when key/section absent | Parse/type | Validation path | Fail-closed behavior |
|---|---|---|---|---|---|
| `opening_range_anchors` | `opening_range_anchors` | `()` | array of `{"session": "<SessionName member>", "start_hour_utc": int, "start_minute_utc": int}` objects; `"session"` validated against `SessionName.__members__`, wrapped in `ConfigError` (mirrors `compliance.rule_profile_name`'s existing `ValueError`→`ConfigError` pattern) before being passed as a tuple to the constructor | existing `_validate_no_overlapping_anchors` (unchanged) **plus** the new feasibility check (§15) | `ConfigError` at startup for a bad session name; the dataclass's own `ValueError` (wrapped) for overlap/feasibility |
| `opening_range_duration_minutes` | same | `30` | int | existing `(0, 1440]` check | `ConfigError`, startup |
| `opening_range_min_bars` | same | `3` | int | existing `>= 1` check **plus** the new feasibility check (§15) | same |
| `expected_bar_interval_seconds` | same | `300` | int | existing `> 0` check **plus** the new feasibility check (§15) | same |

`opening_range_post_range_bar_window` is **not** wired (§16) — remains at
its Python default (`5`), which its own docstring already documents as a
deliberate safety margin over §13's `orb_min_confirmation_candles` range;
no operational need to override it has been identified, and wiring it
would be scope beyond what §13 requires.

**Section-absent behavior (backward compatibility, the primary safety
property of this whole Plan):** if `"strategy_engine"` and/or
`"evidence_engine"` are absent from an operator's existing JSON config
(every config file that predates this Phase), `config_loader.py` must
construct both dataclasses with their pure, existing Python defaults —
byte-identical to today's `StrategyEngineConfig()`/`EvidenceEngineConfig()`
calls. This follows automatically from the `dataclasses.replace()`-over-
defaults idiom (a field never present in the override set keeps the base
object's own default), the same guarantee already relied on for
`compliance_config`.

**`DeploymentSettings` and the three call sites (the wiring's actual
consumers — a gap the Research pass under-specified and this Plan
closes):** `config_loader.py`'s `DeploymentSettings` dataclass has no
`strategy_config`/`evidence_config` fields today, and
`deployment_windows/start.py:1126`/`1194`, `health_check.py:190`, and
`install.py:301,303` all construct `StrategyEngineConfig()`/
`EvidenceEngineConfig()` as bare, unconditional Python defaults —
**wiring the fields into `load_settings()` alone would be dead code
unless these three call sites are also updated to use
`settings.strategy_config`/`settings.evidence_config`.** This Plan adds
both fields to `DeploymentSettings` and updates all three call sites
(one line each: replace the bare constructor call with the
`settings`-sourced object) — required, not optional, for the wiring to
have any effect.

**Pre-existing, disclosed, non-blocking consistency note (not a new
Phase 5 risk):** `expected_bar_interval_seconds` is Evidence Engine's own
independent concept (already documented in its own docstring as
deliberately not imported from `market_data_ingestion`'s `Timeframe`
vocabulary). `market_data_ingestion`'s own timeframe configuration is
equally unwired through `config_loader.py` today (confirmed by direct
grep — no `"timeframe"` key anywhere in the loader or example config).
An operator who sets `expected_bar_interval_seconds` to a value that
doesn't match the real bar cadence has always been able to do so by
editing Python; Phase 5 moves this same, already-existing risk to a JSON
edit — it does not create a new risk, and reconciling the two engines'
timeframe vocabularies is out of ADR-035's scope entirely (§16).

### 15. Cross-field validation — final contract for all three §13 rules

1. **Duplicate/overlapping anchors — no change to the check itself.**
   `EvidenceEngineConfig._validate_no_overlapping_anchors()` (existing,
   correct, tested) is not touched. Phase 5's only action is ensuring
   `config_loader.py` threads parsed JSON anchors into
   `EvidenceEngineConfig(opening_range_anchors=...)` so the existing
   check has real input — confirmed via a new integration-level test
   (§18) proving an overlapping-anchor JSON config fails closed through
   `load_settings()`, not merely at the dataclass level (already proven).
2. **Range-duration/bar-count feasibility — new, fully specified.** Add
   `_validate_range_duration_feasible(duration_minutes: int, min_bars:
   int, expected_interval_seconds: int) -> None` to
   `titan_protocol/evidence_engine/config.py`, called from
   `__post_init__` immediately after the existing
   `_validate_no_overlapping_anchors` call. **Derived directly from
   `opening_range.py`'s own real computation** (`_compute_single_range`'s
   `included_indices = [... range_start <= bar.timestamp < range_end]`,
   a half-open window), not invented: the maximum number of bars that
   can possibly form inside a half-open `[range_start, range_end)`
   window, given bars arriving every `expected_interval_seconds` with no
   gap, is the ceiling of `duration_seconds / expected_interval_seconds`
   — `max_possible_bars = -(-duration_seconds // expected_interval_seconds)`
   (`duration_seconds = duration_minutes * 60`). **Boundary semantics:**
   inclusive-minimum-passes, matching this file's own established
   convention (`opening_range_min_bars`'s existing `< 1` rejection, same
   as `orb_min_confirmation_candles`'s precedent) — `if max_possible_bars
   < min_bars: raise ValueError(f"opening_range_min_bars ({min_bars})
   cannot be satisfied within opening_range_duration_minutes
   ({duration_minutes}) given expected_bar_interval_seconds
   ({expected_interval_seconds}); at most {max_possible_bars} bar(s) can
   form in that window")`. **Worked boundary examples (re-derived, not
   assumed):** `duration_minutes=30`, `expected_bar_interval_seconds=300`
   → `max_possible_bars=6` exactly (1800/300); `min_bars=6` passes
   (not `< 6`), `min_bars=7` fails closed. Non-exact-division case:
   `duration_minutes=22`, `expected_bar_interval_seconds=300` (1320s) →
   `max_possible_bars = ceil(1320/300) = 5`; `min_bars=5` passes,
   `min_bars=6` fails closed.
3. **Weight-sum bound — resolved per §13 above.** No new validation
   function; the existing `orb_fvg_score_weight` per-field bound is
   documented, via one comment, as satisfying this requirement for the
   ADR's own authorized single-weight field set.

### 16. Field inventory reconciliation and explicit out-of-scope items

**Phase 5 adds zero new dataclass fields to either config** — the
cleanest possible outcome of the score-weight and anchor-ownership
decisions above. Every field §13 names already exists with correct
per-field validation (Research §2, re-confirmed); this Plan's only
production-code additions are (a) one new cross-field validation
function on `EvidenceEngineConfig` (§15 item 2) and (b) one clarifying
comment on `StrategyEngineConfig` (§13). No field is duplicated under a
second owner — `opening_range_anchors` and its overlap check remain
solely on `EvidenceEngineConfig`; no parallel `StrategyEngineConfig`-side
anchor field or check is introduced (Research §7's finding, re-confirmed
here: doing so would be exactly the duplicate logic CLAUDE.md §1.3/§1.4
forbid).

**`orb_approved_pairs` / pair-eligibility wiring — explicitly excluded
from Phase 5.** Grounded in the same reasoning ADR-035 §18.A item 2
already used to move the session-lockout mechanism from Phase 1 to Phase
2 ("the first phase at which the answer has any observable effect"):
ORB has zero registry presence until Phase 6, so its approved-pairs list
has no observable effect before then; no precedent exists for wiring
*any* strategy's pairs through `config_loader.py` (confirmed: none of
the five legacy strategies' `approved_pairs_by_strategy` entries are
JSON-configurable either). §18.B item 4 ("empty-by-default... a Phase 5
configuration question") is read as naming the *default-value* question
(already resolved: empty, per that section's own text), not a mandate to
JSON-wire it now. Deferred to Phase 6, if ever needed.

### 17. Preservation requirements — confirmed by construction, not merely asserted

Because §13 resolved to Option A (zero `orb_breakout.py` changes) and no
new fields are added anywhere (§16), every preservation requirement
holds trivially and is verifiable by `git diff --name-only` at Implement
time showing none of these touched: Phase 2 breakout/lockout semantics
(`orb_breakout.py`, `OrbQualificationStore` — untouched); Phase 3 FVG
score-only behavior (same file, same reason); Phase 4 range-selection/MI/
range-quality eligibility (same file); ORB's unregistered status
(`build_default_registry()`/`strategies/__init__.py` — untouched, no
registration logic anywhere in this Plan); the five legacy strategy
files (untouched — this Plan touches only `config.py` files and
`deployment_windows/`); Phase 7's formation-time-blackout limitation
(untouched — no news/blackout logic anywhere in this Plan's scope).

### 18. File-impact matrix

**REQUIRED:**
- `titan_protocol/evidence_engine/config.py` — new
  `_validate_range_duration_feasible()` function + one call site in
  `__post_init__` (§15 item 2). No new fields.
- `titan_protocol/strategy_engine/config.py` — one clarifying comment
  only (§13). No new fields, no logic change.
- `deployment_windows/config_loader.py` — new `"strategy_engine"`/
  `"evidence_engine"` section parsing; `DeploymentSettings` gains
  `strategy_config: StrategyEngineConfig` and `evidence_config:
  EvidenceEngineConfig` fields (§14).
- `deployment_windows/start.py` — line 1126/1194: use
  `settings.strategy_config`/`settings.evidence_config` instead of bare
  defaults (§14).
- `deployment_windows/health_check.py` — line 190: same substitution for
  its own `StrategyEngineConfig()` call.
- `deployment_windows/install.py` — lines 301/303: same substitution for
  both constructor calls.
- `deployment_windows/config/titan_protocol_config.example.json` — two
  new sections (`"strategy_engine"`, `"evidence_engine"`) documenting
  every wired field with the established `_maps_to`/`_note` convention;
  update the `trading_profile` section's now-partially-stale comment to
  reflect that ORB's own fields are now wired while the five legacy
  strategies' fields remain not independently overridable.
- `tests/titan_protocol/evidence_engine/test_opening_range.py` — new
  feasibility-check tests (§15 item 2's worked examples).
- `tests/deployment_windows/test_config_loader.py` — new tests per §19.

**POSSIBLY REQUIRED (Implement-phase discretion, within minimal-change
bounds — state explicitly in the Implement report if touched or not):**
- `deployment_windows/KNOWN_GAPS.md` — an optional entry disclosing that
  `opening_range_anchors` is now operator-configurable (previously
  always empty/inert in production) — documentation only, no ADR
  mandate.

**READ ONLY (consulted for evidence, not modified):**
- `docs/adr/ADR-035-orb-strategy.md` (§5, §13, §17, §18.B).
- `docs/plans/adr-035-phase2-orb-breakout-lockout.md`,
  `adr-035-phase3-fvg-confirmation.md`,
  `adr-035-phase4-mi-eligibility-integration.md`.
- `titan_protocol/strategy_engine/strategies/orb_breakout.py` (confirmed
  unaffected by Option A — must remain byte-for-byte unchanged, verified
  by diff at Implement time, not merely "not edited").
- `titan_protocol/strategy_engine/strategies/__init__.py` /
  `registry.py` (confirmed ORB remains unregistered).
- The five legacy strategy files (confirmed untouched).
- `titan_protocol/market_data_ingestion/config.py` (confirmed no
  timeframe-consistency wiring is in scope, §14).

**OUT OF SCOPE (must not be touched — explicit, not merely implied):**
- `titan_protocol/strategy_engine/strategies/orb_breakout.py` — no score
  formula change (§13, Option A).
- Both Strategy-Engine structural-boundary allowlists
  (`compliance_state_store`/`news_ingestion` `test_structural_boundary.py`)
  — no new entries; `evidence_engine/config.py` and
  `strategy_engine/config.py` are already-authorized exceptions in both
  files (re-confirmed by direct read), and no other `titan_protocol/`
  production file is touched.
- `titan_protocol/strategy_engine/config.py`'s
  `DEFAULT_APPROVED_PAIRS_BY_STRATEGY` / any `orb_approved_pairs` wiring
  (§16 — deferred to Phase 6).
- `opening_range_post_range_bar_window` JSON wiring (§14).
- `docs/adr/ADR-035-orb-strategy.md` — no amendment (§13's evidence
  trail shows none is required).
- `build_default_registry()` / ORB registration (Phase 6, unauthorized).
- Any Phase 7 formation-time-blackout work (unauthorized).
- `titan_protocol/market_data_ingestion/config.py` (timeframe wiring —
  a separate, pre-existing, disclosed concern, not this Plan's scope,
  §14).

### 19. Test and validation matrix

**Targeted — `tests/titan_protocol/evidence_engine/test_opening_range.py`
(new):**
- `test_range_duration_feasibility_exact_boundary_passes` —
  `duration_minutes=30, expected_bar_interval_seconds=300,
  opening_range_min_bars=6` constructs without error.
- `test_range_duration_feasibility_one_above_boundary_raises` — same
  fixture with `opening_range_min_bars=7` raises `ValueError`.
- `test_range_duration_feasibility_non_exact_division_boundary` —
  `duration_minutes=22, expected_bar_interval_seconds=300` (`max=5`):
  `min_bars=5` passes, `min_bars=6` raises.
- Re-run (no change expected): `test_overlapping_anchors_raise_value_error_at_construction`,
  `test_invalid_min_bars_raises_value_error`, `test_invalid_duration_raises_value_error`,
  `test_invalid_expected_interval_raises_value_error` — must remain green,
  proving the new check doesn't interfere with the existing ones.

**Targeted — `tests/deployment_windows/test_config_loader.py` (new):**
- Per wired field (both sections): JSON value honored; section/key
  absent → engine default preserved (byte-identical
  `StrategyEngineConfig()`/`EvidenceEngineConfig()`); out-of-safe-range
  value raises `ConfigError` at `load_settings()` time, never later.
- `opening_range_anchors`: valid JSON round-trips to the correct tuple of
  `(SessionName, hour, minute)`; an unknown `"session"` string raises
  `ConfigError`; two overlapping anchors in JSON raise `ConfigError`
  (proving the existing check is reachable end-to-end through the
  loader, §15 item 1); an infeasible `min_bars`/`duration`/`interval`
  combination in JSON raises `ConfigError` (proving the new check is
  reachable end-to-end, §15 item 2).
- Backward compatibility: a JSON fixture with no `"strategy_engine"`/
  `"evidence_engine"` section at all (representing every pre-Phase-5
  config file) produces `DeploymentSettings.strategy_config ==
  StrategyEngineConfig()` and `.evidence_config == EvidenceEngineConfig()`
  exactly.

**Score behavior (proving Option A introduced zero change):** no new
test required — the existing `tests/titan_protocol/strategy_engine/test_orb_breakout_foundation.py`
suite (78 tests as of Phase 4) must remain 100% green with zero
reason-string or score-value changes, verified by re-running it
unmodified at Implement time.

**Preservation / full regression:**
- `python -m compileall` on every touched file.
- `python -m unittest discover -s tests/titan_protocol` — must remain
  1370 baseline + the new `test_opening_range.py` additions, zero
  regressions elsewhere.
- `python -m unittest tests.deployment_windows.test_config_loader` —
  19 baseline + new additions.
- `tests/titan_protocol/strategy_engine/test_architecture.py` and
  `tests/titan_protocol/evidence_engine/test_architecture.py` — both
  green, no new entries expected (no new imports, no forbidden
  vocabulary introduced by either change).
- Both `test_structural_boundary.py` suites — green, zero new allowlist
  entries (§18).
- `build_default_registry()` — still exactly 5 strategies, ORB excluded.
- `git diff --name-only` against current HEAD — must match exactly the
  REQUIRED file-impact list (§18), confirming `orb_breakout.py` and the
  five legacy strategy files are untouched.
- `python3 scripts/check_architecture.py` — mandatory per `TEAM.md` §9
  (scans `phantom_pipeline/`, unaffected by this change).

### 20. Adversarial review (performed against this finalized Plan before disposition)

- **Contradictory ownership:** none found. `opening_range_anchors`
  (and its overlap check) is owned solely by `EvidenceEngineConfig`;
  the new feasibility check is added to the same file, same
  `__post_init__`, no ownership split. `orb_fvg_score_weight` remains
  solely owned by `StrategyEngineConfig`.
- **Duplicate validation:** none found. The overlap check is not
  reimplemented; the feasibility check is added exactly once; the
  weight-sum question resolves to zero new validation logic (a comment
  only), not a second check duplicating the first.
- **Magic-number/config inconsistencies:** the new feasibility check
  introduces no new numeric literal — it operates purely on
  already-existing, already-validated fields (`duration_minutes`,
  `min_bars`, `expected_interval_seconds`). Constraint made explicit for
  Implement: JSON key names must exactly match dataclass field names
  (no renaming), matching every existing section's own convention, to
  prevent silent drift between the example config's documentation and
  the real fields.
- **Score inflation:** none introduced — §13's Option A leaves the score
  formula, and its existing `clamp(...)` ceiling, completely unchanged.
- **Startup configs that could bypass fail-closed validation:** checked
  explicitly — every new/changed field reaches its target dataclass via
  the same `dataclasses.replace()`-over-defaults idiom already used for
  `compliance_config`, which constructs a new instance through the
  dataclass's real `__init__`/`__post_init__` path every time (confirmed:
  `dataclasses.replace()` does not bypass `__post_init__` — it is not a
  shortcut like `object.__new__`). No new construction path is
  introduced that could skip validation.
- **Stale governance statements:** this Plan does not claim Phase 6 or
  Phase 7 authorization anywhere; does not claim any ADR needs
  amendment (§13's evidence trail shows none is required); does not
  restate the historical "Research §6/§12 open question" framing as
  still-open now that §13-§16 above resolve it.
- **Accidental Phase 6/7 scope creep:** checked explicitly against §18's
  OUT OF SCOPE list — `build_default_registry()`, ORB registration,
  `orb_approved_pairs` wiring, and all Phase 7 formation-time-blackout
  work are named and excluded, not merely absent by omission.

No adversarial finding requires a further revision to this Plan.

## Validation

(Not started — Implement phase. This Plan authorizes no implementation.)

---

**Disposition: PHASE 5 PLAN FINALIZED — READY FOR INDEPENDENT
IMPLEMENTATION-READINESS REVIEW.**

Every implementation-significant question this task named has been
resolved with evidence, not invented: the score-weight contract (Option
A, §13, with a full textual trail across ADR-035 §5/§13/§17 and both
already-accepted Phase 2/3 Plans); the configuration-loader's exact
per-field contract (§14); all three §13 cross-field rules (§15); the
final field inventory, confirming zero new dataclass fields anywhere
(§16); preservation requirements, satisfied by construction (§17); a
REQUIRED/POSSIBLY-REQUIRED/READ-ONLY/OUT-OF-SCOPE file-impact matrix
(§18); a full test/validation matrix (§19); and an adversarial re-read
that surfaced no further revision (§20). No Accepted-ADR contradiction
was found — ADR-035's own text already authorizes every decision made
here, and no governance action (amendment or otherwise) is required
before Implement.

**Phase 5 implementation remains prohibited** until this Plan receives
its own independent implementation-readiness review. **Phase 6 and
Phase 7 remain unauthorized regardless of this Plan's disposition.**
