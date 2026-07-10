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
- **Own the pending-exposure reservation ledger** (Architecture
  Hardening — closes Red Team Audit Finding 2.2): reserve the exposure
  a `SizingRecommendation` implies at the moment it is produced, and
  release that reservation only when the corresponding
  `ExecutionReport` confirms fill, rejection, cancellation, or a
  configured timeout elapses with no report at all — never on
  submission alone.
- **Apply a minimum-sample-size gate** (closes Red Team Audit Finding
  7.1) before trusting any rolling statistic (Sharpe/Sortino/
  expectancy/VaR/CVaR/risk of ruin) for sizing.

## 3. Public interfaces

```
risk_engine.evaluate(idea: TradeIdea, portfolio: PortfolioSnapshot, now: Clock)
    -> Union[SizingRecommendation, RiskVeto]
risk_engine.portfolio_stats(now: Clock) -> PortfolioStatistics
risk_engine.release_exposure(correlation_id: str, reason: ReleaseReason, now: Clock) -> None
```

`portfolio_stats` is the read surface Research & Learning Engine's
`performance_attribution.py` is required to use (see §9) rather than
recomputing its own rolling statistics.

**Reservation is internal to `evaluate()`, not a separate call**
(deliberate design choice, Architecture Hardening): `evaluate()`
reserves the exposure a `SizingRecommendation` implies as part of the
same call that computes it — atomically, before returning — so there is
no window between "recommendation computed" and "reservation recorded"
for a second, correlated pair's `evaluate()` call to slip through
unreserved. This is why Risk Engine's per-pair `evaluate()` calls
**must be serialized by Runtime** even though Evidence Engine's and
Strategy Engine's earlier per-pair steps may be parallelized (Finding
16.1 still holds for those two; it is narrowed here to exclude this
component's `evaluate()` step specifically, see §11). `release_exposure`
remains a separate call, invoked by Runtime once a command's outcome
(fill, rejection, cancellation, or timeout) is known — see §6 for the
ledger's shape and §12 for the timeout path.

## 4. Inputs

- `TradeIdea` (Strategy Engine).
- `PairEvidence`'s confidence score (Evidence Engine) — read via the
  `TradeIdea.evidence_snapshot` it already carries, not a separate
  call.
- `PairSafetyScore` (Market Intelligence Engine).
- `PortfolioSnapshot`: current open positions, currency exposure,
  account balance/equity — sourced from PhantomBridgeEA's existing
  telemetry. **Must be aggregated correctly under both netting and
  hedging account modes** (closes Red Team Audit Finding 13.1): under
  hedging, multiple tickets per symbol+direction can coexist and must
  each be counted, not collapsed into one net position the way netting
  mode's own aggregate naturally is. `PhantomBridgeEA`'s reported
  `ACCOUNT_MARGIN_MODE` selects which aggregation rule applies.
- Historical trade/return series for Monte Carlo/VaR/Sharpe/Sortino/
  expectancy inputs.

## 5. Outputs

