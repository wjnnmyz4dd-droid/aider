"""Monte Carlo Validation (ADR-030 §5.9): randomized trade-ordering
replay, validating drawdown, recovery, risk of ruin, and confidence.
Reuses `risk_engine.monte_carlo.run_monte_carlo` and
`risk_engine.statistics.compute_statistical_metrics` directly -- zero
new simulation code (ADR-030 Hard Rule 5)."""

from __future__ import annotations

from typing import Optional, Sequence

from titan_protocol.risk_engine.config import RiskEngineConfig
from titan_protocol.risk_engine.models import TradeHistory, TradeResult
from titan_protocol.risk_engine.monte_carlo import run_monte_carlo
from titan_protocol.risk_engine.statistics import compute_statistical_metrics
from titan_protocol.research_engine.models import ClosedTrade, executed_trades

from .config import ValidationEngineConfig
from .models import MonteCarloValidationResult


def _to_trade_result(trade: ClosedTrade) -> TradeResult:
    return TradeResult(
        pair=trade.pair, strategy_id=trade.strategy_id, risk_r=trade.risk_r, r_multiple=trade.r_multiple,
        opened_at=trade.opened_at, closed_at=trade.closed_at, won=trade.won,
    )


def run_monte_carlo_validation(
    trades: Sequence[ClosedTrade], config: ValidationEngineConfig,
) -> Optional[MonteCarloValidationResult]:
    executed = executed_trades(trades)
    if not executed:
        return None

    history = TradeHistory(results=tuple(_to_trade_result(t) for t in executed))
    risk_config = RiskEngineConfig(
        min_trade_history_for_statistics=config.research_config.bucket_statistics_min_sample_size,
        statistics_window=max(len(executed), 1),
        risk_of_ruin_simulations=config.research_config.bucket_risk_of_ruin_simulations,
        monte_carlo_sequence_length=config.research_config.bucket_monte_carlo_sequence_length,
        monte_carlo_simulations=config.research_config.bucket_risk_of_ruin_simulations,
    )

    monte_carlo = run_monte_carlo(history, risk_config)
    statistics = compute_statistical_metrics(history, risk_config)
    if monte_carlo is None:
        return None

    return MonteCarloValidationResult(
        sample_size=len(executed), simulations_run=monte_carlo.simulations_run,
        expected_drawdown=monte_carlo.expected_drawdown, worst_case_drawdown=monte_carlo.worst_case_drawdown,
        risk_of_ruin=statistics.risk_of_ruin, confidence_note=monte_carlo.risk_distribution_summary,
    )


__all__ = ["run_monte_carlo_validation"]
