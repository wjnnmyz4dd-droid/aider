"""Portfolio Statistical Risk Engine (Phase 2D).

The only authority responsible for determining whether statistical
conditions justify risk, recommended position size, portfolio exposure,
and confidence-adjusted allocation. It never decides direction, strategy
selection, trade execution, news approval, or prop-firm compliance --
it approves or rejects a strategy-selected setup and explains why. See
`docs/adr/ADR-027-portfolio-statistical-risk-engine.md`.
"""

from __future__ import annotations

from .config import DEFAULT_CONFIDENCE_SCHEDULE, RISK_ENGINE_VERSION, RiskEngineConfig
from .confidence import confidence_tier_for_evidence_score
from .correlation import compute_correlation_status, estimate_pair_correlation
from .engine import RiskEngine
from .explainability import build_risk_snapshot
from .exposure import compute_exposure_summary, split_currency_pair
from .gate import check_evidence_gate
from .logging_sink import log_risk_snapshot
from .metrics import RiskEngineMetrics
from .models import (
    SCHEMA_VERSION,
    ConfidenceTier,
    CorrelationStatus,
    DataQuality,
    Direction,
    ExposureSummary,
    MonteCarloResult,
    OpenPosition,
    PortfolioState,
    PositionSizeRecommendation,
    RejectionReason,
    RiskSnapshot,
    RMultipleSummary,
    StatisticalMetrics,
    TradeHistory,
    TradeResult,
    VolatilityAdjustment,
)
from .monte_carlo import run_monte_carlo, simulate_equity_paths
from .position_sizing import compute_position_size
from .reservation import Reservation, ReservationLedger
from .safety_limits import check_safety_limits
from .statistics import compute_statistical_metrics
from .volatility import compute_volatility_adjustment

__all__ = [
    "RISK_ENGINE_VERSION",
    "DEFAULT_CONFIDENCE_SCHEDULE",
    "RiskEngineConfig",
    "SCHEMA_VERSION",
    "RiskEngine",
    "RiskEngineMetrics",
    "RejectionReason",
    "DataQuality",
    "Direction",
    "OpenPosition",
    "PortfolioState",
    "TradeResult",
    "TradeHistory",
    "ExposureSummary",
    "CorrelationStatus",
    "RMultipleSummary",
    "StatisticalMetrics",
    "MonteCarloResult",
    "VolatilityAdjustment",
    "ConfidenceTier",
    "PositionSizeRecommendation",
    "RiskSnapshot",
    "check_evidence_gate",
    "confidence_tier_for_evidence_score",
    "compute_exposure_summary",
    "split_currency_pair",
    "compute_correlation_status",
    "estimate_pair_correlation",
    "compute_statistical_metrics",
    "run_monte_carlo",
    "simulate_equity_paths",
    "compute_volatility_adjustment",
    "compute_position_size",
    "check_safety_limits",
    "build_risk_snapshot",
    "log_risk_snapshot",
    "Reservation",
    "ReservationLedger",
]
