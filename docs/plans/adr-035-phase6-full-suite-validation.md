# Plan: ADR-035 Phase 6 — Full-Suite Validation

Status: **PLAN REVISED — IMPLEMENTATION AUTHORIZED.** An independent
implementation-readiness review of the finalized Plan (commit `68e977e`)
returned "PHASE 6 PLAN APPROVED WITH REQUIRED MINOR REVISIONS" — two
findings, both resolved in this pass: **F1** (`deployment_windows/install.py`'s
own `StrategyEngine` construction site was not inventoried by the file-impact
matrix — resolved in §P3a: confirmed construction-only, explicitly
recorded as NO CHANGE REQUIRED, not silently omitted); **F2** (the §15/
integration test matrix required ORB to be pair-eligible to exercise its
own qualification logic through the real `StrategyEngine`, but the Plan
never specified the test-only mechanism that achieves this without
touching the production default — resolved in §P7a: the existing
`make_config(approved_pairs_by_strategy=...)` override mechanism is now
specified explicitly, with the exact test items that require it named).
No design decision already settled in P1-P3/P6 was reopened — both
findings were documentation/specification gaps, not production-code
defects, and both are addressed without changing anything about the
already-verified-sound registration/eligibility/store/exception-safety
design.

Owner (Research phase): Software Architect (ADR-035/ADR-025/ADR-026
owner precedent, unchanged from Phases 2-5).
Owner (Plan phase): Software Architect (same precedent, unchanged).

Touched components (final, per the Plan section's file-impact matrix,
§P11): `titan_protocol/strategy_engine/strategies/__init__.py`
(`build_default_registry()` gains one optional parameter),
`deployment_windows/start.py` (one new construction block + explicit
registry passed to `StrategyEngine`), and new test coverage only — no
existing test file is modified (§P4 supersedes Research's provisional
guess that `test_engine.py`/`test_regression.py` would need updating).
`deployment_windows/install.py` is explicitly READ ONLY / NO CHANGE
REQUIRED (§P3a). **Not in scope:** the anchor hour/minute range-validation
residual risk flagged in the Phase 5 conformance review (a separate,
independently-scoped follow-up, explicitly excluded, §P13), Phase 7's
formation-time news-blackout closure, `DEFAULT_APPROVED_PAIRS_BY_STRATEGY`
(left unchanged, §P2), `config_loader.py`/the example JSON (no change
required, §P3), and any of the five legacy strategy files.

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

**Status of this section: FINALIZED — resolves all four Research-phase
open questions with direct repository evidence. Implementation remains
unauthorized pending independent implementation-readiness review.**

Re-verified fresh this pass (not trusted from the Research artifact):
branch `claude/phantom-ea-visibility-cjjf3a`, HEAD `c616b23`, clean tree;
`tests/titan_protocol` at 1373/1373 green, `tests/deployment_windows -t .`
at 162/162 green — both baselines still current.

### P0. Governing design principle

Every resolution below follows one rule, derived directly from
`titan_protocol/strategy_state_store/store.py`'s own docstring and
`deployment_windows/start.py`'s existing `compliance_state_store`/
`in_flight_commands` construction pattern (both read in full this pass):
**the live system (`start.py`) is the only place that changes.** Every
existing zero-argument call path (`build_default_registry()` with no
args, `StrategyEngine(config)` with no registry argument) keeps its
exact current behavior and exact current output. This is the minimal
diff that satisfies ADR-035 §17's "real five-plus-ORB `StrategyEngine`"
mandate without touching any of the 1373+161 currently-green tests that
never asked for ORB.

### P1. Resolution — ORB registration mechanism (Research question 1)

**Design:** `build_default_registry()` gains one new, optional,
keyword-usable parameter:

```python
def build_default_registry(
    orb_qualification_store: Optional[OrbQualificationStore] = None,
) -> StrategyRegistry:
    """The canonical registry: the 5 legacy strategies, always; plus
    Opening Range Breakout when a qualification-lockout store is
    supplied (ADR-035 Phase 6) -- omitted by default so every existing
    zero-argument caller is unaffected."""
    registry = StrategyRegistry()
    registry.register(LiquiditySweepMssStrategy())
    registry.register(BosFvgStrategy())
    registry.register(TrendContinuationStrategy())
    registry.register(SessionBreakoutStrategy())
    registry.register(RangeReversalStrategy())
    if orb_qualification_store is not None:
        registry.register(OrbBreakoutStrategy(orb_qualification_store))
    return registry
```

**Evidence this does not weaken existing registry behavior:**
- `StrategyRegistry.register()`/`.all()`/`.get()`/`DuplicateStrategyError`
  (`registry.py`, read in full this pass) are untouched — `register()`
  still takes one `Strategy` instance, still keys by
  `strategy.definition.strategy_id`, still raises
  `DuplicateStrategyError` on a repeat `strategy_id`. `OPENING_RANGE_BREAKOUT`
  is a distinct `StrategyId` member, so no collision risk exists.
