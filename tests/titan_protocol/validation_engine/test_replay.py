"""Replay category (ADR-030 §5.1): structural/cross-stage verification
over recorded scenarios."""

from __future__ import annotations

import dataclasses
import unittest

from titan_protocol.compliance_engine.models import ComplianceDecision
from titan_protocol.validation_engine.models import StageName
from titan_protocol.validation_engine.replay import verify_run, verify_scenario
from tests.titan_protocol.validation_engine._fixtures import make_execution_record, make_scenario


class TestVerifyScenario(unittest.TestCase):
    def test_consistent_approved_scenario_passes(self):
        scenario = make_scenario(approved=True, decision=ComplianceDecision.APPROVE)
        result = verify_scenario(scenario)
        self.assertTrue(result.passed)
        self.assertEqual({v.stage for v in result.stage_verifications}, set(StageName) - {StageName.RESEARCH})

    def test_consistent_rejected_scenario_passes(self):
        scenario = make_scenario(approved=False, decision=ComplianceDecision.REJECT)
        result = verify_scenario(scenario)
        self.assertTrue(result.passed)

    def test_mismatched_pair_fails_evidence_stage(self):
        scenario = make_scenario(pair="EURUSD")
        # Corrupt the recorded pair without touching the frozen evidence snapshot's own symbol.
        broken = dataclasses.replace(scenario, pair="GBPUSD")
        result = verify_scenario(broken)
        self.assertFalse(result.passed)
        evidence_result = next(v for v in result.stage_verifications if v.stage == StageName.EVIDENCE)
        self.assertFalse(evidence_result.passed)

    def test_compliance_cannot_exceed_risk_recommendation(self):
        scenario = make_scenario(approved=True, decision=ComplianceDecision.APPROVE)
        inflated_compliance = dataclasses.replace(
            scenario.compliance, approved_size_r=scenario.compliance.original_size_r + 10.0,
        )
        broken = dataclasses.replace(scenario, compliance=inflated_compliance)
        result = verify_scenario(broken)
        self.assertFalse(result.passed)
        compliance_result = next(v for v in result.stage_verifications if v.stage == StageName.COMPLIANCE)
        self.assertFalse(compliance_result.passed)

    def test_bridge_execution_never_exceeds_approved_size(self):
        execution = make_execution_record(approved_size_r=1.0, executed_size_r=1.0, was_executed=True)
        oversized = dataclasses.replace(execution, executed_size_r=5.0)
        scenario = make_scenario(execution=oversized)
        result = verify_scenario(scenario)
        bridge_result = next(v for v in result.stage_verifications if v.stage == StageName.BRIDGE)
        self.assertFalse(bridge_result.passed)

    def test_bridge_stage_skipped_without_execution_record(self):
        scenario = make_scenario(execution=None)
        result = verify_scenario(scenario)
        bridge_result = next(v for v in result.stage_verifications if v.stage == StageName.BRIDGE)
        self.assertTrue(bridge_result.passed)


class TestVerifyRun(unittest.TestCase):
    def test_verify_run_covers_every_scenario(self):
        scenarios = [make_scenario(scenario_id=f"S{i}") for i in range(5)]
        results = verify_run(scenarios)
        self.assertEqual(len(results), 5)
        self.assertTrue(all(r.passed for r in results))


if __name__ == "__main__":
    unittest.main()
