# Plan: ADR-035 Phase 6 — Full-Suite Validation

Status: **RESEARCH ONLY — Plan and Validation sections intentionally
empty.** This artifact records the Research phase of the RPI gate
(`.claude/agents/TEAM.md` §9) for ADR-035 Phase 6. No implementation
decision is made here; several are deliberately left open below for
Plan-phase resolution.

Owner (Research phase): Software Architect (ADR-035/ADR-025/ADR-026
owner precedent, unchanged from Phases 2-5).

Touched components (anticipated, not final — see §7 below): at minimum
`titan_protocol/strategy_engine/strategies/__init__.py`
(`build_default_registry()`), `tests/titan_protocol/strategy_engine/test_engine.py`,
`tests/titan_protocol/strategy_engine/test_regression.py`; very likely
`deployment_windows/start.py` and possibly `deployment_windows/config_loader.py`
and the example JSON, depending on how the Plan phase resolves the two
open questions in §5. **Not in scope:** the anchor hour/minute
range-validation residual risk flagged in the Phase 5 conformance
review (a separate, independently-scoped follow-up, explicitly excluded
per the user's Research directive), Phase 7's formation-time
news-blackout closure, and any of the five legacy strategy files.

---

## Research

### 0. Governance gate (verified against current HEAD, not assumed)

- Branch: `claude/phantom-ea-visibility-cjjf3a`. HEAD:
  `82d5a52295ec89447ad78eae8eefba837dc2a219`. Working tree clean
  (`git status --porcelain` empty).
- `docs/adr/ADR-035-orb-strategy.md`: **Accepted** (2026-07-25).
  Amendment 1 (formation-time news-blackout staged limitation):
  **Accepted** (2026-07-26, commit `9b7d255`).
- Phase 5 (`docs/plans/adr-035-phase5-configuration.md`) is independently
  reviewed and accepted (commit `82d5a52` against Plan commit `6b66b69`;
  see the Phase 5 conformance review, this session). Per CLAUDE.md
  §1.10, Phase 6 implementation may not begin until its own Plan is
  written and independently reviewed — this document is Research only.
- `python3 scripts/check_architecture.py` re-run this pass: **PASS**
  (checks the legacy `phantom_pipeline/` tree; unrelated to
  `titan_protocol/` but confirms no regression there).
- The `titan_protocol/strategy_engine` and `titan_protocol/evidence_engine`
  structural-boundary/architecture test suites (`test_architecture.py`
  in each package) were re-run this pass: 11/11 pass, no change needed
  for anything found so far (see §7).

### 1. ADR-035 §17's exact Phase 6 text (re-read directly, not from memory)

> **Phase 6 — Full-suite validation:** integration (real
> five-plus-ORB `StrategyEngine` competing in the real selection
> cascade), regression (existing five strategies' behavior unchanged —
> `git diff --stat` showing zero change to any of them), exception
> safety, and every edge case in §15 — the cross-phase pass that only
> full end-to-end wiring makes possible, not the first point at which
> any test exists.

Four explicit mandates, all directly from ADR text (not inferred):

1. **Integration** — a real `StrategyEngine` with all five legacy
   strategies *plus* ORB, competing in the real `selection.py` cascade.
2. **Regression** — the five legacy strategy files must show zero
   diff (`git diff --stat`).
3. **Exception safety** — no unhandled exception path introduced by
   full end-to-end wiring.
4. **§15's edge cases**, exercised end-to-end (not just at the unit
   level they were already partially exercised at in Phases 0-5).

Mandate (1) is the load-bearing one: it requires ORB to actually
*compete* — i.e., be registered — which is a materially different
posture than every prior phase (0-5), all of which explicitly kept ORB
unregistered and therefore inert in the live system (§18.B item 4;
Phase 3/4/5 Plans all state "ORB remains unregistered," re-confirmed
directly against current source below, §2).

Nothing in §17's Phase 6 text, §18, or §19 explicitly says "flip the
registry switch" in those words — the requirement to register ORB is
derived from mandate (1)'s own wording ("real five-plus-ORB
`StrategyEngine`"), not a separate, independently-stated instruction.
This derivation is recorded here as evidence, not assumed; the Plan
phase should re-confirm this reading is still correct before proceeding
(see §5, open question 1).

### 2. Current implementation state (read directly this pass)

