# Plan: Statistical Risk Management

Status: Validated
Owner (Plan phase): Quant Validation Engineer
Touched components: `phantom_pipeline/statistical_risk` (new),
`scripts/check_architecture.py` (one-line set addition)

---

## Research

- Affected files and their dependencies:
  - `phantom_pipeline/risk_engine/models.py`, `config.py`, `engine.py` —
    read in full. `RiskDecision`/`AccountState`/`OpenPosition`/`ConstraintEvaluation`/`RiskTier`
    field names confirmed; `RiskEngine.decide()` takes `(score_result,
    candidate, observation, account_state, stop_distance=None)` and
    returns exactly one `RiskDecision` — this package treats all of these
    as read-only input types, never modifies `risk_engine/`.
  - `phantom_pipeline/analytics/performance.py`, `analytics/models.py` —
    read in full. `compute_performance_statistics()` already computes
    whole-sample `win_rate`/`profit_factor`/`sharpe`/`sortino`/`expectancy`/
    `max_drawdown` from `TradeProvenanceRecord.final_outcome.realized_pnl`.
    This is the reuse boundary: `statistical_risk` never re-derives these
    whole-sample numbers; it only computes **rolling** (windowed) versions
    plus the 16 genuinely new capabilities (Monte Carlo, VaR, CVaR, Risk
    of Ruin, Kelly, drawdown-limit probability, volatility/correlation/
    portfolio-heat/regime-confidence/per-trade-confidence-interval
    recommendations) that do not exist anywhere in the repository today.
  - `phantom_pipeline/paper_trading/forward_test_engine.py`,
    `account_tracker.py` — read in full. `ForwardTestReport` composes
    `PerformanceStatistics` plus its own `average_rr`/slippage/latency
    fields; `AccountSnapshot` (from `AccountTracker.observe()`) already
    carries `daily_drawdown_pct`/`total_drawdown_pct`/`peak_equity` — no
    overlap with anything `statistical_risk` computes; no duplication.
  - `phantom_pipeline/data_pipeline/models.py` — read in full.
    `NormalizedBar` (OHLCV) is the ATR data source; no ATR field exists
    anywhere in the repo today, so `volatility.py`'s ATR computation is
    genuinely new, not a duplicate.
  - `phantom_pipeline/scanner/models.py` — read in full. `VolatilityState.ratio`
    is a compression ratio, not ATR; `MarketPhase`/`RangeStructure`/
    `StructureConfidence` are the regime fields read for regime-based
    confidence.
  - `docs/adr/ADR-020-knowledge-rag-subsystem.md`, `ADR-021-ai-research-desk.md`,
    `scripts/check_architecture.py` — read in full as the direct template
    for this ADR's cross-cutting-observer posture and its enforcement
    mechanism (`CROSS_CUTTING_OBSERVER_PACKAGES`).
- Touched stage's ADR status: `ADR-022-statistical-risk-management.md` —
  **Accepted** (this session, explicit full user specification; see ADR
  header).
- Duplicate logic / potential regressions found: none in the 16 existing
  packages needs changing. The only duplication risk identified and
  avoided: re-implementing whole-sample win-rate/profit-factor/Sharpe/
  Sortino/expectancy/max-drawdown, all of which `analytics.performance`
  already owns — `statistical_risk` computes rolling-window variants of
  these (a genuinely different computation: a trailing subsequence, not
  the whole sample) and never calls itself the authority on the whole-
  sample figures.
- `python3 scripts/check_architecture.py` result (before this change):
  16 packages, PASS on all three checks (baseline, confirmed 2026-07-07
  during the `DEPLOYMENT_PACKAGE` rebuild task).

## Plan

- Approach: build `phantom_pipeline/statistical_risk/` as a 17th,
  cross-cutting-observer package (same posture as `knowledge`/
  `research_desk`), stateless (no `InMemory*Store` — every call takes its
  historical input explicitly), producing one new immutable output type,
  `StatisticalRiskAssessment`, per assessment request. Add `"statistical_risk"`
  to `scripts/check_architecture.py`'s `CROSS_CUTTING_OBSERVER_PACKAGES`
  so the "never modifies `risk_engine`" rule is structurally enforced,
  not just documented.
- Architectural-compliance confirmation: against `ADR-001`'s pipeline,
  this package occupies no stage position (mirrors `ADR-011`/`ADR-012`/
  `ADR-020`/`ADR-021`'s own non-stage posture). Against `ADR-005` (Risk
  Engine), zero modification — confirmed by `git diff` scope after
  implementation showing no hunks under `risk_engine/`.
- Files to be touched (all new, one package):
  `phantom_pipeline/statistical_risk/{__init__.py,models.py,config.py,
  probability.py,monte_carlo.py,volatility.py,drawdown.py,expectancy.py,
  correlation.py,portfolio.py,metrics.py,logging_sink.py,engine.py}`,
  `tests/phantom_pipeline/statistical_risk/` (new test package),
  `scripts/check_architecture.py` (one-line set addition), `CHANGELOG.md`.
- Boundaries (what this change explicitly does NOT do):
  - Does not modify `risk_engine/`, `compliance_engine/`,
    `execution_validator/`, `position_manager/`, `mt5_bridge/`, `scanner/`,
    or `strategy_engine/` — not one line.
  - Does not wire `StatisticalRiskAssessment` into `orchestrator.py`,
    `paper_trading`, `knowledge`, `research_desk`, or `dashboard` — those
    five are named as future consumers of this package's output (ADR-022
    §7), not packages this plan modifies.
  - Does not apply any recommendation automatically anywhere — the
    package has no method capable of mutating another stage's decision.
  - Does not call an LLM or any external service for any numeric value.

## Validation

- `python3 -m compileall phantom_pipeline tests`: PASS (clean compile,
  including the new package and its tests).
- `python3 -m unittest discover -s tests/phantom_pipeline`: PASS, full
  suite plus new `statistical_risk` tests, zero regressions in any
  existing package's tests.
- `python3 validate.py`: PASS, all checks including the pre-existing
  count, unaffected by this addition.
- `python3 scripts/check_architecture.py`: PASS — 17 packages, no
  circular imports, no cross-package private-state access, no pipeline-
  stage → observer-package import (now covering `statistical_risk` too).
- Code Reviewer sign-off: determinism (seeded Monte Carlo), Hard-Rule-2
  invariant (never recommends above `RiskDecision.approved_risk_percent`),
  and the "no duplicate computation" boundary all verified by dedicated
  tests, not just prose.
- Test Results Analyzer sign-off: full new suite green, zero regressions.
- Integration Engineer (`TEAM.md` RACI): confirms `risk_engine/` and the
  other six named pipeline-stage packages are byte-for-byte unchanged,
  and that `statistical_risk` correctly appears only as an observer in
  the dependency graph.
