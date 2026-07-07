"""Statistical Risk Management (`ADR-022`).

**Not a 17th pipeline stage.** Exactly like `knowledge` (`ADR-020`) and
`research_desk` (`ADR-021`), this package is a cross-cutting observer
with no position in the trading decision chain — it reads already-
produced, immutable records after the fact and computes derived
statistics about them. It holds no decision, execution, risk,
compliance, or scoring authority (`ADR-022` Hard Rules 1-3); its sole
output, `statistical_recommendation`, is advisory-only and structurally
incapable of ever recommending more risk than the deterministic Risk
Engine (`ADR-005`) already approved. No pipeline-stage package imports it
(`scripts/check_architecture.py` enforces this).

See `docs/adr/ADR-022-statistical-risk-management.md` and
`docs/plans/statistical-risk-management.md` for the full research/plan
record.
"""

from __future__ import annotations

from .config import DEFAULT_CONFIG, STATISTICAL_RISK_VERSION, StatisticalRiskConfig
from .dashboard import StatisticalRiskDashboardBuilder, trend_point_from_assessment
from .engine import (
    StatisticalRiskEngine,
    conditional_value_at_risk,
    kelly_criterion,
    most_conservative,
    recommendation_for_ruin,
    regime_confidence_score,
    value_at_risk,
)
from .expectancy import (
    closed_trade_pnls,
    confidence_interval_bounds,
    rolling_expectancy,
    rolling_profit_factor,
    rolling_sharpe_ratio,
    rolling_sortino_ratio,
    rolling_win_rate,
    rolling_window_pnls,
)
from .logging_sink import log_assessment
from .metrics import StatisticalRiskMetrics
from .models import (
    SCHEMA_VERSION,
    ConfidenceInterval,
    CorrelationState,
    MonteCarloResult,
    RiskRecommendation,
    StatisticalRiskAssessment,
    StatisticalRiskDashboardSnapshot,
    StatisticalRiskTrendPoint,
    StatisticalRiskTrendReport,
    VolatilityState,
)

__all__ = [
    "SCHEMA_VERSION",
    "STATISTICAL_RISK_VERSION",
    "DEFAULT_CONFIG",
    "StatisticalRiskConfig",
    "RiskRecommendation",
    "VolatilityState",
    "CorrelationState",
    "MonteCarloResult",
    "ConfidenceInterval",
    "StatisticalRiskAssessment",
    "StatisticalRiskTrendPoint",
    "StatisticalRiskTrendReport",
    "StatisticalRiskDashboardSnapshot",
    "StatisticalRiskDashboardBuilder",
    "trend_point_from_assessment",
    "StatisticalRiskEngine",
    "most_conservative",
    "value_at_risk",
    "conditional_value_at_risk",
    "kelly_criterion",
    "regime_confidence_score",
    "recommendation_for_ruin",
    "closed_trade_pnls",
    "rolling_window_pnls",
    "rolling_win_rate",
    "rolling_profit_factor",
    "rolling_expectancy",
    "rolling_sharpe_ratio",
    "rolling_sortino_ratio",
    "confidence_interval_bounds",
    "StatisticalRiskMetrics",
    "log_assessment",
]
