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
