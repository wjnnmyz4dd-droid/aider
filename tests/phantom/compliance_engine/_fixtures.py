"""Shared test-only fixtures for the Compliance Engine test suite --
reuses the Risk Engine's and Strategy Engine's own fixture builders for
`EvidenceSnapshot`/`MarketIntelligenceSnapshot`/`StrategySnapshot`
(no second, divergent construction of the same upstream types), and
adds builders for this engine's own new types (`RiskSnapshot`,
`PortfolioState`, `AccountState`)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Sequence

from phantom.compliance_engine.config import ComplianceEngineConfig
from phantom.compliance_engine.models import AccountState, ComplianceLockState
from phantom.risk_engine.models import (
    ConfidenceTier,
    Direction,
    OpenPosition,
    PortfolioState,
    PositionSizeRecommendation,
    RiskSnapshot,
)
from tests.phantom.risk_engine._fixtures import make_evidence_snapshot, make_mi_snapshot, make_strategy_snapshot

T0 = datetime(2026, 7, 10, 13, 0, 0, tzinfo=timezone.utc)  # Friday, London/NY overlap


def make_config(**overrides) -> ComplianceEngineConfig:
    return ComplianceEngineConfig(**overrides)


def make_position_size_recommendation(final_r: float = 1.25) -> PositionSizeRecommendation:
    return PositionSizeRecommendation(
        fixed_fractional_r=0.25, confidence_scaled_r=final_r, volatility_scaled_r=final_r,
        kelly_r=None, final_r=final_r, lot_size=final_r, capped=False, cap_reason=None,
    )


def make_confidence_tier(label: str = "TIER_5", base_r: float = 1.25) -> ConfidenceTier:
    return ConfidenceTier(label=label, min_score=90.0, max_score=100.0, base_r=base_r)


def make_risk_snapshot(
    pair: str = "EURUSD",
    now: datetime = T0,
    approved: bool = True,
    approved_risk_r: float = 1.25,
    recommended_position_size: Optional[PositionSizeRecommendation] = None,
) -> RiskSnapshot:
    if not approved:
        return RiskSnapshot(
            pair=pair, generated_at=now, approved=False, approved_risk_r=0.0,
            recommended_position_size=None, confidence_tier=None, exposure_summary=None,
            correlation_status=None, statistical_metrics=None, monte_carlo=None,
            reasons=("rejected",), warnings=(), rejection_reason=None, reservation_id=None,
        )
    sizing = recommended_position_size or make_position_size_recommendation(approved_risk_r)
    return RiskSnapshot(
        pair=pair, generated_at=now, approved=True, approved_risk_r=approved_risk_r,
        recommended_position_size=sizing, confidence_tier=make_confidence_tier(),
        exposure_summary=None, correlation_status=None, statistical_metrics=None, monte_carlo=None,
        reasons=("ok",), warnings=(), rejection_reason=None, reservation_id="RSV-TEST",
    )


def make_open_position(pair: str = "GBPUSD", direction: Direction = Direction.LONG, size_r: float = 1.0, opened_at: datetime = T0) -> OpenPosition:
    return OpenPosition(pair=pair, direction=direction, size_r=size_r, opened_at=opened_at)


def make_portfolio_state(positions: Sequence[OpenPosition] = ()) -> PortfolioState:
    return PortfolioState(open_positions=tuple(positions))


def make_account_state(
    account_balance: float = 100_000.0,
    daily_starting_balance: float = 100_000.0,
    peak_balance: float = 100_000.0,
    compliance_lock: Optional[ComplianceLockState] = None,
    consecutive_losses: int = 0,
    trading_days_count: int = 0,
    trades_today_count: int = 0,
    pending_orders_count: int = 0,
    best_single_day_profit_pct: Optional[float] = None,
    cumulative_profit_pct: Optional[float] = None,
    emergency_stop_active: bool = False,
    rule_profile_name: str = "example_generic_profile",
) -> AccountState:
    return AccountState(
        account_balance=account_balance, daily_starting_balance=daily_starting_balance,
        peak_balance=peak_balance, compliance_lock=compliance_lock or ComplianceLockState(),
        consecutive_losses=consecutive_losses, trading_days_count=trading_days_count,
        trades_today_count=trades_today_count, pending_orders_count=pending_orders_count,
        best_single_day_profit_pct=best_single_day_profit_pct, cumulative_profit_pct=cumulative_profit_pct,
        emergency_stop_active=emergency_stop_active, rule_profile_name=rule_profile_name,
    )


__all__ = [
    "T0",
    "make_config",
    "make_evidence_snapshot",
    "make_mi_snapshot",
    "make_strategy_snapshot",
    "make_position_size_recommendation",
    "make_confidence_tier",
    "make_risk_snapshot",
    "make_open_position",
    "make_portfolio_state",
    "make_account_state",
]
