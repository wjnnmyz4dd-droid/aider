"""The remaining configurable rule-profile checks (ADR-028 §5.5, §5.9)
that depend only on `AccountState`/`RiskSnapshot`/`now` and the active
`ComplianceRuleProfile` -- weekend holding, required stop loss, max
trades per day, the consistency rule, disabled pairs, and the two
purely informational checks (profit target, minimum trading days) that
never block a trade."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from titan_protocol.risk_engine.models import RiskSnapshot

from .config import ComplianceEngineConfig
from .models import AccountState, ComplianceRuleProfile


def check_pair_disabled(pair: str, config: ComplianceEngineConfig) -> bool:
    return pair in config.disabled_pairs


def check_weekend_restriction(now: datetime, profile: ComplianceRuleProfile, config: ComplianceEngineConfig) -> bool:
    if profile.weekend_holding_allowed or not config.weekend_restriction_check_enabled:
        return False
    weekday = now.weekday()
    if weekday == config.weekend_cutoff_weekday and now.hour >= config.weekend_cutoff_hour:
        return True
    return weekday > config.weekend_cutoff_weekday


def check_required_stop_loss(risk: RiskSnapshot, profile: ComplianceRuleProfile) -> bool:
    """`True` if violated (missing). §5.5's scope note: this engine has
    no order-level stop-loss price to inspect (that belongs to the
    not-yet-built Execution Validator) -- it verifies the only
    stop-loss-adjacent fact available: Risk Engine's R-based sizing,
    which by construction presupposes a defined stop-loss distance."""

    if not profile.required_stop_loss:
        return False
    return not (risk.recommended_position_size is not None and risk.recommended_position_size.final_r > 0)


def check_max_trades_per_day(account: AccountState, profile: ComplianceRuleProfile) -> bool:
    return account.trades_today_count >= profile.max_trades_per_day


def check_consistency_rule(account: AccountState, profile: ComplianceRuleProfile) -> bool:
    """`True` if violated. `None`-valued aggregates mean the rule is not
    yet evaluable (no data), which is treated as not-applicable -- never
    as a violation and never as a pass (ADR-028 Hard Rule 3)."""

    if account.best_single_day_profit_pct is None or account.cumulative_profit_pct is None:
        return False
    if account.cumulative_profit_pct <= 0:
        return False
    share = account.best_single_day_profit_pct / account.cumulative_profit_pct
    return share > profile.consistency_max_single_day_share


def trading_days_status(account: AccountState, profile: ComplianceRuleProfile) -> Optional[bool]:
    """Informational only -- never blocks a trade (ADR-028 §5.5)."""

    if profile.min_trading_days is None:
        return None
    return account.trading_days_count >= profile.min_trading_days


def profit_target_status(account: AccountState, profile: ComplianceRuleProfile) -> Optional[bool]:
    """Informational only -- never blocks a trade (ADR-028 §5.5)."""

    if profile.profit_target_pct is None or account.cumulative_profit_pct is None:
        return None
    return account.cumulative_profit_pct >= profile.profit_target_pct


__all__ = [
    "check_pair_disabled",
    "check_weekend_restriction",
    "check_required_stop_loss",
    "check_max_trades_per_day",
    "check_consistency_rule",
    "trading_days_status",
    "profit_target_status",
]
