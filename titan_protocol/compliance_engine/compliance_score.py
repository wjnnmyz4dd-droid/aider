"""The Compliance Score (ADR-028 §5.11, Hard Rule 8): a 0-100
operational-health metric for dashboards/monitoring only. Computed
independently of, and never substituting for, the rule-based
APPROVE/REDUCE/REJECT decision."""

from __future__ import annotations

from .config import ComplianceEngineConfig
from .daily_loss import daily_loss_pct_consumed
from .drawdown import total_drawdown_pct_consumed
from .lock import is_locked
from .models import AccountState, ComplianceRuleProfile

#: Weights sum to 1.0 -- daily loss and drawdown are the two hardest
#: account-ending risks, weighted equally and highest; consecutive-loss
#: pressure is a softer signal, weighted lowest.
DAILY_LOSS_WEIGHT = 0.4
DRAWDOWN_WEIGHT = 0.4
CONSECUTIVE_LOSS_WEIGHT = 0.2


def compute_compliance_score(account: AccountState, profile: ComplianceRuleProfile, config: ComplianceEngineConfig) -> float:
    if is_locked(account):
        return 0.0

    daily_component = max(0.0, 100.0 - min(100.0, daily_loss_pct_consumed(account, profile)))
    drawdown_component = max(0.0, 100.0 - min(100.0, total_drawdown_pct_consumed(account, profile)))
    if config.consecutive_loss_pause_threshold > 0:
        consecutive_component = max(0.0, 100.0 * (1.0 - account.consecutive_losses / config.consecutive_loss_pause_threshold))
    else:
        consecutive_component = 100.0

    score = DAILY_LOSS_WEIGHT * daily_component + DRAWDOWN_WEIGHT * drawdown_component + CONSECUTIVE_LOSS_WEIGHT * consecutive_component
    return max(0.0, min(100.0, score))


__all__ = ["compute_compliance_score"]
