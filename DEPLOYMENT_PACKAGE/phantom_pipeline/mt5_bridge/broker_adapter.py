"""The broker communication boundary (ADR-008 §1, §10, §16).

`BrokerAdapter` is the sole abstraction through which the MT5 Bridge
"owns MT5 communication" (ADR-008 §2) — every broker call the engine
makes goes through this interface, never inline. No dedicated MT5
broker-communication module exists anywhere in this repository yet (no
`MetaTrader5` import, no `order_send` — ADR-008 §16 states this
explicitly and treats it as a from-first-principles design, not a
migration). Phase 1 ships `FakeBrokerAdapter`, a fully deterministic,
in-memory test double — the same "no live external dependency in unit
tests" discipline `ADR-002` §15 and `ADR-015` §11 already established
for every other stage. A real adapter wrapping the `MetaTrader5` package
is future work (ADR-008 §16's own acknowledgement that this stage is
greenfield), not invented here.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional, Tuple

from .models import BrokerAcknowledgement, BrokerError, BrokerRequest, ExecutionReceipt


class BrokerAdapter(ABC):
    @abstractmethod
    def connect(self) -> bool:
        ...

    @abstractmethod
    def disconnect(self) -> None:
        ...

    @abstractmethod
    def heartbeat(self) -> bool:
        ...

    @abstractmethod
    def send_request(self, request: BrokerRequest) -> "BrokerAcknowledgement | BrokerError":
        ...

    @abstractmethod
    def poll_execution(self, execution_id: str) -> Optional["ExecutionReceipt | BrokerError"]:
        ...

    @abstractmethod
    def query_open_position_ids(self) -> Tuple[str, ...]:
        ...

    @abstractmethod
    def query_account_equity(self) -> Optional[float]:
        ...


class FakeBrokerAdapter(BrokerAdapter):
    """A deterministic, fully scriptable in-memory broker double for
    tests. Nothing here talks to any real network or process — every
    response is either programmed in advance via the constructor/setter
    methods, or a fixed deterministic default."""

    def __init__(
        self,
        connect_result: bool = True,
        heartbeat_result: bool = True,
        expected_position_ids: Tuple[str, ...] = (),
        account_equity: Optional[float] = 10000.0,
    ) -> None:
        self._connect_result = connect_result
        self._heartbeat_result = heartbeat_result
        self._expected_position_ids = expected_position_ids
        self._account_equity = account_equity
        self._connected = False
        self._acknowledgements: dict = {}
        self._errors_on_send: dict = {}
        self._execution_results: dict = {}

    def connect(self) -> bool:
        self._connected = self._connect_result
        return self._connected

    def disconnect(self) -> None:
        self._connected = False

    def heartbeat(self) -> bool:
        return self._heartbeat_result

    def set_heartbeat_result(self, result: bool) -> None:
        self._heartbeat_result = result

    def set_error_on_send(self, execution_id: str, reason: str) -> None:
        self._errors_on_send[execution_id] = reason

    def set_execution_result(self, execution_id: str, result) -> None:
        self._execution_results[execution_id] = result

    def set_open_position_ids(self, position_ids: Tuple[str, ...]) -> None:
        self._expected_position_ids = position_ids

    def send_request(self, request: BrokerRequest):
        if request.execution_id in self._errors_on_send:
            return BrokerError(
                schema_version=1,
                execution_id=request.execution_id,
                trace_id=request.trace_id,
                request_kind=request.request_kind,
                reason=self._errors_on_send[request.execution_id],
                timestamp=request.timestamp,
            )
        broker_ref = f"broker-ref-{request.execution_id}"
        self._acknowledgements[request.execution_id] = broker_ref
        return BrokerAcknowledgement(
            schema_version=1,
            execution_id=request.execution_id,
            trace_id=request.trace_id,
            request_kind=request.request_kind,
            broker_ref=broker_ref,
            timestamp=request.timestamp,
        )

    def poll_execution(self, execution_id: str):
        return self._execution_results.get(execution_id)

    def query_open_position_ids(self) -> Tuple[str, ...]:
        return self._expected_position_ids

    def query_account_equity(self) -> Optional[float]:
        return self._account_equity
