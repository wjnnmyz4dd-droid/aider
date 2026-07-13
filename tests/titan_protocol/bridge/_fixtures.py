"""Shared test-only fixtures for the TitanProtocolEA bridge test suite."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from titan_protocol.bridge.command_queue import CommandQueue
from titan_protocol.bridge.config import BridgeConfig
from titan_protocol.bridge.models import CommandKind, SCHEMA_VERSION, TradeCommand

T0 = datetime(2026, 7, 9, 12, 0, 0, tzinfo=timezone.utc)
SYMBOL = "EURUSD"
API_KEY = "test-secret-key"


def make_config(**overrides) -> BridgeConfig:
    kwargs = dict(
        api_key=API_KEY,
        allowed_symbols=(SYMBOL,),
        magic_number=20260709,
        max_lot_size=5.0,
        max_slippage_points=20,
        heartbeat_timeout_seconds=30.0,
        command_ttl_seconds=15.0,
    )
    kwargs.update(overrides)
    return BridgeConfig(**kwargs)


def make_command(
    correlation_id: str = "corr-1",
    command_kind: CommandKind = CommandKind.BUY,
    symbol: Optional[str] = SYMBOL,
    volume: Optional[float] = 0.1,
    stop_loss: Optional[float] = 1.0950,
    take_profit: Optional[float] = 1.1100,
    position_id: Optional[str] = None,
    close_volume: Optional[float] = None,
    magic_number: int = 20260709,
    issued_at: datetime = T0,
) -> TradeCommand:
    return TradeCommand(
        schema_version=SCHEMA_VERSION,
        correlation_id=correlation_id,
        command_kind=command_kind,
        symbol=symbol,
        volume=volume,
        stop_loss=stop_loss,
        take_profit=take_profit,
        position_id=position_id,
        close_volume=close_volume,
        magic_number=magic_number,
        max_slippage_points=20,
        issued_at=issued_at,
    )


def make_queue(config: Optional[BridgeConfig] = None) -> CommandQueue:
    return CommandQueue(config or make_config())