- `titan_protocol/strategy_engine/strategies/__init__.py::build_default_registry()`
  registers exactly the five legacy strategies
  (`LiquiditySweepMssStrategy`, `BosFvgStrategy`,
  `TrendContinuationStrategy`, `SessionBreakoutStrategy`,
  `RangeReversalStrategy`) and does **not** register
  `OrbBreakoutStrategy`, though `OrbBreakoutStrategy` is already
  imported and re-exported from the same module's `__all__`. Live-run
  confirmation: `build_default_registry().all()` returns 5 strategy
  instances; ORB is absent.
- `titan_protocol/strategy_engine/strategies/orb_breakout.py`'s own
  module docstring states directly: *"Still absent from
  `build_default_registry()` -- production registration remains no
  earlier than Phase 6 (ADR-035 §17)"* — a self-documenting marker
  consistent with the ADR.
- `OrbBreakoutStrategy.__init__(self, store: OrbQualificationStore)` has
  **no default constructor** — unlike all five legacy strategies (each
  takes zero constructor arguments, confirmed by reading
  `build_default_registry()`'s own `register(Strategy())` calls). ORB is
  Strategy Engine's first, and only, stateful strategy (by design,
  ADR-035 §18.A item 2).
- `OrbQualificationStore.__init__(self, config: StrategyStateStoreConfig)`
  — also no default; `StrategyStateStoreConfig` is a frozen dataclass
  with a single **mandatory**, no-default field: `state_file: Path`.
- `build_default_registry()` has exactly one production call site in
  the entire repository: `titan_protocol/strategy_engine/engine.py`'s
  `StrategyEngine.__init__`, invoked with zero arguments
  (`registry if registry is not None else build_default_registry()`).
  `deployment_windows/start.py` line 1194 constructs
  `StrategyEngine(strategy_config)` with no explicit registry, i.e. it
  is the one live call path that currently receives the
  five-legacy-only registry.
- **Nowhere in the repository** — not `config_loader.py`, not
  `start.py`, not the example JSON, not any test fixture outside
  `tests/titan_protocol/strategy_engine/test_orb_breakout_foundation.py`'s
  own `_OrbTestCase` helper — is `StrategyStateStoreConfig`/
  `OrbQualificationStore` constructed with a real file path tied to
  deployment. This is a genuine, previously-undocumented gap: Phase 5's
  config wiring (§13's fields) never touched the strategy-state-store
  layer at all (confirmed: `orb_max_qualifications_per_range`, the one
  §13 field the lockout store's *limit* comes from, is wired; the
  store's own *file path* is not, because no phase before Phase 6 needed
  it to be — ORB was never registered, so nothing ever constructed a
  live store).
- `StrategyEngineConfig.DEFAULT_APPROVED_PAIRS_BY_STRATEGY` (the
  pair-eligibility hard gate, ADR-026 Hard Rules 4-5) has **zero entry**
  for `StrategyId.OPENING_RANGE_BREAKOUT`.
  `StrategyEngineConfig.approved_pairs_for(OPENING_RANGE_BREAKOUT)`
  therefore falls through to `return ()` (confirmed by reading
  `config.py` lines 145-149), and `eligibility.check_eligibility()`
  returns `NOT_ELIGIBLE` unconditionally whenever a pair is outside a
  strategy's approved set (confirmed by reading `eligibility.py` in
  full). **Concrete consequence, independently derived and important
  for blast-radius assessment:** if `build_default_registry()` registers
  ORB *today*, with no other change, ORB's `qualify()` would hit its own
  first gate (`check_eligibility`, `orb_breakout.py` line 78) and return
  `NOT_ELIGIBLE` for every pair, every cycle — ORB would appear in
  `all_qualifications` (changing its count from 5 to 6) but could never
  win the selection cascade and could never produce a trade. Registering
  ORB alone, without also adding an approved-pairs entry, is therefore a
  test-assertion-only change with **zero live trading-behavior impact**.
