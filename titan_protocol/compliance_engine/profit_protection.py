"""Daily Profit Protection (ADR-028 §5.3) -- optional, enabled by
default. Reduces risk once configured profit thresholds are reached and,
if `config.profit_protection_stop_at_pct` is set, additionally rejects
new positions past that level -- protecting gains without ever
increasing size."""

from __future__ import annotations

from typing import Optional

from .bands import BandEvaluation, evaluate_graduated_bands
from .config import ComplianceEngineConfig
from .models import AccountState


def daily_profit_pct(account: AccountState) -> float:
    if account.daily_starting_balance <= 0:
        return 0.0
    return max(0.0, (account.account_balance - account.daily_starting_balance) / account.daily_starting_balance * 100.0)


def evaluate_profit_protection(account: AccountState, config: ComplianceEngineConfig) -> Optional[BandEvaluation]:
    if not config.profit_protection_enabled:
        return None

    pct = daily_profit_pct(account)
    evaluation = evaluate_graduated_bands(pct, config.profit_protection_bands)

    if config.profit_protection_stop_at_pct is not None and pct >= config.profit_protection_stop_at_pct:
        return BandEvaluation(
            multiplier=evaluation.multiplier, hard_reject=True, label=evaluation.label,
            gate_failed_reason=f"daily profit {pct:.2f}% reached configured stop threshold {config.profit_protection_stop_at_pct:.2f}%",
        )
    return evaluation


__all__ = ["daily_profit_pct", "evaluate_profit_protection"]
