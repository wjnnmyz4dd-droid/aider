"""Bridge handoff (ADR-031 SS3): constructs a `TradeCommand` from
already-computed values only -- the one place arithmetic (not a
decision) happens, scaling an already-computed lot size by an
already-computed reduction percentage. `stop_loss`/`take_profit` are
`None` this phase (disclosed scope boundary, ADR-031 SS3): no engine in
this pipeline currently computes an absolute price level, and
`phantom.bridge.validation.check_stop_loss_take_profit` already accepts
`None` for both."""

from __future__ import annotations

from datetime import datetime

from phantom.bridge.models import CommandKind, TradeCommand
from phantom.bridge.models import SCHEMA_VERSION as BRIDGE_SCHEMA_VERSION
from phantom.compliance_engine.models import ComplianceSnapshot
from phantom.risk_engine.models import RiskSnapshot
from phantom.strategy_engine.models import StrategySnapshot, TradeIntent

from .config import RuntimeConfig

_COMMAND_KIND_BY_TRADE_INTENT = {
    TradeIntent.BUY: CommandKind.BUY,
    TradeIntent.SELL: CommandKind.SELL,
}


def build_trade_command(
    pair: str,
    strategy: StrategySnapshot,
    risk: RiskSnapshot,
    compliance: ComplianceSnapshot,
    cycle_id: str,
    now: datetime,
    config: RuntimeConfig,
) -> TradeCommand:
    """Callers must only invoke this once `compliance.ready_for_bridge`
    is `True` -- at that point `strategy.trade_intent` is BUY or SELL
    (never NONE, since NONE only occurs when `strategy.rejected`, which
    already ends the cycle before Compliance is ever reached) and
    `risk.recommended_position_size` is not `None` (guaranteed by
    `risk.approved is True`, ADR-027's own invariant)."""

    reduction_fraction = 1.0 - (compliance.reduction_pct / 100.0)
    volume = risk.recommended_position_size.lot_size * reduction_fraction

    return TradeCommand(
        schema_version=BRIDGE_SCHEMA_VERSION,
        correlation_id=f"{cycle_id}:{pair}",
        command_kind=_COMMAND_KIND_BY_TRADE_INTENT[strategy.trade_intent],
        symbol=pair,
        volume=volume,
        stop_loss=None,
        take_profit=None,
        position_id=None,
        close_volume=None,
        magic_number=config.magic_number,
        max_slippage_points=config.max_slippage_points,
        issued_at=now,
    )


__all__ = ["build_trade_command"]
