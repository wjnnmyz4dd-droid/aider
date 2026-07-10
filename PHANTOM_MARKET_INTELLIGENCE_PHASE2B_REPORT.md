# Phantom Market Intelligence Engine — Phase 2B Implementation Report

**Status:** Complete. Bridge and Evidence Engine remain frozen and
untouched. Strategy Engine and everything downstream is explicitly
**not** started, per this phase's own "STOP" instruction.

Authority: `docs/adr/ADR-025-market-intelligence-engine.md` (Accepted,
this session). Scope: `phantom/market_intelligence/` only — a new,
independent package, built fresh with no reuse of
`phantom_pipeline/compliance_engine` or `ADR-016`'s AI News Intelligence
Layer.

---

## 1. Folder structure

```
phantom/market_intelligence/
    __init__.py               public exports
    models.py                  data models (no trade-decision types)
    config.py                  MarketIntelligenceConfig -- every
                              threshold/weight named
    news.py                    pair-currency extraction, event
                              bucketing, blackout computation, news score
    peg_policy.py               PegPolicyRegistry -- explicit
                              activate/clear, no auto-timeout
    session_intelligence.py     reuses evidence_engine.session directly,
                              applies MI-specific preference weighting
    liquidity_intelligence.py   spread-ratio-based liquidity scoring
    market_safety.py            holiday/early-close/weekend/
                              maintenance/halt/closure scoring
    scoring.py                  Pair Safety + Trade Readiness composites
    explainability.py           7-field explanation assembly
    engine.py                   MarketIntelligenceEngine.evaluate()/
                              evaluate_batch(), bounded news-feed cache
    logging_sink.py, metrics.py

tests/phantom/market_intelligence/
    _fixtures.py, test_news.py, test_peg_policy.py,
    test_session_liquidity_market_safety.py,
    test_scoring_explainability.py, test_engine.py, test_boundary.py,
    test_concurrency.py, test_determinism.py, test_caching.py,
    test_failure_modes.py, test_architecture.py, test_regression.py

docs/adr/ADR-025-market-intelligence-engine.md
```

## 2. File list

13 production files (1,180 lines), 14 test files + fixtures (1,057
lines), 1 ADR, 1 report. `phantom/bridge/`, `phantom/evidence_engine/`,
`phantom_pipeline/`, and `scripts/check_architecture.py` are
byte-for-byte unchanged — confirmed via `git status`.

## 3. Interfaces

```python
MarketIntelligenceEngine(config, peg_policy_registry=None, metrics=None)
    .evaluate(pair, evidence: EvidenceReport, events, current_spread,
              average_spread, market_safety_inputs, now=None,
              news_feed_trusted=True) -> MarketIntelligenceSnapshot
    .evaluate_batch(pairs: Dict[str, EvidenceReport], events, spreads,
                    market_safety_inputs, now=None, news_feed_trusted=True)
              -> Tuple[MarketIntelligenceSnapshot, ...]

PegPolicyRegistry
    .activate(pair, event_type, reason, at) -> PegPolicyStatus
    .clear(pair, at) -> PegPolicyStatus       # the only way to deactivate
    .status_for(pair) -> PegPolicyStatus       # inactive by default

pair_currencies(pair) -> (base, quote)
build_pair_news_intelligence(pair, events, now, config) -> PairNewsIntelligence
compute_blackout(pair, events, now, config) -> (bool, Optional[str])
evaluate_session(now, config) -> SessionIntelligence
evaluate_liquidity(current_spread, average_spread, config) -> LiquidityIntelligence
evaluate_market_safety(now, inputs, config) -> MarketSafetyStatus
build_pair_safety(pair, news, liquidity, session, market_safety, peg_policy, config) -> PairSafety
build_trade_readiness(pair_safety, config) -> TradeReadiness
build_explanation(pair_safety, trade_readiness) -> MarketIntelligenceExplanation
```

No method accepts or returns a trade direction, size, strategy
selection, or FTMO decision — verified by `test_architecture.py`.

## 4. Data models

