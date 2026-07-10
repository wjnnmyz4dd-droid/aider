"""Daily Loss Protection: the graduated safety curve (ADR-028 §5.1).

Reduces allowable risk before the configured daily loss limit is
reached, using only `AccountState`'s raw balances -- this is this
engine's own first computation of "% of the daily limit consumed,"
never a duplicate of anything upstream.
"""

from __future__ import annotations

from typing import Optional

from .bands import BandEvaluation, evaluate_graduated_bands
from .config import ComplianceEngineConfig
from .models import AccountState, ComplianceRuleProfile


def daily_loss_pct_consumed(account: AccountState, profile: ComplianceRuleProfile) -> float:
    """Percentage of the configured daily loss *limit* consumed so far
    (0-100+ scale) -- e.g. `70.0` means 70% of `profile.max_daily_loss_pct`
    has been lost today, regardless of what that limit's absolute value is."""

    if account.daily_starting_balance <= 0 or profile.max_daily_loss_pct <= 0:
        return 0.0
    daily_loss_pct_of_equity = max(0.0, (account.daily_starting_balance - account.account_balance) / account.daily_starting_balance * 100.0)
    return (daily_loss_pct_of_equity / profile.max_daily_loss_pct) * 100.0


def evaluate_daily_loss_protection(
    account: AccountState,
    profile: ComplianceRuleProfile,
    config: ComplianceEngineConfig,
    evidence_score: Optional[float] = None,
    strategy_score: Optional[float] = None,
) -> BandEvaluation:
    pct = daily_loss_pct_consumed(account, profile)
    return evaluate_graduated_bands(pct, config.daily_loss_bands, evidence_score, strategy_score)


__all__ = ["daily_loss_pct_consumed", "evaluate_daily_loss_protection"]
