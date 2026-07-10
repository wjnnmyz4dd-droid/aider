# ADR-027 — Portfolio Statistical Risk Engine

Status: **Accepted**

Owner: Backend Architect (per `TEAM.md`'s RACI, the same Accountable
role named for `ADR-005`'s deterministic Risk Engine — this is the
pipeline-stage authority for sizing/exposure)

Consulted: Quant Validation Engineer (statistical methodology —
expectancy, VaR/CVaR, Monte Carlo, Sharpe/Sortino/Calmar/Ulcer — advisory
lens only, per its charter; never modifies this engine's logic directly)

Accepted By: User direction, this session (explicit, full
specification: mission, input restrictions, the 65-point evidence gate,
a configurable confidence-scaling schedule, 10 named portfolio-risk
computations, 8 named correlation computations, 15 named statistical
computations, Monte Carlo simulation, volatility management, 6 named
position-sizing methods, 9 named safety limits, the `RiskSnapshot`
output shape, architecture rules, performance targets, and a
10-category testing mandate) — the same in-session approving authority
already used to accept `ADR-024` through `ADR-026`.

Reviewed by: (post-hoc, this session) — checked against `ADR-005`
(Risk Engine, `phantom_pipeline/`) and `ADR-022` (Statistical Risk
Management, `phantom_pipeline/`) before acceptance; see §0.

Date: 2026-07-10

Depends on: `ADR-024-evidence-engine.md` (Accepted, Amendment 1 —
consumes `EvidenceSnapshot` read-only), `ADR-025-market-intelligence-engine.md`
(Accepted — consumes `MarketIntelligenceSnapshot` read-only),
`ADR-026-strategy-engine.md` (Accepted — consumes `StrategySnapshot`
read-only). Imports nothing else.

---

# 0. Relationship to existing architecture

Two existing `phantom_pipeline/` packages overlap this ADR's scope,
disclosed rather than hidden:

- **`ADR-005` Risk Engine (`phantom_pipeline/risk_engine/`)** — the
  deterministic sizing/constraints authority in the old pipeline
  (`models.py`, `config.py`, `constraints.py`, `engine.py`).
- **`ADR-022` Statistical Risk Management (`phantom_pipeline/statistical_risk/`)**
  — VaR/CVaR, Monte Carlo, correlation, expectancy, drawdown, explicitly
  scoped there as a **cross-cutting observer**, never a pipeline
  authority, reading `analytics.models.TradeProvenanceRecord` after the
  fact.

This ADR's Portfolio Statistical Risk Engine is neither of those: it
folds both concerns (deterministic sizing/exposure gating **and**
statistical analysis) into one pipeline-stage authority, per the task
spec's own instruction that it is "the ONLY authority responsible for
... whether statistical conditions justify risk ... recommended
position size ... portfolio exposure ... confidence-adjusted
allocation." This is a real, deliberate departure from the old
architecture's split (deterministic sizing kept separate from
statistical analysis, which stayed advisory-only), made because the
task explicitly requires it. It resolves exactly the way `ADR-024`
through `ADR-026` already resolved the same class of question for this
session's `phantom/` track: **fresh, independent, no reuse.**
`phantom/risk_engine/` is built clean-room, imports nothing from
`phantom_pipeline/`, and does not share a model, config, constraint
function, or Monte Carlo implementation with either
`phantom_pipeline/risk_engine/` or `phantom_pipeline/statistical_risk/`.
Both are mined for proven formulas only (VaR/CVaR definitions, Sharpe/
Sortino/Calmar/Ulcer formulas are standard, not proprietary), never
imported.

---

# 0a. Resolved design question: portfolio state and trade history inputs

The task's own input list says "Consume ONLY: EvidenceSnapshot,
MarketIntelligenceSnapshot, StrategySnapshot," but its own required
computations (Portfolio Heat, Currency/Symbol Exposure, Correlation,
Rolling Expectancy, VaR/CVaR, Drawdown, Monte Carlo, Kelly Criterion,
Daily/Weekly/Monthly Risk Limits) are only computable from data that
exists in none of the three named snapshots: currently-open positions
and historical trade outcomes. The task simultaneously forbids direct
communication with the Bridge, and no Position Manager exists yet to be
a source (`ADR-009` is unimplemented).

Put directly to the user before any code was written, the resolution
(explicit, this session): **add two new, optional, caller-supplied
input types** — `PortfolioState` (currently-open positions) and
`TradeHistory` (a sequence of realized, per-pair, per-strategy trade
outcomes) — passed as parameters to `evaluate()`/`evaluate_batch()`,
**never fetched by this engine itself.** Whatever orchestrates the
pipeline (today: a caller in a test or a future orchestrator; later:
the Position Manager / Analytics stage) is responsible for supplying
them. This is consistent with "consume ONLY the 3 snapshots" read as
"never compute evidence, strategy, or news facts a second time" — it
does not forbid accepting the portfolio's own state, which is not an
upstream engine's calculation to duplicate in the first place.

Both inputs default to `None`/empty, and per the task's own explicit
rule ("Unknown statistical state defaults to fail closed"):

