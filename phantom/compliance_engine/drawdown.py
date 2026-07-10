"""Total Drawdown Protection: a graduated curve, same shape as Daily
Loss Protection but against `(peak_balance - account_balance) /
peak_balance` (ADR-028 §5.2). Never trades into the hard limit -- the
final configured band always hard-rejects."""

from __future__ import annotations

from .bands import BandEvaluation, evaluate_graduated_bands
from .config import ComplianceEngineConfig
from .models import AccountState, ComplianceRuleProfile


def total_drawdown_pct_consumed(account: AccountState, profile: ComplianceRuleProfile) -> float:
    if account.peak_balance <= 0 or profile.max_total_drawdown_pct <= 0:
        return 0.0
    drawdown_pct_of_equity = max(0.0, (account.peak_balance - account.account_balance) / account.peak_balance * 100.0)
    return (drawdown_pct_of_equity / profile.max_total_drawdown_pct) * 100.0


def evaluate_drawdown_protection(
    account: AccountState, profile: ComplianceRuleProfile, config: ComplianceEngineConfig,
) -> BandEvaluation:
    pct = total_drawdown_pct_consumed(account, profile)
    return evaluate_graduated_bands(pct, config.drawdown_bands)


__all__ = ["total_drawdown_pct_consumed", "evaluate_drawdown_protection"]
