# Plan: ADR-035 Phase 1 — ORB Strategy Foundation

Status: **BLOCKED — NOT IMPLEMENTATION-READY** (see §3 Governance
Preconditions; both blockers are repository-verified, independent of
each other, and unresolved as of this document)
Owner (Plan phase): Software Architect
Touched components (if/when unblocked): `titan_protocol/strategy_engine/` only

---

> **PHASE 1 NOT IMPLEMENTATION-READY.** Two independent governance
> preconditions are unresolved, verified directly against the current
> repository this session. Neither is invented, assumed, or silently
> resolved below. Implementation of any part of this Plan must not
> begin until both are explicitly settled by the appropriate authority.
> See §3 for full evidence.
>
> **Blocker A — ADR-035's own document status.** `docs/adr/ADR-035-orb-strategy.md`
> line 3 reads `Status: **Proposed**` today. ADR-035 §17 itself states:
> *"Requires its own Accepted status before Phase 1 begins (CLAUDE.md
> §1.10)"* and *"this document is the Research artifact for Phase 0
> only; Phases 1-6 each need their own Plan artifact once Phase 0 is
> Accepted."* No commit in this repository's history
> (`git log -- docs/adr/ADR-035-orb-strategy.md`) ever changed this
> line. This contradicts every prior turn's working assumption
> (including this task's own §0 "Governing State," ADR-036's own
> "Depends on" line citing "ADR-035-orb-strategy.md (Accepted)", and
> `CHANGELOG.md`'s 2026-07-25 entry describing "Phase 0 of ADR-035
> (Opening Range Breakout strategy, Accepted)") — none of which is
> repository ground truth for the ADR document itself.
>
> **Blocker B — ADR-035 §18.A item 2, lockout persistence, unresolved.**
> ADR-035 itself: *"Should `orb_max_qualifications_per_range`'s
> in-memory lockout state survive a process restart? Must be settled
> before Phase 1 begins... that assumption should be explicitly
> confirmed, not silently carried forward, if a restart mid-range
> allowing a fresh qualification is judged unacceptable."* A
> repository-wide search (`docs/`, `CHANGELOG.md`, `deployment_windows/KNOWN_GAPS.md`)
> for `orb_max_qualifications_per_range` finds only ADR-035's own three
> occurrences — no resolution exists anywhere.
>
> Everything below this point is genuine, repository-grounded Research
> and Plan content, complete and internally consistent **except** where
> a section depends on one of these two blockers being resolved first —
> those sections state the dependency explicitly rather than guessing
> an answer.

---

## 1. Phase Objective

Introduce the minimum Strategy Engine structure required for ORB — a
new `StrategyId` member and a conformant, foundation-level
`OrbBreakoutStrategy` that consumes `EvidenceSnapshot.opening_ranges`
(ADR-035 Phase 0, implemented) for range-formed/valid gating and the
§6 session-lockout only — without pulling forward any later phase's
qualification, scoring, FVG, Market Intelligence, or configuration-
loading behavior. Per ADR-035 §17's own words: *"Phase 1 — Core ORB
detection: consume `opening_ranges` inside a new `OrbBreakoutStrategy`
(naming to match `StrategyId.OPENING_RANGE_BREAKOUT`); range-formed/valid
checks and the §6 session-lockout only, no qualification scoring yet."*

## 2. Repository Evidence Summary

Verified directly this session (not inferred from ADR prose alone):

- `titan_protocol/strategy_engine/models.py:23-28` — `StrategyId` is a
  5-member closed enum today (`LIQUIDITY_SWEEP_MSS`, `BOS_FVG`,
  `TREND_CONTINUATION`, `SESSION_BREAKOUT`, `RANGE_REVERSAL`); no
  `OPENING_RANGE_BREAKOUT` member exists.
- `titan_protocol/strategy_engine/strategies/base.py` — the `Strategy`
  ABC has exactly two members: the `definition` property
  (`StrategyDefinition`) and `qualify(pair, evidence, market_intelligence,
  config) -> QualificationResult`. Every concrete strategy (read in
  full or in relevant part this session: `liquidity_sweep_mss.py`,
  `bos_fvg.py`, `trend_continuation.py`, `session_breakout.py`,
  `range_reversal.py`) is a **stateless class with no `__init__`
  override and no instance attribute** — `OrbBreakoutStrategy` would be
  the first stateful strategy in this package's history if the §6
  lockout is implemented as ADR-035 describes.
- `titan_protocol/strategy_engine/strategies/__init__.py::build_default_registry()`
  is the sole production registration point (re-confirmed this
  session); `titan_protocol/strategy_engine/engine.py:36-46`'s
  `StrategyEngine.__init__` defaults to it whenever no explicit
  `registry` is passed; `deployment_windows/start.py:1196` and
  `install.py:303` both use this default, unmodified.
- `titan_protocol/strategy_engine/selection.py::select_winning_strategy()`
  (re-read in full this session, unchanged since the ADR-036 review) is
  generic over `Sequence[QualificationResult]` — confirmed to handle
  zero, one, or many candidates correctly with no `StrategyId`-specific
  branch.
- `titan_protocol/strategy_engine/eligibility.py::check_eligibility()` —
  the hard pair-eligibility gate every existing strategy calls first;
  `StrategyEngineConfig.approved_pairs_for(strategy_id)` (config.py:81-85)
  already falls back to `()` for any `StrategyId` with no configured
  entry — meaning **no config change is required** for a new
  `StrategyId` to correctly and automatically fail `NOT_ELIGIBLE` for
  every pair until an operator adds an entry (§13, mirrors ADR-035
  §18.B item 4's own "empty by default" philosophy with zero new code).
- `titan_protocol/strategy_engine/config.py` — `StrategyEngineConfig`
  has **no `__post_init__` and no validation of any kind** today
  (confirmed by direct read — no `raise` anywhere in the file). This
  contrasts with `EvidenceEngineConfig`'s `ValueError`-raising
  `__post_init__` (ADR-035 Phase 0) and matters for any new Phase 1
  config field's fail-closed behavior (§14).
- `tests/titan_protocol/strategy_engine/test_architecture.py` —
  `ALLOWED_UPSTREAM_PREFIXES = ("titan_protocol.evidence_engine",
  "titan_protocol.market_intelligence")`; `FORBIDDEN_IMPORT_PREFIXES =
  ("phantom_pipeline", "titan_protocol.bridge")`. This is a real,
  already-existing, automated architecture-boundary test that would
  immediately catch an `OrbBreakoutStrategy` importing
  `market_data_ingestion`, `bridge`, or any raw-ingestion internals —
  unlike the situation found during the Phase 0 review
  (`scripts/check_architecture.py` does not cover `titan_protocol` at
  all), this package's own `test_architecture.py` is genuinely
  effective and needs no extension for Phase 1's purposes.
- `tests/titan_protocol/strategy_engine/test_regression.py::test_default_fixture_always_rejects`
  hardcodes `self.assertEqual(len(snapshot.all_qualifications), 5)`.
  **This is the direct, repository-verified reason Phase 1 should not
  register `OrbBreakoutStrategy` into the production
  `build_default_registry()`** (§11) — doing so breaks this exact
  anchor test for zero functional benefit, since a Phase-1-only ORB
  strategy (no qualification scoring yet) can never legitimately
  qualify anyway.
- `tests/titan_protocol/strategy_engine/test_boundary.py::TestEmptyRegistry::test_engine_with_no_registered_strategies_always_rejects`
  confirms the "zero strategies → always rejects, never raises" boundary
  is already tested generically — the same class of guarantee Phase 1's
  own foundation-level fail-closed behavior depends on.
- ADR-035 §17's Phase 6 bullet: *"integration (real five-plus-ORB
  `StrategyEngine` competing in the real selection cascade)"* — ADR-035
  itself frames the six-strategy **competing** registry as a Phase 6
  milestone, not Phase 1's, corroborating the registration decision
  above from the ADR's own text, not only from test-anchor evidence.

## 3. Governance Preconditions

See the boxed blocker statement at the top of this document for full
evidence. Summary table:

| Precondition (per this task's §0 "Governing State") | Expected | Actual (verified this session) | Status |
|---|---|---|---|
| ADR-035: Accepted | Accepted | `Status: **Proposed**` (`docs/adr/ADR-035-orb-strategy.md:3`), never changed in git history | **CONTRADICTED — Blocker A** |
| ADR-035 Phase 0: implemented and independently validated | Yes | Confirmed: `OpeningRangeState`, `EvidenceSnapshot.opening_ranges`, `opening_range.py`, config fields all exist and are wired; 22+5 tests green (§4) | Verified true |
| ADR-036: Accepted | Accepted | Confirmed: `docs/adr/ADR-036-orb-strategy-consolidation.md:3` reads `Status: **Accepted**` | Verified true |
| ADR-035 §18.A item 2 (lockout persistence) resolved | Resolved before Phase 1 begins | No resolution found anywhere in `docs/`, `CHANGELOG.md`, `KNOWN_GAPS.md` | **UNRESOLVED — Blocker B** |

Per this task's own instruction ("If current repository state
contradicts an Accepted ADR... STOP and report the contradiction before
creating or editing the Phase 1 Plan") and its Governance Blocker Rule
("You MAY create the Research portion and a conditional Plan, but you
MUST label: PHASE 1 NOT IMPLEMENTATION-READY"): this document proceeds
as the conditional Research + Plan artifact, not an implementation
authorization.

## 4. Current Architecture Assessment (Phase 0 verification)

Verified directly, not assumed from documentation:

- `titan_protocol/evidence_engine/models.py` — `OpeningRangeState` exists
  exactly as specified: `session: SessionName`, `range_start: datetime`,
  `range_end: datetime`, `range_start_index: int`, `range_end_index: int`,
  `range_high: float`, `range_low: float`, `range_midpoint: float`,
  `is_formed: bool`, `is_valid: bool`. `EvidenceSnapshot.opening_ranges:
  Tuple[OpeningRangeState, ...] = ()` exists, additive, defaulted.
- `titan_protocol/evidence_engine/opening_range.py` — `compute_opening_ranges(bars, now, config)`
  exists; per-anchor computation only produces an entry once the
  anchor's window start has been reached by the supplied bars (no
  placeholder for a not-yet-started anchor); `is_formed = now >=
  range_end`; `is_valid` requires both a minimum bar count and no
  detected temporal gap (`_has_temporal_gap`, checked against
  `Bar.timestamp` alone — confirmed no `market_data_ingestion` import
  anywhere in this file, enforced by a dedicated test).
- `titan_protocol/evidence_engine/engine.py` — `_analyze()` calls
  `compute_opening_ranges(bars, now, self.config)` after
  `detect_fair_value_gaps(bars)`; `evaluate_snapshot()`'s
  `EvidenceSnapshot(...)` construction includes `opening_ranges=opening_ranges`;
  `evaluate()` discards the value exactly as it already discards
  `fair_value_gaps` — confirmed unaffected.
- `titan_protocol/evidence_engine/config.py` — `opening_range_anchors`
  (`()` default), `opening_range_duration_minutes` (30),
  `opening_range_min_bars` (3), `expected_bar_interval_seconds` (300),
  all validated in `__post_init__` (`ValueError`, including the
  anchor-overlap check).
- `titan_protocol/evidence_engine/__init__.py` — `OpeningRangeState` and
  `compute_opening_ranges` both exported.
- `tests/titan_protocol/evidence_engine/test_opening_range.py` (22
  tests) and `test_architecture.py` (5 tests) — both re-run this
  session, both green, alongside the full 155-test Evidence Engine
  suite.

**Conclusion: Phase 0 documentation and implementation match — no
material discrepancy found.** Phase 0 itself is not the blocker;
ADR-035's own document status and §18.A item 2 are (§3).

## 5. Phase 1 Scope

Extracted from ADR-035 §17's own Phase 1 bullet and cross-checked
against §4/§6:

**REQUIRED IN PHASE 1:**
- New `StrategyId.OPENING_RANGE_BREAKOUT` member (§8).
- New `OrbBreakoutStrategy` class conforming to `Strategy` (§9).
- Range-formed/valid gating: `is_formed=False` → `NOT_QUALIFIED`
  ("range not yet formed"); `is_valid=False` → `NOT_QUALIFIED` ("range
  invalidated by a data gap or insufficient bar count") — both directly
  from ADR-035 §4's exact wording, applicable at Phase 1 since these
  are range-state checks, not breakout-qualification rules.
- The §6 session-lockout (`orb_max_qualifications_per_range`, in-memory,
  session-scoped) — **contingent on Blocker B (§3)**.
- Phase 1's own unit tests for exactly this scope (§15).

**DEFERRED TO PHASE 2+:**
- Breakout qualification (§4: close-beyond-range, ATR-relative
  distance, body/wick ratio, momentum, confirmation-candle count) —
  Phase 2.
- FVG confirmation/scoring (§5) — Phase 3.
- Market Intelligence/eligibility integration (session-anchor matching,
  news/liquidity/holiday gates) — Phase 4.
- ORB's own `StrategyEngineConfig` fields beyond the lockout count
  (`orb_approved_pairs`, `orb_min_range_atr_ratio`,
  `orb_min_breakout_distance_atr_multiple`, etc., ADR-035 §13) and their
  `config_loader.py`/example-config wiring — Phase 5.
- Stop-loss/take-profit reference-level reporting (§8/§9) — out of
  scope for every phase per ADR-031 §3's disclosed boundary, unchanged.
- Risk sizing — Risk Engine's existing, unmodified authority.
- Registering `OrbBreakoutStrategy` into the production
  `build_default_registry()` — evidence points to Phase 6 (§11), not
  Phase 1; flagged as an open design decision for independent review,
  not asserted as settled ADR text.

**ALREADY IMPLEMENTED BY PHASE 0:** `OpeningRangeState`,
`EvidenceSnapshot.opening_ranges`, the independent temporal-gap check,
the index model (§10).

**EXISTING GENERIC INFRASTRUCTURE (reused, not reimplemented):**
`Strategy`/`StrategyRegistry`/`StrategyDefinition`/`QualificationResult`/
`TradeIntent`/`StrategySnapshot` (ADR-026), `check_eligibility()`
(ADR-026 Hard Rules 4-5), `select_winning_strategy()`'s cascade
(unaffected by strategy count, §2), Runtime's existing
reservation/in-flight-command machinery (ADR-034) for duplicate-submission
prevention — ADR-035 §6 itself: *"ORB introduces no new
duplicate-prevention logic, reusing what exists."*

**OPEN DESIGN DECISION (Phase 1, not textually settled by ADR-035):**
how `qualify()` selects "the" relevant `OpeningRangeState` out of
`evidence.opening_ranges` when Phase 4's Market-Intelligence/anchor-
reconciliation logic does not exist yet (§10) — this Plan proposes a
conservative, fail-closed answer, flagged for explicit independent
confirmation, not asserted as ADR-mandated.

## 6. Explicit Phase 2+ Deferrals

(Restated from §5 for the template's own section numbering — no new
content beyond §5's "DEFERRED TO PHASE 2+" list.) Phase 2 owns breakout
qualification; Phase 3 owns FVG confirmation; Phase 4 owns Market
Intelligence/eligibility integration; Phase 5 owns the remainder of
`StrategyEngineConfig`'s ORB fields and their config-loader wiring;
Phase 6 owns full-suite integration including the production registry
question (§11). None of these is pulled forward by this Plan.

## 7. Production Call Path

Traced directly this session: `EvidenceEngine.evaluate_snapshot()`
(Evidence Engine) → `StrategyEngine.evaluate(pair, evidence,
market_intelligence, now)` (`engine.py:49-76`) → `strategy.qualify(pair,
evidence, market_intelligence, self.config)` for every strategy in
`self.registry.all()` → `select_winning_strategy(qualifications,
evidence, market_intelligence, self.config)` → `StrategySnapshot` →
Runtime's generic consumption (`winning_strategy`/`trade_intent`) → Risk
Engine sizing → Compliance Engine gates → `runtime/bridge_handoff.py::build_trade_command()`
→ Bridge. `deployment_windows/start.py:1196` constructs one
`StrategyEngine` instance once at startup (no `registry` argument,
hence `build_default_registry()`); Runtime's live-cycle loop is a
single-threaded, sequential `for pair in profile.allowed_pairs:` (a
prior-session finding, unchanged) — confirming no intra-cycle
concurrency risk for any strategy-held in-memory state (relevant to
§11 of the lockout investigation below).

**Where ORB enters this path:** exactly where every other strategy
already does — as one more `Strategy` instance inside
`self.registry.all()`'s iteration in `StrategyEngine.evaluate()`. No
second path is proposed or would be architecturally coherent; ADR-035
§11/§12 (Evidence Engine integration, Strategy Router compatibility)
already established this and is re-confirmed unchanged by this
session's direct reading of `selection.py`/`engine.py`.

## 8. Model / StrategyId Changes

**Required (contingent on Blocker A being resolved):**
- Add `OPENING_RANGE_BREAKOUT = "OPENING_RANGE_BREAKOUT"` to
  `titan_protocol/strategy_engine/models.py`'s `StrategyId` enum — the
  exact name ADR-035 §17 itself specifies ("naming to match
  `StrategyId.OPENING_RANGE_BREAKOUT`"), not inferred.
- No other model changes: `QualificationResult`, `StrategyDefinition`,
  `TradeIntent`, `StrategySnapshot`, `WinningStrategy` all already
  support any `StrategyId` value generically — confirmed by direct read
  (§2), no `StrategyId`-specific branch exists in any of them.

**Affected generic mappings (verified, not assumed):**
- `titan_protocol/runtime/profiles.py::_ALL_STRATEGIES = tuple(StrategyId)`
  and `_TRADEABLE_PAIR_UNIVERSE` (derived from
  `DEFAULT_APPROVED_PAIRS_BY_STRATEGY`) — both self-deriving; adding one
  `StrategyId` member automatically includes it in `_ALL_STRATEGIES` for
  every default Trading Profile's `allowed_strategies`, with **zero code
  change** in `profiles.py` (re-confirmed this session, same mechanism
  documented during the ADR-036 review).
- `tests/titan_protocol/runtime/test_trading_profiles.py:78`
  (`assertEqual(set(profile.allowed_strategies), frozenset(StrategyId), ...)`)
  — self-deriving, continues to pass unmodified (same finding as the
  ADR-036 review).
- **No Runtime file requires modification** for the `StrategyId` addition
  itself — this is an accurate, re-verified extension of the ADR-036
  review's own finding to this specific, concrete addition (not merely
  the hypothetical shrink-to-one case).
- Logging: `runtime/logging_sink.py:47`'s `record.selected_strategy.value`
  would simply serialize `"OPENING_RANGE_BREAKOUT"` on a cycle ORB wins
  — no code change, confirmed by the same generic `.value` access
  pattern already used for all five existing values.
- Selection compatibility: `select_winning_strategy()` requires no
  change (§2, §7) — it already treats every `StrategyId` identically.

## 9. ORB Strategy Foundation

**Structural precedent:** `SessionBreakoutStrategy`
(`titan_protocol/strategy_engine/strategies/session_breakout.py`),
per ADR-035 §0's own explicit finding ("closest existing analog") and
re-confirmed by this session's direct read: a module-level
`_DEFINITION: StrategyDefinition` constant, a small `_breakout_trade_intent()`-shaped
helper returning `Optional[TradeIntent]` (never a guess), and a
`qualify()` built from sequential early-return `NOT_QUALIFIED` checks
before any scoring. **Only the structure is reused — no trading logic
is copied**, per this task's own instruction.

**Phase 1 foundation, minimum viable shape:**
- Module: `titan_protocol/strategy_engine/strategies/orb_breakout.py`
  (new).
- Class: `OrbBreakoutStrategy(Strategy)`.
- **Constructor**: unlike every existing strategy, Phase 1's
  `OrbBreakoutStrategy` needs an `__init__` to hold the §6 lockout's
  in-memory `Dict[(pair, range_start), bool]`-shaped state — **the
  first stateful strategy in this package's history** (§2), an
  explicit, narrow, ADR-035-§6-documented exception to Strategy Engine
  statelessness. This is contingent on Blocker B (§3) — if the
  governance decision determines this state must instead be persisted
  (analogous to `compliance_state_store`), the constructor/lifecycle
  design changes materially (a new persisted-store dependency, not a
  bare in-memory dict) and this section must be revised before
  implementation.
- **`qualify()` signature**: identical to every other strategy's
  (`pair: str, evidence: EvidenceSnapshot, market_intelligence:
  MarketIntelligenceSnapshot, config: StrategyEngineConfig) ->
  QualificationResult`) — no signature change, no new parameter.
- **Fail-closed behavior, Phase 1 scope only:**
  1. `check_eligibility(StrategyId.OPENING_RANGE_BREAKOUT, pair, config)`
     first, exactly like every existing strategy (§2 — this already
     returns `NOT_ELIGIBLE` for every pair today with zero config
     change, §13).
  2. No relevant `OpeningRangeState` found in `evidence.opening_ranges`
     → `NOT_QUALIFIED` ("no opening range configured" / ambiguous
     multi-range case, §10).
  3. `is_formed=False` → `NOT_QUALIFIED` ("range not yet formed").
  4. `is_valid=False` → `NOT_QUALIFIED` ("range invalidated by a data
     gap or insufficient bar count").
  5. Lockout already consumed for this `(pair, range_start)` →
     `NOT_QUALIFIED` ("already qualified for this opening range") —
     contingent on Blocker B.
  6. Otherwise → **Phase 1 cannot legitimately produce `QUALIFIED`** —
     no breakout-qualification rule exists yet (Phase 2's own scope).
     Per this task's explicit instruction ("A foundation phase may
     correctly return NOT_QUALIFIED until later rules exist... No fake
     behavior"), Phase 1's `qualify()` returns `NOT_QUALIFIED` ("no
     breakout qualification logic exists yet — Phase 2") at this final
     step, always, for every input that survives steps 1-5. This is
     the explicit, honest answer to this task's §8 instruction — no
     provisional trading logic is invented to make ORB "work" early.

**`StrategyDefinition` for Phase 1:** all 13 fields populated the same
way `SessionBreakoutStrategy`'s are, with `market_regime=MarketRegime.BREAKOUT`
(ADR-035 §12) and `purpose`/`entry_conditions`/etc. describing the
range-formed/valid/lockout gate only — not later phases' rules (would
be misleading self-declaration otherwise).

## 10. OpeningRangeState Consumption

- **No raw-bar access, no `market_data_ingestion` import, no
  recomputation of range high/low** — Phase 1 reads only
  `evidence.opening_ranges`, a tuple Evidence Engine already computed
  (ADR-024 Hard Rule, "sole interpreter of market data," unchanged).
- **`session` is descriptive only** (ADR-035 §3's "Identification"
  correction, re-verified against the actual `OpeningRangeState`
  dataclass this session) — never used to pick a range.
- **`opening_ranges == ()`** → no relevant range → `NOT_QUALIFIED` (§9
  step 2).
- **Exactly one entry** → that is the relevant range for Phase 1's
  purposes; check `is_formed`/`is_valid` on it directly.
- **More than one entry** → Phase 1 has no Phase-4 anchor-reconciliation
  logic (session/eligibility matching, §17 Phase 4) to disambiguate
  "which configured range is currently relevant to this evaluation
  cycle" the way ADR-035 §3/§15 describe for the full design. This
  Plan's proposed, conservative answer: **`NOT_QUALIFIED` on ambiguity**
  ("multiple opening ranges configured, cannot disambiguate before
  Phase 4"), consistent with ADR-035 §14's own "no ambiguity, no
  closest guess" principle for the equivalent full-design scenario —
  **flagged explicitly as an open design decision for independent
  review**, not asserted as ADR-035's own explicit text (it is this
  Plan's synthesis from the ADR's stated principles, applied to a
  mechanical detail the ADR did not spell out for the pre-Phase-4
  state).
- **Index fields (`range_start_index`/`range_end_index`)**: **no Phase 1
  behavior depends on them** — they exist for a future consumer (ADR-035
  §5/§9, Phase 3's FVG temporal comparison), not Phase 1's range-formed/
  valid/lockout scope. Confirmed by re-reading ADR-035 §17's Phase 1
  bullet: no index usage named.

## 11. Lockout Design

**Contingent on Blocker B (§3) — this section describes the design
ADR-035 itself provisionally assumes, not a settled Phase 1
implementation decision.**

- **What it solves (task §10's five-way distinction, resolved directly
  from ADR-035 §6's own text):** duplicate **strategy qualification**
  only — preventing the same already-completed opening range from
  producing a fresh `QUALIFIED` result every cycle until the range rolls
  over. It does **not** solve duplicate winning selection
  (`selection.py`, already generic and unrelated), duplicate reservation
  (`risk_engine`'s `ReservationLedger`, unrelated), duplicate command
  submission (Runtime's `InFlightCommandRegistry`, ADR-034, unrelated —
  ADR-035 §6 itself: *"ORB introduces no new duplicate-prevention logic,
  reusing what exists"*), or duplicate actual position
  (`compliance_engine`'s `max_positions_per_pair`, unrelated).
- **State shape:** `Dict[(pair, range_start), bool]`, keyed by the exact
  tuple ADR-035 §6 specifies — `range_start` (not `range_start_index`)
  as the per-anchor identity, consistent with §10's per-instance
  `OpeningRangeState.range_start` field.
- **Lifecycle:** one `OrbBreakoutStrategy` instance is constructed once
  (wherever it is registered, §11 of this Plan's own registration
  question, not `build_default_registry()` in Phase 1 per §12) and
  reused across every pair/cycle for the process's lifetime — confirmed
  safe for the single-threaded, sequential live-cycle loop (§7); no
  intra-process concurrency risk. **Process restart is exactly where
  Blocker B bites**: an in-memory dict resets to empty on restart,
  meaning a range that already produced one `QUALIFIED` result before a
  restart could produce a second one after — the exact scenario ADR-035
  §18.A item 2 says "must be settled... if a restart mid-range allowing
  a fresh qualification is judged unacceptable," and which this session
  found no resolution for.
- **Configuration:** `orb_max_qualifications_per_range: int = 1` must
  be added to `StrategyEngineConfig` at Phase 1 (not deferred to Phase
  5) — this is a code-level default powering Phase 1's own required
  mechanism, not a Phase-5 "config-loader wiring" concern (§13); per
  CLAUDE.md §3, this number must be named, never a magic literal
  embedded in `orb_breakout.py` itself.

## 12. Registration / Composition Plan

**Proposed answer (flagged for independent confirmation, not asserted
as ADR-035's own explicit instruction):** Phase 1 does **not** add
`OrbBreakoutStrategy` to the production `build_default_registry()`.

Evidence supporting this:
- ADR-035 §17 Phase 6: *"integration (real five-plus-ORB `StrategyEngine`
  competing in the real selection cascade)"* — the six-strategy
  competing registry is framed as a Phase 6 milestone.
- `test_regression.py::test_default_fixture_always_rejects` hardcodes
  `len(snapshot.all_qualifications) == 5` (§2) — registering ORB now
  breaks this anchor for zero functional benefit, since Phase 1's
  `qualify()` can never legitimately return `QUALIFIED` (§9).
- Phase 1's own tests (§15) instantiate `OrbBreakoutStrategy()` directly
  and call `.qualify()` on it — no production registration is needed to
  test Phase 1's own scope.

**What later phase activates it:** not settled by this Plan (out of
Phase 1's own scope to decide) — plausibly Phase 4 (once eligibility/MI
integration exists, making a real `QUALIFIED` outcome possible) or
Phase 6 (explicit "five-plus-ORB competing" integration milestone,
matching ADR-035's own words most directly). This Plan does not choose
between them; it only establishes that Phase 1 itself does not need to.

**If this proposed answer is rejected by independent review** (i.e., if
ORB should be registered in production starting at Phase 1), the direct
consequence is: `test_regression.py`'s `len(...) == 5` assertion becomes
a **legitimate additive expectation change** (§14 of the governing
task's own taxonomy: "6" replacing "5"), not an ADR-036 retirement act
(the five legacy strategies remain registered — inventory becomes six,
temporarily, exactly as this task's §11 anticipates) — this Plan would
need a corresponding revision to §15 (Testing Plan) to reflect that
path instead.

## 13. Configuration Plan

Distinguishing (per this task's own required distinction):

| Concept | Owner | Phase 1 action |
|---|---|---|
| `EvidenceEngineConfig.opening_range_anchors`/`opening_range_duration_minutes`/etc. | Evidence Engine, Phase 0 (implemented) | None — read-only consumption via `evidence.opening_ranges` |
| `StrategyEngineConfig.approved_pairs_by_strategy` entry for `OPENING_RANGE_BREAKOUT` | Existing generic Strategy Engine config surface | **None required** — `approved_pairs_for()` already falls back to `()` for any unlisted `StrategyId` (§2), correctly producing `NOT_ELIGIBLE` for every pair with zero code change, mirroring ADR-035 §18.B item 4's own "empty by default" philosophy |
| `StrategyEngineConfig.orb_max_qualifications_per_range` | Phase 1's own mechanism (§11) | **Add**, default `1`, contingent on Blocker B |
| ADR-035 §13's remaining ORB fields (`orb_approved_pairs`, `orb_min_range_atr_ratio`, `orb_min_breakout_distance_atr_multiple`, `orb_min_body_to_range_ratio`, `orb_min_confirmation_candles`, `orb_fvg_*`, `orb_min_liquidity_score`) | Phase 5 (config loading) / Phase 2-4 (the rules that consume them) | None — out of Phase 1 scope entirely |

No duplication of Evidence Engine's own opening-range computation
configuration inside Strategy Engine is proposed or needed — Phase 1
only ever reads `evidence.opening_ranges`, never recomputes a range.

## 14. Fail-Closed Analysis

| Condition | Phase 1 result | Contingent on |
|---|---|---|
| Pair outside approved universe | `NOT_ELIGIBLE` | Nothing — works today with zero config (§13) |
| `opening_ranges == ()` | `NOT_QUALIFIED` | Nothing |
| Multiple ambiguous ranges | `NOT_QUALIFIED` (proposed, §10) | Independent review confirmation |
| `is_formed=False` | `NOT_QUALIFIED` | Nothing — direct ADR-035 §4 text |
| `is_valid=False` | `NOT_QUALIFIED` | Nothing — direct ADR-035 §4 text |
| Lockout already consumed | `NOT_QUALIFIED` | Blocker B resolution |
| Every other input | `NOT_QUALIFIED` (no qualification logic exists yet) | Nothing — Phase 2's own scope, no fake behavior (§9) |

No path in this table produces `QUALIFIED` — a direct, intended
consequence of Phase 1 being a foundation phase, not a defect.

## 15. Testing Plan

New file: `tests/titan_protocol/strategy_engine/test_orb_breakout_foundation.py`
(mirrors this package's one-file-per-concern convention, distinct from
`test_qualification.py`'s per-existing-strategy shared file, since
Phase 1's scope is deliberately narrower than a full qualification
suite).

- **Unit tests:** each of §14's table rows, one test per row, calling
  `OrbBreakoutStrategy().qualify(...)` directly (no registry, no
  `StrategyEngine`) with hand-built `EvidenceSnapshot`s carrying a
  controlled `opening_ranges` tuple.
- **Boundary tests:** `is_formed`/`is_valid` combinations at their exact
  True/False edges (four combinations); zero vs. one vs. two
  `opening_ranges` entries.
- **Negative tests:** pair outside `approved_pairs_for()`'s empty
  fallback (confirms `NOT_ELIGIBLE` with zero config, §13); lockout
  re-qualification attempt within the same `(pair, range_start)`
  (contingent on Blocker B).
- **Model integrity tests:** `StrategyId.OPENING_RANGE_BREAKOUT`
  round-trips through `QualificationResult`/`StrategySnapshot`
  unchanged (mirrors existing per-`StrategyId` coverage patterns).
- **Architecture test:** `test_architecture.py` (existing, unmodified)
  re-run — confirms `orb_breakout.py` introduces no forbidden import
  (`ALLOWED_UPSTREAM_PREFIXES` already covers exactly what Phase 1
  needs: `evidence_engine`, `market_intelligence`) and no trade-decision
  vocabulary beyond the already-permitted `TradeIntent` (§2).
- **Regression tests:** full existing Strategy Engine suite (`test_qualification.py`,
  `test_trade_intent.py`, `test_selection.py`, `test_engine.py`,
  `test_boundary.py`, `test_determinism.py`, `test_property.py`,
  `test_explainability.py`, `test_performance.py`) re-run unmodified —
  **no expectation change needed in any of them**, since
  `OrbBreakoutStrategy` is not registered in `build_default_registry()`
  (§12) and therefore never participates in any test that exercises the
  default registry. `test_regression.py`'s `len(...) == 5` anchor
  **remains true and unmodified** under this Plan's proposed
  registration answer.
- **Runtime regression:** the three Runtime tests identified during the
  ADR-036 review (`test_configuration.py`, `test_integration.py`,
  `test_phase_3c_ingestion_integration.py`) are **unaffected by Phase 1**
  — they reference `StrategyId.TREND_CONTINUATION` concretely, not
  generically, and Phase 1 adds a new member without touching that one;
  confirmed no code change required in any of the three.

Every Phase 1 implementation item has its own Phase 1 test above — none
is deferred to Phase 6, per this task's own instruction and ADR-035
§17's own corrected wording (re-verified this session, unchanged).

## 16. Legacy Strategy Preservation

Explicitly re-verified this session, immediately before writing this
Plan:

- All five legacy strategy files exist:
  `liquidity_sweep_mss.py`, `bos_fvg.py`, `trend_continuation.py`,
  `session_breakout.py`, `range_reversal.py`.
- All five remain registered in `build_default_registry()` (unchanged
  file, re-read this session).
- All five `StrategyId` values remain in the enum (unchanged).
- All five `StrategyEngineConfig` per-strategy field groups remain
  (unchanged).
- All five's dedicated test coverage remains (`test_qualification.py`,
  `test_trade_intent.py`, `test_regression.py`, `test_selection.py`, all
  unchanged, re-read this session).

**Phase 1 Acceptance Criteria (§19) must include a regression gate
proving all five remain present, registered, and passing — this Plan
proposes exactly zero changes to any of the five's files, `StrategyId`
values, config fields, or tests.** No ADR-036 retirement work appears
anywhere in this Plan; ADR-036 remains dormant per its own Acceptance
scope.

## 17. Risk Assessment

| Risk | Classification | Evidence | Failure mode | Severity | Mitigation | Test/gate |
|---|---|---|---|---|---|---|
| Implementing against a Proposed (not Accepted) ADR-035 | Governance | `docs/adr/ADR-035-orb-strategy.md:3` (§3) | Implementation proceeds without the CLAUDE.md §1.10 precondition ADR-035 itself requires | High (governance, not technical) | Do not implement until Blocker A is resolved | This Plan's own blocked status |
| Lockout persistence decision made by default (silently in-memory) | Governance/Capital-preservation | ADR-035 §18.A item 2 unresolved (§3) | A restart mid-range could allow a second `QUALIFIED` result for the same range if the "unacceptable" branch of the open question is the correct answer | Medium (bounded by Runtime's existing reservation/in-flight controls even if it occurs, per ADR-035 §6) | Do not implement lockout until Blocker B is explicitly settled | This Plan's own blocked status |
| Premature `QUALIFIED` result from an incomplete strategy | Behavioral/Capital-preservation | §9's fail-closed table — every path returns `NOT_QUALIFIED` | None if this Plan's §9 design is followed exactly | Low | §9's explicit "no fake behavior" design | §15's unit tests for every §14 row |
| Malformed/missing `OpeningRangeState` | Behavioral | §10 | Handled: `()` and ambiguous-multiple both fail closed | Low | §10's explicit rules | §15 boundary tests |
| Adding a 6th `StrategyId` breaks a hardcoded test | Testing | `test_regression.py:22` (§2) | None, if not registered in `build_default_registry()` (§12) | Low (avoided by design) | §12's registration answer | §15 regression tests |
| Registry/selection effects from a 6th `StrategyId` | Architectural | `selection.py` re-confirmed generic (§2, §7) | None expected | Low | N/A — already generic | §15 regression tests |
| Runtime `allowed_strategies`/logging effects | Concurrency/state, Configuration | `profiles.py`'s self-deriving constants, `logging_sink.py`'s generic `.value` access (§8) | None expected | Low | N/A — already generic | Runtime test re-run, unmodified |
| First stateful strategy in this package's history | Concurrency/state, Architectural | `OrbBreakoutStrategy`'s proposed constructor (§9, §11) | A narrow, documented exception to ADR-026's stateless-strategy convention; single-threaded sequential call path confirmed safe (§7) | Medium (novel pattern, not a functional defect) | Explicit documentation in the class docstring citing ADR-035 §6; no concurrency risk given confirmed sequential Runtime loop | §15 model-integrity/regression tests |
| Phase leakage from Phase 2+ | Governance | §5/§6's explicit deferral list | A future implementer adds breakout/FVG/MI logic "while they're in there" | Low if this Plan is followed; the risk is procedural, not technical | §5's explicit REQUIRED/DEFERRED split; each phase's own RPI gate (`TEAM.md` §9) | Independent review of the eventual diff against this Plan |

No risk above is Critical. Two items (governance) are the reason this
Plan is blocked, not merely risky.

## 18. Out-of-Scope Confirmation

Phase 1 does **not** implement, and this Plan does not describe:
breakout qualification (Phase 2), FVG confirmation (Phase 3), Market
Intelligence/eligibility integration (Phase 4), ORB's remaining
`StrategyEngineConfig` fields or `config_loader.py` wiring (Phase 5),
production registration of `OrbBreakoutStrategy` (proposed as Phase 4
or 6, §12, not decided here), stop-loss/take-profit computation (out of
every phase's scope, ADR-031 §3), Risk Engine sizing, Compliance Engine
gates, Runtime orchestration changes, Bridge/execution changes, or any
part of ADR-036's retirement roadmap (dormant, per ADR-036's own
Acceptance scope).

## 19. Acceptance Criteria

**Governance (must pass before any of the below is implementation-ready):**
- Blocker A resolved: ADR-035's own document `Status:` line reads
  **Accepted**.
- Blocker B resolved: ADR-035 §18.A item 2 (lockout persistence) is
  explicitly confirmed one way or the other, in writing, by the
  appropriate authority — not silently carried forward.

**Once unblocked, objective, repository-verifiable gates:**
- `StrategyId.OPENING_RANGE_BREAKOUT` exists.
- `OrbBreakoutStrategy` exists, conforms to `Strategy`, and is
  constructible/callable directly (not necessarily registered, §12).
- `evidence.opening_ranges` is consumed without recomputation and
  without any `market_data_ingestion`/raw-bar access (verified by
  `test_architecture.py`, unmodified, still green).
- Every §14 fail-closed row is verified by a dedicated test, all
  passing.
- Lockout behavior matches whatever Blocker B's resolution specifies
  (in-memory or persisted) — verified by dedicated tests.
- No Risk/Compliance/Bridge/Execution authority is transferred to ORB
  (verified by `test_architecture.py`'s forbidden-vocabulary check,
  unmodified).
- All five legacy strategies remain present, registered, and passing
  (§16) — `git diff --stat` shows zero change to any of their five
  files.
- `selection.py` remains valid and unmodified.
- Runtime remains compatible with zero code change (§8).
- `tests/titan_protocol/strategy_engine/test_orb_breakout_foundation.py`
  (new) passes in full.
- Every pre-existing Strategy Engine test passes **unmodified** (§12's
  proposed registration answer means no expectation-update is needed
  anywhere, unlike Phase 0's own experience with unrelated packages).
- Evidence Engine's own test suite remains green (untouched by this
  Plan).
- `python3 -m compileall titan_protocol/strategy_engine tests/titan_protocol/strategy_engine` clean.
- Full relevant regression suite (Strategy Engine + Runtime + Evidence
  Engine) green.
- `git diff --stat` confined to `titan_protocol/strategy_engine/` and
  its own new test file — no other package touched.

No criterion above is marked PASS by this document — these are future
implementation gates, per this task's own instruction.

## 20. Rollback Strategy

Deterministic and low-risk, mirroring Phase 0's own rollback pattern:
revert the future implementation commit(s); `OrbBreakoutStrategy`,
`StrategyId.OPENING_RANGE_BREAKOUT`, and `orb_max_qualifications_per_range`
disappear entirely; no other file depends on any of them (§8, §12 — not
registered in production, so no downstream consumer to unwind); the
five legacy strategies and every existing test are already confirmed
untouched (§16), so rollback has zero cascading effect outside
`titan_protocol/strategy_engine/` and its own new test file.

## 21. Engineering Checklist

*(Blocked — none of the following may begin until §3's two blockers are
resolved.)*

- [ ] Blocker A resolved: ADR-035 marked Accepted in its own document.
- [ ] Blocker B resolved: lockout persistence decision made explicit.
- [ ] `StrategyId.OPENING_RANGE_BREAKOUT` added.
- [ ] `orb_breakout.py` created with `OrbBreakoutStrategy`, matching §9
      exactly.
- [ ] `orb_max_qualifications_per_range` added to `StrategyEngineConfig`,
      default `1`.
- [ ] Lockout mechanism implemented per Blocker B's resolved design.
- [ ] `test_orb_breakout_foundation.py` written covering §15's full list.
- [ ] Every pre-existing Strategy Engine and Runtime test re-run,
      confirmed unmodified (§15).
- [ ] `compileall` clean.
- [ ] `test_architecture.py` (Strategy Engine's own) re-run and PASS.
- [ ] `git diff --stat` confined to §8/§9/§11's files plus the new test
      file.
- [ ] CHANGELOG entry drafted.
- [ ] Independent review confirms §12's registration-timing answer
      (or overrides it with a documented reason).

## 22. Final Readiness Assessment

This Plan is grounded entirely in code and documents read directly
this session (`ADR-035-orb-strategy.md`, `ADR-036-orb-strategy-consolidation.md`,
every relevant `titan_protocol/strategy_engine/` and
`titan_protocol/evidence_engine/` file, the full Strategy Engine and
relevant Runtime test directories, `CHANGELOG.md`, `KNOWN_GAPS.md`).
Two governance preconditions remain unresolved and are not settled by
this document (§3) — this Plan is **content-complete but
implementation-blocked**. Once both are resolved, no further research
is anticipated to be needed before implementation begins; the one
genuinely open design question this Plan carries forward (§10's
multi-range ambiguity handling) is flagged for explicit confirmation,
not silently assumed.

## 23. Validation

*(To be completed during/after Phase 1 implementation, once unblocked —
recorded here as the expected checklist, not yet executed.)*

- `python3 -m compileall titan_protocol/strategy_engine tests/titan_protocol/strategy_engine`:
- `python3 -m unittest discover -s tests/titan_protocol/strategy_engine`:
- `python3 -m unittest tests.titan_protocol.strategy_engine.test_architecture`:
- `python3 -m unittest discover -s tests/titan_protocol/runtime`:
- Code Reviewer sign-off:
- Test Results Analyzer sign-off:
- Software Architect sign-off (mandatory per `TEAM.md` §3 for a Strategy
  Engine change):
- Confirmation that Blocker A and Blocker B were resolved *before*
  implementation began, not retroactively.
