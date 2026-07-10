# Phantom Portfolio Statistical Risk Engine — Phase 2D Implementation Report

**Status:** Complete. Bridge, Evidence Engine, Market Intelligence
Engine, and Strategy Engine remain frozen and byte-for-byte untouched
this phase. Prop Firm Compliance Engine, Research & Learning Engine,
and Validation are explicitly **not** started, per this phase's "STOP"
instruction.

Authority: `docs/adr/ADR-027-portfolio-statistical-risk-engine.md`
(Accepted, this session). Scope: `phantom/risk_engine/` — a new,
independent package, built fresh with no reuse of
`phantom_pipeline/risk_engine/` (deterministic sizing) or
`phantom_pipeline/statistical_risk/` (VaR/CVaR/Monte Carlo/correlation)
despite conceptual overlap with both (see ADR-027 §0).

---

## 0. Resolved design question this phase required

Before any code was written, a real gap surfaced between what this
task requires (Portfolio Heat, Currency/Symbol Exposure, Correlation,
Rolling Expectancy, VaR/CVaR, Drawdown, Monte Carlo, Kelly Criterion,
Daily/Weekly/Monthly Risk Limits) and what the task's own named input
list (`EvidenceSnapshot`, `MarketIntelligenceSnapshot`,
`StrategySnapshot`) actually contains: none of the three carries
currently-open-position or historical-trade-outcome data, the task
forbids direct Bridge communication, and no Position Manager exists yet
to be a source.

Put directly to the user before any code was written, the answer
(explicit, this session): **add two new, optional, caller-supplied
input types** — `PortfolioState` (open positions) and `TradeHistory`
(realized R-multiples) — passed as parameters to
`evaluate()`/`evaluate_batch()`, never fetched by this engine itself.
Both default to absent, and per the task's own explicit rule ("unknown
correlation/statistical state defaults to fail closed"):

- `portfolio_state=None` → zero open positions assumed, but every
  exposure/correlation field is tagged `data_quality=UNKNOWN` rather
  than silently reported as "all clear."
- `trade_history=None` (or below `config.min_trade_history_for_statistics`,
  default 20) → every history-dependent statistic is
  `sufficient_data=False`/`None`, and **position sizing is capped at
  the lowest confidence tier (0.25R) regardless of the Evidence
  Score's own band** until real history exists.

Full rationale, including the disclosed overlap with the two existing
`phantom_pipeline/` packages, is in ADR-027 §0/§0a.

---

## 1. Folder structure

```
phantom/risk_engine/
    __init__.py            public exports
    models.py               all dataclasses/enums (RiskSnapshot, PortfolioState,
                           TradeHistory, ExposureSummary, CorrelationStatus,
                           StatisticalMetrics, MonteCarloResult, etc.)
    config.py                RiskEngineConfig -- every threshold named; the
                           confidence-scaling schedule, owned only by this engine
    gate.py                  the 65-point evidence hard gate
    confidence.py            Evidence Score -> confidence tier -> base R
    exposure.py              portfolio heat, currency/symbol/long/short/net exposure
    correlation.py           currency/pair/rolling correlation, clusters,
                           cross-currency exposure, correlation limit check
    statistics.py            rolling expectancy, win/loss distribution, risk of ruin,
                           VaR, CVaR, drawdown, recovery factor, profit factor,
                           Sharpe/Sortino, Calmar, Ulcer Index, R-multiple, Kelly fraction
    monte_carlo.py           seeded, deterministic simulation -- advisory only
    volatility.py            ATR/volatility-adjusted sizing multiplier
    position_sizing.py       fixed fractional, confidence scaling, volatility
                           scaling, fractional-capped Kelly, min/max clamp, lot
                           normalization
    safety_limits.py         daily/weekly/monthly risk, portfolio heat, correlation,
                           max open positions/per-pair/currency-exposure limits
    reservation.py           thread-safe pending-exposure reservation ledger
    explainability.py        RiskSnapshot assembly (reasons, warnings)
    engine.py                RiskEngine.evaluate()/evaluate_batch()
    logging_sink.py, metrics.py

tests/phantom/risk_engine/
    _fixtures.py, test_gate.py, test_confidence.py, test_exposure.py,
    test_correlation.py, test_statistics.py, test_monte_carlo.py,
    test_position_sizing.py, test_safety_limits.py, test_reservation.py,
    test_engine.py, test_boundary.py, test_determinism.py,
    test_performance.py, test_regression.py, test_architecture.py

docs/adr/ADR-027-portfolio-statistical-risk-engine.md
```

## 2. File list

17 production files (1,641 lines), 17 test files including fixtures
(1,515 lines), 1 new ADR, 1 report. `phantom/bridge/`,
`phantom/evidence_engine/`, `phantom/market_intelligence/`,
`phantom/strategy_engine/`, `phantom_pipeline/`, and
`scripts/check_architecture.py` are byte-for-byte unchanged this phase
— confirmed via `git status`.

