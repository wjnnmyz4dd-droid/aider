"""Position/exposure limits (ADR-028 §5.8) -- an independently
configured, prop-firm-operational cap distinct from Risk Engine's own
portfolio-heat-driven limits. Reuses `phantom.risk_engine.exposure`'s
existing pure functions rather than a second exposure implementation
(ADR-028 Hard Rule 4)."""

from __future__ import annotations

from typing import Optional, Tuple

from phantom.risk_engine.exposure import compute_exposure_summary, split_currency_pair
from phantom.risk_engine.models import ExposureSummary, PortfolioState

from .models import AccountState, ComplianceRuleId, ComplianceRuleProfile


def check_position_limits(
    pair: str,
    candidate_risk_r: float,
    portfolio_state: PortfolioState,
    account: AccountState,
    profile: ComplianceRuleProfile,
) -> Tuple[Optional[ComplianceRuleId], ExposureSummary]:
    exposure = compute_exposure_summary(portfolio_state, ())

    if len(portfolio_state.open_positions) >= profile.max_open_positions:
        return ComplianceRuleId.MAX_OPEN_POSITIONS_EXCEEDED, exposure

    positions_for_pair = sum(1 for p in portfolio_state.open_positions if p.pair == pair)
    if positions_for_pair >= profile.max_positions_per_pair:
        return ComplianceRuleId.MAX_POSITIONS_PER_PAIR_EXCEEDED, exposure

    base, quote = split_currency_pair(pair)
    currency_map = dict(exposure.currency_exposure_r)
    projected_currency_exposure = max(
        abs(currency_map.get(base, 0.0)) + candidate_risk_r,
        abs(currency_map.get(quote, 0.0)) + candidate_risk_r,
    )
    if projected_currency_exposure > profile.max_currency_exposure_r:
        return ComplianceRuleId.MAX_CURRENCY_EXPOSURE_EXCEEDED, exposure

    symbol_map = dict(exposure.symbol_exposure_r)
    if symbol_map.get(pair, 0.0) + candidate_risk_r > profile.max_symbol_exposure_r:
        return ComplianceRuleId.MAX_SYMBOL_EXPOSURE_EXCEEDED, exposure

    if account.pending_orders_count >= profile.max_pending_orders:
        return ComplianceRuleId.MAX_PENDING_ORDERS_EXCEEDED, exposure

    if exposure.portfolio_heat_r + candidate_risk_r > profile.max_simultaneous_risk_r:
        return ComplianceRuleId.MAX_SIMULTANEOUS_RISK_EXCEEDED, exposure

    return None, exposure


__all__ = ["check_position_limits"]
