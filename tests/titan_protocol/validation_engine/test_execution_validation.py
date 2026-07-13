"""Unit category (ADR-030 §5.12): Execution Validation -- static
consistency checks over recorded `BridgeExecutionRecord`s."""

from __future__ import annotations

import unittest

from titan_protocol.compliance_engine.models import ComplianceDecision
from titan_protocol.validation_engine.execution_validation import validate_execution
from tests.titan_protocol.validation_engine._fixtures import make_config, make_execution_record, make_scenario


class TestExecutionValidation(unittest.TestCase):
    def test_consistent_execution_passes(self):
        execution = make_execution_record(approved_size_r=1.0, executed_size_r=1.0, was_executed=True)
        scenario = make_scenario(approved=True, decision=ComplianceDecision.APPROVE, execution=execution)
        result = validate_execution([scenario], make_config())
        self.assertTrue(result.passed)
        self.assertEqual(result.records_checked, 1)

    def test_executed_size_exceeding_approved_size_fails(self):
        execution = make_execution_record(approved_size_r=1.0, executed_size_r=5.0, was_executed=True)
        scenario = make_scenario(approved=True, decision=ComplianceDecision.APPROVE, execution=execution)
        result = validate_execution([scenario], make_config())
        self.assertFalse(result.passed)
        self.assertTrue(result.violations)

    def test_executed_without_compliance_ready_fails(self):
        execution = make_execution_record(approved_size_r=1.0, executed_size_r=1.0, was_executed=True)
        scenario = make_scenario(approved=False, decision=ComplianceDecision.REJECT, execution=execution)
        result = validate_execution([scenario], make_config())
        self.assertFalse(result.passed)

    def test_excessive_slippage_fails(self):
        execution = make_execution_record(approved_size_r=1.0, executed_size_r=1.0, was_executed=True, slippage_pips=100.0)
        scenario = make_scenario(execution=execution)
        result = validate_execution([scenario], make_config(max_acceptable_slippage_pips=10.0))
        self.assertFalse(result.passed)

    def test_no_execution_records_is_trivially_passed(self):
        scenario = make_scenario(execution=None)
        result = validate_execution([scenario], make_config())
        self.assertTrue(result.passed)
        self.assertEqual(result.records_checked, 0)


if __name__ == "__main__":
    unittest.main()
