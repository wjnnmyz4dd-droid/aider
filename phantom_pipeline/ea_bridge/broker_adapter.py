"""`EABrokerAdapter` — a `BrokerAdapter` implementation backed by the EA
bridge (`ADR-023` §2, Hard Rule 2).

Implements `mt5_bridge.broker_adapter.BrokerAdapter`'s existing 7-method
ABC exactly — the same abstraction `MT5Adapter`/`FakeBrokerAdapter`
already satisfy — so `MT5Bridge` needs zero code change to use this
adapter instead. `send_request()` translates an already-fully-decided
`BrokerRequest` (produced only by `mt5_bridge.checks.translate_order`/
`translate_position_adjustment`/`translate_position_close`) into an
`ExecutionCommand` and enqueues it; nothing here computes a score, size,
SL/TP, or verdict (`ADR-023` Hard Rule 1).

Every method takes an explicit `now` via the injected `clock` callable —
no `datetime.now()` call anywhere in this file, the same "no wall-clock
dependence" discipline every prior stage's engine already established.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Optional, Tuple

from ..mt5_bridge import BrokerAdapter
from ..mt5_bridge.models import (
    BrokerAcknowledgement,
    BrokerError,
    BrokerRequest,
    ExecutionReceipt,
)
from . import validation
from .command_queue import CommandQueue
from .config import EABridgeConfig
from .models import SCHEMA_VERSION, ExecutionCommand


def command_from_broker_request(
    request: BrokerRequest, magic_number: int, max_slippage_points: int, now: datetime
) -> ExecutionCommand:
    """A direct field mapping from an already-decided `BrokerRequest` —
    never a re-derivation (`ADR-023` Hard Rule 1, mirrors
    `mt5_adapter.py`'s own "translation only" posture)."""
    return ExecutionCommand(
        schema_version=SCHEMA_VERSION,
        execution_id=request.execution_id,
        trace_id=request.trace_id,
        request_kind=request.request_kind,
        symbol=request.symbol,
        direction=request.direction,
        lot_size=request.lot_size,
        stop_loss=request.stop_loss,
        take_profit=request.take_profit,
        position_id=request.position_id,
        close_fraction=request.close_fraction,
        magic_number=magic_number,
        max_slippage_points=max_slippage_points,
        issued_at=now,
    )


class EABrokerAdapter(BrokerAdapter):
    """Holds no idempotency/connection-state logic of its own beyond what
    `CommandQueue`/heartbeat tracking require — mirrors `MT5Adapter`'s own
    "only ever executes exactly what it is asked to submit or query"
    scoping."""

    def __init__(
        self,
        command_queue: CommandQueue,
        clock: Callable[[], datetime],
        config: EABridgeConfig,
    ) -> None:
        self._queue = command_queue
        self._clock = clock
        self._config = config
        self._last_heartbeat_at: Optional[datetime] = None
        self._latest_account_equity: Optional[float] = None
        self._latest_position_ids: Tuple[str, ...] = ()

    # -- Telemetry recorded by the HTTP layer (never by MT5Bridge) -------

    def record_heartbeat(self, at: datetime) -> None:
        self._last_heartbeat_at = at

    def record_account_equity(self, equity: float) -> None:
        self._latest_account_equity = equity

    def record_open_position_ids(self, position_ids: Tuple[str, ...]) -> None:
        self._latest_position_ids = tuple(position_ids)

    # -- BrokerAdapter ABC -------------------------------------------------

    def connect(self) -> bool:
        """Nothing to actively connect to — the EA connects to Phantom,
        not the reverse. Always `True`; `heartbeat()` is the real
        liveness gate `MT5Bridge`'s own state machine already relies on
        (`ADR-008` §6, unchanged)."""
        return True

    def disconnect(self) -> None:
        self._last_heartbeat_at = None

    def heartbeat(self) -> bool:
        if self._last_heartbeat_at is None:
            return False
        elapsed = (self._clock() - self._last_heartbeat_at).total_seconds()
        return elapsed <= self._config.heartbeat_timeout_seconds

    def send_request(self, request: BrokerRequest) -> "BrokerAcknowledgement | BrokerError":
        now = self._clock()
        command = command_from_broker_request(
            request, self._config.magic_number, self._config.max_slippage_points, now
        )

        # Transport-integrity validation only (ADR-023 Hard Rule 6) --
        # never re-decides a trade, only defends the relay from carrying
        # a corrupted command to the EA.
        reason = (
            validation.check_symbol_allowed(command.symbol, self._config)
            or validation.check_volume(command.lot_size, self._config)
            or validation.check_stop_loss_take_profit(command.stop_loss, command.take_profit)
        )
        if reason is None:
            reason = self._queue.enqueue(command, is_ready=self.heartbeat())
        if reason is not None:
            return BrokerError(
                schema_version=SCHEMA_VERSION,
                execution_id=request.execution_id,
                trace_id=request.trace_id,
                request_kind=request.request_kind,
                reason=reason,
                timestamp=request.timestamp,
            )
        return BrokerAcknowledgement(
            schema_version=SCHEMA_VERSION,
            execution_id=request.execution_id,
            trace_id=request.trace_id,
            request_kind=request.request_kind,
            broker_ref=None,
            timestamp=request.timestamp,
        )

    def poll_execution(self, execution_id: str) -> Optional["ExecutionReceipt | BrokerError"]:
        command = self._queue.command_for(execution_id)
        report = self._queue.result_for(execution_id)
        if command is None or report is None:
            return None
        if report.success:
            return ExecutionReceipt(
                schema_version=SCHEMA_VERSION,
                execution_id=execution_id,
                trace_id=command.trace_id,
                request_kind=command.request_kind,
                broker_ref=report.broker_ticket,
                filled_price=report.filled_price,
                filled_size=report.filled_size,
                timestamp=report.reported_at,
            )
        return BrokerError(
            schema_version=SCHEMA_VERSION,
            execution_id=execution_id,
            trace_id=command.trace_id,
            request_kind=command.request_kind,
            reason=report.reason or "ea_execution_failed",
            timestamp=report.reported_at,
        )

    def query_open_position_ids(self) -> Tuple[str, ...]:
        return self._latest_position_ids

    def query_account_equity(self) -> Optional[float]:
        return self._latest_account_equity


__all__ = ["EABrokerAdapter", "command_from_broker_request"]