- `portfolio_state=None` → zero open positions assumed for exposure
  arithmetic (nothing to conflict with), but every exposure/correlation
  field is tagged `data_quality=UNKNOWN` in the output rather than
  silently reported as "0% heat, all clear."
- `trade_history=None` or below `config.min_trade_history_for_statistics`
  → every history-dependent statistic (expectancy, VaR, CVaR, Sharpe,
  Sortino, Calmar, Ulcer, recovery factor, profit factor, risk of ruin,
  Kelly, Monte Carlo) is reported as `sufficient_data=False`/`None`, and
  — this is the fail-closed behavior — **position sizing is capped at
  the lowest confidence tier (0.25R) regardless of the Evidence Score's
  own band**, until real history exists to justify anything larger.

This mirrors the already-established `EvidenceSnapshot`-expansion
precedent (`ADR-024` Amendments 1–2: "expand the snapshot, not create a
second analyzer") applied to a case where there is no existing upstream
snapshot to expand — so a new, narrowly-scoped, caller-supplied type is
the correct analogous move instead.

---

# Pipeline position

Per `ADR-001`, this is pipeline stage 5: **Market Data → Scanner →
Strategy Engine → Scoring Engine → Risk Engine → Compliance Engine →
Execution Validator → MT5 Bridge → Position Manager → Analytics.** This
implementation occupies the Risk Engine slot for the `phantom/` track.
Not wired into any execution pipeline yet — no orchestrator exists in
`phantom/` at this phase. Per the user's stated sequence, this is Phase
2D; Prop Firm Compliance Engine, Research & Learning Engine, and
Validation remain unimplemented and out of scope here.

---

# 1. Mission

Answers exactly one question per pair: **"Do statistical conditions
justify risk here, and if so, how much?"** It never decides direction,
strategy selection, trade execution, news approval, or prop-firm
compliance — those remain, respectively, the Strategy Engine's (frozen,
`ADR-026`), the not-yet-built Compliance Engine's, and the not-yet-built
Execution Validator's own questions.

**Compliance may only reduce size or reject a trade this engine
approved — never increase it.** This engine's own internal logic
follows the identical discipline: no sizing method here is ever allowed
to push the final recommendation above what the confidence-tier
schedule and every configured limit would otherwise allow. Capital
preservation overrides profit (CLAUDE.md §2) is the tiebreaker whenever
two sizing methods disagree — the smaller number always wins.

---

# 2. Inputs

- `EvidenceSnapshot` (`ADR-024`, read-only) — `report.score.composite`
  drives the 65-point gate and the confidence-tier schedule;
  `volatility` drives volatility-adjusted sizing.
- `MarketIntelligenceSnapshot` (`ADR-025`, read-only) —
  `pair_safety.liquidity` (spread/liquidity score) contributes to
  volatility-adjusted sizing as a liquidity-risk factor. Never consulted
  for news-approval purposes — that would violate "never decides news
  approval."
- `StrategySnapshot` (`ADR-026`, read-only) — a trade cannot be sized
  without a winning strategy already selected upstream; if
  `StrategySnapshot.rejected`, this engine rejects too
  (`NO_QUALIFIED_STRATEGY`), without ever selecting a strategy itself.
- `PortfolioState` (new, optional, caller-supplied — §0a).
- `TradeHistory` (new, optional, caller-supplied — §0a).

No direct communication with the Bridge, Trading Economics, Forex
Factory, Evidence Engine internals, or Strategy Engine internals.
AST-verified (`test_architecture.py`), exactly as `ADR-026` verified its
own upstream-import boundary.

---

# 3. Hard Rules

1. **65-point evidence gate.** `EvidenceSnapshot.report.score.composite < 65`
   → reject immediately, reason `INSUFFICIENT_EVIDENCE`, no further
   evaluation (no statistical sizing, no Monte Carlo, nothing computed
   past the gate check).
2. **No strategy, no trade.** `StrategySnapshot.rejected` → reject,
   reason `NO_QUALIFIED_STRATEGY`.
3. **Confidence-scaling schedule is configurable and owned only by this
   engine.** No other package may define or override it.
4. **Kelly Criterion is always fractional and capped**, and only ever
   acts as a ceiling on the confidence-tier base size — it can shrink
   the recommendation, never grow it beyond the schedule.
5. **Pending exposure reservations are atomic.** Two concurrent
   `evaluate()` calls competing for the same portfolio-heat budget must
   never both be approved in a way that together breaches a configured
   limit — enforced with a real lock around the reserve-and-check step
   (`reservation.py`), not merely documented.
6. **Unknown correlation and unknown statistical state fail closed**
   (§0a) — never silently treated as "no risk" or "full confidence."
7. **No randomness in live sizing.** Every sizing/exposure/limit
   decision is a pure function of its inputs — reproducible byte-for-
   byte across repeated calls with the same inputs. Monte Carlo *is*
   permitted to use a pseudo-random sequence, but only a **seeded**
   one (`config.monte_carlo_seed` by default, or an explicit seed
   parameter), so the same inputs always reproduce the same simulated
   distribution — and its output is advisory-only, attached to
   `RiskSnapshot` for explanation, never consumed by the sizing
   arithmetic itself. `test_determinism.py` and
   `test_architecture.py` both verify this split.