- `engine.py`'s `self.registry = registry if registry is not None else
  build_default_registry()` (read in full this pass, line 46) requires
  **zero changes** — it still calls `build_default_registry()` with no
  arguments, which — under this design — still returns exactly the
  five-strategy registry it does today, byte-identical to current
  behavior. Every test that constructs `StrategyEngine(make_config())`
  with no registry argument (the overwhelming majority of the Strategy
  Engine suite) is therefore provably unaffected, not merely assumed
  unaffected.
- `OrbBreakoutStrategy.__init__(self, store: OrbQualificationStore)`
  (read in full this pass, `orb_breakout.py` line 64) is unchanged —
  the store is passed positionally exactly as its existing constructor
  already requires; no change to `orb_breakout.py` itself.

**Where ORB actually becomes live:** `deployment_windows/start.py` line
1194 (`strategy_engine = StrategyEngine(strategy_config)`) is the
**one** production call site that changes, to:

```python
orb_qualification_store = OrbQualificationStore(
    StrategyStateStoreConfig(state_file=settings.state_dir / "orb_qualifications.json")
)
strategy_registry = build_default_registry(orb_qualification_store)
strategy_engine = StrategyEngine(strategy_config, registry=strategy_registry)
```

placed immediately before that line, mirroring the exact
`ComplianceStateStore(ComplianceStateStoreConfig(state_file=settings.state_dir
/ "compliance_state.json"))` and `InFlightCommandStore(InFlightStoreConfig(
state_file=settings.state_dir / "in_flight_commands.json"))` construction
pattern already present a few lines below it (`start.py` lines 1203-1226,
read in full this pass) — this is not a new convention, it is the
existing one applied to a third store.

### P2. Resolution — pair-eligibility default (Research question 2)

**Decision: `DEFAULT_APPROVED_PAIRS_BY_STRATEGY` (`strategy_engine/config.py`,
read in full this pass, lines 41-47) receives NO entry for
`StrategyId.OPENING_RANGE_BREAKOUT` in Phase 6.**

**Evidence:** ADR-035 §18.B item 4 (read directly, `docs/adr/ADR-035-orb-strategy.md`)
states verbatim: *"Should ORB be limited to major pairs only at first
(`orb_approved_pairs` empty by default, fail-closed until an operator
configures it), or ship with a starter default list? ... This document
proposes empty-by-default (safest, forces deliberate operator choice)."*
This is a "Future design consideration" the ADR explicitly does not
assign to any specific phase, and Phase 5's own Accepted Plan
explicitly excluded it from Phase 5's scope (`docs/plans/adr-035-phase5-configuration.md`
line ~751, "explicitly excluded from Phase 5... no precedent exists for
wiring *any* strategy's pairs through `config_loader.py`"). Nothing in
§17's Phase 6 text ("full-suite validation") reopens or reassigns this
question to Phase 6 either — "full-suite validation" is a testing/
integration mandate, not a pair-eligibility policy mandate. Absent an
explicit instruction to populate it, the ADR's own stated default
("safest") is the correct one to preserve.

**Explicit three-way distinction (per this task's own requirement):**
1. **Registering ORB in `StrategyEngine`** (P1, above) — makes ORB
   *present* in `all_qualifications` and in the selection cascade's
   candidate pool.
2. **Making ORB eligible for particular pairs** — governed entirely by
   `DEFAULT_APPROVED_PAIRS_BY_STRATEGY`, which this Plan leaves empty
   for ORB. `eligibility.check_eligibility()` (read in full this pass)
   returns `NOT_ELIGIBLE` unconditionally whenever
   `config.approved_pairs_for(strategy_id)` does not contain the pair;
   `approved_pairs_for(OPENING_RANGE_BREAKOUT)` falls through to `return
   ()` (no matching entry, `config.py` lines 145-149) — i.e., every
   pair, always, until a future, separately-authorized phase or
   operator action adds an entry.
3. **Authorizing any live-trading behavior** — this Plan authorizes
   none. `OrbBreakoutStrategy.qualify()`'s very first line
   (`orb_breakout.py` line 78) is `check_eligibility(...)`; with an
   empty approved-pairs set, every call returns `NOT_ELIGIBLE` before
   any other ORB logic (opening-range state, FVG, breakout distance,
   lockout) is even reached. **Consequence, stated explicitly per this
   task's instruction:** registering ORB in Phase 6 has **zero live
   trading-behavior impact** — ORB will appear in `start.py`'s real
   `StrategyEngine`, in the real selection cascade, and will be
   `NOT_ELIGIBLE` for every configured pair, every cycle, indefinitely,
   until pair-eligibility is separately and explicitly authorized by a
   future phase. This fail-closed consequence must be directly asserted
   by a Phase 6 test (§P8, item 5), not left as an implicit assumption.

### P3. Resolution — strategy-state-store path and deployment wiring (Research question 3)

**No `config_loader.py` or example-JSON change is required.**
`settings.state_dir: Path` already exists on `DeploymentSettings`
(populated from `logging.state_dir` in the shipped example config,
confirmed present and unchanged since before Phase 5) and is already
the exact mechanism `compliance_state_store` and `in_flight_commands`
use for their own state files (`start.py` lines 1203-1205, 1224-1226,
read in full this pass — `state_file=settings.state_dir / "<name>.json"`
in both cases, constructed directly in `start.py`, not via
`config_loader.py`). Phase 6 follows this identical, already-established
convention for a third store:

- **Configuration ownership:** `deployment_windows/start.py`, exactly
  like the two existing precedents — not `config_loader.py`, which
  owns only `settings.state_dir` itself (already Phase-0-era wiring,
  untouched).
- **Default/path semantics:** `settings.state_dir / "orb_qualifications.json"`
  — a new filename sibling to `compliance_state.json` and
  `in_flight_commands.json` inside the same already-existing, already-
  created state directory (`_write_pid_file()`/`state_dir.mkdir(parents=True,
  exist_ok=True)` already guarantees this directory exists by the time
  any store is constructed, per `start.py`'s existing startup sequence,
  read in full this pass — no new directory-creation code is needed).
- **Startup construction:** at the same point in `start.py`'s startup
  sequence as `strategy_engine = StrategyEngine(strategy_config)`
  currently sits (line 1194), per P1 above — before the live-cycle
  thread starts, exactly matching where `compliance_state_store`/
  `in_flight_store` are constructed a few lines later.
- **Failure behavior:** `OrbQualificationStore.__init__` → `_load_initial()`
  (`strategy_state_store/store.py`, read in full this pass) raises
  `CorruptStateError` if the state file exists but is unreadable/corrupt
  and no usable `.bak` exists — with **no try/except around its
  construction call in `start.py`**, exactly mirroring
  `ComplianceStateStore`'s own construction one line below it (also
  unguarded, confirmed by direct read of `start.py` lines 1203-1209: a
  `CorruptStateError` there crashes the entire startup sequence). This
  is not a new risk Phase 6 introduces — it is the same fail-closed-at-
  startup precedent already accepted for compliance state, applied
  identically to ORB state, and is exactly what ADR-035 §18.A item 2's
  own text mandates ("if persisted state cannot be read... ORB must not
  qualify... until the state is resolved" — a full startup refusal is
  the strictest reading of "must not qualify," and the one this
  project's precedent already uses for the analogous compliance case).
  A missing (not corrupt) file is not an error — `_load_initial()`
  returns `{}` when `path.exists()` is `False`, so a fresh install with
  no prior ORB history starts cleanly with zero consumed qualifications.
- **Mid-run persist failures never propagate:** `try_consume()`
  (`store.py`, read in full this pass) catches and logs any exception
  from `self._persist()` internally (`_safe_log_persist_failure()`),
  documented explicitly in the module's own docstring as existing
  *specifically* to prevent "an exception escaping into
  `OrbBreakoutStrategy.qualify()`" from "abort[ing]
  `StrategyEngine.evaluate()`/`evaluate_batch()` for every strategy and
  pair in that cycle." This closes the "exception path capable of
  taking down the selection cascade" adversarial concern (§P9) for the
  *steady-state* case; only construction-time corruption can raise, and
  that happens once, at startup, before any strategy ever evaluates —
  never mid-cycle.

New imports required in `start.py` (currently only imports `StrategyEngine`
from `titan_protocol.strategy_engine.engine`, confirmed by grep this
pass): `build_default_registry` from `titan_protocol.strategy_engine.strategies`,
`StrategyStateStoreConfig` from `titan_protocol.strategy_state_store.config`,
`OrbQualificationStore` from `titan_protocol.strategy_state_store.store`.

### P3a. `deployment_windows/install.py`'s own `StrategyEngine` construction site (resolves independent-review finding F1)

A repo-wide grep for every production call site of `StrategyEngine(`/
`build_default_registry(` (re-run this pass, not reused from Research or
the prior Plan draft) surfaces a **third** production construction site
neither the original Plan nor the Research artifact inventoried:
`deployment_windows/install.py::step_verify_runtime()`, line 301:
`strategy_engine = StrategyEngine(settings.strategy_config)`.

**Direct re-read of `step_verify_runtime()` in full (`install.py` lines
290-312):** the function constructs `EvidenceEngine`, `MarketIntelligenceEngine`,
`StrategyEngine`, `RiskEngine`, `ComplianceEngine`, and a `RuntimeOrchestrator`
inside one `try/except Exception`, and returns `StepReport("Verify Runtime",
_OK, "Constructed all 5 core engines (Evidence, Market Intelligence,
Strategy, Risk, Compliance) and the RuntimeOrchestrator with no error")`
on success. It **never calls `.evaluate()`/`.evaluate_batch()`** on any
engine, never touches `strategy_engine.registry` after construction, and
its own success message explicitly names its scope as "5 core engines" —
this is a one-shot, construction-only smoke check exercised during
`install.py`'s pre-flight verification, not a code path that ever
qualifies a strategy or reaches the selection cascade.

**Decision: leave `install.py` unchanged. Explicitly recorded as READ
ONLY / NO CHANGE REQUIRED**, for the reason above — this is not "changed
for symmetry with `start.py`," it is a considered non-change grounded in
what the function actually does:
- `StrategyEngine.__init__` never touches `orb_qualification_store` or
  any store — it only stores `self.registry` (either the caller-supplied
  one or the zero-argument `build_default_registry()` default, §P1).
  Construction cannot fail differently with ORB registered vs. not,
  since ORB's own constructor is never invoked here at all under the
  unchanged zero-argument path.
- `step_verify_runtime()`'s own purpose (per its literal success message)
  is to prove the five *core engines* construct without error — it is
  not, and was never, a check that ORB is registered, eligible, or
  reachable. Extending it to construct a real `OrbQualificationStore`
  and a six-strategy registry would be new scope this function's own
  stated purpose does not call for, and would require `install.py` to
  also decide a state-file path and directory-creation sequencing
  identical to `start.py`'s (§P3) purely to duplicate a check `start.py`
  itself already performs at real startup — CLAUDE.md §6's "smallest
  correct change" and "tolerate... before extracting an abstraction"
  both argue against duplicating that wiring here for a construction-only
  smoke test that has no way to observe ORB's behavior regardless.
- No other file in `install.py` references `StrategyRegistry`,
  `build_default_registry`, or `OrbQualificationStore` (confirmed by
  grep) — this is the only surface in that file this finding could
  possibly touch, and it does not need to.

**File-impact matrix correction:** `deployment_windows/install.py` is
added to §P11's table as **READ ONLY / NO CHANGE REQUIRED**, with this
reasoning, rather than being absent from the matrix as it was in the
prior Plan draft. No other Plan claim that "all `StrategyEngine`
production construction sites were inventoried" survives unqualified —
this section is the corrected, complete inventory of all three
(`engine.py`'s own default-substitution line, `start.py`, `install.py`).

### P4. Resolution — existing five-strategy test assumptions (Research question 4)

**Refined conclusion, superseding Research's provisional guess:**
`tests/titan_protocol/strategy_engine/test_engine.py:19`
(`test_returns_a_fully_populated_snapshot`) and
`tests/titan_protocol/strategy_engine/test_regression.py:22`
(`test_default_fixture_always_rejects`) both construct
`StrategyEngine(make_config())` with **no registry argument** — under
P1's design, this zero-argument path still returns exactly five
strategies, forever, by construction. **These two tests require NO
change.** They correctly assert the cardinality of
`StrategyEngine`'s own default-substitution path, which P1 deliberately
leaves untouched. Re-verified fresh this pass (both assertions still
present at these exact lines, both suites still 1373/162 green) —
Research's tentative "these will need updating to 6" guess is
superseded by this more precise design, which was only derivable once
the registration mechanism itself (P1) was settled; this is exactly the
kind of "do not mechanically replace every occurrence of 5" distinction
this task's instructions required.

`test_orb_breakout_foundation.py::test_five_legacy_strategy_ids_remain`
(read in full this pass) asserts `StrategyId.__members__` enum
membership, not registry size — already correctly out of scope,
confirmed unaffected either way.

**No existing test anywhere is modified by this Plan.** All new
coverage (§P8) lives in new test code that explicitly builds the
six-strategy registry the same way `start.py` now does — proving the
"real... competing in the real selection cascade" mandate through the
actual production factory function (`build_default_registry(store)`),
never through a hand-assembled synthetic registry that merely happens
to contain six strategies (closing the "tests that prove six
qualifications synthetically" adversarial concern, §P9).

### P5. Phase 6 algorithm / integration sequence

1. Add `build_default_registry(orb_qualification_store: Optional[OrbQualificationStore] = None)` (P1).
2. Add the three-line construction block to `start.py` (P1/P3) — no
   other line in `start.py` changes.
3. No `config_loader.py`/example-JSON change (P3).
4. No `DEFAULT_APPROVED_PAIRS_BY_STRATEGY` change (P2).
5. No change to any of the five legacy strategy files, `orb_breakout.py`,
   `strategy_state_store/`, `eligibility.py`, `selection.py`, or any ADR.
6. Add new integration/regression/edge-case/exception-safety tests
   (§P8) exercising the real `build_default_registry(store)` +
   `StrategyEngine(config, registry=...)` construction path.
7. Full regression re-run (§P11) before this Plan may be considered
   ready for implementation-readiness review.

### P6. Exception-safety contract (ADR-035 §17)

- **Startup-time:** a corrupt/unreadable `orb_qualifications.json`
  raises `CorruptStateError` out of `OrbQualificationStore.__init__`,
  uncaught in `start.py`, crashing startup — by design, mirroring
  `ComplianceStateStore`'s identical treatment (P3). Required test:
  construct `OrbQualificationStore` against a deliberately corrupted
  file and assert `CorruptStateError` is raised — proving the contract,
  not merely citing the docstring.
- **Steady-state (mid-`evaluate()`):** `try_consume()` never raises for
  a persist failure (caught/logged internally, P3) — required test:
  simulate a persist failure (e.g., monkeypatch `_persist()` to raise,
  or make the state directory read-only after construction) mid-`evaluate()`
  and assert `StrategyEngine.evaluate()` still returns a normal
  `StrategySnapshot` for all six strategies, with ORB's own result
  reflecting "already qualified"/`NOT_QUALIFIED` per its existing logic,
  never an unhandled exception.
- **No change to `StrategyEngine.evaluate()`'s own lack of a
  per-strategy try/except** (`engine.py`, read in full this pass) —
  this Plan does not add one, because P3's evidence shows
  `OrbQualificationStore` already cannot raise mid-cycle; introducing
  a new per-strategy exception boundary would be scope beyond what
  ADR-035 §17 asks for (it names "exception safety" as something to
  *validate*, not a new architectural feature to *build*), and would
  be exactly the kind of speculative defensive code CLAUDE.md §6/§7
  disallow for a scenario (a legacy strategy raising) that has never
  occurred and that this Plan finds no new reason to guard against.

### P7. §15 edge-case matrix — Phase 6 required tests

| §15 case | Required Phase 6 test (new) | Level |
|---|---|---|
| Gap open before/inside range window | Extend existing Evidence Engine coverage is sufficient (Phase 0); add one integration-level test confirming a gap-invalidated range still lets the other five strategies evaluate normally through the real six-strategy `StrategyEngine` | Integration (new) |
| Missing candles / temporal gap | Same as above, integration-level confirmation only — unit coverage already complete (Phase 0) | Integration (new) |
| Session reconnect mid-range | New test: no bars missed → range forms normally through the real engine; bars missed → `is_valid=False`, ORB still `NOT_QUALIFIED`/`NOT_ELIGIBLE`, five legacy strategies unaffected | Integration (new) |
| DST transitions | No new test — ADR §15 documents this as an explicit, accepted operator responsibility, not a code path; out of scope | N/A (documented, not tested) |
| Holiday sessions | Confirm existing Phase 4 unit test still passes; add one integration-level assertion through the real registry | Integration (new) |
| Multiple ranges / anchor overlap | Confirm existing Phase 0/5 coverage; add one integration-level test with two configured anchors through the real six-strategy engine | Integration (new) |
| Broker time differences | No new ORB-specific test — explicitly another package's concern (`market_data_ingestion`, ADR-033), confirmed out of ADR-035's own scope by §15's text | N/A (out of scope) |
| Partial trading days / early close | New test: an early-close day with `MarketSafetyInputs.early_closes` set, confirming the range never forms and ORB fails closed to `NOT_QUALIFIED`, five legacy strategies unaffected | Integration (new) |

Every "Integration (new)" row above requires ORB to be pair-eligible for
at least the test's own fixture pair — under the unchanged production
default (P2), `check_eligibility()` intercepts every one of these cases
at `orb_breakout.py` line 78 before any of the row's own logic (opening
range, FVG, breakout distance, lockout) ever runs. **§P7a, immediately
below, specifies the exact, test-only mechanism every one of these rows
must use** — none of them are implementable as literally described
without it.

### P7a. Test-only ORB eligibility mechanism (resolves independent-review finding F2)

**The production default must never change.** `DEFAULT_APPROVED_PAIRS_BY_STRATEGY`
(`strategy_engine/config.py`) keeps zero `OPENING_RANGE_BREAKOUT` entry,
exactly as P2 resolved — this section specifies how *tests* reach past
that gate, never how production does.

**Mechanism, re-confirmed sufficient by direct inspection this pass:**
`tests/titan_protocol/strategy_engine/_fixtures.py::make_config(**overrides)`
(read in full again this pass) is exactly `return StrategyEngineConfig(**overrides)`
— an unrestricted passthrough to every field the dataclass exposes,
already the established idiom every existing test in this file uses to
override any `StrategyEngineConfig` field without touching a shared
default. No change to `_fixtures.py` is needed; `make_config` already
accepts `approved_pairs_by_strategy` today. Any new Phase 6 test that
needs ORB to be reachable constructs its own config exactly like this,
entirely inside the new test module, never inside `_fixtures.py` or any
production file:

```python
from titan_protocol.strategy_engine.config import DEFAULT_APPROVED_PAIRS_BY_STRATEGY
from titan_protocol.strategy_engine.models import StrategyId

_TEST_ORB_APPROVED_PAIRS = DEFAULT_APPROVED_PAIRS_BY_STRATEGY + (
    (StrategyId.OPENING_RANGE_BREAKOUT, ("EURUSD",)),
)

config = make_config(approved_pairs_by_strategy=_TEST_ORB_APPROVED_PAIRS)
```

This starts from the *real* `DEFAULT_APPROVED_PAIRS_BY_STRATEGY` tuple
(imported, not re-typed by hand, so it can never silently drift from
the production default it's supposed to extend) and appends exactly one
additional entry, for exactly one test-chosen pair. It is a plain
Python value passed into a test-local `StrategyEngineConfig` instance —
it cannot leak into `deployment_windows/config_loader.py`, the example
JSON, or any deployment artifact, because nothing in this mechanism
writes to or reads from any of those; the override exists only for the
lifetime of the test's own `config` object.

**The three-way test/production separation this Plan requires, stated
explicitly:**
1. **Production** (`start.py`, real installs): `build_default_registry(store)`
   registers ORB; `StrategyEngineConfig()`'s own default
   `approved_pairs_by_strategy` (i.e. `DEFAULT_APPROVED_PAIRS_BY_STRATEGY`,
   unmodified) leaves ORB `NOT_ELIGIBLE` for every pair. No test file,
   fixture, or override touches this.
2. **Tests that verify the production default itself** (§P8 item 6):
   must construct `StrategyEngineConfig()`/`make_config()` with **no**
   `approved_pairs_by_strategy` override — i.e. the real, unmodified
   default — and assert ORB is `NOT_ELIGIBLE`. Using the P7a override in
   this specific test would defeat its own purpose (it would prove
   nothing about the production default), so this test is explicitly
   the one place the override must **not** appear.
3. **Tests that exercise ORB's breakout/FVG/lockout logic** (every
   "Integration (new)" row in §P7's table, plus §P8 items 2, 7, 8): use
   the §P7a override, applied only to that test's own `config` object,
   to reach past `check_eligibility()` for one chosen test pair — while
   still constructing the registry via the real
   `build_default_registry(store)` factory (never a hand-assembled
   `StrategyRegistry()`), per §P4's own requirement.

**Exact P7/P8 items requiring the §P7a override:** §P7's rows for "Gap
open before/inside range window," "Missing candles / temporal gap,"
"Session reconnect mid-range," "Holiday sessions," "Multiple ranges /
anchor overlap," and "Partial trading days / early close" (six of the
eight table rows — DST and broker-time-differences are out of scope
and need no test at all, §P7); and §P8 items 2 (real six-strategy
regression proof), 7 (the same six §P7 rows), and 8 (lockout/persistence
through the real engine). §P8 item 6 (the `NOT_ELIGIBLE`-under-default
proof) is the one item that must explicitly **not** use it, per point 2
above.

### P8. Required new test coverage (summary list)

1. `build_default_registry(store)` returns exactly 6 strategies,
   including `OPENING_RANGE_BREAKOUT`; `build_default_registry()` (no
   arg) still returns exactly 5 — both asserted in the same test module.
2. A real `StrategyEngine(config, registry=build_default_registry(store))`
   evaluates all six strategies; the five legacy strategies' individual
   `QualificationResult`s are identical (score, status, reason) to what
   they produce when evaluated against a five-strategy registry with
   the same evidence/MI/config inputs — the literal regression proof
   §17 asks for, at the behavioral level (in addition to the file-level
   `git diff --stat` proof, which needs no test since it is a source
   fact, not a runtime one). This item does **not** need the §P7a
   override — the unmodified production default is sufficient here,
   since the point is proving the *other five* strategies are
   unaffected by ORB's mere presence, regardless of ORB's own
   eligibility outcome.
3. `git diff --stat` against the pre-Phase-6 baseline shows zero change
   to any of the five legacy strategy files (a Validation-phase check,
   recorded here as a Plan requirement so Implement knows to verify it).
4. Startup-time `CorruptStateError` test (§P6).
5. Steady-state persist-failure containment test (§P6).
6. **Explicit pair-ineligibility assertion (P2):** construct the real
   six-strategy engine with the shipped, unmodified
   `DEFAULT_APPROVED_PAIRS_BY_STRATEGY`, evaluate any pair, and assert
   ORB's own qualification result is `NOT_ELIGIBLE` — proving Phase 6's
   stated zero-blast-radius consequence rather than leaving it assumed.
7. §15 edge-case tests per §P7's table — using the §P7a test-only
   eligibility override for the six rows §P7a names.
8. A lockout/persistence test through the *real* engine construction
   path (not `_OrbTestCase`'s existing unit-level store) — confirming
   `try_consume()`'s existing max-qualifications-per-range behavior
   still holds when ORB is reached via `build_default_registry(store)`
   rather than constructed directly, i.e. that no wiring step silently
   substitutes a different/fresh store mid-test. Requires the §P7a
   override (ORB must be eligible for the test's chosen pair, or
   `try_consume()` is never reached at all).

### P9. Preservation requirements

- All five legacy strategy files: zero diff (`git diff --stat`),
  verified at Implement/Validation time.
- `orb_breakout.py`, `strategy_state_store/*.py`, `eligibility.py`,
  `selection.py`: zero diff — none of P1-P3's design requires touching
  them; `OrbBreakoutStrategy`'s constructor signature and
  `OrbQualificationStore`'s fail-closed contract are consumed exactly
  as they already exist, never modified.
- No ADR file changes.
- `build_default_registry()`'s zero-argument behavior: unchanged
  (proven by test P8.1, not merely asserted).

### P10. Architecture / structural-boundary impact

`tests/titan_protocol/strategy_engine/test_architecture.py`'s
`ALLOWED_UPSTREAM_PREFIXES` (read in full this pass, line 30) already
includes `"titan_protocol.strategy_state_store"` — required because
`orb_breakout.py` has imported `OrbQualificationStore` since Phase 2.
**No allowlist change is needed for Phase 6**, since `build_default_registry()`
lives inside `titan_protocol/strategy_engine/strategies/__init__.py`
(the same package `orb_breakout.py` already lives in) and its new
parameter's type annotation (`Optional[OrbQualificationStore]`) is
exactly the same already-allowed upstream import, just referenced one
file over. `deployment_windows/` is not part of the
`check_architecture.py`/`test_architecture.py`-checked `titan_protocol/`
package graph and already imports engine-owned classes directly
(established precedent since Phase 5) — its three new imports (P3) need
no allowlist change either.

### P11. Complete file-impact matrix

| File | Change | Classification |
|---|---|---|
| `titan_protocol/strategy_engine/strategies/__init__.py` | `build_default_registry()` gains one optional parameter (P1) | Required |
| `deployment_windows/start.py` | 3-line construction block + registry passed explicitly into `StrategyEngine(...)`; 3 new imports (P1/P3) | Required |
| New test module (e.g. `tests/titan_protocol/strategy_engine/test_orb_full_suite_integration.py`) | §P7/§P8's full new-coverage matrix | Required |
| `docs/plans/adr-035-phase6-full-suite-validation.md` | This Plan section (already being written) | Required (this artifact) |
| `titan_protocol/strategy_engine/config.py` | **No change** — `DEFAULT_APPROVED_PAIRS_BY_STRATEGY` untouched (P2) | Explicitly excluded |
| `deployment_windows/config_loader.py` | **No change** (P3) | Explicitly excluded |
| `deployment_windows/config/titan_protocol_config.example.json` | **No change** (P3) | Explicitly excluded |
| `titan_protocol/strategy_engine/strategies/orb_breakout.py` | **No change** | Explicitly excluded |
| `titan_protocol/strategy_state_store/*.py` | **No change** | Explicitly excluded |
| `titan_protocol/strategy_engine/eligibility.py`, `selection.py` | **No change** | Explicitly excluded |
| `deployment_windows/install.py` | **No change** — `step_verify_runtime()`'s `StrategyEngine(settings.strategy_config)` (line 301) is construction-only, never calls `.evaluate()`, and its own success message scopes it to "5 core engines"; extending it to the six-strategy path would duplicate `start.py`'s wiring for a check that can't observe ORB's behavior regardless (§P3a) | READ ONLY / NO CHANGE REQUIRED (§P3a, resolves independent-review finding F1) |
| Five legacy strategy files | **No change** — regression-proof target | Explicitly excluded |
| `tests/titan_protocol/strategy_engine/test_engine.py`, `test_regression.py` | **No change** (P4, superseding Research's guess) | Explicitly excluded |
| Any ADR file | **No change** | Explicitly excluded |
| `titan_protocol/evidence_engine/config.py` (anchor hour/minute range validation) | **No change — separate follow-up, not this Plan's scope** | Explicitly excluded (Phase 5 residual risk) |
| Any Phase 7 formation-time news-blackout code | **No change** | Explicitly excluded (Phase 7 unauthorized) |

### P12. Targeted and full-regression validation (to run at Implement/Validation time)

Targeted:
```
python3 -m unittest tests.titan_protocol.strategy_engine.test_orb_full_suite_integration -v
python3 -m unittest tests.titan_protocol.strategy_engine.test_engine tests.titan_protocol.strategy_engine.test_regression -v
python3 -m unittest discover -s tests/titan_protocol/strategy_engine
python3 -m unittest tests.titan_protocol.strategy_engine.test_architecture tests.titan_protocol.evidence_engine.test_architecture
python3 scripts/check_architecture.py
```
Full regression (expected baselines, re-verified this pass):
```
python3 -m compileall titan_protocol deployment_windows tests
python3 -m unittest discover -s tests/titan_protocol        # baseline: 1373/1373, plus new P8 tests
python3 -m unittest discover -s tests/deployment_windows -t .  # baseline: 162/162, unaffected (no deployment_windows test file touched)
git diff --stat <phase-6-base-commit> HEAD -- titan_protocol/strategy_engine/strategies/liquidity_sweep_mss.py titan_protocol/strategy_engine/strategies/bos_fvg.py titan_protocol/strategy_engine/strategies/trend_continuation.py titan_protocol/strategy_engine/strategies/session_breakout.py titan_protocol/strategy_engine/strategies/range_reversal.py
# must show zero output
```

### P13. Explicit exclusions (restated)

- **Phase 7** (formation-time news-blackout closure): not begun, not
  designed, not referenced beyond the existing Amendment 1 pointer.
  Requires its own Research → Plan → Implement pass and its own
  Accepted ADR-035 amendment per §17's own text.
- **Phase 5 anchor hour/minute range-validation residual risk**
  (`EvidenceEngineConfig`/`config_loader.py` never range-checking
  `start_hour_utc`/`start_minute_utc`): remains a separate,
  independently-scoped follow-up candidate, per the Phase 5 conformance
  review's own classification (RESIDUAL RISK, non-blocking, pre-existing
  since Phase 0). Not touched, not referenced as in-scope, by any item
  in this Plan.
- **Pair-eligibility population** (a starter or operator-driven
  approved-pairs list for ORB): explicitly deferred past Phase 6 (P2);
  any future phase that wants to resolve it differently needs its own
  fresh Plan and, given CLAUDE.md's capital-preservation priority, very
  likely its own independent implementation-readiness review given it
  would be the first phase with genuine live-trading effect for ORB.

### P14. Adversarial re-read (performed against this finalized Plan)

- **Registration without dependency construction?** No — P1's
  `build_default_registry(store)` requires the caller to supply a
  constructed `OrbQualificationStore`; there is no path that registers
  `OrbBreakoutStrategy` without one (the `if orb_qualification_store is
  not None` branch is the only registration path for ORB).
- **Dependency construction without deployment propagation?** No — P3
  places construction directly in `start.py`, immediately followed by
  P1's registry-construction call and the `StrategyEngine(...,
  registry=...)` call in the same function, in sequence; there is no
  intermediate state where a store exists but isn't wired into the
  engine that uses it.
- **Silently discarded configuration?** No — no new configuration
  field is introduced by this Plan (P2, P3 both resolve to "no config
  change"); the one path-derived value used (`settings.state_dir`) is
  already read and already propagated identically to two existing
  stores.
- **Implicit filesystem paths?** No — `settings.state_dir /
  "orb_qualifications.json"` is explicit, directly analogous to the two
  existing sibling files in the same directory, and `settings.state_dir`
  itself already has explicit, tested default/override semantics from
  Phase 0-era `config_loader.py` wiring (unchanged by this Plan).
- **ORB becoming broadly eligible by accident?** No — P2 explicitly
  leaves `DEFAULT_APPROVED_PAIRS_BY_STRATEGY` untouched; P8 item 6
  requires an explicit test proving `NOT_ELIGIBLE` for every pair
  against the unmodified default. The only way ORB becomes pair-
  eligible is a future, separately-authorized Plan changing that table.
- **Changes to legacy strategy behavior?** No — P1's change is
  additive only (`if store is not None`); the five `registry.register(...)`
  calls for legacy strategies are unchanged, in the same order, with
  the same zero-argument constructors; P8 item 2 requires a test proving
  their individual qualification results are unaffected by ORB's
  presence in the same registry (qualification is a pure per-strategy
  function of `(pair, evidence, market_intelligence, config)` — adding
  another registry entry cannot alter another strategy's own `qualify()`
  call or its inputs, but this Plan requires it be *proven*, not merely
  assumed from the code's own shape).
- **Lockout persistence becoming optional or bypassed?** No — P1 does
  not add any parameter to skip or stub `OrbQualificationStore`; the
  only construction path in `start.py` uses the real, file-backed store
  with its existing fail-closed/atomic-write/corruption-handling
  contract, entirely unmodified (P9).
- **Exception paths capable of taking down the selection cascade?**
  Addressed directly in P6/P3 — `try_consume()` already cannot raise
  mid-cycle (existing Phase 2 guarantee, cited from its own docstring,
  now required to be *proven* by a new Phase 6 test rather than merely
  cited); construction-time failure crashes startup only, before any
  cascade runs, matching the existing `ComplianceStateStore` precedent.
  This Plan does not add new per-strategy exception handling to
  `evaluate()` (deliberately, per P6's own reasoning) — flagged here
  explicitly as a considered, evidence-based non-action, not an
  oversight.
- **Tests that prove six qualifications synthetically without
  exercising the real production factory?** Explicitly disallowed by
  P4/P8's own wording — every new test must go through
  `build_default_registry(store)` (the actual function `start.py` calls,
  per P1), never a hand-assembled `StrategyRegistry()` with six manual
  `.register()` calls standing in for it.
- **Phase 7 or the anchor-validation residual risk leaking into Phase
  6 scope?** No — both are named exclusions in P13 and neither appears
  in P11's file-impact matrix (both rows are explicitly marked "no
  change"/"explicitly excluded").

No new issue was found in this adversarial pass beyond what P1-P13
already resolve. This Plan is assessed as internally consistent and
fully evidence-grounded against current repository state.

### P15. Post-revision re-check (F1/F2 applied) — confirms no new blocker

Performed after §P3a/§P7a were added, specifically re-checking each item
the independent review's revision request named:

- `build_default_registry()` with no store: still exactly the five
  legacy strategies — unchanged by §P3a/§P7a, neither of which touches
  `build_default_registry()`'s own body beyond P1's already-approved
  `if orb_qualification_store is not None` gate.
- `build_default_registry(store)`: still registers exactly six
  strategies (five legacy, unconditionally, plus ORB, conditionally on
  `store`) — unchanged.
- Production `start.py` still supplies the one real
  `OrbQualificationStore` (§P3), now with `install.py`'s parallel
  construction site explicitly dispositioned (§P3a) rather than left
  unaddressed — no second construction path was introduced.
- Production ORB eligibility: still `NOT_ELIGIBLE` for every pair under
  the unchanged `DEFAULT_APPROVED_PAIRS_BY_STRATEGY` — §P7a's override
  is textually confined to test-module-local `config` objects and is
  never referenced from any production file in this Plan.
- Test-only eligibility cannot leak into production: confirmed by
  construction — §P7a's override lives in a Python literal inside a
  test module, imports the real `DEFAULT_APPROVED_PAIRS_BY_STRATEGY`
  rather than re-typing it (so it can only ever *extend*, never
  silently diverge from, the true production default), and is never
  passed to `config_loader.py`, `install.py`, or `start.py` anywhere in
  this Plan.
- Qualifying ORB behavior, FVG score-only behavior, and lockout are now
  reachable in the designated tests: §P7a's override makes ORB eligible
  for one test-chosen pair, after which `orb_breakout.py`'s existing
  breakout/FVG/lockout logic (unmodified, §P9) runs exactly as it does
  today when called directly — the override changes only which pairs
  clear the eligibility gate, not any qualification logic itself.
- The same `OrbQualificationStore` instance reaches
  `OrbBreakoutStrategy`: unchanged from §P1/§P3 — one instance,
  constructed once, passed into `build_default_registry(store)`, which
  passes it directly into `OrbBreakoutStrategy(store)`'s constructor;
  §P7a's config override is orthogonal to this (it changes eligibility
  data, not store wiring) and does not introduce a second store anywhere.
- `install.py`'s construction site: now has an explicit, evidence-based
  recorded disposition (§P3a, READ ONLY / NO CHANGE REQUIRED) instead of
  being absent from the Plan.
- No other `StrategyEngine`/`build_default_registry` production
  construction site remains unaccounted for: the repo-wide re-grep this
  pass found exactly three (`engine.py`'s own default-substitution line,
  `start.py`, `install.py`) — all three now have an explicit disposition
  in this Plan (P1/P3, P3, P3a respectively).
- All five legacy strategy files remain untouched: §P3a/§P7a add no new
  reference to any of them; the file-impact matrix (§P11) still lists
  them as the zero-diff regression target.
- Phase 7 and the anchor hour/minute validation follow-up remain out of
  scope: neither §P3a nor §P7a references either; §P13's exclusions are
  unchanged and still accurate.

No design decision already settled in P1-P3/P6 was reopened by this
revision — both findings were resolved by adding explicit specification
(§P3a, §P7a) and one file-impact-matrix row, not by changing any
already-verified production-code design. No new blocker was discovered
in this re-check.

## Validation

*(Intentionally left empty — this is the Implement phase's own
responsibility, per `TEAM.md` §9. P12 above states the exact commands
and expected baselines that phase must execute and record here.)*
