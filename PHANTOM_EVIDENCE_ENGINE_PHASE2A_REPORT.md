# Phantom Evidence Engine — Phase 2A Implementation Report

**Status:** Complete. Bridge remains frozen and untouched. Strategy
Engine and everything downstream is explicitly **not** started, per
this phase's own "STOP" instruction.

Authority: `docs/adr/ADR-024-evidence-engine.md` (Accepted, this
session). Scope: `phantom/evidence_engine/` only — a new, independent
package, built fresh with no reuse of `phantom_pipeline/scanner` or
`phantom_pipeline/scoring_engine` (explicit user decision; see ADR-024
§0).

---

## 1. Folder structure

```
phantom/evidence_engine/
    __init__.py          public exports
    models.py            data models (no trade-decision types)
    config.py            EvidenceEngineConfig -- every threshold named
    structure.py         swings, BOS/CHOCH (internal/external), S/R
    liquidity.py          equal highs/lows, pools, sweeps, stop hunts,
                         trap filter, displacement detection
    candlesticks.py       21 patterns (6 single, 7 two-, 8 three-candle)
    trend.py             6-state trend classification
    volatility.py         ATR, expansion/compression, volatility score
    session.py           London/overlap/early-NY/late-NY/Asian + quality
    indicators.py         Indicator ABC + registry + bounded cache
                         (interface only, no concrete indicators)
    scoring.py           7 component scores -> composite Evidence Score
    ranking.py           pair ranking, highest first
    explainability.py     Evidence Report assembly
    engine.py            EvidenceEngine orchestrator
    logging_sink.py       structured logging
    metrics.py           evaluation/cache counters

tests/phantom/evidence_engine/
    _fixtures.py, test_structure.py, test_liquidity.py,
    test_candlesticks.py, test_trend_volatility_session.py,
    test_indicators.py, test_scoring_ranking_explainability.py,
    test_engine.py, test_boundary.py, test_determinism.py,
    test_property.py, test_performance.py, test_regression.py,
    test_architecture.py

docs/adr/ADR-024-evidence-engine.md
```

## 2. File list (this phase)

16 production files (1,949 lines), 14 test files + fixtures (1,412
lines), 1 ADR, 1 report. `phantom/bridge/`, `phantom_pipeline/`, and
`scripts/check_architecture.py` are byte-for-byte unchanged — confirmed
via `git status`. One pre-existing test
(`tests/phantom/bridge/test_structural_boundary.py`) had its allowed-path
list extended by one entry (`docs/adr/`) since it hard-coded "Phase 1's
scope" and this phase legitimately adds an ADR outside the paths it
previously recognized; no other line in that file changed.

## 3. Public interfaces

```python
EvidenceEngine(config, registry=None, metrics=None)
    .evaluate(symbol: str, bars: Sequence[Bar], now: Optional[datetime]) -> EvidenceReport
    .evaluate_batch(pairs: Dict[str, Sequence[Bar]], now: Optional[datetime]) -> Tuple[PairRanking, ...]

Indicator (ABC)                 -- .name, .compute(bars, **params) -> IndicatorResult
IndicatorRegistry                -- .register/.get/.names/__contains__
IndicatorCache                   -- .get_or_compute/.size/.clear (thread-safe)

analyze_market_structure(bars, config) -> MarketStructureResult
analyze_liquidity(bars, swings, config) -> LiquidityResult
recognize_patterns(bars, config, contexts=None) -> Tuple[CandlestickMatch, ...]
classify_trend(structure_result, volatility_state, config) -> TrendClassification
analyze_volatility(bars, config) -> VolatilityState
analyze_session(timestamp, config) -> SessionState
compute_component_scores(...) -> Tuple[ComponentScore, ...]   # 7, fixed order
compute_evidence_score(components) -> EvidenceScore
rank_pairs(reports) -> Tuple[PairRanking, ...]
build_evidence_report(symbol, generated_at, score) -> EvidenceReport
```

No method anywhere in this surface accepts or returns a trade direction,
size, or order — verified by `test_architecture.py`.

## 4. Data models

`Bar`, `SwingPoint`/`SwingType`, `StructureEvent`/`StructureEventType`/`StructureDirection`,
`TrendClassification` (6 states), `PriceLevel`, `MarketStructureResult`,
`EqualLevel`, `LiquidityPool`, `LiquiditySweep`, `LiquidityResult`,
`CandlestickPattern` (21 values), `PatternContext`, `CandlestickMatch`,
`VolatilityState`, `SessionName`, `SessionState`, `IndicatorResult`,
`ComponentScore` (name/value/weight/confidence/reason — all mandatory),
`EvidenceScore`, `EvidenceReport` (symbol/score/strengths/weaknesses/confidence_explanation),
`PairRanking`. All frozen dataclasses; all `Tuple[...]` collection
fields (immutable, hashable, safe to compare for determinism tests).