## 3. Interfaces

```python
RiskEngine(config, metrics=None)
    .evaluate(pair, evidence: EvidenceSnapshot, market_intelligence: MarketIntelligenceSnapshot,
              strategy: StrategySnapshot, portfolio_state: Optional[PortfolioState] = None,
              trade_history: Optional[TradeHistory] = None, now=None) -> RiskSnapshot
    .evaluate_batch(pairs: Dict[str, Tuple[EvidenceSnapshot, MarketIntelligenceSnapshot, StrategySnapshot]],
                    portfolio_state=None, trade_history=None, now=None) -> Tuple[RiskSnapshot, ...]
    .release_reservation(reservation_id) -> bool

check_evidence_gate(evidence, config) -> Optional[RejectionReason]
confidence_tier_for_evidence_score(score, config) -> Optional[ConfidenceTier]
compute_exposure_summary(portfolio_state, pending_reservations) -> ExposureSummary
compute_correlation_status(pair, portfolio_state, trade_history, config) -> CorrelationStatus
compute_statistical_metrics(trade_history, config) -> StatisticalMetrics
run_monte_carlo(trade_history, config) -> Optional[MonteCarloResult]
compute_volatility_adjustment(volatility, liquidity, config) -> VolatilityAdjustment
compute_position_size(confidence_tier, volatility_adjustment, statistical_metrics, config) -> PositionSizeRecommendation
check_safety_limits(pair, candidate_risk_r, portfolio_state, trade_history, exposure_summary,
                    correlation_status, config, now) -> Tuple[Optional[RejectionReason], Tuple[str, ...]]
build_risk_snapshot(...) -> RiskSnapshot

ReservationLedger
    .reserve(pair, risk_r) / .reserve_if(pair, risk_r, predicate) / .release(id) / .pending_total_r()
```

No method anywhere accepts or returns a trade direction, a strategy
choice, an order, or a compliance decision — verified by
`test_architecture.py`.

## 4. Data models

`RejectionReason` (10 values), `DataQuality` (`KNOWN`/`UNKNOWN`),
`Direction` (`LONG`/`SHORT`, describing existing portfolio state, never
a decision this engine makes), `OpenPosition`, `PortfolioState`,
`TradeResult`, `TradeHistory` (caller-supplied — ADR-027 §0a),
`ExposureSummary`, `CorrelationStatus`, `RMultipleSummary`,
`StatisticalMetrics` (15 named statistics + Kelly fraction),
`MonteCarloResult`, `VolatilityAdjustment`, `ConfidenceTier`,
`PositionSizeRecommendation`, `RiskSnapshot` (approved, approved risk,
recommended position size, confidence tier, exposure/correlation/
statistical summaries, Monte Carlo, reasons, warnings, rejection reason
— no execution, no compliance decision, ever). All frozen dataclasses.

## 5. Dependency graph

```
phantom.evidence_engine.models.EvidenceSnapshot            <- read-only, engine.py + volatility.py
phantom.market_intelligence.models.MarketIntelligenceSnapshot <- read-only, engine.py + volatility.py
phantom.strategy_engine.models.StrategySnapshot            <- read-only, engine.py + models.py (TradeResult.strategy_id)

models.py, config.py       <- everything else in this package
gate.py, confidence.py,
exposure.py, correlation.py,
statistics.py, volatility.py,
monte_carlo.py, reservation.py  <- independent leaves, consumed by position_sizing.py,
                                   safety_limits.py, explainability.py, engine.py
statistics.py               <- monte_carlo.py (shared simulate_equity_paths/percentile,
                               risk-of-ruin reuses the same resampling helper -- no
                               second, divergent Monte Carlo implementation)
position_sizing.py, safety_limits.py, explainability.py  <- engine.py
engine.py                   <- __init__.py (only)
```

No cycles. Nothing imports `phantom_pipeline` or `phantom.bridge`
(AST-verified); the only upstream imports are the three named snapshot
types' packages, verified as the sole permitted subset by a dedicated
test. `random` (stdlib) is imported by exactly one file
(`monte_carlo.py`), and even there only ever used to construct a
seeded `random.Random(seed)` instance — never a bare `random.<fn>()`
call against un-seeded global state (both AST-verified).

## 6. Testing report

- New suite: **110/110 pass** across 17 files, covering all 10
  mandated categories (unit, Monte Carlo verification, boundary,
  portfolio, correlation, stress, concurrency, determinism, regression,
  architecture).
- Unit/boundary: the 65-point gate at, above, and one-thousandth below
  threshold; the confidence schedule's exact bands from the task's own
  worked example (65–69→0.25R … 90–100→1.25R); tier boundaries proven
  non-overlapping and gap-free.
- Portfolio: exposure heat/long/short/net/currency/symbol computed from
  hand-built `PortfolioState`s, including pending-reservation inclusion
  and the `UNKNOWN`-vs-`KNOWN` `data_quality` distinction for absent vs.
  empty portfolio state.
