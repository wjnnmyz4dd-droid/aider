"""Stress category (ADR-030 §5.7): extreme market conditions must never
crash replay verification, and a defined subset must show a correctly
restricted recorded Compliance decision."""

from __future__ import annotations

import unittest

from titan_protocol.compliance_engine.models import ComplianceDecision
from titan_protocol.validation_engine.models import StressScenarioTag
from titan_protocol.validation_engine.stress_testing import run_stress_test, run_stress_tests
from tests.titan_protocol.validation_engine._fixtures import make_scenario


class TestStressTesting(unittest.TestCase):
    def test_hard_restriction_tag_requires_no_ready_for_bridge(self):
        scenario = make_scenario(approved=False, decision=ComplianceDecision.REJECT, stress_tag=StressScenarioTag.HOLIDAY_TRADING)
        result = run_stress_test(scenario)
        self.assertTrue(result.survived)
        self.assertTrue(result.correctly_restricted)

    def test_hard_restriction_tag_flags_incorrectly_permitted_trade(self):
        scenario = make_scenario(approved=True, decision=ComplianceDecision.APPROVE, stress_tag=StressScenarioTag.FLASH_CRASH)
        result = run_stress_test(scenario)
        self.assertTrue(result.survived)
        self.assertFalse(result.correctly_restricted)

    def test_soft_condition_tag_does_not_require_hard_block(self):
        scenario = make_scenario(approved=True, decision=ComplianceDecision.APPROVE, stress_tag=StressScenarioTag.HIGH_SPREAD)
        result = run_stress_test(scenario)
        self.assertTrue(result.survived)
        self.assertTrue(result.correctly_restricted)

    def test_run_stress_tests_only_includes_tagged_scenarios(self):
        tagged = make_scenario(scenario_id="tagged", stress_tag=StressScenarioTag.NFP)
        untagged = make_scenario(scenario_id="untagged", stress_tag=None)
        results = run_stress_tests([tagged, untagged])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].scenario_id, "tagged")

    def test_every_stress_tag_can_be_replayed_without_error(self):
        for tag in StressScenarioTag:
            scenario = make_scenario(scenario_id=tag.value, stress_tag=tag)
            result = run_stress_test(scenario)
            self.assertTrue(result.survived, f"{tag} raised during replay")


if __name__ == "__main__":
    unittest.main()
