# Phantom Strategy Engine — Phase 2C Implementation Report

**Status:** Complete. Bridge, Evidence Engine, and Market Intelligence
Engine remain frozen; Evidence Engine received two additive amendments
this phase (see §0). Portfolio Statistical Risk Engine, Prop Firm
Compliance Engine, Research & Learning Engine, and Validation are
explicitly **not** started, per this phase's "STOP" instruction.

Authority: `docs/adr/ADR-026-strategy-engine.md` (Accepted, this
session). Scope: `phantom/strategy_engine/` — a new, independent
package, built fresh with no reuse of `phantom_pipeline/strategy_engine`
despite 3-of-5 strategy names overlapping (see ADR-026 §0).

---

## 0. Two upstream amendments this phase required

Before any Strategy Engine code was written, two real gaps surfaced
between what this task requires strategies to consume and what
`EvidenceReport` (Phase 2A's public output) actually exposed:

1. **Raw structural/liquidity/candlestick facts.** `EvidenceReport`
   only carries seven aggregated 0–100 scores, not the underlying
   swings, structure events, liquidity pools/sweeps, or candlestick
   matches this task requires every strategy to consume. Put directly
   to the user, the explicit answer (given twice) was **"expand the
   EvidenceSnapshot, not create a second analyzer."**
   `docs/adr/ADR-024-evidence-engine.md` Amendment 1 added a new,
   additive `EvidenceSnapshot` type (`EvidenceEngine.evaluate_snapshot()`)
   carrying the raw facts plus a new `support_resistance.py` module
   (Previous Day/Week/Month High/Low, Session High/Low, Psychological
   Levels, Confluence Score, Break Quality Score, False Break
   Probability — concepts Evidence Engine never computed before).
2. **Fair Value Gaps.** While implementing "BOS + Fair Value Gap,"
   FVG detection (a 3-candle imbalance concept) also didn't exist
   anywhere and couldn't be derived by Strategy Engine itself (its only
   inputs are the two snapshots, never raw bars). `ADR-024` Amendment 2
   applied the same resolution: `detect_fair_value_gaps()` added to
   `structure.py`, a new `fair_value_gaps` field added to
   `EvidenceSnapshot`.

Both amendments are purely additive: `EvidenceReport`, `evaluate()`,
and every pre-existing type/field are byte-for-byte unchanged (the full
110-test pre-amendment suite passes unmodified both times; 133/133
after both amendments, +18 and +5 new tests respectively).

---

## 1. Folder structure

```
phantom/strategy_engine/
    __init__.py            public exports
    models.py                StrategyId, MarketRegime, QualificationStatus,
                            QualificationResult, StrategyDefinition,
                            WinningStrategy, StrategySnapshot
    config.py                StrategyEngineConfig -- every threshold named;
                            per-strategy approved-pair eligibility matrix
    eligibility.py            the hard pair-eligibility gate
    strategies/
        base.py                 the Strategy ABC
        registry.py              explicit registration, duplicate rejection
        _helpers.py              shared component()/clamp() helpers
        liquidity_sweep_mss.py   Liquidity Sweep + Market Structure Shift
        bos_fvg.py               BOS + Fair Value Gap
        trend_continuation.py   Trend Continuation
        session_breakout.py      Session Breakout
        range_reversal.py        Range Reversal
    selection.py              the 6-step deterministic cascade
    explainability.py          StrategySnapshot assembly
    engine.py                  StrategyEngine.evaluate()/evaluate_batch()
    logging_sink.py, metrics.py

tests/phantom/strategy_engine/
    _fixtures.py, test_qualification.py, test_selection.py,
    test_engine.py, test_boundary.py, test_determinism.py,
    test_performance.py, test_regression.py, test_architecture.py,
    test_explainability.py

docs/adr/ADR-026-strategy-engine.md
```

## 2. File list

18 production files (1,347 lines), 10 test files + fixtures (987
lines), 1 new ADR, 2 amendments to the existing Evidence Engine ADR, 1
report. `phantom/bridge/`, `phantom/market_intelligence/`,
`phantom_pipeline/`, and `scripts/check_architecture.py` are
byte-for-byte unchanged this phase — confirmed via `git status`.

## 3. Interfaces

```python
StrategyEngine(config, registry=None, metrics=None)
    .evaluate(pair, evidence: EvidenceSnapshot, market_intelligence: MarketIntelligenceSnapshot, now=None) -> StrategySnapshot
    .evaluate_batch(pairs: Dict[str, Tuple[EvidenceSnapshot, MarketIntelligenceSnapshot]], now=None) -> Tuple[StrategySnapshot, ...]

Strategy (ABC)
    .definition -> StrategyDefinition
    .qualify(pair, evidence, market_intelligence, config) -> QualificationResult

StrategyRegistry
    .register(strategy) / .get(strategy_id) / .all() / __contains__ / __len__

check_eligibility(strategy_id, pair, config) -> Optional[QualificationResult]
select_winning_strategy(qualifications, evidence, market_intelligence, config) -> Optional[WinningStrategy]
build_strategy_snapshot(pair, now, qualifications, winning_strategy, evidence, market_intelligence) -> StrategySnapshot
```

No method anywhere accepts or returns a trade direction, size, or
order — verified by `test_architecture.py`.

