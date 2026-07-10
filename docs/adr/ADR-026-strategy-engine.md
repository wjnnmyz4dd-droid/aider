# ADR-026 — Strategy Engine

Status: **Accepted**

Owner: Software Architect (per the precedent set by `ADR-024`/`ADR-025`
— a cross-cutting evaluation component, not a playbook-orchestration
one, despite the name)

Accepted By: User direction, this session (explicit, full
specification: mission, input restrictions, strategy qualification
rules, 5 named strategies with 13 required definition fields each,
qualification scoring, a 6-step deterministic selection cascade,
mandatory S/R/liquidity/candlestick consumption, architecture rules,
performance targets, and a 9-category testing mandate — plus a
mid-turn addendum adding the Strategy Eligibility Matrix) — the same
in-session approving authority already used to accept `ADR-020` through
`ADR-025`.

Reviewed by: (post-hoc, this session) — checked against
`ADR-003` (Strategy Engine, `phantom_pipeline/`) before acceptance; see
§0.

Date: 2026-07-10

Depends on: `ADR-024-evidence-engine.md` (Accepted, Amendment 1 — this
engine consumes `EvidenceSnapshot` read-only) and
`ADR-025-market-intelligence-engine.md` (Accepted — consumes
`MarketIntelligenceSnapshot` read-only). Imports nothing else.

---

# 0. Relationship to existing architecture