- Correlation: the sign-aware same-currency heuristic (verified against
  real FX pair-correlation intuition: `EURUSD`/`GBPUSD` positive,
  `EURUSD`/`USDCHF` negative), measured rolling correlation from
  `TradeHistory` once enough samples exist, clusters, and the
  fail-closed `UNKNOWN` state when portfolio state itself is absent.
- Monte Carlo verification: same seed + same history reproduces
  byte-identical simulated paths; different seeds diverge; advisory
  scope confirmed (`None` below the history-sufficiency floor).
- Stress/Performance: a 28-pair batch with full statistics and Monte
  Carlo attached completes in ~134ms (~4.8ms/pair); a 28-pair batch
  with no history in ~2.7ms (~0.10ms/pair).
- Concurrency: 64 threads racing the same pair against a 2R portfolio
  heat cap with a 0.25R fixed position size never together approve more
  than the configured 2R total — the reservation ledger's atomic
  `reserve_if()` is the mechanism, verified directly with 100 threads
  racing a 10R cap (exactly 10 succeed, never more).
- Determinism: repeated calls, two independent engine instances, and
  `evaluate_batch()` vs. individual `evaluate()` calls all agree
  byte-for-byte.
- Architecture: no trade-decision/execution/compliance vocabulary
  appropriate to this engine's actual mission (this engine legitimately
  computes `lot_size`/`position_size` — unlike upstream engines, those
  are not forbidden here; what is forbidden is direction selection,
  order placement, strategy selection, and news parsing), no
  `phantom_pipeline`/`phantom.bridge` import, only the three permitted
  upstream packages imported, no ML imports, `random` confined to
  `monte_carlo.py` and used only via a seeded instance, no mutation
  method on the config or the engine's public surface.
- Full repository suite: **2,136/2,136 pass**. `compileall` clean.
  `scripts/check_architecture.py` (scoped to `phantom_pipeline/`):
  PASS, unaffected.

### 6a. Performance fix found during validation

The first working version of `evaluate_batch()` called the public
`evaluate()` once per pair, and `evaluate()` unconditionally recomputed
`compute_statistical_metrics()` and `run_monte_carlo()` from
`trade_history` — both of which depend only on `trade_history` and
`config`, never on the pair being evaluated. For a 28-pair batch this
meant running the same 1,000-simulation Monte Carlo 28 times over
(3.80s total, ~136ms/pair), a direct instance of the "no duplicate
calculations" rule (ADR-027 Hard Rule 8) this package is supposed to
enforce on itself. Fixed by extracting a shared `_evaluate()` core:
`evaluate()` still computes both fresh for a single-pair call, but
`evaluate_batch()` now computes them **once** for the whole batch and
passes the same values into every pair. Confirmed via the full 110-test
suite passing unmodified, and batch time dropping from 3.80s to 134ms
(28x) for the same workload.

## 7. Performance

`evaluate_batch()` across the task's own 28-pair Forex universe:
**~2.7ms total (~0.10ms/pair)** with no trade history; **~134ms total
(~4.8ms/pair)** with 100 trades of history and full statistics +
1,000-simulation Monte Carlo attached (computed once per batch, not
once per pair — see §6a).

## 8. Coverage

All 17 production modules have at least one direct test file; every
public function/method in the interface list (§3) is exercised,
including the reservation ledger's atomic `reserve_if()` under real
concurrent load.

## 9. Architecture verification

- No forbidden trade-decision/execution/compliance identifiers bound
  anywhere in the package (AST-based, scoped to what this engine must
  never do — direction/strategy selection, order placement, news
  parsing, FTMO checks).
- No import of `phantom_pipeline` or `phantom.bridge`; the only
  upstream imports are `phantom.evidence_engine`,
  `phantom.market_intelligence`, and `phantom.strategy_engine`.
- No ML-library import; `random` confined to `monte_carlo.py`, used
  only via a seeded `random.Random(seed)` instance (AST-verified) —
  satisfies "no randomness in live sizing" while still supporting the
  task's own Monte Carlo requirement.
- `RiskEngineConfig` and `RiskEngine` expose no mutation method.
- `scripts/check_architecture.py` (scoped to `phantom_pipeline/`):
  PASS, unaffected.
- `phantom/bridge/`, `phantom/evidence_engine/`,
  `phantom/market_intelligence/`, and `phantom/strategy_engine/` are
  untouched, confirmed via `git status`.

---

## Recommendation

Ship as-is. The 65-point gate, the configurable confidence schedule,
the fail-closed handling of unknown portfolio/statistical state, the
atomic reservation ledger, and the "smallest sizing method always
wins" rule (confidence schedule → volatility adjustment → fractional-
capped Kelly ceiling → min/max clamp) together give a conservative,
capital-preservation-first sizing authority exactly as specified. Per
this phase's explicit "STOP": Prop Firm Compliance Engine, Research &
Learning Engine, and Validation are **not** started. Awaiting approval
to begin Phase 2E.