`SizingRecommendation` (pair, direction, volume, tier per the Risk
Schedule, the specific statistics that justified it) **or**
`RiskVeto` (pair, reason: sub-65 score / correlation breach / heat
breach / ruin-probability breach / insufficient sample size), never
both. A successful `SizingRecommendation` also creates an
`ExposureReservation` internally (§6.1's neighbor, §3) before returning.

## 6. Internal data models

| Model | Shape |
|---|---|
| `PortfolioSnapshot` | open positions, per-currency exposure, balance, equity, as of a timestamp |
| `PortfolioStatistics` | expectancy, Sharpe, Sortino, VaR, CVaR, risk of ruin, correlation matrix, portfolio heat, drawdown probability — all as of a timestamp, all read-only |
| `RiskTier` | enum matching the Risk Schedule bands exactly (see §11 table) |
| `SizingRecommendation` | `(pair, direction, volume, tier, justification)` — **structurally incapable of being increased**: no setter/mutator exists on this type; a consumer can only read it or replace it wholesale with a smaller one it computes itself |
| `RiskVeto` | `(pair, reason, contributing_statistic)` — `reason` now includes `INSUFFICIENT_SAMPLE_SIZE` (§7.1) alongside the pre-existing sub-65/correlation/heat/ruin-probability reasons |
| `ExposureReservation` | `(correlation_id, pair, direction, volume, reserved_at, released_at, release_reason)` — the pending-exposure ledger entry (Architecture Hardening, closes Finding 2.2); `correlation.py`/`exposure.py`/`portfolio_heat.py` must include every *unreleased* `ExposureReservation` alongside `PortfolioSnapshot`'s confirmed positions when computing their statistics |
| `ReleaseReason` | enum: `FILLED`, `REJECTED`, `CANCELLED`, `TIMEOUT` |

### 6.1 Minimum-sample-size gate (closes Red Team Audit Finding 7.1)

Below a configured minimum trade count (`config.py`'s
`min_sample_size`, no default assumed here), Sharpe/Sortino/expectancy/
VaR/CVaR/risk-of-ruin are **not** trusted for tier selection — `evaluate()`
forces the "Minimal allocation" tier (or below, if the Risk Schedule's
sub-65 rule already applies) regardless of what the undersampled
statistic itself would suggest, and `portfolio_stats()` marks every
affected statistic as `insufficient_sample` rather than returning a
numeric value a caller could mistake for a trustworthy one.

## 7. Decision authority

The sole statistical-risk authority: no other component computes
Monte Carlo, VaR/CVaR, risk of ruin, Kelly, rolling expectancy/Sharpe/
Sortino, correlation, exposure, or portfolio heat, **and the sole owner
of the pending-exposure reservation ledger** — no other component may
reserve or release exposure. Risk Engine may veto a trade on
statistical grounds; it may not enforce regulatory/prop-firm rules
(that is Compliance Engine's authority, downstream) and it may not
select or reject a strategy (that is Strategy Engine's authority,
upstream) or evaluate news/session conditions (Market Intelligence
Engine's authority).

**Authority restatement (Architecture Hardening):** Portfolio
Statistical Risk Engine holds **sizing authority only** (see the
system-wide authority matrix in `PHANTOM_ARCHITECTURE_HARDENING.md`).

## 8. Dependencies

Strategy Engine (via Runtime, post-tie-break), Evidence Engine (Phase
3a, via the idea's snapshot), Market Intelligence Engine (Phase 3b),
PhantomBridgeEA (Phase 1, position/account telemetry), `phantom/shared/`.

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
- Never leaves an `ExposureReservation` unreleased indefinitely — every
  reservation has a configured timeout (§12) after which it releases
  automatically even with no `ExecutionReport` ever arriving.
- Never reserves or releases exposure for any command it did not itself
  produce a `SizingRecommendation` for (no reservation exists without a
  matching, prior `evaluate()` call).

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
- **Pending-exposure reservation test** (closes Finding 2.2): two
  correlated-pair `TradeIdea`s evaluated in the same cycle — the second
  `evaluate()` call must see the first's `ExposureReservation` already
  counted in `correlation.py`/`portfolio_heat.py`'s inputs, and must be
  sized down or vetoed if the combined (reserved + confirmed) exposure
  would breach a limit that either alone would not.
- **Reservation-release test:** each of the four `ReleaseReason` values
  (filled/rejected/cancelled/timeout) correctly frees the reserved
  exposure for a subsequent evaluation to use.
- **Minimum-sample-size test** (closes Finding 7.1): fewer than
  `config.py`'s configured minimum trades forces "Minimal allocation"
  (or a veto, if score-based rejection already applies) regardless of
  what the raw statistic would otherwise recommend.
- **Hedging/netting aggregation test** (closes Finding 13.1): a fixture
  hedging-mode account with multiple same-symbol tickets is aggregated
  correctly (each ticket counted), and a fixture netting-mode account's
  single aggregate position is not double-counted.

## 11. Performance requirements

Monte Carlo simulation parameters (iteration count) must be tunable in
`config.py` to trade off runtime against precision; `evaluate()` must
complete within the same decision-cycle budget as Strategy Engine's
`evaluate()` (target validated during implementation, not guaranteed
here). **Concurrency note (Architecture Hardening):** unlike Evidence
Engine's and Strategy Engine's per-pair steps, Risk Engine's
`evaluate()` calls must be invoked **serially** by Runtime within a
cycle (never in parallel across pairs), because `evaluate()`'s internal
exposure reservation (§3) is shared, order-dependent state across
correlated pairs.

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
| An `ExposureReservation`'s command never receives an `ExecutionReport` | Released automatically after a configured `reservation_timeout_seconds` (`config.py`, no default assumed here) with `ReleaseReason.TIMEOUT` — prevents a lost report (the already-documented Phase 1 limitation) from permanently locking exposure out of future sizing decisions. |

## 13. Security considerations

In-process library, no external network surface. Historical trade data
read from internal storage only; no external market-data credentials
live in this component.

## 14. Logging requirements

`logging_sink.py` logs every `evaluate()` call's inputs (idea, tier,
contributing statistics) and outcome (recommendation or veto with
reason), plus every reservation create/release event with its reason.
`metrics.py` tracks veto counts by reason (including
`INSUFFICIENT_SAMPLE_SIZE`), tier distribution, Monte Carlo runtime,
portfolio heat over time, and current outstanding-reservation count (a
sustained high count is itself an operational signal worth alerting
on).
