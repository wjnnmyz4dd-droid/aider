"""Safety limits: daily/weekly/monthly risk, portfolio heat, correlation,
max open positions, max positions per pair, max currency exposure
(ADR-027 §3). Every check here can only ever reject or pass -- none of
them can increase the approved risk above what the confidence-tier
schedule already set (ADR-027 §1).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional, Tuple

from .config import RiskEngineConfig
from .exposure import split_currency_pair
from .models import CorrelationStatus, ExposureSummary, PortfolioState, RejectionReason, TradeHistory


def _period_risk_r(trade_history: Optional[TradeHistory], portfolio_state: Optional[PortfolioState], now: datetime, since: datetime) -> float:
    risk = 0.0
    if trade_history is not None:
        risk += sum(r.risk_r for r in trade_history.results if since <= r.opened_at <= now)
    if portfolio_state is not None:
        risk += sum(p.size_r for p in portfolio_state.open_positions if since <= p.opened_at <= now)
    return risk


def check_safety_limits(
    pair: str,
    candidate_risk_r: float,
    portfolio_state: Optional[PortfolioState],
    trade_history: Optional[TradeHistory],
    exposure_summary: ExposureSummary,
    correlation_status: CorrelationStatus,
    config: RiskEngineConfig,
    now: datetime,
) -> Tuple[Optional[RejectionReason], Tuple[str, ...]]:
    warnings = []

    if portfolio_state is None:
        warnings.append("Portfolio state unknown -- heat/exposure/position-count limits could not be fully verified.")
        return None, tuple(warnings)

    open_positions = portfolio_state.open_positions

    if len(open_positions) >= config.max_open_positions:
        return RejectionReason.MAX_OPEN_POSITIONS_EXCEEDED, tuple(warnings)

    positions_for_pair = sum(1 for p in open_positions if p.pair == pair)
    if positions_for_pair >= config.max_positions_per_pair:
        return RejectionReason.MAX_POSITIONS_PER_PAIR_EXCEEDED, tuple(warnings)

    base, quote = split_currency_pair(pair)
    currency_map = dict(exposure_summary.currency_exposure_r)
    projected_currency_exposure = max(
        abs(currency_map.get(base, 0.0)) + candidate_risk_r,
        abs(currency_map.get(quote, 0.0)) + candidate_risk_r,
    )
    if projected_currency_exposure > config.max_currency_exposure_r:
        return RejectionReason.MAX_CURRENCY_EXPOSURE_EXCEEDED, tuple(warnings)

    projected_heat = exposure_summary.portfolio_heat_r + candidate_risk_r
    heat_limit = min(config.portfolio_heat_limit_r, config.max_concurrent_risk_r)
    if projected_heat > heat_limit:
        return RejectionReason.PORTFOLIO_HEAT_EXCEEDED, tuple(warnings)

    correlated_open_risk = sum(p.size_r for p in open_positions if p.pair in correlation_status.highly_correlated_pairs)
    if correlated_open_risk + candidate_risk_r > config.max_correlated_risk_r:
        return RejectionReason.CORRELATION_LIMIT_EXCEEDED, tuple(warnings)

    daily = _period_risk_r(trade_history, portfolio_state, now, now - timedelta(days=1))
    if daily + candidate_risk_r > config.daily_risk_limit_r:
        return RejectionReason.DAILY_RISK_LIMIT_EXCEEDED, tuple(warnings)

    weekly = _period_risk_r(trade_history, portfolio_state, now, now - timedelta(days=7))
    if weekly + candidate_risk_r > config.weekly_risk_limit_r:
        return RejectionReason.WEEKLY_RISK_LIMIT_EXCEEDED, tuple(warnings)

    monthly = _period_risk_r(trade_history, portfolio_state, now, now - timedelta(days=30))
    if monthly + candidate_risk_r > config.monthly_risk_limit_r:
        return RejectionReason.MONTHLY_RISK_LIMIT_EXCEEDED, tuple(warnings)

    return None, tuple(warnings)


__all__ = ["check_safety_limits"]
