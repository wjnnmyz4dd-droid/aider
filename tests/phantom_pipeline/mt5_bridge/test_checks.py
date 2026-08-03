"""Validation and translation unit tests (ADR-008 §1, §2, §4, §7)."""

from __future__ import annotations

import unittest

from phantom_pipeline.execution_validator.models import Verdict as ExecutionVerdict
from phantom_pipeline.mt5_bridge import checks as c
from phantom_pipeline.mt5_bridge.models import PositionAdjustmentRequest, PositionCloseRequest, RequestKind
from tests.phantom_pipeline.mt5_bridge._fixtures import PRICE, STOP_DISTANCE, T0, make_full_chain


class TestValidateExecutionDecision(unittest.TestCase):
    def test_missing_is_rejected(self):
        self.assertEqual(c.validate_execution_decision(None), "missing_execution_decision")

    def test_approve_passes(self):
        *_, execution_decision = make_full_chain()
        self.assertIsNone(c.validate_execution_decision(execution_decision))

    def test_reject_verdict_is_rejected(self):
        *_, execution_decision = make_full_chain()
        rejected = execution_decision.__class__(
            **{**execution_decision.__dict__, "verdict": ExecutionVerdict.REJECT}
        )
        self.assertEqual(c.validate_execution_decision(rejected), "execution_decision_not_approved")


class TestValidateOrderConsistency(unittest.TestCase):
    def test_missing_risk_decision(self):
        candidate, _, _, compliance_decision, execution_decision = make_full_chain()
        self.assertEqual(
            c.validate_order_consistency(candidate, None, compliance_decision, execution_decision),
            "missing_risk_decision",
        )

    def test_missing_compliance_decision(self):
        candidate, _, risk_decision, _, execution_decision = make_full_chain()
        self.assertEqual(
            c.validate_order_consistency(candidate, risk_decision, None, execution_decision),
            "missing_compliance_decision",
        )

    def test_consistent_chain_passes(self):
        candidate, _, risk_decision, compliance_decision, execution_decision = make_full_chain()
        self.assertIsNone(c.validate_order_consistency(candidate, risk_decision, compliance_decision, execution_decision))

    def test_mismatched_candidate_fails(self):
        from tests.phantom_pipeline.mt5_bridge._fixtures import make_candidate

        candidate, _, risk_decision, compliance_decision, execution_decision = make_full_chain()
        other = make_candidate(trace_id="different-trace")
        self.assertEqual(
            c.validate_order_consistency(other, risk_decision, compliance_decision, execution_decision),
            "trace_id_candidate_id_mismatch",
        )


class TestValidateSizing(unittest.TestCase):
    def test_missing_lot_size_is_rejected(self):
        _, _, risk_decision, _, _ = make_full_chain()
        zeroed = risk_decision.__class__(**{**risk_decision.__dict__, "lot_size": None})
        self.assertEqual(c.validate_sizing(zeroed), "missing_lot_size")

    def test_valid_lot_size_passes(self):
        _, _, risk_decision, _, _ = make_full_chain()
        self.assertIsNone(c.validate_sizing(risk_decision))

    def test_non_positive_lot_size_is_rejected(self):
        _, _, risk_decision, _, _ = make_full_chain()
        zeroed = risk_decision.__class__(**{**risk_decision.__dict__, "lot_size": 0.0})
        self.assertEqual(c.validate_sizing(zeroed), "invalid_lot_size")


class TestValidatePositionAdjustment(unittest.TestCase):
    def test_missing_request_is_rejected(self):
        self.assertEqual(c.validate_position_adjustment(None), "missing_position_adjustment_request")

    def test_missing_position_id_is_rejected(self):
        request = PositionAdjustmentRequest(1, "e1", "t1", "", 1.0, None, T0)
        self.assertEqual(c.validate_position_adjustment(request), "missing_position_id")

    def test_no_change_specified_is_rejected(self):
        request = PositionAdjustmentRequest(1, "e1", "t1", "p1", None, None, T0)
        self.assertEqual(c.validate_position_adjustment(request), "no_adjustment_specified")

    def test_valid_request_passes(self):
        request = PositionAdjustmentRequest(1, "e1", "t1", "p1", 1.05, None, T0)
        self.assertIsNone(c.validate_position_adjustment(request))


class TestValidatePositionClose(unittest.TestCase):
    def test_missing_request_is_rejected(self):
        self.assertEqual(c.validate_position_close(None), "missing_position_close_request")

    def test_invalid_fraction_is_rejected(self):
        request = PositionCloseRequest(1, "e1", "t1", "p1", 1.5, T0)
        self.assertEqual(c.validate_position_close(request), "invalid_close_fraction")

    def test_full_close_passes(self):
        request = PositionCloseRequest(1, "e1", "t1", "p1", 1.0, T0)
        self.assertIsNone(c.validate_position_close(request))

    def test_partial_close_passes(self):
        request = PositionCloseRequest(1, "e1", "t1", "p1", 0.5, T0)
        self.assertIsNone(c.validate_position_close(request))


class TestTranslateOrder(unittest.TestCase):
    def test_direct_field_mapping_no_rederivation(self):
        candidate, _, risk_decision, _, execution_decision = make_full_chain()
        broker_request = c.translate_order(
            execution_decision, risk_decision, candidate, "exec-1", PRICE - STOP_DISTANCE, PRICE + STOP_DISTANCE, T0
        )
        self.assertEqual(broker_request.request_kind, RequestKind.OPEN)
        self.assertEqual(broker_request.symbol, risk_decision.symbol)
        self.assertEqual(broker_request.direction, candidate.direction)
        self.assertEqual(broker_request.lot_size, risk_decision.lot_size)
        self.assertEqual(broker_request.stop_loss, PRICE - STOP_DISTANCE)
        self.assertEqual(broker_request.candidate_id, execution_decision.candidate_id)
        self.assertIsNone(broker_request.position_id)


class TestTranslatePositionAdjustment(unittest.TestCase):
    def test_direct_field_mapping(self):
        request = PositionAdjustmentRequest(1, "e1", "t1", "p1", 1.05, 1.2, T0)
        broker_request = c.translate_position_adjustment(request, T0)
        self.assertEqual(broker_request.request_kind, RequestKind.ADJUST)
        self.assertEqual(broker_request.position_id, "p1")
        self.assertEqual(broker_request.stop_loss, 1.05)
        self.assertEqual(broker_request.take_profit, 1.2)
        self.assertIsNone(broker_request.symbol)


class TestTranslatePositionClose(unittest.TestCase):
    def test_direct_field_mapping(self):
        request = PositionCloseRequest(1, "e1", "t1", "p1", 0.5, T0)
        broker_request = c.translate_position_close(request, T0)
        self.assertEqual(broker_request.request_kind, RequestKind.CLOSE)
        self.assertEqual(broker_request.position_id, "p1")
        self.assertEqual(broker_request.close_fraction, 0.5)


if __name__ == "__main__":
    unittest.main()
