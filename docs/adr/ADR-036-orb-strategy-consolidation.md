# ADR-036 — Strategy Consolidation to ORB

Status: **Proposed** — architectural governance/product-direction
decision only. No implementation accompanies this document. Per
CLAUDE.md §1.10, no implementation may begin until this ADR is
independently reviewed and marked **Accepted** — and, independently of
that, the actual strategy-registry swap this ADR authorizes cannot begin
until ADR-035's own remaining phases (1–6) are themselves implemented
and Accepted, since ORB does not exist as a registrable `Strategy` in the
repository today (§2, §11).

Owner: Principal Software Architect.

Depends on: `ADR-026-strategy-engine.md` (Accepted, Amendment 1) — the
`Strategy` interface, `StrategyRegistry`, and selection cascade this
decision operates within, unchanged. `ADR-035-orb-strategy.md` (Accepted)
— ORB's own design; this ADR does not redesign it. `ADR-024-evidence-engine.md`
(Accepted, Amendment 1, Phase 0 implemented) — unaffected, read-only
context.

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
Execution, Scanner, Market Intelligence, Runtime) is untouched — none of
them reference a specific `StrategyId` by name (§4, §10). This document
authorizes the *decision*; the retirement itself is future work gated on
ADR-035 Phases 1–6 (§13, §15).

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
- **No coupling to specific strategies outside Strategy Engine**: a
  repository-wide search for every `StrategyId` value and every
  strategy class name, excluding `titan_protocol/strategy_engine/`
  itself, returns only `titan_protocol/research_engine/models.py`'s
  generic `strategy_id: Optional[StrategyId]` field (a type-level
  reference to the enum itself, not to any one of the five values) and
  an unrelated same-named `AttributionDimension.BOS_FVG` enum member in
  `research_engine/attribution.py` (a coincidental name, not an import of
  `strategy_engine.StrategyId.BOS_FVG`). Risk Engine, Compliance Engine,
  Runtime, Bridge, and Execution consume only generic
  `StrategySnapshot`/`QualificationResult`/`TradeIntent` types — never a
  named strategy.
- **Test coupling to the count and identity of the five exists**:
  `tests/titan_protocol/strategy_engine/test_regression.py` asserts
  `len(snapshot.all_qualifications) == 5` and asserts a specific
  strategy (`TREND_CONTINUATION`) wins a specific fixture; per-strategy
  files (`test_qualification.py`, `test_trade_intent.py`) exist per the
  same five; `test_selection.py` exercises the cascade using some subset
  of the five's `StrategyId` values.
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
| Runtime | Orchestrates the cycle; does not reference a `StrategyId` | Yes |

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
- Modify Risk Engine, Compliance Engine, Runtime, Bridge, or Execution
  — verified (§2) that none references a specific `StrategyId`.
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

No component listed above is redesigned, reinterpreted, or extended by
this ADR.

## 11. Retired Strategy Inventory

For each of the five, retirement means: removing its file from
`titan_protocol/strategy_engine/strategies/`, removing its
`StrategyId` member, removing its registration line from
`build_default_registry()`, removing its dedicated `StrategyEngineConfig`
fields, and removing/rewriting its dedicated test coverage. This is
future implementation work (§15), not performed by this ADR.

| Strategy | Location | Registration | Configuration | Tests | Docs | Removal impact | Dependencies | Migration considerations | Evidence |
|---|---|---|---|---|---|---|---|---|---|
| `LIQUIDITY_SWEEP_MSS` | `strategies/liquidity_sweep_mss.py` | One line in `build_default_registry()` | 2 threshold fields + 1 `approved_pairs_by_strategy` entry | Shared per-strategy test files (§4) | ADR-026 §1 | None outside Strategy Engine (§2) — no other package references it | Only `evidence_engine`/`market_intelligence` public models + sibling Strategy Engine modules | `test_regression.py`'s hardcoded `len(...) == 5` and its `TREND_CONTINUATION`-wins fixture must be rewritten for a 1-strategy registry | §2, §4 |
| `BOS_FVG` | `strategies/bos_fvg.py` | Same | 2 threshold fields + 1 entry | Same | ADR-026 §1 | Same | Same | Same | §2, §4 |
| `TREND_CONTINUATION` | `strategies/trend_continuation.py` | Same | Threshold field(s) + 1 entry | Same | ADR-026 §1 | Same | Same | `test_regression.py`'s specific winning-strategy assertion currently depends on this one by name — must be replaced with an ORB-appropriate fixture | §2, §4 |
| `SESSION_BREAKOUT` | `strategies/session_breakout.py` | Same | Threshold field(s) + 1 entry | Same | ADR-026 §1 | Same | Same | ADR-035 §0 itself notes `SessionBreakoutStrategy` is ORB's "closest existing analog" — its retirement removes that analog, not ORB's own logic (ORB does not depend on this file) | §2, §4, ADR-035 §0 |
| `RANGE_REVERSAL` | `strategies/range_reversal.py` | Same | Threshold field(s) + 1 entry | Same | ADR-026 §1 | Same | Same | None beyond the shared test-suite update | §2, §4 |

No strategy depends on another (§2) — retiring any subset, or all five,
carries no cross-strategy ripple effect.

## 12. ORB Strategy Designation

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

## 13. Migration Strategy

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
- **Removal phase**: delete the five strategy files, their `StrategyId`
  members, their `build_default_registry()` lines, their
  `StrategyEngineConfig` fields, and their dedicated test files (or
  rewrite the shared ones, e.g. `test_regression.py`,
  `test_selection.py`, to reflect a single-strategy registry).
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
| Repository consistency | Verified today: zero references to any legacy `StrategyId` outside Strategy Engine except `research_engine`'s generic, type-level field (§2) | Retirement is self-contained to Strategy Engine + its docs; no hidden cross-package consistency risk found |

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
2. Strategy removal: delete the five legacy strategy files and their
   `StrategyId` members.
3. Registration cleanup: update `build_default_registry()` to register
   ORB alone.
4. Configuration cleanup: remove the five strategies' dedicated
   `StrategyEngineConfig` fields; retain/introduce only ORB's own
   (ADR-035 §13).
5. Documentation cleanup: update ADR-026 and ADR-035 §0's own
   strategy-count language to reflect the new inventory.
6. Test cleanup: prune or rewrite `test_regression.py`,
   `test_selection.py`, and the per-strategy test files to reflect a
   single-strategy registry.
7. ORB registration: register `OrbBreakoutStrategy` (or whatever ADR-035
   Phase 1 ultimately names it) as the registry's sole member.
8. Validation: full Strategy Engine suite green; architecture tests
   green; `git diff --stat` confined to Strategy Engine + docs.

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
`deployment_windows/start.py:1196`, `deployment_windows/install.py:303`,
`tests/titan_protocol/strategy_engine/{test_regression,test_selection,test_qualification,test_trade_intent}.py`,
`docs/adr/ADR-026-strategy-engine.md`, `docs/adr/ADR-035-orb-strategy.md`.

## 20. Final Recommendation

This ADR should be independently reviewed and, if the architectural
preservation claims in §10 and the Non-Goal verifications in §9 hold
under that review, marked **Accepted** as a product-direction decision.
Its Implementation Roadmap (§15) should not begin until ADR-035's
remaining phases (1–6) are themselves Accepted and implemented — this
ADR documents where Titan is headed, not a task to execute today.
