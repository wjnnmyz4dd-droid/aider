"""The MT5 Bridge (ADR-008, Amendment 1).

`MT5Bridge` is a deterministic translation and transport layer — it
never decides whether to trade (§1). `submit_order()` accepts only an
`ExecutionDecision` APPROVE (Hard Rules); `submit_position_adjustment()`/
`submit_position_close()` accept only `PositionAdjustmentRequest`/
`PositionCloseRequest` (Amendment 1 Hard Rules) — the only two request
shapes MT5 Bridge's public interface exposes for broker submission,
which is how "accept only from Position Manager"/"accept only Execution
Validator APPROVE" is enforced: there is no third code path capable of
constructing a submittable request from anything else (structural/type-
boundary enforcement, the same mechanism every prior stage's "only
consumes X" boundary already relies on — none of them implement runtime
caller-identity checks either).

Every submission path follows the same shape: validate (Phantom-side,
never reaches the broker on failure) → check transport-layer idempotency
(§7) → check connection is `READY` (§6, §8: "if connection fails, no
order") → translate (a direct field mapping, `checks.py`) → record the
submission → call the broker adapter → log and meter the result. No
automatic resubmission of an order whose outcome is unknown ever occurs
here (§8) — `poll_execution()` only observes and reports.

The connection state machine, heartbeat, and synchronization logic all
take an explicit `now: datetime` parameter — no `datetime.now()` call
anywhere in this file — the same "no wall-clock dependence" discipline
every prior stage's engine already established.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Tuple, Union

from ..compliance_engine.models import ComplianceDecision
from ..execution_validator.models import ExecutionDecision
from ..risk_engine.models import RiskDecision
from ..strategy_engine.models import CandidateTrade
from . import checks
from .broker_adapter import BrokerAdapter
from .config import DEFAULT_CONFIG, MT5BridgeConfig
from .execution_id import make_execution_id
from .idempotency_store import TransportIdempotencyStore
from .logging_sink import (
    log_acknowledgement,
    log_disconnect,
    log_execution,
    log_fill,
    log_phantom_side_reject,
    log_reconnect,
    log_reject,
    log_submission,
    log_synchronization,
    log_timeout,
)
from .metrics import MT5BridgeMetrics
from .models import (
    SCHEMA_VERSION,
    BrokerAcknowledgement,
    BrokerError,
    BrokerRequest,
    ConnectionState,
    ConnectionStatus,
    ExecutionReceipt,
    FillReport,
    PositionAdjustmentRequest,
    PositionCloseRequest,
    SynchronizationStatus,
)

BrokerResponse = Union[BrokerAcknowledgement, BrokerError]


class MT5Bridge:
    def __init__(
        self,
        adapter: BrokerAdapter,
        idempotency_store: TransportIdempotencyStore,
        config: MT5BridgeConfig = DEFAULT_CONFIG,
        metrics: Optional[MT5BridgeMetrics] = None,
    ):
        self.adapter = adapter
        self.idempotency = idempotency_store
        self.config = config
        self.metrics = metrics
        self.state = ConnectionState.DISCONNECTED
        self._last_heartbeat_ok_at: Optional[datetime] = None

    # -- Connection management (§6) ------------------------------------

    def connect(self, now: datetime) -> ConnectionStatus:
        self.state = ConnectionState.CONNECTING
        ok = self.adapter.connect()
        if not ok:
            self.state = ConnectionState.DISCONNECTED
            status = ConnectionStatus(SCHEMA_VERSION, self.state, "connect failed", now)
            log_disconnect(status)
            return status
        self.state = ConnectionState.CONNECTED
        self._last_heartbeat_ok_at = now
        return ConnectionStatus(SCHEMA_VERSION, self.state, "connected", now)

    def heartbeat(self, now: datetime) -> ConnectionStatus:
        ok = self.adapter.heartbeat()
        if ok:
            self._last_heartbeat_ok_at = now
        if self.metrics is not None:
            self.metrics.record_heartbeat_status(ok)

        missed_too_long = (
            self._last_heartbeat_ok_at is None
            or (now - self._last_heartbeat_ok_at).total_seconds() > self.config.heartbeat_timeout_seconds
        )
        if missed_too_long and self.state != ConnectionState.DISCONNECTED:
            self.state = ConnectionState.DISCONNECTED
            status = ConnectionStatus(SCHEMA_VERSION, self.state, "heartbeat missed beyond threshold", now)
            log_disconnect(status)
            return status
        return ConnectionStatus(SCHEMA_VERSION, self.state, "heartbeat ok" if ok else "heartbeat missed", now)

    def synchronize(
        self, now: datetime, expected_position_ids: Tuple[str, ...] = ()
    ) -> Tuple[ConnectionStatus, SynchronizationStatus]:
        if self.state not in (ConnectionState.CONNECTED, ConnectionState.SYNCHRONIZING, ConnectionState.READY):
            sync_status = SynchronizationStatus(SCHEMA_VERSION, False, ("not_connected",), now)
            conn_status = ConnectionStatus(SCHEMA_VERSION, self.state, "cannot synchronize while not connected", now)
            return conn_status, sync_status

        self.state = ConnectionState.SYNCHRONIZING
        broker_position_ids = set(self.adapter.query_open_position_ids())
        expected = set(expected_position_ids)
        discrepancies = []
        missing_on_broker = expected - broker_position_ids
        unexpected_on_broker = broker_position_ids - expected
        if missing_on_broker:
            discrepancies.append(f"missing_on_broker:{sorted(missing_on_broker)}")
        if unexpected_on_broker:
            discrepancies.append(f"unexpected_on_broker:{sorted(unexpected_on_broker)}")

        in_sync = not discrepancies
        self.state = ConnectionState.READY if in_sync else ConnectionState.CONNECTED
        sync_status = SynchronizationStatus(SCHEMA_VERSION, in_sync, tuple(discrepancies), now)
        conn_status = ConnectionStatus(
            SCHEMA_VERSION, self.state, "synchronized" if in_sync else "discrepancy detected", now
        )
        log_synchronization(sync_status)
        if self.metrics is not None:
            self.metrics.record_synchronization_status(in_sync)
        return conn_status, sync_status

    def disconnect(self, now: datetime) -> ConnectionStatus:
        self.adapter.disconnect()
        self.state = ConnectionState.DISCONNECTED
        status = ConnectionStatus(SCHEMA_VERSION, self.state, "disconnected", now)
        log_disconnect(status)
        return status

    def reconnect(self, now: datetime) -> ConnectionStatus:
        """A bounded, backoff-based reconnect sequence (§6) — deterministic
        attempt counting, never an unbounded retry loop. Reconnection does
        not imply resubmission of any order in flight (§8)."""
        for attempt in range(self.config.reconnect_max_attempts):
            if self.adapter.connect():
                self.state = ConnectionState.CONNECTED
                self._last_heartbeat_ok_at = now
                if self.metrics is not None:
                    self.metrics.record_reconnect()
                status = ConnectionStatus(SCHEMA_VERSION, self.state, f"reconnected after {attempt + 1} attempt(s)", now)
                log_reconnect(status)
                return status
        self.state = ConnectionState.DISCONNECTED
        status = ConnectionStatus(SCHEMA_VERSION, self.state, "reconnect failed after max attempts", now)
        log_disconnect(status)
        return status

    # -- Order submission (§2, §4, §7) ---------------------------------

    def submit_order(
        self,
        execution_decision: Optional[ExecutionDecision],
        risk_decision: Optional[RiskDecision],
        compliance_decision: Optional[ComplianceDecision],
        candidate: CandidateTrade,
        now: datetime,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> Tuple[Optional[str], Optional[BrokerRequest], Optional[BrokerResponse]]:
        reason = checks.validate_execution_decision(execution_decision)
        if reason is None:
            reason = checks.validate_order_consistency(candidate, risk_decision, compliance_decision, execution_decision)
        if reason is None:
            reason = checks.validate_sizing(risk_decision)

        execution_id = make_execution_id(candidate.trace_id, candidate.candidate_id)

        if reason is None and self.idempotency.has_submitted(execution_id, now):
            reason = "duplicate_submission"
        if reason is None and self.state != ConnectionState.READY:
            reason = "connection_not_ready"

        if reason is not None:
            log_phantom_side_reject(execution_id, candidate.trace_id, reason)
            if self.metrics is not None:
                self.metrics.record_phantom_side_reject()
            return reason, None, None

        broker_request = checks.translate_order(
            execution_decision, risk_decision, candidate, execution_id, stop_loss, take_profit, now
        )
        return None, broker_request, self._send_and_record(broker_request, now)

    def submit_position_adjustment(
        self, request: Optional[PositionAdjustmentRequest], now: datetime
    ) -> Tuple[Optional[str], Optional[BrokerRequest], Optional[BrokerResponse]]:
        reason = checks.validate_position_adjustment(request)
        if reason is None and self.idempotency.has_submitted(request.execution_id, now):
            reason = "duplicate_submission"
        if reason is None and self.state != ConnectionState.READY:
            reason = "connection_not_ready"

        if reason is not None:
            log_phantom_side_reject(
                request.execution_id if request is not None else "unknown",
                request.trace_id if request is not None else "unknown",
                reason,
            )
            if self.metrics is not None:
                self.metrics.record_phantom_side_reject()
            return reason, None, None

        broker_request = checks.translate_position_adjustment(request, now)
        return None, broker_request, self._send_and_record(broker_request, now)

    def submit_position_close(
        self, request: Optional[PositionCloseRequest], now: datetime
    ) -> Tuple[Optional[str], Optional[BrokerRequest], Optional[BrokerResponse]]:
        reason = checks.validate_position_close(request)
        if reason is None and self.idempotency.has_closed(request.execution_id):
            reason = "duplicate_close"
        if reason is None and self.idempotency.has_submitted(request.execution_id, now):
            reason = "duplicate_submission"
        if reason is None and self.state != ConnectionState.READY:
            reason = "connection_not_ready"

        if reason is not None:
            log_phantom_side_reject(
                request.execution_id if request is not None else "unknown",
                request.trace_id if request is not None else "unknown",
                reason,
            )
            if self.metrics is not None:
                self.metrics.record_phantom_side_reject()
            return reason, None, None

        broker_request = checks.translate_position_close(request, now)
        response = self._send_and_record(broker_request, now)
        self.idempotency.record_closed(request.execution_id)
        return None, broker_request, response

    def _send_and_record(self, broker_request: BrokerRequest, now: datetime) -> BrokerResponse:
        log_submission(broker_request.execution_id, broker_request.trace_id, broker_request.request_kind.value)
        self.idempotency.record_submitted(broker_request.execution_id, now)
        response = self.adapter.send_request(broker_request)
        if isinstance(response, BrokerAcknowledgement):
            self.idempotency.record_acknowledged(response.execution_id)
            log_acknowledgement(response)
        elif isinstance(response, BrokerError):
            log_reject(response)
            if self.metrics is not None:
                self.metrics.record_broker_reject()
        return response

    # -- Execution polling and fills (§5, §7, §8) -----------------------

    def poll_execution(
        self, execution_id: str, trace_id: str, submitted_at: datetime, now: datetime
    ) -> Optional[Union[ExecutionReceipt, BrokerError]]:
        result = self.adapter.poll_execution(execution_id)
        if result is not None:
            if isinstance(result, ExecutionReceipt):
                log_execution(result)
            elif isinstance(result, BrokerError):
                log_reject(result)
                if self.metrics is not None:
                    self.metrics.record_broker_reject()
            return result

        elapsed = (now - submitted_at).total_seconds()
        if elapsed > self.config.acknowledgement_timeout_seconds:
            log_timeout(execution_id, trace_id, "poll_execution")
            if self.metrics is not None:
                self.metrics.record_timeout()
        return None

    def record_fill(self, fill: FillReport) -> bool:
        """Returns `True` if this fill was newly recorded, `False` if it
        is a duplicate of an already-recorded terminal fill for this
        `execution_id` (§7: "flagged, not silently accepted as a second,
        additional fill")."""
        if self.idempotency.has_filled(fill.execution_id):
            return False
        self.idempotency.record_filled(fill.execution_id)
        log_fill(fill)
        return True
