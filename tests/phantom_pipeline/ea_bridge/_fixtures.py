"""Shared test-only fixtures for the EA Bridge test suite (`ADR-023`)."""

from __future__ import annotations

from datetime import datetime, timezone

from phantom_pipeline.data_pipeline import DataPipeline
from phantom_pipeline.ea_bridge.command_queue import CommandQueue
from phantom_pipeline.ea_bridge.config import EABridgeConfig
from phantom_pipeline.ea_bridge.models import ExecutionCommand, SCHEMA_VERSION
from phantom_pipeline.mt5_bridge.models import RequestKind
from phantom_pipeline.scanner.models import Direction

T0 = datetime(2026, 7, 8, 10, 0, 0, tzinfo=timezone.utc)
SYMBOL = "EURUSD"
API_KEY = "test-secret-key"


def make_config(**overrides) -> EABridgeConfig:
    kwargs = dict(
        api_key=API_KEY,
        allowed_symbols=(SYMBOL,),
        magic_number=20260708,
        max_lot_size=5.0,
        max_slippage_points=20,
        heartbeat_timeout_seconds=30.0,
        command_ttl_seconds=15.0,
    )
    kwargs.update(overrides)
    return EABridgeConfig(**kwargs)


def make_command(
    execution_id: str = "exec-1",
    trace_id: str = "trace-1",
    symbol: str = SYMBOL,
    lot_size: float = 0.1,
    stop_loss: float = 1.0950,
    take_profit: float = 1.1100,
    magic_number: int = 20260708,
    issued_at: datetime = T0,
) -> ExecutionCommand:
    return ExecutionCommand(
        schema_version=SCHEMA_VERSION,
        execution_id=execution_id,
        trace_id=trace_id,
        request_kind=RequestKind.OPEN,
        symbol=symbol,
        direction=Direction.UP,
        lot_size=lot_size,
        stop_loss=stop_loss,
        take_profit=take_profit,
        position_id=None,
        close_fraction=None,
        magic_number=magic_number,
        max_slippage_points=20,
        issued_at=issued_at,
    )


def make_data_pipeline() -> DataPipeline:
    return DataPipeline()


def make_queue(config: EABridgeConfig | None = None) -> CommandQueue:
    return CommandQueue(config or make_config())
