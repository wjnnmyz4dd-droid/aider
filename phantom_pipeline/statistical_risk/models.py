"""Statistical Risk Management input/output objects (`ADR-022` §3).

`StatisticalRiskAssessment` is this package's sole exported judgment type
— an immutable, advisory-only record. No field on it, or on any type in
this module, is capable of representing a trade approval, rejection,
size, or execution instruction (`ADR-022` Hard Rule 1). Every `Optional`
field is `None` exactly when the corresponding capability has no honest
data source yet (e.g. fewer than `StatisticalRiskConfig.min_sample_size`
closed trades) — never a fabricated placeholder (`ADR-022` Hard Rule 7).

`volatility_state`/`correlation_state` reuse `scanner.models.VolatilityLabel`
and `risk_engine.models.OpenPosition`'s own `correlation_bucket` vocabulary
rather than inventing parallel ones (`ADR-022` §2, "No duplicate
computation").
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Optional, Tuple

from ..scanner.models import VolatilityLabel

SCHEMA_VERSION = 1


class RiskRecommendation(Enum):
    """The four, and only four, advisory values this package may ever
    produce (`ADR-022` §1, Hard Rule 2). Ordered from least to most
    restrictive; `statistical_recommendation` never implies a risk
    percent above whatever the deterministic Risk Engine already
    approved — this package holds no mechanism to apply any of these
    values itself."""

    NORMAL_RISK = "NORMAL_RISK"
    REDUCE_RISK_25 = "REDUCE_RISK_25"
    REDUCE_RISK_50 = "REDUCE_RISK_50"
    SKIP_HIGH_RISK = "SKIP_HIGH_RISK"


@dataclass(frozen=True)
class VolatilityState:
    """ATR and realized-volatility read, plus the qualitative label
    (`ADR-022` §2) — `label` reuses `scanner.models.VolatilityLabel`
    rather than a second, parallel vocabulary. `atr`/`realized_volatility`
    are `None` when fewer than two bars were supplied (Hard Rule 7)."""

    label: VolatilityLabel
    atr: Optional[float]
    realized_volatility: Optional[float]
    ratio_to_average: Optional[float]


@dataclass(frozen=True)
class CorrelationState:
    """Correlation-bucket concentration read from `risk_engine.models.OpenPosition.correlation_bucket`
    (`ADR-022` §2) — never a second, independent bucket assignment."""

    bucket_exposure_count: Mapping[str, int]
    most_concentrated_bucket: Optional[str]
    max_bucket_concentration_count: int
    flagged_buckets: Tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "bucket_exposure_count", dict(self.bucket_exposure_count))
        object.__setattr__(self, "flagged_buckets", tuple(self.flagged_buckets))


@dataclass(frozen=True)
class MonteCarloResult:
    """One seeded Monte Carlo simulation's output (`ADR-022` §1,
    Hard Rule 6) — `seed` is recorded so the exact run is reproducible;
    two calls with the same `seed` and the same input trade sequence
    always produce byte-identical fields on this type."""

    iterations: int
    seed: int
    starting_equity: float
    mean_final_equity: float
    median_final_equity: float
    worst_final_equity: float
    best_final_equity: float
    probability_of_ruin: float
    mean_max_drawdown_pct: float


@dataclass(frozen=True)
class ConfidenceInterval:
    """A per-trade (or per-window) confidence interval on expected return
    (`ADR-022` §1, capability 20) — computed from the rolling trade
    sample's mean/standard-error, never fabricated. `None` bounds mean
    the sample was too small to compute honestly (Hard Rule 7)."""

    trace_id: str
    point_estimate: Optional[float]
    lower_bound: Optional[float]
    upper_bound: Optional[float]
    confidence_level: float
    sample_size: int


@dataclass(frozen=True)
class StatisticalRiskAssessment:
    """The Statistical Risk Manager's sole output type (`ADR-022` §1).

    Advisory only (`ADR-022` Hard Rule 3): the deterministic Risk Engine
    (`ADR-005`) decides whether to use `statistical_recommendation` at
    all; this type carries no method or field capable of applying it.
    `trace_id` is the caller-supplied identifier this assessment was
    computed for (e.g. a `RiskDecision.trace_id`, propagated verbatim,
    never invented) — `None` is not a valid value; a portfolio-level
    (not trade-specific) assessment uses a caller-chosen batch identifier
    instead.
    """

    schema_version: int
    trace_id: str
    confidence_score: float
    risk_of_ruin: Optional[float]
    probability_of_drawdown: Optional[float]
    expected_drawdown: Optional[float]
    expected_return: Optional[float]
    rolling_expectancy: Optional[float]
    rolling_profit_factor: Optional[float]
    rolling_win_rate: Optional[float]
    sharpe_ratio: Optional[float]
    sortino_ratio: Optional[float]
    value_at_risk: Optional[float]
    conditional_value_at_risk: Optional[float]
    portfolio_heat: Optional[float]
    volatility_state: VolatilityState
    correlation_state: CorrelationState
    statistical_recommendation: RiskRecommendation


__all__ = [
    "SCHEMA_VERSION",
    "RiskRecommendation",
    "VolatilityState",
    "CorrelationState",
    "MonteCarloResult",
    "ConfidenceInterval",
    "StatisticalRiskAssessment",
]