## 4. Data models

`StrategyId` (5 values), `MarketRegime` (TRENDING/RANGING/BREAKOUT/
REVERSAL), `QualificationStatus` (QUALIFIED/NOT_QUALIFIED/NOT_ELIGIBLE),
`QualificationResult` (score/confidence/reason/strengths/weaknesses,
all zeroed when not QUALIFIED), `StrategyDefinition` (the 13 required
fields), `WinningStrategy`, `StrategySnapshot` (winning strategy,
qualification score, confidence, reasons, supporting evidence and
market intelligence summaries — no trade direction, no execution, no
sizing). All frozen dataclasses.

## 5. Dependency graph

```
phantom.evidence_engine.models.EvidenceSnapshot        <- consumed read-only, engine.py + all 5 strategies
phantom.market_intelligence.models.MarketIntelligenceSnapshot  <- consumed read-only, engine.py + all 5 strategies

models.py, config.py  <- everything else in this package
eligibility.py         <- every strategy's qualify() (checked first)
strategies/*.py        <- selection.py, engine.py
selection.py           <- engine.py
explainability.py       <- engine.py
engine.py              <- __init__.py (only)
```

No cycles. Nothing imports `phantom_pipeline` or `phantom.bridge`
(AST-verified); the only upstream imports are the two named snapshot
types, verified as the sole permitted subset by a dedicated test.

## 6. Testing report

- New suite: **53/53 pass** across 10 files, covering all 9 mandated
  categories (unit, qualification, boundary, determinism, performance,
  regression, architecture, concurrency, explainability).
- Qualification: 18 tests — every strategy's regime self-check, the
  pair-eligibility hard gate (proven to short-circuit before any other
  logic, even with evidence that would otherwise strongly qualify), and
  a genuine, hand-constructed QUALIFIED path for all 5 strategies.
- Selection: 8 tests covering the 6-step cascade, including a full
  6-step tie correctly rejecting (never randomizing) and
  tolerance-boundary behavior.
- Boundary: 4 tests including an empty `StrategyRegistry` — this
  surfaced a real defect (see §6a).
- Determinism: repeated calls, two independent engine instances, and
  `evaluate_batch()` all produce byte-identical output.
- Performance/Concurrency: 28-pair batch in ~1.1ms total; 28 threads
  each evaluating a distinct pair and 64 threads evaluating the same
  pair concurrently, both zero errors, latter byte-identical results.
- Architecture: no trade-decision vocabulary, no `phantom_pipeline`/
  `phantom.bridge` import, only the two permitted upstream snapshot
  types imported, no randomness/ML, no mutation method on the
  eligibility config or the engine's public surface.
- Full repository suite: **2,026/2,026 pass**. `compileall` clean.
  `scripts/check_architecture.py` (scoped to `phantom_pipeline/`):
  PASS, unaffected.

### 6a. Real defect found and fixed

`StrategyEngine.__init__` used `self.registry = registry or
build_default_registry()`. Since `StrategyRegistry` defines `__len__`,
an **empty-but-explicitly-passed** registry (`len() == 0`) is falsy in
Python, so `or` silently discarded it and substituted the default
5-strategy registry — the exact opposite of what the caller asked for.
A boundary test (`test_engine_with_no_registered_strategies_always_rejects`)
caught this immediately. Fixed with an explicit `is not None` check,
documented inline so the same mistake isn't repeated elsewhere in this
package.

## 7. Performance

`evaluate_batch()` across the task's own 28-pair Forex universe:
**~1.1ms total, ~0.039ms/pair** — this engine only classifies/scores
already-computed snapshots (no market-structure or news computation of
its own), so it is the cheapest of the three engines built this session.

## 8. Coverage

All 18 production modules have at least one direct test file; every
public function/method in the interface list (§3) is exercised. Each of
the 5 strategies has a dedicated, hand-verified QUALIFIED-path test in
addition to its regime-mismatch and eligibility tests.

## 9. Architecture verification

- No forbidden trade-decision identifiers (`BUY`/`SELL`/`position_size`/
  `stop_loss`/`take_profit`/`lot_size`/etc.) bound anywhere in the
  package (AST-based).
- No import of `phantom_pipeline` or `phantom.bridge`; the only
  upstream imports are `phantom.evidence_engine` and
  `phantom.market_intelligence`.
- No `random`/ML-library import.
- `StrategyEngineConfig` and `StrategyEngine` expose no mutation method
  for eligibility or execution.
- `scripts/check_architecture.py` (scoped to `phantom_pipeline/`):
  PASS, unaffected.
- `phantom/bridge/`, `phantom/evidence_engine/`, and
  `phantom/market_intelligence/` (beyond the two disclosed, additive
  Evidence Engine amendments) are untouched, confirmed via `git status`.

---

## Recommendation

Ship as-is. All 5 strategies are implemented with genuine, deterministic
qualification logic (verified against hand-constructed QUALIFIED paths,
not just rejection paths), the pair eligibility matrix is a hard,
non-bypassable, config-only gate, and selection never randomizes. Per
this phase's explicit "STOP": Portfolio Statistical Risk Engine, Prop
Firm Compliance Engine, Research & Learning Engine, and Validation are
**not** started. Awaiting approval to begin Phase 2D.
