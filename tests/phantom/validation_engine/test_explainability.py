"""Explainability category (ADR-030 §5.3): Evidence, Strategy, Risk,
Compliance, Bridge, Research must each carry a non-empty explanation."""

from __future__ import annotations

import dataclasses
import unittest

from phantom.validation_engine.explainability import build_explainability_report
from phantom.validation_engine.models import StageName
from tests.phantom.validation_engine._fixtures import make_execution_record, make_run, make_scenario


class TestExplainabilityReport(unittest.TestCase):
    def test_well_formed_run_is_fully_explained(self):
        scenario = make_scenario(execution=make_execution_record())
        report = build_explainability_report(make_run([scenario]))
        self.assertTrue(report.all_explained)
        self.assertEqual({c.stage for c in report.checks}, {
            StageName.EVIDENCE, StageName.STRATEGY, StageName.RISK,
            StageName.COMPLIANCE, StageName.BRIDGE, StageName.RESEARCH,
        })

    def test_missing_evidence_explanation_fails(self):
        scenario = make_scenario()
        broken_report = dataclasses.replace(scenario.evidence.report, confidence_explanation="")
        broken_evidence = dataclasses.replace(scenario.evidence, report=broken_report)
        broken_scenario = dataclasses.replace(scenario, evidence=broken_evidence)
        report = build_explainability_report(make_run([broken_scenario]))
        self.assertFalse(report.all_explained)
        evidence_check = next(c for c in report.checks if c.stage == StageName.EVIDENCE)
        self.assertFalse(evidence_check.has_explanation)

    def test_rejected_strategy_without_reason_fails(self):
        scenario = make_scenario(approved=False)
        broken_strategy = dataclasses.replace(scenario.strategy, rejection_reason=None)
        broken_scenario = dataclasses.replace(scenario, strategy=broken_strategy)
        report = build_explainability_report(make_run([broken_scenario]))
        strategy_check = next(c for c in report.checks if c.stage == StageName.STRATEGY)
        self.assertFalse(strategy_check.has_explanation)

    def test_no_research_snapshot_is_skipped_not_failed(self):
        scenario = make_scenario()
        report = build_explainability_report(make_run([scenario], research_snapshot=None))
        research_check = next(c for c in report.checks if c.stage == StageName.RESEARCH)
        self.assertTrue(research_check.has_explanation)
        self.assertIn("skipped", research_check.detail)

    def test_no_execution_record_is_skipped_not_failed(self):
        scenario = make_scenario(execution=None)
        report = build_explainability_report(make_run([scenario]))
        bridge_check = next(c for c in report.checks if c.stage == StageName.BRIDGE)
        self.assertTrue(bridge_check.has_explanation)


if __name__ == "__main__":
    unittest.main()