## 5. Dependency graph

```
models.py  <- everything
config.py  <- everything (except models.py)
volatility.py  <- liquidity.py (ATR/displacement reuse), trend.py, scoring.py
structure.py   <- trend.py (structural trend + events), liquidity.py (swings), scoring.py, engine.py
liquidity.py   <- scoring.py, engine.py
candlesticks.py <- scoring.py, engine.py
trend.py       <- scoring.py, engine.py
session.py     <- scoring.py, engine.py
indicators.py  <- engine.py (only)
scoring.py     <- explainability.py (via EvidenceScore), engine.py
ranking.py     <- engine.py
explainability.py <- engine.py
engine.py      <- __init__.py (only)
logging_sink.py, metrics.py <- engine.py
```

No cycles. Nothing imports `phantom_pipeline` or `phantom.bridge`
(enforced by `test_architecture.py::TestNoForbiddenImports`, AST-based,
not text search).

## 6. Test results

- New suite: **110/110 pass** across 14 files, covering all 8 mandated
  categories (unit, property, boundary, performance, determinism,
  explainability, regression, architecture).
- All 21 candlestick patterns individually verified with a crafted
  case each (6 single + 7 two-candle + 8 three-candle).
- Property tests: composite score and every component score bounded
  [0, 100] across 60+ randomized synthetic bar series plus 7 varying
  bar-count edge cases (1 to 300 bars); component weights always sum to
  1.0.
- Determinism tests: identical output across repeated calls, across two
  independent `EvidenceEngine` instances, and across 50 randomized
  synthetic series (each checked instance-to-instance).
- Boundary tests: single bar, exactly-at-swing-lookback series, all-flat
  (zero-range) bars, and extreme prices (1,000,000 and 0.00001 scale) —
  none raise, all stay within score bounds.
- Concurrency: 28 threads evaluating 28 different pairs concurrently,
  plus 64 threads evaluating the same symbol concurrently, produce zero
  errors and byte-identical results.
- Full repository suite: **1,860/1,860 pass** (excluding 3 pre-existing,
  pre-documented flask-import collection errors unrelated to this
  change). `python3 -m compileall` clean on every new file.
  `scripts/check_architecture.py` (scoped to `phantom_pipeline/`, this
  phase touches none of it): **PASS**, unaffected.
- One genuine defect was found and fixed during test-writing: a stale
  boundary test (`test_structural_boundary.py`) hard-coded "Phase 1's
  scope" and didn't recognize `docs/adr/` as an allowed path — fixed by
  adding that one prefix (see §2).

## 7. Performance results

`evaluate_batch()` across the task's own named 28-pair Forex universe
(100 bars each): **51.6 ms total, ~1.84 ms/pair** — no indicator
concrete work exists yet in this phase, so this measures the
structure/liquidity/candlestick/trend/volatility/session/scoring
pipeline's raw cost, not indicator-cache savings (those apply once
concrete indicators exist). 28 concurrent threads each evaluating a
distinct pair complete with zero contention errors.

## 8. Coverage

All 16 production modules have at least one direct test file; every
public function/method in the interface list (§3) is exercised by at
least one passing test. The one area intentionally under-covered by
design: `indicators.py`'s registry/cache is tested via a test-double
indicator (`_CountingIndicator`), since no concrete indicator exists in
this phase (ADR-024 Hard Rule 7) — this is the expected, documented
state, not a gap.

## 9. Architecture verification

- `test_architecture.py`: no forbidden trade-decision identifiers
  (`BUY`/`SELL`/`position_size`/`stop_loss`/`take_profit`/`order_type`/
  `place_order`/`submit_order`) bound anywhere in the package (AST-based
  check — a docstring merely *naming* these to document their absence
  does not trip it); no import of `phantom_pipeline` or `phantom.bridge`;
  no `random`/ML-library import; no socket/HTTP/file-I/O import;
  `EvidenceEngine`'s public surface has no execution method.
- `scripts/check_architecture.py` (scoped to `phantom_pipeline/`):
  PASS, unaffected — this phase touches nothing it scans.
- `phantom/bridge/` and `tests/phantom/bridge/` are untouched except the
  one boundary-test allowlist fix in §2, confirmed via `git status`.

---

## Recommendation

Ship as-is. All 14 requested responsibilities are implemented, all 8
test categories pass, and the package is verifiably free of any trade,
risk, compliance, or execution logic. Per this phase's explicit "STOP":
**the Strategy Engine is not started.** Awaiting approval to begin Phase
2B.
