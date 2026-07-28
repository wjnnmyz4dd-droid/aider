# ADR-036 — Strategy Consolidation to ORB

Status: **Accepted** (product-direction/architectural decision only —
see below for what this does and does not authorize). No implementation
accompanies this document. This Acceptance authorizes the
product-direction decision (§7) and the architectural preservation
claims (§9, §10) only. It does **not** authorize implementation now:
per CLAUDE.md §1.10, the actual strategy-registry swap this ADR
describes cannot begin until ADR-035's own remaining phases (1–6) are
themselves implemented, tested, independently reviewed, and accepted,
since ORB does not exist as a registrable `Strategy` in the repository
today (§2, §11, §13). Until then, the five current production
strategies remain registered and untouched.

Owner: Principal Software Architect.

Depends on: `ADR-026-strategy-engine.md` (Accepted, Amendment 1) — the
`Strategy` interface, `StrategyRegistry`, and selection cascade this
decision operates within, unchanged. `ADR-035-orb-strategy.md` (Accepted)
— ORB's own design; this ADR does not redesign it. `ADR-024-evidence-engine.md`
(Accepted, Amendment 1, Phase 0 implemented) — unaffected, read-only
context.

**Amendment 1 (2026-07-28, Proposed — pending a separate acceptance
pass, history preserved below, not backdated): operational-readiness
precondition for legacy retirement.** Drafted this session in response
to a dedicated governance-resolution pass
(`docs/plans/adr-036-legacy-strategy-retirement.md`'s own prior Research
pass, commit `b74d505`, first surfaced this as an open question rather
than resolving it) that traced the real production construction path
(`deployment_windows/start.py` → `build_default_registry()` →
`StrategyEngine`) end to end and found a gap this ADR's existing text
does not close.

