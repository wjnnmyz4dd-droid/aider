# Plan: ADR-035 Phase 1 — ORB Strategy Foundation

Status: **Planned** (both governance blockers resolved; independent
implementation-governance review completed with two required minor
revisions, both applied and re-verified this revision — see §3
Governance Preconditions and §22 Final Readiness Assessment)
Owner (Plan phase): Software Architect
Touched components: `titan_protocol/strategy_engine/` only

---

> **PHASE 1 UNBLOCKED — SUMMARY OF RESOLUTION.** The two governance
> preconditions recorded against this Plan are both resolved as of this
> revision, per a dedicated governance task explicitly scoped to
> resolve them. See §3 for full evidence and the ADR-035 sections cited
> below for the complete reasoning.
>
> **Blocker A — ADR-035's own document status — RESOLVED, Accepted.**
> `docs/adr/ADR-035-orb-strategy.md` line 3 now reads `Status:
> **Accepted**` (2026-07-25), changed as an explicit, new governance
> decision — not a reconstruction of history. The decision rests on
> repository-verified maturity: the Independent Acceptance Review's
> required corrections (F1-F5) were incorporated (`af5b9c0`), the
> companion Evidence Engine amendment is implemented and independently
> validated (Phase 0, `ee976f4`), and neither §18.A item blocks
> Acceptance (item 1 resolved by Phase 0's own implementation; item 2
> resolved in direction, below).
>
> **Blocker B — ADR-035 §18.A item 2, lockout persistence — RESOLVED IN
> DIRECTION, and found not to gate Phase 1 at all.** The governance
> investigation determined: persistence of the lockout state across a
> restart **is required** (ORB's own "at most N qualifications per
> range" purpose, plus CLAUDE.md's Priority-1 "no duplicate trades"
> rule, override this Plan's original in-memory-only assumption);
> ownership belongs to Strategy Engine; no existing persistence
> mechanism may be safely reused (`compliance_state_store` and
> `runtime/in_flight_store.py` both belong to a different engine, per
> ADR-026 Hard Rule 5); a new, small, Strategy-Engine-owned store is
> therefore required, in the convention of (but not reusing)
> `compliance_state_store`. **That store's concrete design is new
> architecture and is deliberately deferred to Phase 2** — not because
> the question is unresolved, but because Phase 1's own
> `OrbBreakoutStrategy.qualify()` can never return `QUALIFIED` under any
> input (§9 — no breakout-qualification rule exists until Phase 2), so
> the lockout's consumption event can never fire within Phase 1's scope
> regardless of storage. Building lockout state — in-memory or
> persisted — that can never be written would be speculative scaffolding
> for a condition that cannot occur (CLAUDE.md §7). **The entire §6
> session-lockout mechanism therefore moves out of Phase 1's scope and
> into Phase 2's** (ADR-035 §17, revised this session) — the first phase
> at which it has any observable effect and the first phase the
> persistence-architecture precondition actually gates. This revision
> touches every section below that previously described the lockout as
> Phase 1 scope; each is updated accordingly, not merely flagged.
>
> See ADR-035 §18.A item 2 for the complete resolution text (semantic
> requirement, restart evidence, ownership, storage-architecture
> assessment, counter-consumption semantics, state identity, and the
> fail-closed persistence principle governing Phase 2's eventual store
> design).

---

> **INDEPENDENT REVIEW COMPLETED — TWO REQUIRED MINOR REVISIONS
> APPLIED.** A subsequent independent implementation-governance review
> of this Plan (architecturally sound, correctly foundation-only)
> returned five findings, F1-F5. Two required minor revisions (F1, F2)
> are applied in this revision; F3 is a completeness correction, also
> applied; F4 and F5 are recorded as out-of-scope follow-ups, not applied
> here.
>
> - **F1 — formed+valid range lacked an explicit named test — RESOLVED.**
>   §14 now carries a dedicated table row and §15 a dedicated,
>   individually-named test
>   (`test_formed_valid_opening_range_still_not_qualified_without_breakout_logic`)
>   proving a genuinely well-formed, valid opening range still returns
>   `NOT_QUALIFIED` — no longer folded into a generic catch-all.
> - **F2 — Phase 2's concurrency argument relied on today's caller, not
>   `StrategyEngine`'s own contract — RESOLVED.** §7 and §11 now
>   distinguish the operational fact (today's Runtime caller is
>   sequential) from the architectural contract (`StrategyEngine.evaluate()`
>   is documented as callable concurrently); §11 lists the concrete
>   concurrency properties (atomicity, lost-update prevention,
>   read/modify/write races, crash-safe writes) Phase 2's own persistence
>   design must address, without solving them here.
> - **F3 — second hardcoded 5-strategy test uncited — RESOLVED.** §15
>   now names both `test_regression.py` and `test_engine.py`.
> - **F4 — stale "Amendment 2" citations in Phase 0 code docstrings —
>   NOT corrected here** (out of Phase 1 scope; a separate documentation
>   follow-up against `titan_protocol/evidence_engine/models.py` and
>   `opening_range.py`, and against `ADR-024-evidence-engine.md`'s own
>   missing Amendment 3 entry).
> - **F5 — Phase 2's persistence package will need a reviewed
>   `test_architecture.py` boundary extension — recorded, not applied.**
>   §11 now states this explicitly as a Phase 2 prerequisite; this Plan
>   does not pre-authorize it.
>
> No new contradiction was discovered during this revision. Phase 1's
> scope, registration answer, and legacy-strategy preservation are
> unchanged and re-confirmed (§5, §12, §16).

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

Both preconditions below were resolved by a dedicated governance task
this session. Summary table:

| Precondition | Expected | Actual (verified this session) | Status |
|---|---|---|---|
| ADR-035: Accepted | Accepted | `Status: **Accepted**` (`docs/adr/ADR-035-orb-strategy.md:3`), changed this session as an explicit governance decision, not a reconstruction of history | **RESOLVED — Blocker A closed** |
| ADR-035 Phase 0: implemented and independently validated | Yes | Confirmed: `OpeningRangeState`, `EvidenceSnapshot.opening_ranges`, `opening_range.py`, config fields all exist and are wired; 22+5 tests green (§4) | Verified true |
| ADR-036: Accepted | Accepted | Confirmed: `docs/adr/ADR-036-orb-strategy-consolidation.md:3` reads `Status: **Accepted**` | Verified true |
| ADR-035 §18.A item 2 (lockout persistence) resolved | Resolved before the phase it gates begins | Resolved in direction this session: persistence required, ownership = Strategy Engine, counter = on `QUALIFIED`, no existing store reusable, new store required. **Determined to gate Phase 2, not Phase 1** — Phase 1's `qualify()` never returns `QUALIFIED` (§9), so the lockout mechanism itself moves to Phase 2 (ADR-035 §17) | **RESOLVED — does not gate Phase 1; gates Phase 2** |

Per this session's governance task, both preconditions are settled: this
document now proceeds as an implementation-ready Plan, pending only the
normal independent review this project's RPI workflow (`TEAM.md` §9)
requires before any Plan is implemented.

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
- Phase 1's own unit tests for exactly this scope (§15).

**DEFERRED TO PHASE 2+:**
- **The §6 session-lockout (`orb_max_qualifications_per_range`) —
  resolved this revision, moved to Phase 2, not Phase 1** (ADR-035 §17,
  §18.A item 2). Phase 1's `qualify()` can never produce `QUALIFIED`
  under any input (§9), so the lockout's own consumption event ("once
  ORB has produced one `QUALIFIED` result," ADR-035 §6) cannot fire
  within Phase 1's scope regardless of whether the state is in-memory or
  persisted — implementing it here would be speculative scaffolding for
  a condition that cannot occur. Phase 2 is the first phase at which
  `qualify()` can return `QUALIFIED`, and therefore the first phase the
  lockout has anything to protect and the first phase gated by the
  lockout's own persistence-architecture precondition (§11).
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
qualification **and the §6 session-lockout** (moved this revision, §5,
§11); Phase 3 owns FVG confirmation; Phase 4 owns Market
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
single-threaded, sequential `for pair in profile.allowed_pairs:`
(re-verified this revision, unchanged).

**Concurrency framing corrected (independent review finding F2) —
operational fact vs. architectural contract, kept distinct:**
`titan_protocol/strategy_engine/engine.py`'s own docstring states
`StrategyEngine`'s design intent explicitly: *"`evaluate()` may be
called concurrently from many threads against one shared instance."*
That "today's one production caller happens to be sequential" is an
**operational fact about `deployment_windows/start.py`'s current loop,
not a structural guarantee of the `StrategyEngine` class itself** —
which documents broader concurrent-caller support. This distinction has
no consequence for Phase 1 (§9's `OrbBreakoutStrategy` holds no
constructor/instance state at all, so there is nothing for concurrent
callers to race on), but it must not be miscarried into Phase 2's own
design as if it were: Phase 2's persistence design must be safe under
whatever invocation pattern `StrategyEngine` itself supports, never
merely safe under today's one caller's happen-to-be-sequential behavior
(§11 restates this as the governing forward-contract principle).

**Where ORB enters this path:** exactly where every other strategy
already does — as one more `Strategy` instance inside
`self.registry.all()`'s iteration in `StrategyEngine.evaluate()`. No
second path is proposed or would be architecturally coherent; ADR-035
§11/§12 (Evidence Engine integration, Strategy Router compatibility)
already established this and is re-confirmed unchanged by this
session's direct reading of `selection.py`/`engine.py`.

## 8. Model / StrategyId Changes

**Required:**
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
- **No constructor override — resolved this revision:** since the §6
  lockout moves to Phase 2 (§5, §11), Phase 1's `OrbBreakoutStrategy`
  needs no `__init__` and no instance attributes at all, matching every
  existing strategy's stateless convention exactly (§2). This package's
  first stateful strategy, and the persisted-store dependency its
  constructor will need, is now a Phase 2 concern, not Phase 1's —
  removing an entire class of design risk from this phase.
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
  5. **Range is formed and valid (`is_formed=True`, `is_valid=True`) —
     the positive-evidence case, named explicitly (independent review
     finding F1): Phase 1 still returns `NOT_QUALIFIED`** ("no breakout
     qualification logic exists yet — Phase 2"). A valid, formed opening
     range proves the evidence fact is usable; it does not prove a
     breakout occurred. There is no path from "valid evidence exists" to
     "trade qualification exists" in Phase 1 — no breakout-qualification
     rule exists yet (Phase 2's own scope, which also owns the §6
     lockout check, §5/§11). Per this task's explicit instruction ("A
     foundation phase may correctly return NOT_QUALIFIED until later
     rules exist... No fake behavior"), this is the explicit, honest
     answer — no provisional trading logic is invented to make ORB
     "work" early. This is also, by construction, the same unconditional
     branch every other surviving input reaches: nothing about a
     well-formed range receives different treatment from a marginal one
     — both return `NOT_QUALIFIED` for the identical reason.

**`StrategyDefinition` for Phase 1:** all 13 fields populated the same
way `SessionBreakoutStrategy`'s are, with `market_regime=MarketRegime.BREAKOUT`
(ADR-035 §12) and `purpose`/`entry_conditions`/etc. describing the
range-formed/valid gate only — not later phases' rules (would be
misleading self-declaration otherwise).

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
- **More than one entry — resolved this revision, VALID PLAN-LEVEL
  DETAIL (not a contradiction of ADR-035, not a decision requiring
  independent confirmation):** ADR-035 §17 Phase 4 ("Market
  Intelligence/eligibility integration: session anchor matching, using
  §3's corrected identification rule") is the ADR's own, explicit home
  for the real "which configured range is currently relevant to `now`"
  deterministic-matching mechanism — that logic does not exist yet and
  is out of Phase 1's scope by the ADR's own roadmap, not by this Plan's
  choice. Because Phase 1's `qualify()` never produces `QUALIFIED` under
  any input (§9 — every path returns `NOT_QUALIFIED`, by design, since
  no breakout-qualification rule exists until Phase 2), the exact
  `NOT_QUALIFIED` reason string reported when `opening_ranges` has more
  than one entry is **cosmetic at this phase, not a behavioral
  decision** — this Plan's proposed reason ("multiple opening ranges
  configured, cannot disambiguate before Phase 4") is consistent with
  ADR-035 §14's own "no ambiguity, no closest guess" principle and does
  not foreclose or pre-empt Phase 4's own real matching mechanism, which
  will replace this stopgap outright when it lands.
- **Index fields (`range_start_index`/`range_end_index`)**: **no Phase 1
  behavior depends on them** — they exist for a future consumer (ADR-035
  §5/§9, Phase 3's FVG temporal comparison), not Phase 1's range-formed/
  valid/lockout scope. Confirmed by re-reading ADR-035 §17's Phase 1
  bullet: no index usage named.

## 11. Lockout Design (moved to Phase 2 — not part of this Plan's own implementation scope)

**Resolved this revision: the §6 session-lockout is Phase 2 scope, not
Phase 1's.** ADR-035 §18.A item 2 is now resolved in direction (semantic
requirement, ownership, counter-consumption event, and the fail-closed
persistence principle are all settled — see ADR-035 §18.A item 2 for the
complete text); what remains open is the lockout's *concrete storage
architecture*, which is new architecture requiring its own focused
review before Phase 2 implements it — not a Phase 1 concern, since
Phase 1's `qualify()` can never produce `QUALIFIED` and therefore never
reaches the lockout check at all (§9). This section is retained,
renumbered in place, to carry the design summary forward into Phase 2's
own future Plan rather than losing it:

- **What it solves (resolved directly from ADR-035 §6's own text):**
  duplicate **strategy qualification** only — preventing the same
  already-completed opening range from producing a fresh `QUALIFIED`
  result every cycle until the range rolls over. It does **not** solve
  duplicate winning selection (`selection.py`, already generic and
  unrelated), duplicate reservation (`risk_engine`'s `ReservationLedger`,
  unrelated), duplicate command submission (Runtime's
  `InFlightCommandRegistry`, ADR-034, unrelated — ADR-035 §6 itself:
  *"ORB introduces no new duplicate-prevention logic, reusing what
  exists"*), or duplicate actual position (`compliance_engine`'s
  `max_positions_per_pair`, unrelated).
- **State shape:** `(pair, range_start)` as the key, per ADR-035 §6 and
  §18.A item 2 — `range_start` (not `range_start_index`) as the
  per-anchor identity, consistent with §10's per-instance
  `OpeningRangeState.range_start` field. **Persisted, not a bare
  in-memory dict** (resolved, ADR-035 §18.A item 2) — the concrete
  record shape (e.g. a schema-versioned JSON document analogous to
  `compliance_state_store`'s own `PersistedComplianceState`) is Phase
  2's own design work, not specified here.
- **Ownership and storage:** Strategy Engine owns the fact; a new,
  small, Strategy-Engine-owned persistence mechanism (its own sibling
  top-level package, in the convention of but not reusing
  `compliance_state_store`) is required, per ADR-035 §18.A item 2. This
  is new architecture and needs its own focused review before Phase 2
  implements it.
- **Phase 2 test-boundary prerequisite (independent review finding
  F5):** `tests/titan_protocol/strategy_engine/test_architecture.py`'s
  `ALLOWED_UPSTREAM_PREFIXES = ("titan_protocol.evidence_engine",
  "titan_protocol.market_intelligence")` (re-verified this revision,
  unchanged) will, by design, reject an import of any new persistence
  package Phase 2 introduces — the correct, working enforcement of
  ADR-026 Hard Rule 5's boundary today, not a defect. Phase 2's own RPI
  Plan must therefore include a reviewed, narrow extension of this list
  alongside its persistence-store design — not a pre-authorization
  granted here, and not something Phase 2 should work around by
  relaxing the boundary test more broadly than the one new package it
  actually needs.
- **Lifecycle and concurrency (corrected this revision, independent
  review finding F2):** whichever `OrbBreakoutStrategy` instance Phase 2
  constructs will need to read/write this persisted state around each
  qualification. **This must be designed safe under whatever invocation
  pattern `StrategyEngine` itself supports — its own docstring documents
  `evaluate()` as callable "concurrently from many threads against one
  shared instance" — not merely safe under today's one production
  caller's sequential loop (§7).** That today's Runtime caller happens
  to be single-threaded is an operational fact, not an architectural
  guarantee Phase 2 may design against. Phase 2's own RPI/design review
  must therefore explicitly address, without this Plan choosing any of
  them:
  - concurrent qualification attempts against the same `(pair,
    range_start)` (or different ones) arriving at the persisted store;
  - atomic state updates — no reader ever observes a partially-written
    record;
  - lost-update prevention — two near-simultaneous "first qualification
    for this range" attempts must not both succeed;
  - read/modify/write races on the same key;
  - crash-safe writes (mirroring `compliance_state_store`'s own
    temp-file + `os.replace` pattern, §18.A item 2);
  - the deterministic `(pair, range_start)` identity (already settled,
    above);
  - fail-closed behavior when the state cannot be safely established
    (already settled, ADR-035 §18.A item 2's persistence principle).

  None of these is designed, solved, or defaulted here — they are
  Phase 2's own architectural work, explicitly preserved as open
  requirements rather than assumed away by today's caller behavior.
- **Configuration:** `orb_max_qualifications_per_range: int = 1` is
  added to `StrategyEngineConfig` at Phase 2 (moved from Phase 1, per
  this revision) — a code-level default powering Phase 2's own
  mechanism, not a Phase-5 "config-loader wiring" concern; per CLAUDE.md
  §3, this number must be named, never a magic literal.

## 12. Registration / Composition Plan

**Resolved this revision: Phase 1 does not add `OrbBreakoutStrategy` to
the production `build_default_registry()`; production registration is
authorized no earlier than Phase 6.** ADR-035 §17's own roadmap text
was re-checked line by line for every phase 1-5: none of them contains
the word "register" or otherwise describes adding `OrbBreakoutStrategy`
to the production registry — the *first* point at which the ADR's own
words describe a registered, competing ORB is Phase 6: *"integration
(real five-plus-ORB `StrategyEngine` competing in the real selection
cascade)."* This is as close to an explicit answer as ADR-035's text
provides, and this Plan treats it as settled for Phase 1's own purposes
(Phase 1 definitely does not register ORB) while leaving open, for
whichever future phase's own RPI Plan reaches that point, whether
Phase 4 or Phase 5 might reasonably register it earlier than Phase 6 —
that is not a question Phase 1 needs to answer.

Evidence supporting non-registration at Phase 1 specifically:
- `test_regression.py::test_default_fixture_always_rejects` hardcodes
  `len(snapshot.all_qualifications) == 5` (§2) — registering ORB now
  breaks this anchor for zero functional benefit, since Phase 1's
  `qualify()` can never legitimately return `QUALIFIED` (§9).
- Phase 1's own tests (§15) instantiate `OrbBreakoutStrategy()` directly
  and call `.qualify()` on it — no production registration is needed to
  test Phase 1's own scope.

**What later phase activates it:** not settled by this Plan, deliberately
— no earlier than Phase 6 per the ADR's own text above; this Plan only
establishes that Phase 1 itself does not register ORB and does not need
to decide exactly which later phase does.

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
| `StrategyEngineConfig.orb_max_qualifications_per_range` | Phase 2's own mechanism (§11, moved this revision) | **None in Phase 1** — added at Phase 2, alongside the lockout's own persistence store |
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
| **Opening range is formed and valid (`is_formed=True`, `is_valid=True`), but no Phase 2 breakout rule exists** | `NOT_QUALIFIED` — always, unconditionally | Nothing — Phase 1 establishes evidence consumption and gating only. A valid opening range proves the evidence fact is usable; it does not prove a breakout occurred. **Capital-preservation property: there is no path from "valid evidence exists" to "trade qualification exists" in Phase 1** (§9 step 5, independent review finding F1) |
| Every other input (should be unreachable given the above already covers every surviving case) | `NOT_QUALIFIED` (no qualification logic exists yet) | Nothing — Phase 2's own scope, no fake behavior (§9); Phase 2 also owns the lockout check (§11), not Phase 1 |

No path in this table produces `QUALIFIED` — a direct, intended
consequence of Phase 1 being a foundation phase, not a defect. The
formed-and-valid row above is the single most important line in this
table: it is the positive-evidence case, and it is still `NOT_QUALIFIED`.

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
- **`test_formed_valid_opening_range_still_not_qualified_without_breakout_logic`
  (required, independent review finding F1 — not satisfied by a generic
  "all other inputs" assertion; this scenario must be independently
  visible in the test suite):** constructs exactly one `OpeningRangeState`
  with `is_formed=True` and `is_valid=True` (otherwise-valid Phase 1
  inputs: eligible pair, well-formed `range_high`/`range_low`/`range_midpoint`),
  calls `OrbBreakoutStrategy().qualify(...)`, and asserts all of:
  `status == QualificationStatus.NOT_QUALIFIED`; `score == 0.0`;
  `confidence == 0.0`; `trade_intent == TradeIntent.NONE` — i.e. no trade
  qualification is produced despite the range being genuine, positive
  evidence. This is the single scenario the review doctrine calls "a
  valid, formed OpeningRangeState is evidence availability, NOT a
  breakout signal," and it must remain its own named test through every
  future revision of this file, not be re-absorbed into a catch-all.
- **Boundary tests:** `is_formed`/`is_valid` combinations at their exact
  True/False edges (four combinations); zero vs. one vs. two
  `opening_ranges` entries.
- **Negative tests:** pair outside `approved_pairs_for()`'s empty
  fallback (confirms `NOT_ELIGIBLE` with zero config, §13). The lockout
  re-qualification test moves to Phase 2's own test suite along with the
  mechanism itself (§11) — Phase 1 has no lockout behavior to test.
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
  default registry. Two files hardcode this expectation, both re-verified
  this revision (independent review finding F3 — the Plan's evidence
  citation previously named only the first): `test_regression.py`'s
  `test_default_fixture_always_rejects` (`assertEqual(len(snapshot.all_qualifications),
  5)`) and `test_engine.py`'s `test_returns_a_fully_populated_snapshot`
  (identical assertion, `StrategyEngine(make_config())` with no explicit
  registry). **Both remain true and unmodified** under this Plan's
  proposed registration answer.
- **Runtime regression:** the three Runtime tests identified during the
  ADR-036 review (`test_configuration.py`, `test_integration.py`,
  `test_phase_3c_ingestion_integration.py`) are **unaffected by Phase 1**
  — they reference `StrategyId.TREND_CONTINUATION` concretely, not
  generically, and Phase 1 adds a new member without touching that one;
  confirmed no code change required in any of the three.

Every Phase 1 implementation item has its own Phase 1 test above — none
is deferred to Phase 6. The lockout's own future test suite (first
consumption, duplicate attempt, restart-survival, corrupt/unavailable
persisted state, different pair/range unaffected, per ADR-035 §18.A item
2's own fail-closed principle) belongs to Phase 2, moved there with the
mechanism itself (§11) — not omitted, relocated.

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
| Premature `QUALIFIED` result from an incomplete strategy | Behavioral/Capital-preservation | §9's fail-closed table — every path returns `NOT_QUALIFIED` | None if this Plan's §9 design is followed exactly | Low | §9's explicit "no fake behavior" design | §15's unit tests for every §14 row |
| Malformed/missing `OpeningRangeState` | Behavioral | §10 | Handled: `()` and ambiguous-multiple both fail closed | Low | §10's explicit rules | §15 boundary tests |
| Adding a 6th `StrategyId` breaks a hardcoded test | Testing | `test_regression.py:22` (§2) | None, if not registered in `build_default_registry()` (§12) | Low (avoided by design) | §12's registration answer | §15 regression tests |
| Registry/selection effects from a 6th `StrategyId` | Architectural | `selection.py` re-confirmed generic (§2, §7) | None expected | Low | N/A — already generic | §15 regression tests |
| Runtime `allowed_strategies`/logging effects | Concurrency/state, Configuration | `profiles.py`'s self-deriving constants, `logging_sink.py`'s generic `.value` access (§8) | None expected | Low | N/A — already generic | Runtime test re-run, unmodified |
| Lockout mechanism designed/implemented prematurely | Governance/Architectural | ADR-035 §18.A item 2, resolved this revision (§11) | A future implementer adds the lockout (in-memory or persisted) to Phase 1 "since it's in the ADR," reintroducing a stateful strategy and an unreviewed persistence dependency a phase early | Low if this Plan is followed; procedural, not technical | §5/§9/§11's explicit move to Phase 2; Phase 2's own RPI Plan must carry its own persistence-architecture review before implementing it | Independent review of the eventual Phase 1 diff against this Plan (no `__init__`, no lockout check) |
| Phase leakage from Phase 2+ | Governance | §5/§6's explicit deferral list | A future implementer adds breakout/FVG/MI logic "while they're in there" | Low if this Plan is followed; the risk is procedural, not technical | §5's explicit REQUIRED/DEFERRED split; each phase's own RPI gate (`TEAM.md` §9) | Independent review of the eventual diff against this Plan |

No risk above is Critical. The two governance blockers that previously
gated this Plan (ADR-035 Acceptance; lockout persistence direction) are
resolved (§3); the residual risk is procedural (Phase 2 scope leaking
into Phase 1), not a technical or capital-preservation risk within
Phase 1's own scope.

## 18. Out-of-Scope Confirmation

Phase 1 does **not** implement, and this Plan does not describe:
breakout qualification (Phase 2), **the §6 session-lockout and its
persistence mechanism (moved to Phase 2 this revision, §5/§9/§11)**,
FVG confirmation (Phase 3), Market Intelligence/eligibility integration
(Phase 4), ORB's remaining `StrategyEngineConfig` fields or
`config_loader.py` wiring (Phase 5), production registration of
`OrbBreakoutStrategy` (no earlier than Phase 6, §12), stop-loss/take-profit
computation (out of every phase's scope, ADR-031 §3), Risk Engine
sizing, Compliance Engine gates, Runtime orchestration changes,
Bridge/execution changes, or any part of ADR-036's retirement roadmap
(dormant, per ADR-036's own Acceptance scope).

## 19. Acceptance Criteria

**Governance (both satisfied this revision):**
- ADR-035's own document `Status:` line reads **Accepted** — satisfied
  (§3).
- ADR-035 §18.A item 2 (lockout persistence) is resolved in direction
  (semantic requirement, ownership, counter-consumption, fail-closed
  principle) — satisfied (§3, §11). Its concrete storage architecture is
  a Phase 2 precondition, not a Phase 1 one, since the lockout mechanism
  itself moved to Phase 2 (§11).

**Objective, repository-verifiable gates:**
- `StrategyId.OPENING_RANGE_BREAKOUT` exists.
- `OrbBreakoutStrategy` exists, conforms to `Strategy`, is stateless (no
  `__init__` override, §9), and is constructible/callable directly (not
  necessarily registered, §12).
- `evidence.opening_ranges` is consumed without recomputation and
  without any `market_data_ingestion`/raw-bar access (verified by
  `test_architecture.py`, unmodified, still green).
- Every §14 fail-closed row is verified by a dedicated test, all
  passing.
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

No criterion above is marked PASS by this document — these are
implementation gates for whoever carries out Phase 1, not yet executed.

## 20. Rollback Strategy

Deterministic and low-risk, mirroring Phase 0's own rollback pattern:
revert the future implementation commit(s); `OrbBreakoutStrategy` and
`StrategyId.OPENING_RANGE_BREAKOUT` disappear entirely; no other file
depends on either of them (§8, §12 — not registered in production, so no
downstream consumer to unwind); the five legacy strategies and every
existing test are already confirmed untouched (§16), so rollback has
zero cascading effect outside `titan_protocol/strategy_engine/` and its
own new test file. (`orb_max_qualifications_per_range` and its
persistence store no longer exist in Phase 1's own scope, §11 — nothing
to roll back for them here.)

## 21. Engineering Checklist

- [x] Blocker A resolved: ADR-035 marked Accepted in its own document.
- [x] Blocker B resolved in direction: lockout persistence requirement,
      ownership, and counter semantics made explicit; concrete storage
      architecture deferred to Phase 2, which is also where the lockout
      mechanism itself now lives (§11).
- [x] Independent implementation-governance review completed; findings
      F1-F5 issued.
- [x] F1 resolved: explicit formed+valid fail-closed row (§14) and
      individually-named test (§15) added.
- [x] F2 resolved: §7/§11 concurrency framing corrected to distinguish
      today's caller behavior from `StrategyEngine`'s own contract;
      Phase 2's concurrency-safety requirements listed explicitly (§11).
- [x] F3 resolved: `test_engine.py` cited alongside `test_regression.py`
      (§15).
- [ ] F4 (follow-up, out of Phase 1 scope): correct stale "Amendment 2"
      docstrings in `titan_protocol/evidence_engine/{models,opening_range}.py`
      and add ADR-024's own missing Amendment 3 entry.
- [ ] F5 (Phase 2 prerequisite, not Phase 1): extend
      `test_architecture.py`'s `ALLOWED_UPSTREAM_PREFIXES` when Phase 2's
      persistence package is designed.
- [ ] `StrategyId.OPENING_RANGE_BREAKOUT` added.
- [ ] `orb_breakout.py` created with `OrbBreakoutStrategy`, matching §9
      exactly (stateless, no `__init__`).
- [ ] `test_orb_breakout_foundation.py` written covering §15's full list,
      including the F1-named test.
- [ ] Every pre-existing Strategy Engine and Runtime test re-run,
      confirmed unmodified (§15).
- [ ] `compileall` clean.
- [ ] `test_architecture.py` (Strategy Engine's own) re-run and PASS.
- [ ] `git diff --stat` confined to §8/§9's files plus the new test
      file.
- [ ] CHANGELOG entry drafted.

## 22. Final Readiness Assessment

This Plan is grounded entirely in code and documents read directly this
session, the governance-resolution revision, and the independent
implementation-governance review's re-verification pass (`ADR-035-orb-strategy.md`,
`ADR-036-orb-strategy-consolidation.md`, every relevant
`titan_protocol/strategy_engine/`, `titan_protocol/evidence_engine/`,
`titan_protocol/runtime/{profiles,validation,models,logging_sink,engine}.py`,
`deployment_windows/start.py`, `titan_protocol/risk_engine/reservation.py`,
`titan_protocol/runtime/in_flight_commands.py`,
`titan_protocol/compliance_state_store/store.py`, and
`titan_protocol/compliance_engine/position_limits.py` file, the full
Strategy Engine and relevant Runtime test directories, `CHANGELOG.md`,
`KNOWN_GAPS.md`). **Both governance preconditions are resolved** (§3),
and the independent review's two required minor revisions (F1, F2) are
applied and re-verified in this document, along with F3's completeness
correction. F4 and F5 are recorded as explicit, bounded follow-up/Phase-2
prerequisites, correctly left unapplied here since they are out of
Phase 1's own scope. No new contradiction was found during this
revision. This Plan is **content-complete and implementation-ready** —
no further governance or architectural research is anticipated to be
needed before Phase 1 implementation begins.

## 23. Validation

*(To be completed during/after Phase 1 implementation — recorded here
as the expected checklist, not yet executed.)*

- `python3 -m compileall titan_protocol/strategy_engine tests/titan_protocol/strategy_engine`:
- `python3 -m unittest discover -s tests/titan_protocol/strategy_engine`:
- `python3 -m unittest tests.titan_protocol.strategy_engine.test_architecture`:
- `python3 -m unittest discover -s tests/titan_protocol/runtime`:
- Code Reviewer sign-off:
- Test Results Analyzer sign-off:
- Software Architect sign-off (mandatory per `TEAM.md` §3 for a Strategy
  Engine change):
- Confirmation that this Plan's own independent review (§21) occurred
  *before* implementation began, not retroactively.