- `DEFAULT_APPROVED_PAIRS_BY_STRATEGY` is exactly what ADR-035 §18.B
  item 4 named as a **Future design consideration**, explicitly deferred
  past Phase 0-4 as "a Phase 5 configuration question" and then
  explicitly excluded from Phase 5 by that Plan (§16, "explicitly
  excluded from Phase 5... no precedent exists for wiring *any*
  strategy's pairs through `config_loader.py`"). It has never been
  affirmatively resolved by any Accepted artifact. Whether Phase 6 is
  the phase that resolves it, or whether it remains open past Phase 6
  too, is unaddressed by ADR-035 §17's Phase 6 text and is recorded as
  an open question (§5, item 2).
- Existing tests that assume the *current* (five-only) registry size:
  a repo-wide grep for `all_qualifications), 5` found exactly two
  hard-coded assertions —
  `tests/titan_protocol/strategy_engine/test_engine.py:19`
  (`test_returns_a_fully_populated_snapshot`) and
  `tests/titan_protocol/strategy_engine/test_regression.py:22`
  (`test_default_fixture_always_rejects`). Both construct
  `StrategyEngine(make_config())` with the implicit default registry, so
  both will need their assertion updated from `5` to `6` the moment
  `build_default_registry()` registers ORB — regardless of how the
  open questions in §5 are resolved. No other test in
  `tests/titan_protocol` was found to assert a specific registry size
  (verified via the same grep pattern against `== 5`,
  `len(registry)`, `len(r.all())`).
  `test_orb_breakout_foundation.py::test_five_legacy_strategy_ids_remain`
  only checks `StrategyId.__members__` enum membership, not registry
  membership — unaffected either way.
- Structural boundary: `tests/titan_protocol/strategy_engine/test_architecture.py`'s
  `ALLOWED_UPSTREAM_PREFIXES` already includes
  `"titan_protocol.strategy_state_store"` (confirmed by direct read,
  line 30) — this was already required and already allowlisted back
  when `orb_breakout.py` itself was implemented (Phase 2), because
  `orb_breakout.py` already imports `OrbQualificationStore` today. **No
  structural-boundary allowlist change is anticipated for Strategy
  Engine itself.** Whatever wiring Phase 6 adds to obtain a
  `StrategyStateStoreConfig`/file path (§5 item 1) would live in
  `deployment_windows/`, which is not part of the
  `check_architecture.py`/`test_architecture.py` boundary-checked
  `titan_protocol/` package graph, and already imports engine-owned
  config classes directly (established precedent: `StrategyEngineConfig`,
  `EvidenceEngineConfig`, Phase 5).

### 3. Dependencies on Phases 2-5 behavior (re-verified against current source)

- **Phase 2 (breakout qualification + lockout):** `orb_breakout.py`'s
  `qualify()` (read in full this pass) calls
  `self._store.try_consume(pair, opening_range.range_start,
  config.orb_max_qualifications_per_range)` as its final gate before
  returning `QUALIFIED` — the lockout is still the terminal,
  side-effecting step, unchanged. `OrbQualificationStore`'s persistence/
  concurrency/failure-containment semantics are untouched by anything
  in the `6b66b69..82d5a52` diff (confirmed, Phase 5 conformance review
  §11) and by this pass's own read of the current file (no diff since).
- **Phase 3 (FVG confirmation):** the `qualifying_fvg`/`fvg_bonus` block
  (lines 172-190) is score-only, cannot disqualify, and is additive to
  the final `score` expression — unchanged in shape from what Phase 3's
  own Accepted Plan established.
- **Phase 4 (MI eligibility):** the five MI gates (`market_closed`,
  `is_holiday`, `blackout_active`, spread vs. `orb_max_spread_pips`,
  liquidity vs. `orb_min_liquidity_score`) plus the range-quality gate
  (`orb_min_range_atr_ratio`) all appear, in that order, exactly as
  Phase 4's Accepted Plan specified — re-confirmed by direct read this
  pass, not assumed from the earlier conformance review.
- **Phase 5 (config wiring):** `config.orb_max_spread_pips`,
  `config.orb_min_liquidity_score`, `config.orb_min_range_atr_ratio`,
  `config.orb_min_breakout_distance_atr_multiple`,
  `config.orb_min_body_to_range_ratio`,
  `config.orb_min_confirmation_candles`,
  `config.orb_fvg_max_age_bars`, `config.orb_fvg_min_size_atr_multiple`,
  `config.orb_fvg_score_weight`, `config.orb_max_qualifications_per_range`
  are all read directly from the `StrategyEngineConfig` instance passed
  into `qualify()` — i.e. Phase 6's "real" `StrategyEngine` will,
  for the first time, exercise these fields' *values as configured
  through `deployment_windows/config_loader.py`* against a live
  competing strategy, not merely against unit-level `make_config()`
  fixtures. This is new observable coverage Phase 6 provides that no
  earlier phase's tests could, by construction (ORB was never wired
  into a real `StrategyEngine`/`config_loader.py` round trip before).