8. **No duplicate calculations.** Evidence score, strategy
   qualification, and news/session/liquidity facts are read from the
   three snapshots exactly as computed upstream — never recomputed.
9. **No trade decision vocabulary.** No `BUY`/`SELL`, no order type, no
   execution method, anywhere in this package (AST-verified, the same
   pattern `ADR-026`'s `test_architecture.py` established).
10. **No FTMO/compliance rules here.** Prop-firm-specific limits belong
    to the not-yet-built Compliance Engine; this engine's safety limits
    are generic risk-management limits only (daily/weekly/monthly R,
    portfolio heat, correlation, position counts), all named and
    config-driven, none prop-firm-specific.

---

# 4. Architecture

```
phantom/risk_engine/
    __init__.py
    models.py            all dataclasses/enums (see §5)
    config.py             RiskEngineConfig -- every threshold named, confidence
                         schedule configurable
    gate.py                the 65-point evidence hard gate
    confidence.py          Evidence Score -> confidence tier -> base R lookup
    exposure.py            portfolio heat, currency/long/short/net/symbol/
                         sector exposure, from PortfolioState + pending
                         reservations
    correlation.py         currency/pair/rolling correlation (derived from
                         TradeHistory's per-pair R-multiple sequences),
                         clusters, highly-correlated positions, negative
                         correlation, cross-currency exposure, limit checks
    statistics.py          rolling expectancy, win/loss distribution, risk of
                         ruin, VaR, CVaR, max drawdown estimate, recovery
                         factor, profit factor, rolling Sharpe/Sortino,
                         Calmar, Ulcer Index, R-multiple analysis
    volatility.py          ATR-adjusted / volatility-adjusted sizing
                         multiplier, from EvidenceSnapshot.volatility +
                         MarketIntelligenceSnapshot liquidity
    monte_carlo.py         seeded, deterministic simulation -- advisory only
    position_sizing.py     fixed fractional, confidence scaling, volatility
                         scaling, fractional-capped Kelly, min/max clamp,
                         lot normalization
    safety_limits.py       daily/weekly/monthly risk limit, portfolio heat
                         limit, correlation limit, max open positions, max
                         positions per pair, max currency exposure
    reservation.py          thread-safe pending-exposure reservation ledger
    explainability.py       RiskSnapshot assembly (reasons, warnings)
    engine.py              RiskEngine.evaluate()/evaluate_batch()
    logging_sink.py, metrics.py

tests/phantom/risk_engine/
    _fixtures.py, test_gate.py, test_confidence.py, test_exposure.py,
    test_correlation.py, test_statistics.py, test_monte_carlo.py,
    test_position_sizing.py, test_safety_limits.py, test_reservation.py,
    test_engine.py, test_boundary.py, test_determinism.py,
    test_performance.py, test_regression.py, test_architecture.py

docs/adr/ADR-027-portfolio-statistical-risk-engine.md
```

No cycles: `models.py`/`config.py` underlie everything else;
`gate.py`/`confidence.py`/`exposure.py`/`correlation.py`/`statistics.py`/
`volatility.py`/`monte_carlo.py`/`reservation.py` are independent leaves
consumed only by `position_sizing.py`, `safety_limits.py`,
`explainability.py`, and `engine.py`; `engine.py` is the sole
orchestrator, imported only by `__init__.py`.

---

# 5. Data models (summary — see `models.py` for full field lists)

`RejectionReason` (enum: `INSUFFICIENT_EVIDENCE`, `NO_QUALIFIED_STRATEGY`,
`PORTFOLIO_HEAT_EXCEEDED`, `CORRELATION_LIMIT_EXCEEDED`,
`DAILY_RISK_LIMIT_EXCEEDED`, `WEEKLY_RISK_LIMIT_EXCEEDED`,
`MONTHLY_RISK_LIMIT_EXCEEDED`, `MAX_OPEN_POSITIONS_EXCEEDED`,
`MAX_POSITIONS_PER_PAIR_EXCEEDED`, `MAX_CURRENCY_EXPOSURE_EXCEEDED`),
`OpenPosition`, `PortfolioState`, `TradeResult`, `TradeHistory`,
`ExposureSummary`, `CorrelationStatus`, `StatisticalMetrics`,
`MonteCarloResult`, `VolatilityAdjustment`, `PositionSizeRecommendation`,
`RiskSnapshot` (approved, approved_risk_r, recommended position size,
confidence tier, portfolio heat, correlation status, exposure summary,
statistical metrics, Monte Carlo result, reasons, warnings, rejection
reason — no execution, no compliance decision, ever).

---

# 6. Testing mandate

Unit, Monte Carlo verification, boundary, portfolio, correlation,
stress, concurrency, determinism, regression, architecture — 10
categories, mirroring `ADR-026`'s 9 plus a dedicated Monte Carlo
category this task explicitly names.

---

# 7. Performance

28+ Forex pairs, concurrent evaluation, thread safe, deterministic
(outside the seeded-and-isolated Monte Carlo path), no duplicate
statistical calculations across a batch call.
