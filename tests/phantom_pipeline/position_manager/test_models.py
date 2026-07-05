"""Boundary/type-level and immutability tests (ADR-009 §5, §6, §14)."""

from __future__ import annotations

import dataclasses
import unittest

from phantom_pipeline.mt5_bridge.models import PositionAdjustmentRequest as BridgePositionAdjustmentRequest
from phantom_pipeline.mt5_bridge.models import PositionCloseRequest as BridgePositionCloseRequest
from phantom_pipeline.position_manager.models import (
    LifecycleState,
    ManagementAction,
    PositionAdjustmentRequest,
    PositionCloseRequest,
    PositionManagementDecision,
    PositionSynchronizationResult,
    PositionUpdate,
    RuleEvaluation,
    RuleStatus,
)
from tests.phantom_pipeline.position_manager._fixtures import T0

FORBIDDEN_FIELD_NAME_FRAGMENTS = ("score", "verdict", "risk_percent", "approved_risk", "compliance_", "blocking")


class TestOwnershipMove(unittest.TestCase):
    """ADR-009 explicitly transfers ownership of these two types from
    `mt5_bridge` (where they were defined provisionally during ADR-008
    Phase 1) — `mt5_bridge.models` must re-export the exact same class
    objects, not a duplicate definition."""

    def test_mt5_bridge_reexports_the_same_position_adjustment_request_class(self):
        self.assertIs(BridgePositionAdjustmentRequest, PositionAdjustmentRequest)

    def test_mt5_bridge_reexports_the_same_position_close_request_class(self):
        self.assertIs(BridgePositionCloseRequest, PositionCloseRequest)


class TestOutputTypesImmutable(unittest.TestCase):
    def test_position_management_decision_frozen(self):
        decision = PositionManagementDecision(
            schema_version=1, position_id="p1", trace_id="t1", action=ManagementAction.NO_ACTION,
            decision_reason="no_rule_triggered", rule_evaluations=(), timestamp=T0, position_manager_version="1.0.0-phase1",
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            decision.action = ManagementAction.EMERGENCY_CLOSE  # type: ignore[misc]

    def test_rule_evaluations_coerced_to_tuple(self):
        decision = PositionManagementDecision(
            schema_version=1, position_id="p1", trace_id="t1", action=ManagementAction.NO_ACTION,
            decision_reason="x", rule_evaluations=[RuleEvaluation("X", RuleStatus.NOT_TRIGGERED, "")],
            timestamp=T0, position_manager_version="1.0.0-phase1",
        )
        self.assertIsInstance(decision.rule_evaluations, tuple)

    def test_rule_evaluation_frozen(self):
        evaluation = RuleEvaluation("BREAK_EVEN", RuleStatus.TRIGGERED, "x")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            evaluation.status = RuleStatus.NOT_TRIGGERED  # type: ignore[misc]

    def test_position_update_frozen(self):
        update = PositionUpdate(
            schema_version=1, position_id="p1", trace_id="t1", lifecycle_state=LifecycleState.FILLED,
            unrealized_pnl=0.001, current_price=1.1, timestamp=T0,
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            update.current_price = 1.2  # type: ignore[misc]

    def test_position_synchronization_result_frozen(self):
        result = PositionSynchronizationResult(
            schema_version=1, position_id="p1", trace_id="t1", lifecycle_state=LifecycleState.RECOVERED,
            broker_position_found=True, detail="x", timestamp=T0,
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            result.broker_position_found = False  # type: ignore[misc]

    def test_position_adjustment_request_frozen(self):
        request = PositionAdjustmentRequest(
            schema_version=1, execution_id="e1", trace_id="t1", position_id="p1",
            new_stop_loss=1.05, new_take_profit=None, timestamp=T0,
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            request.new_stop_loss = 1.06  # type: ignore[misc]

    def test_position_close_request_frozen(self):
        request = PositionCloseRequest(
            schema_version=1, execution_id="e1", trace_id="t1", position_id="p1", close_fraction=1.0, timestamp=T0
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            request.close_fraction = 0.5  # type: ignore[misc]


class TestBoundaryTypeLevel(unittest.TestCase):
    def _assert_no_forbidden_fields(self, cls):
        field_names = {f.name for f in dataclasses.fields(cls)}
        for fragment in FORBIDDEN_FIELD_NAME_FRAGMENTS:
            for name in field_names:
                self.assertNotIn(fragment, name, f"forbidden fragment '{fragment}' found in '{cls.__name__}.{name}'")

    def test_no_output_type_holds_a_forbidden_field(self):
        for cls in (
            PositionManagementDecision,
            PositionUpdate,
            PositionSynchronizationResult,
            PositionAdjustmentRequest,
            PositionCloseRequest,
        ):
            self._assert_no_forbidden_fields(cls)


if __name__ == "__main__":
    unittest.main()