**`ADR-003` Strategy Engine (Accepted, implemented in
`phantom_pipeline/strategy_engine/`)** already has 5 playbooks:
`orb.py`, `liquidity_reversal.py`, `session_breakout.py`,
`trend_continuation.py`, `range_reversal.py`. Three of this ADR's five
strategy *names* overlap directly (`Trend Continuation`, `Session
Breakout`, `Range Reversal`); `Liquidity Sweep + Market Structure
Shift` is conceptually adjacent to `liquidity_reversal.py`; only `BOS +
Fair Value Gap` has no existing counterpart. This is a real overlap,
disclosed rather than hidden — and it resolves exactly the way
`ADR-024`/`ADR-025` already resolved the same class of question for
this session's `phantom/` track: **fresh, independent, no reuse.**
`phantom/strategy_engine/` is built clean-room, imports nothing from
`phantom_pipeline/`, and does not share a playbook registry, scoring
model, or selection algorithm with `phantom_pipeline/strategy_engine/`.
The two tracks remain fully separate authorities within their own,
non-overlapping pipelines (`ADR-024` §0's reasoning applies unchanged).

---

# Pipeline position

**Not wired into any execution pipeline.** Consumes `EvidenceSnapshot`
(`ADR-024` Amendment 1) and `MarketIntelligenceSnapshot` (`ADR-025`)
only — both already frozen, both read-only. Per the user's stated
future sequence, this is Phase 2C; Portfolio Statistical Risk Engine,
Prop Firm Compliance Engine, Research & Learning Engine, and Validation
remain unimplemented and out of scope here.

---

# 1. Mission

**The Strategy Engine answers exactly one question: "Which strategy, if
any, best fits current market conditions for this pair?"**

It never answers: what size, is this compliant, should we execute,
should news block this. It selects a winning strategy (or rejects the
setup entirely) and explains why — nothing more. **No trade direction
is produced.**

---

# Hard Rules

1. **No trade decision anywhere in this package.** No `BUY`/`SELL`, no
   position size, no order, no FTMO/compliance verdict, anywhere in
   `phantom/strategy_engine/` — verified by a structural test.
2. **Two inputs only.** `evaluate()` accepts an `EvidenceSnapshot` and a
   `MarketIntelligenceSnapshot` for one pair — nothing else. No file in
   this package imports `phantom_pipeline/`, `phantom.bridge`, or
   recomputes anything `phantom.evidence_engine`/
   `phantom.market_intelligence` already computed (no duplicate
   structure/liquidity/candlestick/news calculations).
3. **Every strategy self-qualifies.** A strategy never evaluates a
   market outside its declared regime; `qualify()` returns a
   `QualificationResult` with `score=0`/not-eligible for any input its
   own regime check rejects, before any scoring logic runs.
4. **Pair eligibility is a hard, binary gate — never part of the
   score.** Every strategy declares an approved pair universe. A pair
   outside it: `Qualification Score = 0`, `Status = NOT_ELIGIBLE`,
   `Reason = "Pair not supported by strategy"`, rejected immediately,
   no exceptions, never partially eligible. This check runs *before*
   any qualification-scoring logic, not blended into it (same
   hard-zero-not-blend discipline `ADR-025` already established for its
   absolute blockers).
5. **Eligibility is config-driven and read-only at runtime.** No method
   on `StrategyEngine` or any `Strategy` ever mutates an approved-pairs
   set. Changing eligibility means editing the config and redeploying —
   never a runtime call. (Anticipates a future Research & Learning
   Engine that may *recommend* changes; it can never *apply* them
   itself.)
6. **Deterministic selection, never randomized.** The 6-step cascade
   (Qualification Score → Evidence alignment → historical ranking
   placeholder → portfolio concentration placeholder → liquidity
   quality → news risk) runs in that fixed order; a tie remaining after
   all six steps rejects the trade. No `random`, no arbitrary
   first-registered tiebreak.
7. **No hidden calculations.** Every `QualificationResult` carries
   `score`, `confidence`, `reason`, `strengths`, `weaknesses`.
8. **Thread safety, no shared mutable state.** `StrategyEngine` holds no
   per-call mutable state; evaluating N pairs concurrently never
   corrupts anything.

---

# 2. Architecture

```
phantom/strategy_engine/
    models.py             StrategyId, MarketRegime, QualificationStatus,
                          QualificationResult, StrategyDefinition,
                          EligibilityMatrix, WinningStrategy,
                          StrategySnapshot
    config.py              StrategyEngineConfig -- every threshold
                          named; per-strategy approved-pair sets
    strategies/
        base.py             Strategy ABC: qualify(evidence, mi, config)
                          -> QualificationResult
        liquidity_sweep_mss.py    Liquidity Sweep + Market Structure Shift
        bos_fvg.py                BOS + Fair Value Gap
        trend_continuation.py    Trend Continuation
        session_breakout.py       Session Breakout
        range_reversal.py         Range Reversal
        registry.py             explicit registration, duplicate-name
                              rejection
    eligibility.py          the hard pair-eligibility gate (Hard Rules
                          4-5), checked before any strategy's qualify()
    selection.py            the 6-step deterministic cascade
    explainability.py        StrategySnapshot assembly
    engine.py               StrategyEngine.evaluate()/evaluate_batch()
    logging_sink.py, metrics.py, __init__.py
```

No file here imports `phantom_pipeline/` or `phantom.bridge`. The only
upstream imports are `phantom.evidence_engine.models.EvidenceSnapshot`
and `phantom.market_intelligence.models.MarketIntelligenceSnapshot`
(types only, read-only).

---

# 3. Strategy Eligibility Matrix

Per the user's addendum, mid-phase: every strategy declares a fixed,
config-driven approved-pair set (or, for `Range Reversal`, a
config-driven default set explicitly documented as a placeholder
pending real Research & Learning Engine statistical input — never
invented "statistics"). A pair outside a strategy's set makes that
strategy `NOT_ELIGIBLE` for that pair, unconditionally, before
qualification scoring runs. `StrategyEngine`/`Strategy` expose no
method that mutates this set at runtime.

---

# 4. Testing (mandatory before Accepted → Done)

Per the user's 9-category mandate: unit, qualification, boundary,
determinism, performance (28+ pairs), regression, architecture,
concurrency, explainability.

---

# Success Criteria

- Every strategy rejects out-of-regime and out-of-eligibility inputs
  before scoring, verified by dedicated tests per strategy.
- Selection is byte-for-byte reproducible for identical inputs, and a
  full 6-step tie always rejects rather than picking arbitrarily.
- No trade direction, size, or execution artifact appears anywhere in
  `StrategySnapshot` or this package's public surface.
- 28+ pairs evaluated with no shared mutable state and no duplicate
  Evidence/Market Intelligence/News/Indicator computation.

---

# Amendment 1 (2026-07-10) — Strategy Engine owns `TradeIntent`

**Accepted by:** explicit user architecture decision, this session,
given directly in response to a design question raised during Phase 3A
(Runtime Orchestrator) implementation: none of Evidence, Market
Intelligence, Strategy (pre-amendment), Risk, or Compliance produces a
trade direction, yet the Bridge's `submit_command()` requires one. The
user's own words: *"The Strategy Engine SHALL be the sole owner of
TradeIntent (BUY/SELL). This is not a new engine and not a new decision
authority. It is simply completing the Strategy Engine's existing
responsibility... because it already evaluates the complete entry
thesis."*

## Decision

`StrategySnapshot` gains a `trade_intent: TradeIntent` field
(`BUY` / `SELL` / `NONE`). `TradeIntent` is derived **exclusively from
the winning strategy's own already-computed entry-thesis facts** — no
new detection logic, no reinterpretation of Evidence Engine's output as
a signal Evidence Engine itself never asserted, no Runtime involvement.

This narrows Hard Rule 1's blanket "no `BUY`/`SELL`" to a single,
explicit exception: **a `TradeIntent` value is not a trade decision.**
It carries no size, no order, no execution authority, and cannot by
itself cause anything to trade — it is the directional conclusion of
the same qualification the strategy already performs, exposed rather
than discarded. Every other part of Hard Rule 1 (no position size, no
order, no FTMO/compliance verdict) is unchanged and still enforced by
the architecture test.

## Per-strategy derivation (no new facts invented)

| Strategy | Source fact (already computed) | Mapping |
|---|---|---|
| Liquidity Sweep + MSS | the confirming `CHOCH`'s `StructureDirection` | `BULLISH` → `BUY`, `BEARISH` → `SELL` |
| BOS + FVG | the matched `BOS` event's `StructureDirection` | `BULLISH` → `BUY`, `BEARISH` → `SELL` |
| Trend Continuation | `evidence.structure.trend` (already gated to directional-only) | `TRENDING_UP` → `BUY`, `TRENDING_DOWN` → `SELL` |
| Range Reversal | the nearest confluence zone's `sources` label (already tagged `"support"`/`"resistance"` by `support_resistance.py`'s own `sourced_prices` construction) | `"support"` present → `BUY` (bounce), `"resistance"` present → `SELL` (rejection); if neither label is present, fall back to comparing the zone's price against the midpoint of `session_high`/`session_low` (both already on `SupportResistanceContext`) |
| Session Breakout | the most recently confirmed `StructureEvent.direction` in `evidence.structure.events` (highest `confirmed_index`); if none exist, falls back to `evidence.structure.trend` if directional | `BULLISH`/`TRENDING_UP` → `BUY`, `BEARISH`/`TRENDING_DOWN` → `SELL`; **if no directional fact is available at all, the strategy returns `NOT_QUALIFIED`** (fail-closed — this strategy never guesses a direction merely to have one) |

