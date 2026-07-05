"""Boundary/type-level and immutability tests (ADR-008 §5, §13)."""

from __future__ import annotations

import dataclasses
import unittest

from phantom_pipeline.mt5_bridge.models import (
    BrokerAcknowledgement,
    BrokerError,
    BrokerRequest,
    ConnectionState,
    ConnectionStatus,
    ExecutionReceipt,
    FillReport,
    PositionAdjustmentRequest,
    PositionCloseRequest,
    RequestKind,
    SynchronizationStatus,
)
from phantom_pipeline.scanner.models import Direction
from tests.phantom_pipeline.mt5_bridge._fixtures import T0

FORBIDDEN_FIELD_NAME_FRAGMENTS = ("score", "verdict", "risk_percent", "approved_risk", "compliance", "blocking")


class TestOutputTypesImmutable(unittest.TestCase):
    def test_broker_request_frozen(self):
        request = BrokerRequest(
            schema_version=1,
            execution_id="e1",
            trace_id="t1",
            request_kind=RequestKind.OPEN,
            symbol="EURUSD",
            direction=Direction.UP,
            lot_size=1.0,
            stop_loss=1.0,
            take_profit=1.2,
            position_id=None,
            close_fraction=None,
            candidate_id="c1",
            timestamp=T0,
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            request.lot_size = 2.0  # type: ignore[misc]

    def test_synchronization_status_discrepancies_coerced_to_tuple(self):
        status = SynchronizationStatus(schema_version=1, in_sync=False, discrepancies=["x"], timestamp=T0)
        self.assertIsInstance(status.discrepancies, tuple)

    def test_connection_status_frozen(self):
        status = ConnectionStatus(schema_version=1, state=ConnectionState.READY, detail="ok", timestamp=T0)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            status.state = ConnectionState.DISCONNECTED  # type: ignore[misc]

    def test_broker_acknowledgement_frozen(self):
        ack = BrokerAcknowledgement(
            schema_version=1, execution_id="e1", trace_id="t1", request_kind=RequestKind.OPEN,
            broker_ref="r1", timestamp=T0,
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            ack.broker_ref = "r2"  # type: ignore[misc]

    def test_execution_receipt_frozen(self):
        receipt = ExecutionReceipt(
            schema_version=1, execution_id="e1", trace_id="t1", request_kind=RequestKind.OPEN,
            broker_ref="r1", filled_price=1.1, filled_size=1.0, timestamp=T0,
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            receipt.filled_price = 1.2  # type: ignore[misc]

    def test_broker_error_frozen(self):
        error = BrokerError(
            schema_version=1, execution_id="e1", trace_id="t1", request_kind=RequestKind.OPEN,
            reason="rejected", timestamp=T0,
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            error.reason = "other"  # type: ignore[misc]

    def test_fill_report_frozen(self):
        fill = FillReport(schema_version=1, execution_id="e1", trace_id="t1", fill_price=1.1, fill_size=1.0, fill_timestamp=T0)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            fill.fill_price = 1.2  # type: ignore[misc]

    def test_position_adjustment_request_frozen(self):
        request = PositionAdjustmentRequest(
            schema_version=1, execution_id="e1", trace_id="t1", position_id="p1",
            new_stop_loss=1.0, new_take_profit=1.2, timestamp=T0,
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            request.new_stop_loss = 1.05  # type: ignore[misc]

    def test_position_close_request_frozen(self):
        request = PositionCloseRequest(
            schema_version=1, execution_id="e1", trace_id="t1", position_id="p1", close_fraction=1.0, timestamp=T0
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            request.close_fraction = 0.5  # type: ignore[misc]


class TestBoundaryTypeLevel(unittest.TestCase):
    """No output type can hold a modified upstream decision field or a
    new trading instruction (ADR-008 §5)."""

    def _assert_no_forbidden_fields(self, cls):
        field_names = {f.name for f in dataclasses.fields(cls)}
        for fragment in FORBIDDEN_FIELD_NAME_FRAGMENTS:
            for name in field_names:
                self.assertNotIn(fragment, name, f"forbidden fragment '{fragment}' found in '{cls.__name__}.{name}'")

    def test_no_output_type_holds_a_forbidden_field(self):
        for cls in (
            BrokerRequest,
            BrokerAcknowledgement,
            ExecutionReceipt,
            BrokerError,
            FillReport,
            ConnectionStatus,
            SynchronizationStatus,
        ):
            self._assert_no_forbidden_fields(cls)


if __name__ == "__main__":
    unittest.main()