**The gap, precisely:** §13's governance gate requires ORB to be
"implemented, tested, independently reviewed, and accepted through its
required phases" before legacy retirement begins — a code-completeness
bar, verified satisfied as of this Amendment (ADR-035 Phases 0–7 are all
independently accepted). It says nothing about whether ORB is
*operationally reachable* once retirement completes. Two independent,
pre-existing configuration gates keep ORB dormant today regardless of
its code-completeness: **Gate A** — `OPENING_RANGE_BREAKOUT` is absent
from `DEFAULT_APPROVED_PAIRS_BY_STRATEGY` (a `StrategyEngineConfig`
field, squarely in this ADR's own scope, §8) — and **Gate B** —
`EvidenceEngineConfig.opening_range_anchors` defaults to `()` (a field
this ADR's own §9 Non-Goals places outside its scope: "Modify Evidence
Engine... untouched, read-only inputs").

Tracing §15's own Implementation Roadmap step 4 ("Configuration cleanup:
remove the five strategies' dedicated `StrategyEngineConfig` fields;
retain/introduce only ORB's own") shows Gate A is *mechanically forced
open* as an unavoidable side effect of doing step 4 correctly — ORB
must receive its own `approved_pairs_by_strategy` entry, or nothing
would be eligible for any pair at all, which `titan_protocol.runtime.validation.validate_profile()`
(called, and fail-closed, at every `deployment_windows/start.py` startup
— confirmed by direct source read this pass) would already catch and
refuse to boot on. **Gate B has no equivalent forcing mechanism and no
existing check anywhere.** `validate_profile()` never inspects
`opening_range_anchors` (confirmed by a full, direct read of
`titan_protocol/runtime/validation.py` this pass — no Evidence Engine
field of any kind is referenced there). No Roadmap step names it either,
because `opening_range_anchors` lives in Evidence Engine's own config,
which §8/§9 place outside this ADR's scope by design. The consequence:
**a future Plan could execute every one of this ADR's own Roadmap steps
exactly as written — delete the five files, register ORB alone, migrate
`StrategyEngineConfig` correctly — and the deployment would boot
successfully, pass every existing test and architecture check, and yet
have zero live production strategies, indefinitely, because ORB would
never form an opening range for any pair.** `StrategyEngine.evaluate()`
already returns a well-defined, exception-free `rejected=True` snapshot
in exactly this case (confirmed by direct read of `engine.py`/`selection.py`
this pass: an empty `QUALIFIED` candidate set is `select_winning_strategy()`'s
ordinary "nothing qualified" return path, indistinguishable in code from
a single pair having no signal on a single ordinary cycle); Runtime
reports `CycleOutcome.NO_STRATEGY` for every pair, every cycle,
indefinitely, and no metric, log level, health check, or watchdog signal
anywhere in the repository distinguishes a sustained, total,
every-pair-every-cycle `NO_STRATEGY` rate from routine, expected,
occasional rejections (confirmed by a repository-wide search this pass:
`StrategyEngineMetrics.record_rejection()` is a bare, unthresholded
counter; no `no_strategy`/`NO_STRATEGY`-aware check exists in
`deployment_windows/health_check.py` or `titan_protocol/reliability/`).
This is a genuine, silent capital-preservation gap this ADR's own
Acceptance Criteria (§16) did not contemplate — its risk table (§14)
lists no equivalent entry.

**Authorization (the operative contract this Amendment adds):** §7's
already-Accepted full-retirement decision is **not reopened** — Titan
still will retire all five legacy strategies and register ORB as the
sole production strategy. What changes is the definition of "complete"
for §13's Removal/Completion phase and §15's Roadmap step 8
(Validation): **neither may be considered complete, and the five legacy
strategy files/registrations/config fields may not be finally removed
from the production path, until all of the following hold:**

1. `OPENING_RANGE_BREAKOUT` has at least one entry in
   `approved_pairs_by_strategy` (Gate A lifted) — already an unavoidable
   consequence of Roadmap step 4 done correctly; restated here only so
   the completion criterion is explicit rather than incidental.
2. At least one `opening_range_anchors` entry is configured, covering at
   least one of ORB's approved pairs (Gate B lifted). This is a
   deployment **configuration-value** change (populating a knob Phase 0
   already built for exactly this purpose) — it is not a code, model, or
   logic change to Evidence Engine, and does not conflict with §9's
   Non-Goal against modifying Evidence Engine's own implementation;
   §9 is clarified, not reopened, by this distinction.
3. Deployment startup validation fails closed if either condition above
   is not met whenever ORB is the registry's sole (or majority) member —
   an extension of the existing, already-fail-closed
   `validate_profile()`/`start.py` startup-validation pattern (§SS11),
   not a new validation mechanism. The exact mechanism (a new
   `ConfigValidationIssue` check, a separate startup assertion, or
   another equivalent measurable condition) is deliberately left to a
   future Plan — this Amendment requires the invariant, not its
   implementation.

**Explicitly not required by this Amendment** (rejected as stronger than
the evidence supports): ORB does not need to have been observed
qualifying a real trade in production or paper-trading conditions before
retirement completes. That would be a *sufficient* condition, not the
*necessary* one this Amendment identifies — configuration-completeness
plus a fail-closed startup check is the narrowest invariant that
prevents the silent zero-live-strategy outcome, and this Amendment does
not invent a stronger requirement than the reproduced failure mode
demands.

**Explicitly deferred to future Research/Plan work, not decided here:**
the exact pair(s) to grant ORB eligibility for; the exact opening-range
anchor(s), including their hour/minute values (the separate,
still-unauthorized Phase 5 anchor hour/minute validation residual risk
is a distinct question about anchor-time validation *correctness*, not
about anchor *presence*, and remains untouched by this Amendment); the
exact implementation of the extended startup check; and the rollout
sequencing (activate-then-retire, atomic transition, or another ordering)
by which conditions 1–3 above are satisfied without an intermediate
zero-live-strategy production interval — a future Plan's responsibility,
constrained by this Amendment's invariant, not resolved by it.

This Amendment is **Proposed**, not Accepted. Per this Amendment's own
inclusion in the governance-resolution pass that drafted it, a separate,
explicit acceptance pass — independently re-verifying this Amendment's
own reasoning against repository evidence, following the same pattern
already used for ADR-035 Amendment 1's independent acceptance review —
is required before ADR-036 Plan Finalization may rely on it as Accepted
governance.

---

## 1. Executive Summary

Titan's Strategy Engine today registers five production strategies
(`LIQUIDITY_SWEEP_MSS`, `BOS_FVG`, `TREND_CONTINUATION`,
`SESSION_BREAKOUT`, `RANGE_REVERSAL`) through one factory function,
`build_default_registry()`. This ADR documents the product-direction
decision to retire all five and make the Opening Range Breakout (ORB)
strategy (ADR-035, Accepted) Titan's sole production strategy once ORB
itself is implemented. The architecture is unchanged: the `Strategy`
interface, `StrategyRegistry`, and the existing selection cascade
(`selection.py`) are generic over however many strategies are registered
and require no modification to hold one instead of five. Every other
pipeline stage (Evidence Engine, Risk Engine, Compliance Engine,
Execution, Scanner, Market Intelligence) is untouched, referencing no
specific `StrategyId` by name (§4, §10). **Runtime is a partial
exception**: it genuinely consumes the `StrategyId` type
(`TradingProfile.allowed_strategies`, `RuntimeAuditRecord.selected_strategy`)
and imports Strategy Engine's `DEFAULT_APPROVED_PAIRS_BY_STRATEGY`
directly — but this consumption is self-deriving from `StrategyId`'s own
membership (`tuple(StrategyId)`), never a hardcoded list of the five
legacy names, so it requires no code change at retirement time (§2, §10).
This document authorizes the *decision*; the retirement itself is future
work gated on ADR-035 Phases 1–6 (§13, §15).

## 2. Repository Investigation Summary

Verified directly against the current repository this session:

- **Five strategies exist today**, each a `Strategy` subclass in its own
  file under `titan_protocol/strategy_engine/strategies/`:
  `liquidity_sweep_mss.py`, `bos_fvg.py`, `trend_continuation.py`,
  `session_breakout.py`, `range_reversal.py`.
- **`StrategyId` (`titan_protocol/strategy_engine/models.py:23-28`)** is a
  5-member closed enum: `LIQUIDITY_SWEEP_MSS`, `BOS_FVG`,
  `TREND_CONTINUATION`, `SESSION_BREAKOUT`, `RANGE_REVERSAL`. No
  `OPENING_RANGE_BREAKOUT` member exists.
- **Registration is one explicit factory**,
  `build_default_registry()` (`titan_protocol/strategy_engine/strategies/__init__.py`),
  which calls `StrategyRegistry.register()` once per strategy, in a fixed
  order, unconditionally.
- **`StrategyEngine.__init__`** (`engine.py:36-46`) defaults to
  `build_default_registry()` whenever no explicit `registry` argument is
  passed — the *only* registry-construction path either production
  entrypoint uses.
- **Both production entrypoints use this default**:
  `deployment_windows/start.py:1196` (`StrategyEngine(strategy_config)`)
  and `deployment_windows/install.py:303`
  (`StrategyEngine(StrategyEngineConfig())`) — neither passes an
  explicit `registry`. This is the single point that determines which
  strategies actually run in production today, and the single point a
  future retirement phase would change.
- **Selection is generic**: `selection.py::select_winning_strategy()`
  operates on `Sequence[QualificationResult]` and `Optional[WinningStrategy]`
  — nothing in its 6-step cascade (score → confidence →
  historical-ranking-placeholder → portfolio-concentration-placeholder →
  liquidity → news) references a specific `StrategyId` or assumes a
  particular count. Reducing the registry to one member changes nothing
  about how this function executes.
- **`ORB does not exist as an implemented `Strategy` today** — confirmed
  by a repository-wide search: zero occurrences of
  `OPENING_RANGE_BREAKOUT`, `OrbBreakoutStrategy`, or any `orb_`-prefixed
  identifier anywhere under `titan_protocol/`. ADR-035 Phase 0 (Evidence
  Engine's `OpeningRangeState`/`opening_ranges`) is the only phase of
  ADR-035 implemented to date; Phases 1–6 (the ORB `Strategy` itself,
  its qualification/scoring/config/registration) remain unimplemented.
- **No *concrete* coupling to any of the five legacy strategies outside
  Strategy Engine, but Runtime is a genuine *generic* consumer of
  `StrategyId` (a distinction this document draws precisely, per its own
  review)**: a repository-wide search for every `StrategyId` value and
  every strategy class name, excluding `titan_protocol/strategy_engine/`
  itself, found:
  - `titan_protocol/research_engine/models.py`'s generic
    `strategy_id: Optional[StrategyId]` field, and an unrelated
    same-named `AttributionDimension.BOS_FVG` enum member in
    `research_engine/attribution.py` (a coincidental name, not an import
    of `strategy_engine.StrategyId.BOS_FVG`) — both confirmed harmless,
    as previously documented.
  - **`titan_protocol/runtime/models.py`** holds two real `StrategyId`
    fields: `TradingProfile.allowed_strategies: Tuple[StrategyId, ...]`
    (line 64) and `RuntimeAuditRecord.selected_strategy: Optional[StrategyId]`
    (line 155). `titan_protocol/runtime/engine.py` threads
    `selected_strategy=strategy.winning_strategy.strategy_id` into
    `RuntimeAuditRecord` at five call sites in the live cycle — an
    active, per-cycle production code path.
  - **`titan_protocol/runtime/profiles.py`** imports
    `DEFAULT_APPROVED_PAIRS_BY_STRATEGY` directly from Strategy Engine's
    own `config.py` (line 15), and derives `_ALL_STRATEGIES: Tuple[StrategyId, ...]
    = tuple(StrategyId)` (line 34) and `_TRADEABLE_PAIR_UNIVERSE` from it.
    Every named production profile factory (`make_london_conservative_profile()`,
    etc.) uses these two derived defaults; **none hardcodes an explicit
    subset of the five legacy `StrategyId` values** — confirmed by
    reading every factory in the file.
  - Risk Engine, Compliance Engine, Bridge, and Execution hold no
    `StrategyId` reference at all, generic or concrete (repository-wide
    grep, zero hits).

  **Conclusion**: Runtime is a genuine downstream consumer of `StrategyId`
  and selected-strategy metadata, and `runtime/profiles.py` consumes
  Strategy Engine's approved-pair configuration directly. Current
  production Runtime behavior does not hard-code the five legacy
  `StrategyId`s individually — its strategy membership is self-derived
  from `StrategyId`'s own enum membership and `StrategyEngineConfig`'s
  own contents. This dependency must therefore be included in retirement
  verification (§9, §10, §14), but it does not prevent ORB-only
  production composition: once `StrategyId` and
  `DEFAULT_APPROVED_PAIRS_BY_STRATEGY` shrink to ORB alone,
  `runtime/profiles.py`'s derived constants shrink automatically, with
  zero code change required in that file.
- **Test coupling to the count and identity of the five exists, in two
  packages, not one**:
  - `tests/titan_protocol/strategy_engine/test_regression.py` asserts
    `len(snapshot.all_qualifications) == 5` and asserts a specific
    strategy (`TREND_CONTINUATION`) wins a specific fixture; per-strategy
    files (`test_qualification.py`, `test_trade_intent.py`) exist per the
    same five; `test_selection.py` exercises the cascade using some
    subset of the five's `StrategyId` values.
  - **`tests/titan_protocol/runtime/test_configuration.py:78`**
    constructs a `TradingProfile` with `allowed_strategies=(StrategyId.TREND_CONTINUATION,)`
    to test the "pair ineligible for every allowed strategy" validation
    path — a concrete, named dependency, confirmed by direct read.
  - **`tests/titan_protocol/runtime/test_integration.py:77`** and
    **`tests/titan_protocol/runtime/test_phase_3c_ingestion_integration.py:168`**
    both run the real, unstubbed five-strategy `StrategyEngine` through
    a full `RuntimeOrchestrator` cycle against a trending-bars fixture
    and assert `record.selected_strategy == StrategyId.TREND_CONTINUATION`
    — genuine end-to-end integration tests whose specific assertion
    depends on today's five-strategy competition, confirmed by direct
    read of both files.
  - By contrast, **`tests/titan_protocol/runtime/test_trading_profiles.py:78`**
    (`assertEqual(set(profile.allowed_strategies), frozenset(StrategyId), ...)`)
    is self-deriving and requires no future change — confirmed a **false
    positive** for retirement-coupling purposes, listed here only to
    distinguish it from the three genuinely concrete references above.
- **Configuration is one dataclass, not one file per strategy**:
  `StrategyEngineConfig` (`config.py`) holds
  `DEFAULT_APPROVED_PAIRS_BY_STRATEGY` (one 5-entry tuple, one entry per
  `StrategyId`) plus ten per-strategy threshold fields declared inline
  (e.g. `liquidity_sweep_min_liquidity_score`, `bos_fvg_min_structure_score`).

## 3. Current Architecture

Verified, not assumed, this session:

| Stage | Ownership / responsibility | Verified unaffected by this decision |
|---|---|---|
| Scanner (reference-only, `phantom_pipeline/`) | Not a running authority per ADR-001; irrelevant to this decision | Yes — not part of the live pipeline |
| Evidence Engine | Sole interpreter of market data; produces `EvidenceSnapshot` (incl. `opening_ranges` since Phase 0) | Yes — consumed generically by every strategy, never strategy-specific |
| Market Intelligence | Session/news/liquidity facts | Yes — consumed generically |
| Strategy Engine | Qualifies candidates via registered `Strategy` instances; selects one winner via `selection.py`'s cascade | **This is the component whose production strategy inventory changes** |
| Risk Engine | Position sizing from `StrategySnapshot`/`QualificationResult` (`confidence`, `TradeIntent`) — never branches on `StrategyId` (confirmed, `position_sizing.py`) | Yes |
| Compliance Engine | Daily-loss/drawdown/position-limit gates, strategy-agnostic | Yes |
| Execution / `runtime/bridge_handoff.py` | Builds `TradeCommand` from `StrategySnapshot.trade_intent`, generic | Yes |
| Bridge | Wire-level command/report exchange, strategy-agnostic | Yes |
| Runtime | Orchestrates the cycle; holds `TradingProfile.allowed_strategies` and `RuntimeAuditRecord.selected_strategy` (`StrategyId`-typed) and imports `DEFAULT_APPROVED_PAIRS_BY_STRATEGY` from Strategy Engine (`profiles.py`) | Yes for authority/ownership — Runtime decides nothing about strategies, it only records/whitelists generically; **no code change required** at retirement since both fields derive from `StrategyId`'s own membership (`tuple(StrategyId)`), never a hardcoded 5-name list (§2) |

## 4. Current Strategy Inventory

| Strategy | Purpose | Status | Registration | Configuration | Tests | Docs | Dependencies |
|---|---|---|---|---|---|---|---|
| `LIQUIDITY_SWEEP_MSS` | Fade a stop-hunt sweep once a CHOCH confirms the reversal | **Production** | `build_default_registry()` | `liquidity_sweep_min_liquidity_score`, `liquidity_sweep_min_confidence`, `approved_pairs_by_strategy` entry | `test_qualification.py`, `test_trade_intent.py`, `test_selection.py`, `test_regression.py`, `test_engine.py` (shared) | ADR-026 §1 (Accepted) | `evidence_engine.models`, `market_intelligence.models`, sibling `config`/`eligibility`/`models`/`_helpers`/`base` only |
| `BOS_FVG` | Enter a confirmed structural break with an unfilled same-direction FVG | **Production** | `build_default_registry()` | `bos_fvg_min_structure_score`, `bos_fvg_min_confidence`, `approved_pairs_by_strategy` entry | same shared suite | ADR-026 §1 (Accepted) | same shape |
| `TREND_CONTINUATION` | Join an already-established directional trend on a confirming pullback | **Production** | `build_default_registry()` | trend-continuation threshold field(s), `approved_pairs_by_strategy` entry | same shared suite | ADR-026 §1 (Accepted) | same shape |
| `SESSION_BREAKOUT` | Session-wide volatility-expansion breakout, session-gated | **Production** | `build_default_registry()` | session-breakout threshold field(s), `approved_pairs_by_strategy` entry | same shared suite | ADR-026 §1 (Accepted) | same shape |
| `RANGE_REVERSAL` | Bounce/rejection off a nearby confluence zone in a non-trending market | **Production** | `build_default_registry()` | range-reversal threshold field(s), `approved_pairs_by_strategy` entry | same shared suite | ADR-026 §1 (Accepted) | same shape |
| `OPENING_RANGE_BREAKOUT` (ORB) | Trade the initial breakout of a fixed-width opening range | **Designed, partially implemented (Evidence Engine Phase 0 only), not yet a registrable `Strategy`** | Not yet registered anywhere | Not yet in `StrategyEngineConfig` | Evidence Engine's own `test_opening_range.py` only; no Strategy Engine test exists yet | ADR-035 (Accepted) | Depends on `EvidenceSnapshot.opening_ranges` (implemented), `MarketIntelligenceSnapshot` (existing) |

No strategy in the repository is classified Experimental, Deprecated,
Unused, or Unknown — all five legacy strategies are registered,
imported, and exercised by the shared test suite; none is dead code.

## 5. Problem Statement

Titan's Strategy Engine currently maintains five independent, actively
tested production strategies, each with its own qualification logic,
configuration thresholds, and test coverage, competing in a single
selection cascade. Per this ADR's own commissioning (explicit product
direction, not a repository-observed defect): Titan is to specialize on
ORB as an institutional-focus product rather than continue operating a
general multi-strategy platform. No defect, bug, or architectural
violation in the five existing strategies motivates this change — the
driver is a product-direction decision to reduce Titan's production
surface to one, well-understood, specialized strategy.

## 6. Architectural Drivers

Repository-supported drivers only:

- **Reduced configuration surface**: `StrategyEngineConfig` currently
  carries a 5-entry `approved_pairs_by_strategy` tuple plus ten
  per-strategy threshold fields (§2) — every one of which is an operator
  tuning surface and a startup-validation surface. Consolidating to one
  strategy reduces this to one `approved_pairs` list and ORB's own
  fields (ADR-035 §13).
- **Reduced testing burden**: five strategies each carry dedicated
  qualification and trade-intent test coverage, plus a selection cascade
  that must be exercised across every pairwise tie-break combination
  (`test_selection.py`) — repository-verified test surface that shrinks
  to one strategy's own coverage once retirement completes.
- **Single product focus / institutional ORB specialization**: explicit
  product direction stated in this ADR's own commissioning — not a
  repository-observed fact, disclosed as such.

## 7. Decision

Titan will retire all five current production strategies
(`LIQUIDITY_SWEEP_MSS`, `BOS_FVG`, `TREND_CONTINUATION`,
`SESSION_BREAKOUT`, `RANGE_REVERSAL`) and register ORB
(`OPENING_RANGE_BREAKOUT`) as the sole production strategy, once ORB
itself is implemented and validated per ADR-035's own remaining phases.
The `Strategy` interface, `StrategyRegistry`, and `selection.py`'s
cascade are preserved unmodified — this decision changes only *which*
`Strategy` instances `build_default_registry()` (or its future
equivalent) registers, not how registration, qualification, or selection
work.

## 8. Scope

In scope: the production strategy inventory (`StrategyId` membership,
`build_default_registry()`'s contents, `StrategyEngineConfig`'s
per-strategy fields, the five strategies' own files, their dedicated
tests, and their references in ADR-026/ADR-035's documentation). Nothing
else.

## 9. Non-Goals

This ADR explicitly does **not**:

- Modify Evidence Engine, `EvidenceSnapshot`, or `OpeningRangeState`
  (ADR-024, ADR-035 Phase 0 — untouched, read-only inputs).
- Modify Risk Engine, Compliance Engine, Runtime, Bridge, or Execution.
  Risk Engine, Compliance Engine, and Bridge hold no `StrategyId`
  reference at all (§2, verified). Runtime does hold two generic,
  self-deriving `StrategyId`-typed fields (`TradingProfile.allowed_strategies`,
  `RuntimeAuditRecord.selected_strategy`) and imports Strategy Engine's
  `DEFAULT_APPROVED_PAIRS_BY_STRATEGY` — but no Runtime *file* changes at
  retirement time, since both constants derive from `StrategyId`'s own
  membership rather than naming the five legacy values individually (§2).
- Modify Scanner — reference-only, not a running authority (ADR-001).
- Modify Market Intelligence.
- Modify the selection/routing architecture (`selection.py`'s cascade)
  — it is already strategy-count-agnostic (§2).
- Remove the Strategy Engine package or the `Strategy` interface.
- Replace or redesign the `Strategy` abstraction.
- Introduce any ORB-specific coupling into a package outside
  `titan_protocol/strategy_engine/` — ORB integrates through the exact
  same generic surface (`Strategy.qualify()`, `StrategyDefinition`,
  `QualificationResult`) every existing strategy already uses (ADR-035
  §11/§12).

## 10. Architecture Preservation

Explicitly preserved, unmodified by this decision:

- Evidence Engine, `EvidenceSnapshot`, `OpeningRangeState` (ADR-024,
  ADR-035 Phase 0).
- Risk Engine, Compliance Engine, Execution (Runtime's `bridge_handoff.py`).
- The `Strategy` interface (`strategy_engine/strategies/base.py`) and
  `StrategyRegistry` (`registry.py`) — both already generic over any
  number of registered strategies.
- The selection cascade (`selection.py`) — verified strategy-count- and
  strategy-identity-agnostic (§2).
- Scanner (reference-only).
- Research & Learning Engine (`research_engine`) — verified to hold only
  a generic `Optional[StrategyId]` field, never a hardcoded reference to
  one of the five legacy values; continues to function unmodified
  regardless of `StrategyId`'s membership.
- **Runtime** — verified (§2) to hold two `StrategyId`-typed fields
  (`TradingProfile.allowed_strategies`, `RuntimeAuditRecord.selected_strategy`)
  and one direct import of Strategy Engine's `DEFAULT_APPROVED_PAIRS_BY_STRATEGY`
  (`runtime/profiles.py`). Unlike the other components in this list,
  Runtime's dependency is not merely a passive, unused type reference —
  it is exercised on every live cycle (`runtime/engine.py`, five call
  sites). It is nonetheless preserved unmodified by this ADR: every
  value Runtime derives from `StrategyId`/`DEFAULT_APPROVED_PAIRS_BY_STRATEGY`
  is computed generically (`tuple(StrategyId)` and a set-comprehension
  over the config constant, `profiles.py:34,42-44`), never hardcoded to
  the five legacy names, so no line of Runtime code needs to change when
  the production strategy inventory changes.

No component listed above is redesigned, reinterpreted, or extended by
this ADR. §12.B below states the governance rule this dependency
implies for `StrategyId`'s own future membership.

## 11. Retired Strategy Inventory

For each of the five, retirement means: removing its file from
`titan_protocol/strategy_engine/strategies/`, removing its registration
line from `build_default_registry()`, removing its dedicated
`StrategyEngineConfig` fields, and removing/rewriting its dedicated test
coverage. Whether its `StrategyId` member is also removed is a separate
decision, governed by §12.B, not an automatic part of retirement. This
is future implementation work (§15), not performed by this ADR.

| Strategy | Location | Registration | Configuration | Tests | Docs | Removal impact | Dependencies | Migration considerations | Evidence |
|---|---|---|---|---|---|---|---|---|---|
| `LIQUIDITY_SWEEP_MSS` | `strategies/liquidity_sweep_mss.py` | One line in `build_default_registry()` | 2 threshold fields + 1 `approved_pairs_by_strategy` entry | Shared per-strategy test files (§4) | ADR-026 §1 | None outside Strategy Engine (§2) — no other package references it | Only `evidence_engine`/`market_intelligence` public models + sibling Strategy Engine modules | `test_regression.py`'s hardcoded `len(...) == 5` and its `TREND_CONTINUATION`-wins fixture must be rewritten for a 1-strategy registry | §2, §4 |
| `BOS_FVG` | `strategies/bos_fvg.py` | Same | 2 threshold fields + 1 entry | Same | ADR-026 §1 | Same | Same | Same | §2, §4 |
| `TREND_CONTINUATION` | `strategies/trend_continuation.py` | Same | Threshold field(s) + 1 entry | Same | ADR-026 §1 | Same | Same | `test_regression.py`'s specific winning-strategy assertion currently depends on this one by name — must be replaced with an ORB-appropriate fixture | §2, §4 |
| `SESSION_BREAKOUT` | `strategies/session_breakout.py` | Same | Threshold field(s) + 1 entry | Same | ADR-026 §1 | Same | Same | ADR-035 §0 itself notes `SessionBreakoutStrategy` is ORB's "closest existing analog" — its retirement removes that analog, not ORB's own logic (ORB does not depend on this file) | §2, §4, ADR-035 §0 |
| `RANGE_REVERSAL` | `strategies/range_reversal.py` | Same | Threshold field(s) + 1 entry | Same | ADR-026 §1 | Same | Same | None beyond the shared test-suite update | §2, §4 |

No strategy depends on another (§2) — retiring any subset, or all five,
carries no cross-strategy ripple effect.

**Retirement surface extends beyond `titan_protocol/strategy_engine/`'s
own tests** — verified this revision, three files under
`tests/titan_protocol/runtime/` concretely reference
`StrategyId.TREND_CONTINUATION` and must be revisited in the same future
removal phase:

| File | Reference | Classification |
|---|---|---|
| `test_configuration.py:78` | `allowed_strategies=(StrategyId.TREND_CONTINUATION,)`, testing the "pair ineligible for every allowed strategy" validation path | Migration required — needs an ORB-appropriate `StrategyId` once retirement completes |
| `test_integration.py:77` | `assertEqual(record.selected_strategy, StrategyId.TREND_CONTINUATION)` after a real, unstubbed five-strategy `RuntimeOrchestrator` cycle | Migration required — fixture/assertion depend on today's five-strategy competition |
| `test_phase_3c_ingestion_integration.py:168` | Same pattern as above | Migration required, same reason |
| `test_trading_profiles.py:78` | `assertEqual(set(profile.allowed_strategies), frozenset(StrategyId), ...)` | No change required — self-deriving, confirmed a false positive for retirement-coupling purposes |

None of these four files is modified by this ADR (§8 scope, this
revision task's own constraints) — they are documented here as
retirement surface for the future removal phase (§13, §15).

## 12. ORB Strategy Designation and StrategyId Policy

### 12.A ORB designation

Upon completion of ADR-035's remaining phases (§13), ORB
(`StrategyId.OPENING_RANGE_BREAKOUT`) is designated:

- **Titan's sole production strategy** — the only member of
  `StrategyId` and the only `Strategy` registered by the production
  registry factory.
- **The default strategy** — `StrategyEngine.__init__`'s
  default-registry path (the one both production entrypoints already
  use unmodified, §2) resolves to ORB alone once the registry factory is
  updated.
- **The only registered production strategy** — no other strategy is
  registered by default.

This designation does not foreclose future strategies: `StrategyId` is
an `Enum` and `StrategyRegistry` imposes no cardinality limit (§2,
verified — `register()`'s only constraint is no duplicate `StrategyId`).
A future strategy could be added the same way any of the current five
was, through its own accepted ADR and RPI Plan — this ADR commits only
to today's production inventory being ORB alone, not to a permanent
one-strategy ceiling.

### 12.B StrategyId retention policy

**Production retirement and `StrategyId` enum deletion are separate
decisions.** Making ORB the only registered production strategy does
not, by itself, authorize deleting `LIQUIDITY_SWEEP_MSS`, `BOS_FVG`,
`TREND_CONTINUATION`, `SESSION_BREAKOUT`, or `RANGE_REVERSAL` from the
`StrategyId` enum. This is a governance rule this ADR establishes
explicitly, grounded in repository evidence, not an assumption:

- **Selection-cascade testability**: `selection.py::select_winning_strategy()`'s
  6-step cascade (§2) is exercised in `tests/titan_protocol/strategy_engine/test_selection.py`
  by constructing multiple `QualificationResult`s with *different*
  `StrategyId` values to simulate two-or-more strategies competing for
  the same pair (e.g. `StrategyId.TREND_CONTINUATION` vs.
  `StrategyId.SESSION_BREAKOUT` at tied scores). With exactly one
  `StrategyId` member in existence, this kind of fixture cannot be
  constructed at all — a single registered strategy can produce at most
  one `QualificationResult` per cycle (§5 of the Independent Acceptance
  Review), so steps 2–6 of the cascade would have no realistic
  multi-candidate scenario to test against. Retaining spare `StrategyId`
  members (even unbacked by a production `Strategy` class) preserves the
  ability to exercise this logic meaningfully.
- **Historical log interpretability**: `runtime/logging_sink.py:47`
  serializes `record.selected_strategy.value` into operational JSON logs
  on every cycle. Deleting an enum member does not corrupt or require
  rewriting historical log files (they are plain text, never re-parsed
  into a live `StrategyId` by any component in this repository —
  confirmed by search), but retaining the identifier keeps historical
  logs interpretable against the same vocabulary a maintainer might
  still consult `StrategyId` for.
- **Low-risk rollback**: §13's rollback strategy is simplest if
  `StrategyId` and the five strategy files are reverted together as one
  unit; retaining the identifiers does not itself block or complicate
  this, but premature deletion of just the enum (while, say, deferring
  file deletion) would create an inconsistent intermediate state this
  ADR does not authorize.

**This is not a mandate to retain the four retired identifiers
forever.** It is a governance rule: *any future decision to delete a
retired `StrategyId` member requires its own evidence* that historical
log interpretability is no longer a concern and that selection-cascade
test coverage remains adequate without it (e.g., via synthetic
test-only identifiers, or an accepted rewrite of `test_selection.py`'s
own approach) — that evidence does not exist today and this ADR does
not attempt to manufacture it. Production retirement (§7, §11, §13) and
`StrategyId` vocabulary deletion are, from this point forward, two
separate decisions, each requiring its own evidence.

## 13. Migration Strategy

> **Governance gate, restated for visibility**: legacy strategy
> retirement (§7, §11, §13, §15) **must not begin** until the ORB
> strategy required by ADR-035 is implemented, tested, independently
> reviewed, and accepted through its required phases (ADR-035 §17
> Phases 1–6). ADR-035 Phase 0 (the Evidence Engine amendment,
> `OpeningRangeState`/`opening_ranges`) is implemented today — Phases
> 1–6, which define the ORB `Strategy` itself, are not (§2, verified
> this revision by repository-wide search: zero occurrences of
> `OPENING_RANGE_BREAKOUT`, `OrbBreakoutStrategy`, or any `orb_`-prefixed
> identifier anywhere under `titan_protocol/`). Phase 0 alone does not
> satisfy this gate.

- **Current repository**: five production strategies registered;
  ADR-035 Phase 0 (Evidence Engine) implemented; ADR-035 Phases 1–6 (the
  ORB `Strategy` itself) not yet implemented.
- **Precondition (not this ADR's own work)**: ADR-035 Phases 1–6 must
  each be implemented and pass their own phase's tests, per ADR-035 §17's
  own roadmap and this project's RPI governance (`TEAM.md` §9) — ORB
  must exist as a working, tested `Strategy` before any retirement step
  below begins.
- **Transition**: once ORB is implemented and its own Phase 6
  (full-suite validation, ADR-035 §17) is complete, a dedicated future
  RPI Plan removes the five legacy strategies' files, `StrategyId`
  members, registry entries, and config fields, and registers ORB in
  their place inside `build_default_registry()` (or its renamed
  successor).
- **Removal phase**: delete the five strategy files, their
  `build_default_registry()` lines, and their `StrategyEngineConfig`
  fields; rewrite the shared Strategy Engine tests (`test_regression.py`,
  `test_selection.py` — see §12.B on why `test_selection.py`'s
  multi-`StrategyId` fixtures need deliberate handling, not blind
  deletion) and the three Runtime tests identified in §11
  (`test_configuration.py`, `test_integration.py`,
  `test_phase_3c_ingestion_integration.py`) to reflect a single-strategy
  registry. Whether any `StrategyId` member is deleted at all is a
  separate decision, governed by §12.B, not an automatic consequence of
  this phase.
- **Validation phase**: full Strategy Engine suite green against the new
  one-strategy registry; `git diff --stat` confined to
  `titan_protocol/strategy_engine/` and its tests, plus ADR-026's own
  documentation update recording the inventory change.
- **Completion phase**: `StrategyId` contains exactly one member;
  `build_default_registry()` registers exactly one `Strategy`; both
  production entrypoints (`start.py`, `install.py`) continue to
  construct `StrategyEngine` exactly as they do today, with zero code
  change required in either file (§2 — they already take no strategy
  list argument).
- **Rollback strategy**: deterministic — reverting the future removal
  commit(s) restores all five files, `StrategyId` members, and registry
  entries exactly as they exist today; no other package holds a
  reference to the removed `StrategyId` values (§2), so rollback has no
  cascading effect outside Strategy Engine and its own tests.

## 14. Risks

| Risk | Repository evidence | Assessment |
|---|---|---|
| Test regression | `test_regression.py` hardcodes `len(snapshot.all_qualifications) == 5` and a `TREND_CONTINUATION`-wins fixture; `test_selection.py` exercises multi-strategy tie-breaks | Both must be rewritten for a 1-strategy registry as part of the future removal phase — a known, bounded update, not a surprise |
| Configuration drift | `StrategyEngineConfig` carries 5 per-strategy threshold-field groups plus a 5-entry `approved_pairs_by_strategy` tuple | Retirement must remove all five groups together, not partially — a partial removal would leave orphaned config fields with no consuming strategy |
| Documentation drift | ADR-026 §1 documents the five as Strategy Engine's "initial production set"; ADR-035 §0 explicitly frames ORB as additive to "five registered strategies today" | Both documents' strategy-count language becomes stale the moment retirement completes and must be updated in the same change |
| Registration inconsistency | `build_default_registry()` is the single production registration point (§2) | Low risk — one function, one place to change; no scattered registration calls exist anywhere else in the repository |
| Orphaned tests | Per-strategy files (`test_qualification.py`, `test_trade_intent.py`) contain cases for all five | Must be pruned to ORB-only cases in the same removal phase, not left as dead, always-skipped, or failing tests |
| Dead code | None of the five strategies is currently unused (§4) — retirement, once executed, must delete rather than merely stop-registering, to avoid leaving unreachable code | Addressed explicitly by the Removal phase (§13) specifying file deletion, not just registry-line removal |
| Future extensibility | `StrategyRegistry`/`StrategyId` impose no cardinality constraint (§2, §12) | No risk — the architecture already supports adding a strategy back later without modification |
| Repository consistency | Verified today: no *concrete* reference to any legacy `StrategyId` outside Strategy Engine, but Runtime holds two genuine, self-deriving `StrategyId`-typed fields plus a direct import of `DEFAULT_APPROVED_PAIRS_BY_STRATEGY` (§2, §10) | Runtime requires no code change at retirement (both dependencies self-derive), but must be included in verification, not assumed absent |
| Runtime test regression | Three files under `tests/titan_protocol/runtime/` (`test_configuration.py:78`, `test_integration.py:77`, `test_phase_3c_ingestion_integration.py:168`) concretely assert `StrategyId.TREND_CONTINUATION` (§11) | Must be rewritten in the same removal phase as Strategy Engine's own tests — a previously undocumented but bounded, foreseeable addition to the known test-migration surface |
| Historical log artifacts | `runtime/logging_sink.py:47` serializes `record.selected_strategy.value` into operational JSON logs on every cycle; no reader in the repository deserializes this back into a live `StrategyId` (confirmed by search) | No migration action required — historical logs will contain retired `StrategyId` strings indefinitely, which is harmless and does not imply the retired strategies remain production-enabled (§12.B) |

No risk above is Critical — every one is a bounded, foreseeable
consequence of a single-package, single-factory-function change,
addressed by the Migration Strategy's own Validation phase.

## 15. Implementation Roadmap

Future work only — no code specified here, per this ADR's own scope
discipline:

1. Complete ADR-035 Phases 1–6 (ORB `Strategy` implementation,
   qualification, FVG confirmation, Market Intelligence integration,
   configuration, full-suite validation) — each already its own RPI
   Plan/Accepted-ADR-gated phase per ADR-035 §17, unaffected by this
   ADR.
2. Strategy removal: delete the five legacy strategy files. Whether any
   `StrategyId` member is also deleted is a *separate* decision, governed
   by §12.B — not an automatic part of this step.
3. Registration cleanup: update `build_default_registry()` to register
   ORB alone.
4. Configuration cleanup: remove the five strategies' dedicated
   `StrategyEngineConfig` fields; retain/introduce only ORB's own
   (ADR-035 §13).
5. Documentation cleanup: update ADR-026 and ADR-035 §0's own
   strategy-count language to reflect the new inventory.
6. Test cleanup: prune or rewrite `test_regression.py`, `test_selection.py`
   (per §12.B's multi-`StrategyId` testability constraint), the
   per-strategy test files, and the three Runtime tests identified in
   §11 (`test_configuration.py`, `test_integration.py`,
   `test_phase_3c_ingestion_integration.py`) to reflect a
   single-strategy registry.
7. ORB registration: register `OrbBreakoutStrategy` (or whatever ADR-035
   Phase 1 ultimately names it) as the registry's sole member.
8. Validation: full Strategy Engine **and** Runtime suites green;
   architecture tests green; `git diff --stat` confined to Strategy
   Engine, Runtime's test directory, and docs.

Each numbered step above is its own future RPI Plan, gated by this
project's standing RPI workflow (`TEAM.md` §9) — this roadmap sequences
them, it does not authorize skipping their individual review gates.

## 16. Acceptance Criteria

This ADR may be marked **Accepted** once:

- Independent review confirms ORB is correctly designated Titan's sole
  intended production strategy (§12), contingent on ADR-035's own
  remaining phases.
- Independent review confirms the Strategy Engine, `Strategy` interface,
  and selection cascade are preserved, not redesigned (§10).
- Every one of the five current production strategies is identified with
  its full retirement inventory (§11).
- The migration scope (§13) and preserved-components list (§10) are both
  present and repository-evidenced.
- Every listed Non-Goal (§9) is verified true against the current
  repository, not merely asserted.
- A rollback strategy is present (§13).
- No implementation instruction (code, file diff, or specific function
  body) appears anywhere in this document.
- No speculative architecture (a new component, a new pipeline stage, a
  new abstraction) appears anywhere in this document.

**Acceptance of this ADR authorizes the product-direction decision
only.** It does not authorize beginning the Implementation Roadmap
(§15) — step 1 of that roadmap (ADR-035 Phases 1–6) must independently
reach Accepted-and-implemented status first, and each subsequent step
remains gated by this project's normal RPI governance regardless of this
ADR's own status.

## 17. Consequences

**Positive**: a single, specialized production strategy reduces
Strategy Engine's configuration surface (from 5 per-strategy field
groups to 1), test surface (from 5 dedicated qualification/trade-intent
suites plus a multi-way selection cascade to 1), and documentation
surface (ADR-026/ADR-035 §0's strategy-count language converges to a
single, current statement). **Negative / cost**: the five legacy
strategies' qualification logic, and any future value they might have
independently contributed to the selection cascade's tie-break steps
(§2 — steps 3/4 are already reserved placeholders regardless of
strategy count), is permanently removed rather than retained as a
fallback; re-adding any of them later would require restoring deleted
code from version history, not toggling a flag.

## 18. Alternatives Considered

- **Keep all five strategies registered alongside ORB** (rejected by
  this ADR's own product-direction premise — the explicit driver is
  specialization, not addition; ORB was designed additively in ADR-035
  §0 precisely so this alternative remained possible, but this ADR's
  decision is not to take it).
- **Disable the five via configuration (e.g., empty `approved_pairs`)
  rather than delete their code** (rejected: leaves dead, untested code
  and stale per-strategy config fields in the repository indefinitely —
  contrary to §14's dead-code risk and CLAUDE.md's "leave the codebase
  cleaner" guidance).
- **Build a new, separate "single-strategy mode" component** (rejected:
  `StrategyRegistry`/`selection.py` already support a registry of any
  size, including one, with zero modification — introducing a new
  component here would violate this ADR's own Non-Goals and the
  Minimal Change Engineer philosophy, CLAUDE.md §6).

## 19. Repository References

`titan_protocol/strategy_engine/models.py` (`StrategyId`),
`titan_protocol/strategy_engine/strategies/__init__.py`
(`build_default_registry`), `titan_protocol/strategy_engine/strategies/registry.py`
(`StrategyRegistry`), `titan_protocol/strategy_engine/engine.py`
(`StrategyEngine.__init__`), `titan_protocol/strategy_engine/selection.py`
(`select_winning_strategy`), `titan_protocol/strategy_engine/config.py`
(`StrategyEngineConfig`, `DEFAULT_APPROVED_PAIRS_BY_STRATEGY`),
`titan_protocol/research_engine/models.py` (generic `StrategyId` field),
`titan_protocol/runtime/models.py` (`TradingProfile.allowed_strategies`,
`RuntimeAuditRecord.selected_strategy`), `titan_protocol/runtime/profiles.py`
(`DEFAULT_APPROVED_PAIRS_BY_STRATEGY` import, `_ALL_STRATEGIES`),
`titan_protocol/runtime/engine.py` (`selected_strategy` call sites),
`titan_protocol/runtime/logging_sink.py` (`selected_strategy.value` log
serialization), `deployment_windows/start.py:1196`,
`deployment_windows/install.py:303`,
`tests/titan_protocol/strategy_engine/{test_regression,test_selection,test_qualification,test_trade_intent}.py`,
`tests/titan_protocol/runtime/{test_configuration,test_integration,test_phase_3c_ingestion_integration,test_trading_profiles}.py`,
`docs/adr/ADR-026-strategy-engine.md`, `docs/adr/ADR-035-orb-strategy.md`.

## 20. Final Recommendation

This ADR should be independently reviewed and, if the architectural
preservation claims in §10 and the Non-Goal verifications in §9 hold
under that review, marked **Accepted** as a product-direction decision.
Its Implementation Roadmap (§15) should not begin until ADR-035's
remaining phases (1–6) are themselves Accepted and implemented — this
ADR documents where Titan is headed, not a task to execute today.