No strategy queries raw `Bar` data or anything not already exposed on
`EvidenceSnapshot`/`MarketIntelligenceSnapshot`. `Evidence Engine` is
untouched — it still produces zero `BUY`/`SELL` vocabulary anywhere in
its own package (verified by that package's own unchanged architecture
test).

## Where `TradeIntent` lives

- `QualificationResult` gains `trade_intent: TradeIntent = TradeIntent.NONE`
  (defaulted — every existing `NOT_QUALIFIED`/`NOT_ELIGIBLE` return
  across all five strategies and `eligibility.py` is unchanged code and
  now implicitly correct: no qualified thesis, no intent). Each
  strategy sets a real value only on its `QUALIFIED` path.
- `StrategySnapshot` gains `trade_intent: TradeIntent = TradeIntent.NONE`
  (also defaulted, for the same backward-compatibility reason — every
  existing test fixture across `risk_engine`, `compliance_engine`, and
  `validation_engine` that hand-builds a `StrategySnapshot` keeps
  working unchanged). `build_strategy_snapshot()` sets it to
  `winning_strategy.qualification.trade_intent` when a strategy won,
  `NONE` when the pair was rejected.
- Selection (`selection.py`) is unchanged. Exactly one strategy still
  wins per pair per cycle; its `trade_intent` simply travels with it.
  The 6-step cascade never considers direction — it was never asked to.

## Downstream contract (binds Phase 3A's Runtime Orchestrator, not this package)

Runtime passes `StrategySnapshot.trade_intent` unchanged through Risk
Engine and Compliance Engine — neither reads nor modifies it (their own
snapshot types gain no new field; this is purely a Strategy Engine
output that Runtime carries alongside, not through, Risk/Compliance's
own evaluation). If Compliance rejects, Runtime never constructs a
`TradeCommand`. If Compliance approves or reduces, Runtime submits the
`TradeCommand` using the unchanged `trade_intent`. This contract is
Runtime's responsibility to honor (see `docs/adr/ADR-031-runtime-
orchestrator.md`); it is recorded here only because it is the reason
this amendment exists.

## No new engine

This amendment does not create a Direction Engine, does not place
direction-deciding logic in Runtime, and does not reinterpret Evidence
Engine's trend classification as a trade signal from outside the
Strategy Engine. `TradeIntent` belongs exclusively to, and is computed
exclusively within, `phantom/strategy_engine/`.

## Testing

- One test per strategy verifying its `QUALIFIED` path produces the
  correct `TradeIntent` for both a bullish and a bearish qualifying
  fixture, matching the table above exactly.
- A rejected/`NOT_QUALIFIED` result always carries `TradeIntent.NONE`.
- Session Breakout's fail-closed path: a qualifying setup with no
  structural event and a non-directional trend returns `NOT_QUALIFIED`,
  never a guessed direction.
- The existing architecture test's forbidden-identifier list drops
  `BUY`/`SELL` (now legitimate `TradeIntent` members) but keeps every
  execution/sizing term (`position_size`, `stop_loss`, `take_profit`,
  `order_type`, `place_order`, `submit_order`, `lot_size`) forbidden,
  plus the existing "no `select_direction`/`choose_direction` method"
  check on `StrategyEngine`'s public surface (already present,
  unchanged) — confirming direction is a derived data field, never a
  method a caller invokes to pick one.
- Full pre-amendment `strategy_engine` suite (all tests that existed
  before this amendment) must continue to pass unmodified, since every
  new field is additive and defaulted.

## Acceptance criteria

- ✓ `TradeIntent` derived only from facts each strategy already computed
  (table above), never a new detection.
- ✓ Evidence Engine unmodified; still produces zero `BUY`/`SELL`.
- ✓ Runtime never chooses a direction — it only forwards
  `StrategySnapshot.trade_intent`.
- ✓ Backward compatible: every pre-amendment call site of
  `QualificationResult`/`StrategySnapshot` still compiles and passes
  unchanged (defaulted fields).
