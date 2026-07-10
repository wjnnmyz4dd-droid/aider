# Technical Specification — Portfolio Statistical Risk Engine

Specification only. Cross-references `PHANTOM_FINAL_ARCHITECTURE.md`
and `PHANTOM_IMPLEMENTATION_ROADMAP.md` §3.1 and Phase 5.

## 1. Purpose

The single statistical-risk authority: converts a `TradeIdea` plus
current portfolio state into either a concrete `SizingRecommendation`
or a veto, using the locked Risk Schedule as the sole score-to-tier
mapping.

## 2. Responsibilities

- Compute Monte Carlo simulations, VaR/CVaR, risk of ruin, rolling
  expectancy, rolling Sharpe/Sortino, correlation matrix, currency
  exposure, portfolio heat, and drawdown probability from trade/
  position history.
- Apply the Risk Schedule to Evidence Engine's confidence score to
  select an allocation tier.
- Apply Market Intelligence Engine's Pair Safety Score as an
  additional scaling input.
- Produce a final `SizingRecommendation` (or veto) per `TradeIdea`.
- Offer Kelly-criterion output strictly as an advisory figure, never
  auto-applied to sizing without passing through `position_sizing.py`'s
  own cap logic.

## 3. Public interfaces

```
risk_engine.evaluate(idea: TradeIdea, portfolio: PortfolioSnapshot, now: Clock)
    -> Union[SizingRecommendation, RiskVeto]
risk_engine.portfolio_stats(now: Clock) -> PortfolioStatistics
```

`portfolio_stats` is the read surface Research & Learning Engine's
`performance_attribution.py` is required to use (see §9) rather than
recomputing its own rolling statistics.

## 4. Inputs

- `TradeIdea` (Strategy Engine).
- `PairEvidence`'s confidence score (Evidence Engine) — read via the
  `TradeIdea.evidence_snapshot` it already carries, not a separate
  call.
- `PairSafetyScore` (Market Intelligence Engine).
- `PortfolioSnapshot`: current open positions, currency exposure,
  account balance/equity — sourced from PhantomBridgeEA's existing
  telemetry.
- Historical trade/return series for Monte Carlo/VaR/Sharpe/Sortino/
  expectancy inputs.

## 5. Outputs

`SizingRecommendation` (pair, direction, volume, tier per the Risk
Schedule, the specific statistics that justified it) **or**
`RiskVeto` (pair, reason: sub-65 score / correlation breach / heat
breach / ruin-probability breach), never both.

## 6. Internal data models

| Model | Shape |
|---|---|
| `PortfolioSnapshot` | open positions, per-currency exposure, balance, equity, as of a timestamp |
| `PortfolioStatistics` | expectancy, Sharpe, Sortino, VaR, CVaR, risk of ruin, correlation matrix, portfolio heat, drawdown probability — all as of a timestamp, all read-only |
| `RiskTier` | enum matching the Risk Schedule bands exactly (see §11 table) |
| `SizingRecommendation` | `(pair, direction, volume, tier, justification)` — **structurally incapable of being increased**: no setter/mutator exists on this type; a consumer can only read it or replace it wholesale with a smaller one it computes itself |
| `RiskVeto` | `(pair, reason, contributing_statistic)` |

## 7. Decision authority

The sole statistical-risk authority: no other component computes
Monte Carlo, VaR/CVaR, risk of ruin, Kelly, rolling expectancy/Sharpe/
Sortino, correlation, exposure, or portfolio heat. Risk Engine may
veto a trade on statistical grounds; it may not enforce regulatory/
prop-firm rules (that is Compliance Engine's authority, downstream)
and it may not select or reject a strategy (that is Strategy Engine's
and Market Intelligence Engine's authority, upstream).

## 8. Dependencies

Strategy Engine (Phase 4a), Evidence Engine (Phase 3a, via the idea's
snapshot), Market Intelligence Engine (Phase 3b), PhantomBridgeEA
(Phase 1, position/account telemetry), `phantom/shared/`.

## 9. Explicit non-responsibilities

- Never enforces drawdown/trading-day/position-count/trade-count
  limits — those are Compliance Engine's rules, evaluated after this
  component, never duplicated here.
- Never re-derives Evidence Engine's score or Market Intelligence's
  scores — consumes them as given.
- Never executes anything — has no dependency on submitting commands
  to PhantomBridgeEA.
- Never lets Kelly's raw output become a size directly —
  `position_sizing.py` is the only file permitted to produce the final
  `volume` field, and it must apply the Risk Schedule's tier cap
  regardless of what Kelly alone would suggest.
- **Must never be recomputed by another component.** Research &
  Learning Engine's `performance_attribution.py` reads
  `portfolio_stats()`'s stored values; it does not, and structurally
  cannot (per its own boundary test), reimplement Sharpe/Sortino/
  expectancy independently.

## 10. Test plan

- Unit tests per statistical module against fixed-seed inputs with
  hand-verified expected outputs (Monte Carlo/VaR/CVaR/risk of ruin/
  Kelly/expectancy/Sharpe/Sortino).
- Risk Schedule table test: every integer score 65–100 maps to exactly
  the tier in §11's table; every score below 65 produces a `RiskVeto`,
  with no gap or overlap between bands.
- Determinism test: identical inputs (including RNG seed) always
  produce an identical `SizingRecommendation`/`RiskVeto`.
- Type-level test: attempt to construct a larger `SizingRecommendation`
  from an existing one via any public method — must not compile/must
  raise, proving the "cannot be increased" property structurally.
- Structural-boundary test: `phantom/risk/` is the only package
  computing Sharpe/Sortino/expectancy (grep-based, mirroring
  `test_structural_boundary.py`'s pattern).

## 11. Performance requirements

Monte Carlo simulation parameters (iteration count) must be tunable in
`config.py` to trade off runtime against precision; `evaluate()` must
complete within the same decision-cycle budget as Strategy Engine's
`evaluate()` (target validated during implementation, not guaranteed
here).

**Risk Schedule (locked, restated for this spec's completeness):**

| Score band | Tier |
|---|---|
| 95–100 | Maximum approved risk |
| 90–94 | High risk allocation |
| 85–89 | Standard allocation |
| 80–84 | Reduced allocation |
| 75–79 | Conservative allocation |
| 70–74 | Minimal allocation |
| 65–69 | Minimum qualified trade |
| Below 65 | Reject |

## 12. Failure modes

| Failure | Expected behavior |
|---|---|
| Insufficient historical data for a statistic (e.g. too few trades for Sharpe) | Explicit "insufficient data" state on that statistic, propagated as a veto reason if it blocks a required calculation — never a fabricated/default value. |
| Monte Carlo simulation exceeds its time budget | Configurable timeout; on timeout, veto with reason `RISK_STATISTIC_TIMEOUT` rather than proceeding on a partial result. |
| PhantomBridgeEA's position telemetry stale/unavailable | Fail closed — no `SizingRecommendation` produced without current portfolio state. |

## 13. Security considerations

In-process library, no external network surface. Historical trade data
read from internal storage only; no external market-data credentials
live in this component.

## 14. Logging requirements

`logging_sink.py` logs every `evaluate()` call's inputs (idea, tier,
contributing statistics) and outcome (recommendation or veto with
reason). `metrics.py` tracks veto counts by reason, tier distribution,
Monte Carlo runtime, and portfolio heat over time.