- **Registry/legacy strategies:** `build_default_registry()`'s current
  five registrations, and all five legacy strategy files, show no diff
  against `82d5a52` in this pass's re-read — the regression baseline
  Phase 6 must preserve is the current, already-green state (§12 will
  record fresh counts once Plan/Implement exist; Research does not run
  a bespoke pre-emptive suite beyond what's recorded below).

### 4. §15 edge cases — current coverage state (per-row, verified against actual test files, not summarized)

| §15 edge case | Where it is exercised today | End-to-end (real registered ORB + real `StrategyEngine`) coverage |
|---|---|---|
| Gap open before/inside range window | `tests/titan_protocol/evidence_engine/test_opening_range.py` (`TestNegativeCases`, gap tests) | Not yet — only at the Evidence Engine unit level |
| Missing candles / temporal gap | Same file, `test_gap_exactly_at_threshold_is_not_a_gap` / `test_gap_one_second_beyond_threshold_is_a_gap` | Not yet, same reason |
| Session reconnect mid-range | Not found as a named test anywhere under `tests/titan_protocol` | Not covered at any level today |
| DST transitions | Not found as a named test | Documented as an operator responsibility in the ADR (§15), not testable in isolation |
| Holiday sessions | `orb_breakout.py`'s own `is_holiday` gate, unit-tested in Phase 4's suite (`test_orb_breakout_foundation.py`, per that phase's own test matrix) | Unit-level only |
| Multiple ranges / anchor overlap | `test_opening_range.py::TestSessionIsDescriptiveOnly`, plus the Phase 5 anchor-overlap tests in `test_config_loader.py` | Config-loader + Evidence Engine levels; not yet through a live `StrategyEngine` selecting among a real ORB entry |
| Broker time differences | Not found as an ORB-specific test; relies on `market_data_ingestion`'s existing clock-skew validation (unchanged, out of ADR-035's scope per §15's own text) | N/A — explicitly another package's concern |
| Partial trading days / early close | Not found as an ORB-specific test; relies on `MarketSafetyInputs.early_closes` (existing, ADR-025) | Not covered by an ORB-specific test at any level today |

None of these are Phase-6-introduced regressions — they are simply not
yet exercised **end-to-end**, which is exactly the gap ADR-035 §17
assigns to Phase 6 ("the cross-phase pass that only full end-to-end
wiring makes possible, not the first point at which any test exists").
Session reconnect, broker time differences, and partial trading days
have no ORB-specific test at any level today, unit or integration —
these are the widest gaps and should be prioritized in the Plan's test
matrix.

### 5. Open design/governance questions for Plan finalization (not resolved here)

1. **Does Phase 6 register ORB in `build_default_registry()` at all, or
   does it validate a *parallel*, test-only "five-plus-ORB" registry
   without changing the production default?** ADR-035 §17's own words
   ("real five-plus-ORB `StrategyEngine`") lean toward registering it
   in production, but this is this Research's own derivation (§1), not
   an explicit instruction quoted verbatim from the ADR. Competing
   options and their evidence:
   - **Option A — register in production `build_default_registry()`.**
     Directly satisfies "real... competing in the real selection
     cascade" without qualification. Given §2's finding that
     `approved_pairs_for(OPENING_RANGE_BREAKOUT)` returns `()` by
     default, this has **zero live trading-behavior impact** unless
     paired with question 2's resolution — a materially lower-risk
     change than it might first appear. Requires resolving the
     `OrbQualificationStore` construction gap (question 3) since
     `build_default_registry()` is currently a zero-argument factory.
   - **Option B — a Phase-6-only integration-test harness constructs
     a real registry with all six strategies (bypassing
     `build_default_registry()`'s production default) purely to
     exercise the "real selection cascade" requirement in tests,
     leaving `build_default_registry()`/`start.py`'s live behavior
     unchanged until a later phase.** This would satisfy the literal
     integration-test requirement without touching production
     registration, but arguably does not satisfy "real... `StrategyEngine`"
     if "real" is read as "the one `start.py` actually constructs" —
     a live-vs-test distinction the ADR text does not explicitly
     disambiguate.
   Recommendation for the Plan phase to state and justify explicitly,
   not silently default (per this project's established practice for
   exactly this kind of ambiguity, e.g. Phase 4's §18.A item 2
   treatment).

2. **Does Phase 6 also add a `DEFAULT_APPROVED_PAIRS_BY_STRATEGY` entry
   for `OPENING_RANGE_BREAKOUT`, making it pair-eligible (and therefore
   actually reachable in live trading), or does it leave that entry
   absent, per ADR-035 §18.B item 4's "empty-by-default (safest, forces
   deliberate operator choice)" recommendation?** This is the single
   decision that determines whether Phase 6 is purely a wiring/test
   validation with zero live blast radius, or the phase at which ORB
   becomes capable of producing a real trade for the first time. §18.B
   item 4 explicitly frames this as a "Phase 5 configuration question"
   that Phase 5 then explicitly declined to answer (deferred, not
   resolved) — nothing in §17's Phase 6 text revisits it. Options:
   - **Option A — leave empty (§18.B item 4's own stated default).**
     Phase 6 becomes purely integration/regression/edge-case validation
     of a registered-but-still-inert strategy; the "first phase with
     observable live effect" question moves to a still-later,
     unscheduled phase (an operator configuring pairs after Phase 6, or
     a Phase 8 the roadmap does not yet name).
   - **Option B — Phase 6 adds a starter list (or wires it through
     `config_loader.py` the same way §13's other fields were wired in
     Phase 5).** This would be new scope beyond what §17's Phase 6 text
     literally describes ("full-suite validation" does not, on its
     face, include "decide the pair-eligibility default"), and would be
     the first phase to give ORB genuine live trading effect —
     arguably itself deserving of a fresh independent
     implementation-readiness review given CLAUDE.md's Priority-1 rule
     ("capital preservation overrides profit").
   Recommendation for the Plan phase to decide and justify with
   evidence, not invent silently; Research flags this as unresolved
   rather than assuming either direction.

3. **How does `build_default_registry()` obtain the
   `StrategyStateStoreConfig`/`state_file: Path` `OrbQualificationStore`
   needs, given `build_default_registry()` is currently a zero-argument
   function and no deployment-layer wiring for this store exists
   anywhere in the repository today (§2)?** This is a genuine, previously
   undocumented contract gap — not a Phase 5 omission (Phase 5's Plan
   never claimed to wire the store's file path; ADR-035 §18.A item 2
   only required the store's *design*, which Phase 2 delivered) but a
   precondition Phase 6 cannot avoid if question 1 resolves to Option A.
   Options, by rough analogy to `compliance_state_store`'s own existing
   `deployment_windows` wiring (its file path is derived from the
   config's existing `state_dir` value, confirmed as an existing
   convention in `titan_protocol_config.example.json`'s `logging.state_dir`
   field):
   - **Option A — `build_default_registry()` gains an optional
     parameter** (e.g., `orb_store: Optional[OrbQualificationStore] =
     None`) that, if omitted, either (a) does not register ORB at all
     (preserves every existing zero-arg call site's behavior exactly,
     but then Option A of question 1 is not actually achieved by this
     function alone), or (b) constructs a store against a
     Strategy-Engine-owned default path. Needs Plan-phase resolution of
     exactly what "default path" means when no deployment config is
     present (e.g., in every existing unit test that calls
     `StrategyEngine(make_config())` with no registry argument today).
   - **Option B — `deployment_windows/start.py`/`config_loader.py`
     gains new wiring** (a new `strategy_state_store` or similar JSON
     section/field analogous to `logging.state_dir`) that constructs a
     real `OrbQualificationStore` and passes an explicit registry into
     `StrategyEngine(strategy_config, registry=...)`, leaving
     `build_default_registry()`'s own zero-argument shape and every
     existing test's call pattern untouched. This confines the new
     contract entirely to the deployment layer, consistent with how
     Phase 5 confined its own new wiring to `config_loader.py` rather
     than touching engine-internal defaults.
   Recommendation for the Plan phase; Research does not pick between
   them, since the correct answer depends on question 1's resolution
   and on a design review of the store's own file-path/atomic-write
   conventions this Research did not perform (out of scope — that
   would be implementation, not research).

4. **Do `test_engine.py`/`test_regression.py`'s hard-coded `len(...),
   5` assertions get updated in place, or does the Plan introduce new,
   separate ORB-aware integration tests and leave these two files
   untouched (accepting that they would then fail once ORB is
   registered, which cannot be the final state)?** This is close to
   mechanical (the two assertions clearly need to become `6` once ORB
   is registered under Option A of question 1), flagged mainly so the
   Plan's file-impact matrix explicitly lists these two files rather
   than discovering the failure only during Implement.

### 6. Distinguishing ADR-mandated requirements from implementation choices

**Explicitly mandated by ADR-035 (§17, quoted verbatim in §1 above):**
- A real `StrategyEngine` with all five legacy strategies plus ORB
  competing in the real selection cascade.
- Zero diff to any of the five legacy strategy files
  (`git diff --stat`).
- Exception-safety coverage.
- End-to-end exercise of every §15 edge case.

**Left to Plan-phase implementation choice (not decided by the ADR
text, listed in §5 above):**
- Whether "register in the real selection cascade" means production
  `build_default_registry()` or a test-only harness (§5.1).
- Whether ORB's pair-eligibility list is populated in this phase
  (§5.2) — the ADR's own §18.B explicitly defers this decision without
  naming which phase resolves it.
- The concrete mechanism for supplying `OrbQualificationStore` a real
  `state_file` path (§5.3) — ADR-035 authorizes the store's *design*
  (§18.A item 2) but never specifies deployment-layer wiring, because
  no phase before Phase 6 needed a live store.
- The exact shape of new/updated tests (§5.4, §4's table).

### 7. Anticipated file/boundary impact (provisional — Plan phase confirms or revises)

- `titan_protocol/strategy_engine/strategies/__init__.py` —
  `build_default_registry()`, if question 1 resolves to Option A.
- `tests/titan_protocol/strategy_engine/test_engine.py` — assertion
  update (5→6), near-certain regardless of how the open questions
  resolve, so long as ORB is registered anywhere the default-registry
  path reaches these tests.
- `tests/titan_protocol/strategy_engine/test_regression.py` — same.
- Possibly `deployment_windows/start.py` and/or
  `deployment_windows/config_loader.py` and the example JSON, only if
  question 3 resolves to Option B (deployment-layer store wiring).
- New test file(s) for the integration/regression/exception-safety/
  edge-case matrix §17 and §15 require — likely a new
  `tests/titan_protocol/strategy_engine/test_orb_full_suite_integration.py`
  or an addition to the existing `test_engine.py`/`test_regression.py`,
  Plan phase to decide.
- **No change anticipated** to: any of the five legacy strategy files;
  `titan_protocol/evidence_engine/` (Phase 0-Phase 5 behavior, already
  independently verified unchanged as of the Phase 5 conformance
  review); `titan_protocol/market_intelligence/`; any ADR file; any
  structural-boundary allowlist (§2 — `strategy_state_store` is already
  an allowed Strategy Engine upstream import); the anchor hour/minute
  range-validation residual risk (explicitly out of scope, per the
  user's directive).

### 8. Baseline validation results (re-run fresh this pass)

| Check | Result |
|---|---|
| `python3 -m compileall titan_protocol deployment_windows tests` | OK |
| `python3 scripts/check_architecture.py` | PASS |
| `tests.titan_protocol.strategy_engine.test_architecture` + `tests.titan_protocol.evidence_engine.test_architecture` | 11/11 OK |
| `python3 -c "from titan_protocol.strategy_engine.strategies import build_default_registry; ..."` (live construction) | 5 strategies, ORB absent — confirmed |
| `git status --porcelain` | clean |
| `git diff --stat 6b66b69 82d5a52` (unchanged from Phase 5 review, re-confirmed) | 10 files, matches the already-accepted Phase 5 diff exactly |

A full `unittest discover -s tests/titan_protocol` re-run is deferred to
this document's own Validation section once a Plan exists — Research
does not re-run the entire suite pre-emptively beyond the targeted
architecture/compile checks above, since no code change has been
proposed yet to validate against.

---

## Plan

*(Intentionally left empty — Research only, per this task's authorization. §5's four open questions must be explicitly resolved here before Implement begins.)*

## Validation

*(Intentionally left empty — Research only.)*
