"""Consecutive Loss Protection (ADR-028 §5.4): pause new entries after
a configured number of consecutive losses, until the caller's reset
event clears `AccountState.consecutive_losses` in a later call -- this
engine never tracks the counter itself."""

from __future__ import annotations

from .config import ComplianceEngineConfig
from .models import AccountState


def consecutive_loss_pause_triggered(account: AccountState, config: ComplianceEngineConfig) -> bool:
    return account.consecutive_losses >= config.consecutive_loss_pause_threshold


__all__ = ["consecutive_loss_pause_triggered"]
