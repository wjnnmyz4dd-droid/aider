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

from collections import deque
from datetime import datetime
from typing import Callable, Deque, Dict, Optional, Sequence, Tuple

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

# Amendment 1 (ADR-023): market_data_ingestion imports only
# titan_protocol.evidence_engine.models -- no cycle with this package.
from titan_protocol.market_data_ingestion.engine import MarketDataIngestionEngine
from titan_protocol.market_data_ingestion.models import IngestionResult, RawBar, TickEvent


class BridgeEngine:
    def __init__(
        self,
        config: BridgeConfig,
        command_queue: CommandQueue,
        connection_health: ConnectionHealth,
        clock: Callable[[], datetime],
        metrics: Optional[BridgeMetrics] = None,
        market_data_engine: Optional[MarketDataIngestionEngine] = None,
    ) -> None:
        self.config = config
        self._queue = command_queue
        self._health = connection_health
        self._clock = clock
        self.metrics = metrics
        # Amendment 1 (ADR-023): optional so every existing call site
        # (start.py, every pre-amendment test) is unaffected -- market
        # data is a new, additive capability, never a required one.
        self._market_data_engine = market_data_engine
        self._latest_account_state: Optional[AccountState] = None
        self._latest_positions: Dict[str, PositionReport] = {}
        # Set unconditionally by handle_positions() below, including when
        # the reported list is empty (an all-closed snapshot) -- unlike
        # PositionReport.received_at, which simply doesn't exist when
        # there are zero positions to attach it to. Lets a caller (
        # InFlightCommandRegistry.confirm_position_report()) know a fresh
        # snapshot was taken, even one confirming zero positions.
        self._last_positions_received_at: Optional[datetime] = None
        self._latest_pending_orders: Dict[str, PendingOrderReport] = {}
        # Phase 1.6: bounded, deterministic FIFO caps (oldest dropped
        # first once full) -- these two audit-only logs grew unbounded
        # before this change. `deque.append()` is atomic under CPython's
        # GIL, same as the `list.append()` it replaces, so no new lock
        # is needed here (verified by this phase's concurrency tests).
        self._errors: Deque[ErrorReport] = deque(maxlen=config.max_error_history)
        self._trade_transactions: Deque[TradeTransactionReport] = deque(maxlen=config.max_trade_transaction_history)

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

    def handle_positions(self, positions: Sequence[PositionReport], now: datetime) -> None:
        self._latest_positions = {p.position_id: p for p in positions}
        self._last_positions_received_at = now
        log_positions(len(positions), self.config.magic_number)
        if self.metrics is not None:
            self.metrics.record_position_update()

    def handle_pending_orders(self, orders: Sequence[PendingOrderReport]) -> None:
        self._latest_pending_orders = {o.order_id: o for o in orders}
        log_pending_orders(len(orders), self.config.magic_number)
        if self.metrics is not None:
            self.metrics.record_pending_order_update()

    # -- Market data (Amendment 1, ADR-023) -----------------------------
    #
    # Both methods do nothing but delegate to `MarketDataIngestionEngine`
    # -- no validation, normalization, ordering, or freshness logic is
    # (or may ever be) duplicated here. If no engine was constructed
    # (`market_data_engine=None`, the default), the message is accepted
    # at the transport layer and silently has nowhere to go -- callers
    # gate on `has_market_data_engine` before wiring the endpoint at all.

    @property
    def has_market_data_engine(self) -> bool:
        return self._market_data_engine is not None

    def handle_bar(self, raw: RawBar, now: datetime) -> Optional[IngestionResult]:
        if self._market_data_engine is None:
            return None
        return self._market_data_engine.ingest_bar(raw, now)

    def handle_tick(self, tick: TickEvent, now: datetime) -> Optional[IngestionResult]:
        if self._market_data_engine is None:
            return None
        return self._market_data_engine.ingest_tick(tick, now)

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

    def command_resolved(self, correlation_id: str) -> bool:
        """Read-only passthrough to CommandQueue.is_executed() -- lets a
        caller (Runtime's InFlightCommandRegistry) ask whether a
        correlation_id it submitted has reached a terminal state,
        without reaching into this engine's private `_queue`. Adds no
        new decision logic here: the answer is exactly whatever
        CommandQueue already tracks."""
        return self._queue.is_executed(correlation_id)

    def command_abandoned(self, correlation_id: str, now: datetime) -> bool:
        """Read-only passthrough to CommandQueue.is_abandoned() -- lets
        Runtime's InFlightCommandRegistry ask, atomically, whether a
        correlation_id it submitted has already vanished from
        CommandQueue undelivered (never reached the EA, past
        command_ttl_seconds), as opposed to being genuinely delivered
        and still awaiting resolution. See CommandQueue.is_abandoned()'s
        own docstring for why this must be a single atomic query rather
        than composing separate is_delivered()/age checks: a command
        already delivered is never abandoned, no matter how old."""
        return self._queue.is_abandoned(correlation_id, now)

    def execution_succeeded(self, correlation_id: str) -> Optional[bool]:
        """Read-only passthrough exposing the recorded ExecutionReport's
        own `success` flag -- lets Runtime's InFlightCommandRegistry
        distinguish "executed successfully, must wait for a confirming
        position report before releasing its Risk Engine reservation"
        from "executed and rejected, safe to release immediately."
        command_resolved()/CommandQueue.is_executed() alone cannot make
        this distinction (it is True for either outcome). Returns None
        if no result has been recorded yet for this correlation_id."""
        result = self._queue.result_for(correlation_id)
        return result.success if result is not None else None

    @property
    def latest_account_state(self) -> Optional[AccountState]:
        return self._latest_account_state

    @property
    def latest_positions(self) -> Tuple[PositionReport, ...]:
        return tuple(self._latest_positions.values())

    @property
    def last_positions_received_at(self) -> Optional[datetime]:
        """When the most recent `/bridge/positions` snapshot was received
        -- set even when that snapshot reported zero positions, unlike
        deriving a timestamp from `latest_positions` itself (which has
        nothing to derive from when the list is empty). Used to confirm a
        just-resolved command's pair has a post-execution position
        snapshot before allowing a new submission (see
        InFlightCommandRegistry.confirm_position_report())."""
        return self._last_positions_received_at

    @property
    def latest_pending_orders(self) -> Tuple[PendingOrderReport, ...]:
        return tuple(self._latest_pending_orders.values())

    @property
    def errors(self) -> Tuple[ErrorReport, ...]:
        return tuple(self._errors)

    @property
    def trade_transactions(self) -> Tuple[TradeTransactionReport, ...]:
        return tuple(self._trade_transactions)

    def queue_retention_stats(self) -> Dict[str, int]:
        """Phase 1.6 observability passthrough -- surfaces
        `CommandQueue`'s retention/cleanup counters without requiring a
        caller to reach into the private `_queue` attribute. Additive
        only; no existing method's signature or behavior changed."""
        return {
            "pending_count": self._queue.pending_count(),
            "completed_count": self._queue.completed_count(),
            "cached_report_count": self._queue.cached_report_count(),
            "duplicate_cache_size": self._queue.duplicate_cache_size(),
            "total_tracked_correlation_ids": self._queue.total_tracked_correlation_ids(),
            "largest_pending_queue_observed": self._queue.largest_pending_queue_observed(),
            "cleanup_run_count": self._queue.cleanup_run_count(),
            "expired_entries_removed_count": self._queue.expired_entries_removed_count(),
            "estimated_memory_bytes": self._queue.estimated_memory_bytes(),
        }


__all__ = ["BridgeEngine"]
