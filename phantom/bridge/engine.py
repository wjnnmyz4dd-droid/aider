"""`BridgeEngine` -- the execution authority's orchestrator (Phase 1).

Wires `ConnectionHealth`, `CommandQueue`, and the validation module
together. Every handler here does exactly one of: store a read-model
snapshot (account state, positions, pending orders, errors), validate
and relay a command, record an execution result, or record an
independent trade-transaction mirror for drift detection. Nothing here
computes a trading decision -- this phase has none to compute; it only
ever relays a command supplied to it via `submit_command()`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from . import validation
from .command_queue import CommandQueue
from .config import BridgeConfig
from .connection_health import ConnectionHealth
from .logging_sink import (
    log_account_state,
    log_command_delivered,
    log_command_submitted,
    log_emergency_stop,
    log_error_report,
    log_execution_report,
    log_heartbeat,
    log_pending_orders,
    log_positions,
    log_trade_transaction,
)
from .metrics import BridgeMetrics
from .models import (
    AccountState,
    EmergencyStopState,
    ErrorCode,
    ErrorReport,
    ExecutionReport,
    HeartbeatMessage,
    PendingOrderReport,
    PositionReport,
    TradeCommand,
    TradeTransactionReport,
)


class BridgeEngine:
    def __init__(
        self,
        config: BridgeConfig,
        command_queue: CommandQueue,
        connection_health: ConnectionHealth,
        clock: Callable[[], datetime],
        metrics: Optional[BridgeMetrics] = None,
    ) -> None:
        self.config = config
        self._queue = command_queue
        self._health = connection_health
        self._clock = clock
        self.metrics = metrics
        self._latest_account_state: Optional[AccountState] = None
        self._latest_positions: Dict[str, PositionReport] = {}
        self._latest_pending_orders: Dict[str, PendingOrderReport] = {}
        self._errors: List[ErrorReport] = []
        self._trade_transactions: List[TradeTransactionReport] = []

    # -- Inbound telemetry --------------------------------------------

    def handle_heartbeat(self, message: HeartbeatMessage) -> None:
        self._health.record_heartbeat(message.received_at)
        log_heartbeat(message)
        if self.metrics is not None:
            self.metrics.record_heartbeat()

    def handle_account_state(self, state: AccountState) -> None:
        self._latest_account_state = state
        log_account_state(state)
        if self.metrics is not None:
            self.metrics.record_account_update()

    def handle_positions(self, positions: Sequence[PositionReport]) -> None:
        self._latest_positions = {p.position_id: p for p in positions}
        log_positions(len(positions), self.config.magic_number)
        if self.metrics is not None:
            self.metrics.record_position_update()

    def handle_pending_orders(self, orders: Sequence[PendingOrderReport]) -> None:
        self._latest_pending_orders = {o.order_id: o for o in orders}
        log_pending_orders(len(orders), self.config.magic_number)
        if self.metrics is not None:
            self.metrics.record_pending_order_update()

    # -- Command submission and relay (the execution authority) -------

    def submit_command(self, command: TradeCommand, now: datetime) -> Optional[ErrorCode]:
        """The only entry point through which a `TradeCommand` enters
        this system. Runs the same transport-integrity checks
        `send_request`-style callers must pass before the command ever
        reaches the queue -- this never re-decides whether the trade
        should happen (this phase has no such authority), it only
        defends the relay from carrying a malformed command."""
        reason = (
            validation.check_symbol_allowed(command.symbol, self.config)
            or validation.check_volume(command.volume, self.config)
            or validation.check_stop_loss_take_profit(command.stop_loss, command.take_profit)
            or validation.check_timestamp_fresh(command.issued_at, now, self.config.command_ttl_seconds)
        )
        if reason is None:
            reason = self._queue.enqueue(command, is_ready=self._health.is_ready())
        log_command_submitted(command, reason.value if reason is not None else "")
        if self.metrics is not None:
            if reason is None:
                self.metrics.record_command_submitted()
            else:
                self.metrics.record_command_rejected()
        return reason

    def poll_commands(self, now: datetime) -> Tuple[TradeCommand, ...]:
        delivered = self._queue.poll(now)
        for command in delivered:
            log_command_delivered(command.correlation_id)
        return delivered

    def handle_execution_report(self, report: ExecutionReport) -> bool:
        recorded = self._queue.record_result(report.correlation_id, report)
        log_execution_report(report, recorded)
        if self.metrics is not None:
            if recorded:
                self.metrics.record_execution_report()
            else:
                self.metrics.record_duplicate_execution_report()
        return recorded

    # -- Independent drift-detection cross-check -----------------------

    def handle_trade_transaction(self, report: TradeTransactionReport) -> bool:
        """Records an unsolicited, platform-native trade-transaction
        mirror and checks whether its ticket matches a known executed
        command's own reported broker ticket. Returns `True` if it
        matches (or there is nothing to compare against yet), `False`
        if it references a ticket no recorded `ExecutionReport` claims
        -- a drift signal, logged as a warning, never used to alter or
        override the execution report itself."""
        self._trade_transactions.append(report)
        known_tickets = {
            result.broker_ticket
            for result in self._queue.all_results()
            if result.broker_ticket is not None
        }
        matched = report.deal_ticket is None or report.deal_ticket in known_tickets
        log_trade_transaction(report, matched)
        if self.metrics is not None:
            self.metrics.record_trade_transaction()
            if not matched:
                self.metrics.record_trade_transaction_drift()
        return matched

    def handle_error(self, error: ErrorReport) -> None:
        self._errors.append(error)
        log_error_report(error)
        if self.metrics is not None:
            self.metrics.record_error_report()

    # -- Emergency stop (transport-level halt for this component only) -

    def activate_emergency_stop(self, reason: str, at: datetime) -> EmergencyStopState:
        state = self._queue.set_emergency_stop(True, reason, at)
        log_emergency_stop(state)
        if self.metrics is not None:
            self.metrics.record_emergency_stop()
        return state

    def deactivate_emergency_stop(self) -> EmergencyStopState:
        state = self._queue.set_emergency_stop(False, None, None)
        log_emergency_stop(state)
        return state

    # -- Read models -----------------------------------------------------

    @property
    def emergency_stop_state(self) -> EmergencyStopState:
        return self._queue.emergency_stop_state

    @property
    def is_connection_healthy(self) -> bool:
        return self._health.is_ready()

    @property
    def latest_account_state(self) -> Optional[AccountState]:
        return self._latest_account_state

    @property
    def latest_positions(self) -> Tuple[PositionReport, ...]:
        return tuple(self._latest_positions.values())

    @property
    def latest_pending_orders(self) -> Tuple[PendingOrderReport, ...]:
        return tuple(self._latest_pending_orders.values())

    @property
    def errors(self) -> Tuple[ErrorReport, ...]:
        return tuple(self._errors)

    @property
    def trade_transactions(self) -> Tuple[TradeTransactionReport, ...]:
        return tuple(self._trade_transactions)


__all__ = ["BridgeEngine"]
