"""Determinism category (ADR-030 §5.2): repeated verification of the
same recorded scenario must produce identical results."""

from __future__ import annotations

import unittest

from phantom.validation_engine.determinism import check_determinism, check_determinism_for_run
from tests.phantom.validation_engine._fixtures import make_config, make_scenario


class TestDeterminism(unittest.TestCase):
    def test_repeated_verification_is_identical(self):
        scenario = make_scenario()
        config = make_config(determinism_repeat_count=5)
        result = check_determinism(scenario, config)
        self.assertTrue(result.all_identical)
        self.assertEqual(result.mismatches, ())
        self.assertEqual(result.runs, 5)

    def test_run_level_report_aggregates_every_scenario(self):
        scenarios = [make_scenario(scenario_id=f"S{i}") for i in range(4)]
        config = make_config()
        report = check_determinism_for_run(scenarios, config)
        self.assertEqual(len(report.checks), 4)
        self.assertTrue(report.all_deterministic)


if __name__ == "__main__":
    unittest.main()