`NewsImpact` (3), `NewsCategory` (19, including `CENTRAL_BANK_CATEGORIES`
as a named subset of 10), `NewsEvent`, `PairNewsIntelligence`,
`PegPolicyEventType` (5), `PegPolicyStatus`, `SessionIntelligence`,
`LiquidityIntelligence`, `MarketSafetyInputs`, `MarketSafetyStatus`,
`PairSafety`, `TradeReadiness`, `MarketIntelligenceExplanation` (7
fields, matching the task's own explainability list), `MarketIntelligenceSnapshot`.
All frozen dataclasses.

## 5. Dependency graph

```
phantom.evidence_engine.models.SessionName   <- models.py
phantom.evidence_engine.config.EvidenceEngineConfig  <- config.py (embedded, for session-boundary reuse)
phantom.evidence_engine.session.analyze_session      <- session_intelligence.py (direct reuse, not reimplemented)
phantom.evidence_engine.models.EvidenceReport         <- engine.py (consumed read-only)

models.py, config.py  <- everything else in this package
news.py, peg_policy.py, session_intelligence.py,
liquidity_intelligence.py, market_safety.py            <- scoring.py, engine.py
scoring.py             <- explainability.py (via PairSafety/TradeReadiness), engine.py
explainability.py      <- engine.py
engine.py              <- __init__.py (only)
```

No cycles. Nothing imports `phantom_pipeline` or `phantom.bridge`
(AST-verified). The only upstream import is
`phantom.evidence_engine.{session,models,config}` — verified as the
sole permitted subset by a dedicated test.

## 6. Testing report

- New suite: **90/90 pass** across 13 files, covering all 9 mandated
  categories (unit, integration, boundary, concurrency, determinism,
  caching, failure-mode, architecture, regression).
- Unit: news classification/bucketing/blackout (13 tests), peg/policy
  registry explicit activate/clear semantics (6), session/liquidity/
  market-safety scoring (18), Pair Safety/Trade Readiness/explainability
  (13) — 50 unit tests total.
- Integration: 8 tests exercising `MarketIntelligenceEngine.evaluate()`/
  `evaluate_batch()` end-to-end against real `EvidenceReport`s.
- Boundary: 9 tests — empty events/batches, zero/negative/huge spreads,
  midnight and exact session-boundary hours, events exactly at the
  blackout-window edge.
- Concurrency: 3 tests — 28 pairs evaluated concurrently across 28
  threads (zero errors), 64 threads evaluating the same pair
  concurrently (byte-identical results), 200 concurrent peg/policy
  registry activate/clear/status calls (zero errors).
- Determinism: 3 tests — repeated calls, two independent engine
  instances, and `evaluate_batch()` all produce identical output.
- Caching: 5 tests confirming the news-feed cache hits on repeated
  lookups within the same minute, differentiates by pair/minute/event
  content, and stays bounded by `max_entries`.
- Failure-mode: 4 tests confirming `news_feed_trusted=False` fails
  closed (forces blackout + zero score, never silently trusts supplied
  events) and that broker maintenance / market closure hard-zero both
  scores regardless of every other factor.
- Architecture: 6 tests — no trade-decision vocabulary (AST-based), no
  import from `phantom_pipeline`/`phantom.bridge`, only the permitted
  `evidence_engine` submodules imported, no randomness/ML/network/file
  I/O, no execution method on the public surface.
- Regression: 2 tests anchoring the "no concerns" (100/100) and
  "NFP-in-10-minutes forces blackout + zero readiness" scenarios worked
  through by hand during development.
- Full repository suite: **1,950/1,950 pass** (excluding the 3
  pre-existing, pre-documented flask-import collection errors).
  `compileall` clean on every new file. `scripts/check_architecture.py`
  (scoped to `phantom_pipeline/`): **PASS**, unaffected.
- Two test-authoring bugs were found and fixed while writing the suite
  (not production defects): several `NewsEvent(...)` test calls omitted
  the required `released` argument. Fixed in
  `test_caching.py`/`test_determinism.py`/`test_failure_modes.py`.

## 7. Performance report

`evaluate_batch()` across the task's own 28-pair Forex universe (30
bars of Evidence per pair, no news events): **0.92 ms total, ~0.033
ms/pair** — markedly cheaper than Evidence Engine's own per-pair cost
(§7 of the Phase 2A report), since this engine does no market-structure
computation itself, only classification/scoring over already-supplied
facts. 28 concurrent threads each evaluating a distinct pair complete
with zero contention errors; 64 threads evaluating the same pair
concurrently produce byte-identical results.

## 8. Coverage

All 13 production modules have at least one direct test file; every
public function/method in the interface list (§3) is exercised by at
least one passing test.

## 9. Architecture verification

- No forbidden trade-decision identifiers bound anywhere in the package
  (AST-based, not text search — a docstring naming "BUY"/"SELL" to
  document their absence never trips it).
- No import of `phantom_pipeline` or `phantom.bridge`; the only
  cross-package import is the three permitted
  `phantom.evidence_engine` submodules (`session`, `models`, `config`).
- No `random`/ML-library import; no socket/HTTP/file-I/O import.
- `MarketIntelligenceEngine`'s public surface has no execution or
  strategy-selection method.
- `scripts/check_architecture.py` (scoped to `phantom_pipeline/`):
  PASS, unaffected — this phase touches nothing it scans.
- `phantom/bridge/`, `phantom/evidence_engine/`, and their test suites
  are untouched, confirmed via `git status`.

---

## Overlap disclosures (transparency, not a defect)

Two real overlaps were checked and resolved before implementation (see
`ADR-025` §0 for the full reasoning):

1. **`ADR-006` Compliance Engine** (Accepted, implemented in
   `phantom_pipeline/compliance_engine/`) already specifies news/session/
   weekend/spread checks with real binary blocking authority. This
   engine has zero pipeline wiring and zero blocking authority in this
   phase — its `blackout_active`/`Trade Readiness` fields are labels on
   its own snapshot, consumed by nothing.
2. **`ADR-016` AI News Intelligence Layer** (Accepted, not implemented)
   is LLM-based/narrative/human-facing — a different shape and purpose
   from this engine's deterministic, rule-based, structured output. No
   mechanism or consumer overlap.

## Recommendation

Ship as-is. All 12 requested responsibilities are implemented (including
the "Additional Requirements" — pair-specific news and readiness,
session preference ordering, avoid-high-impact/avoid-central-bank/avoid-
peg-policy behaviors, and independent per-pair scoring), all 9 test
categories pass, and the package is verifiably free of any trade,
strategy, risk, or compliance authority. Per this phase's explicit
"STOP": **the Strategy Engine is not started.** Awaiting approval to
begin Phase 2C.
