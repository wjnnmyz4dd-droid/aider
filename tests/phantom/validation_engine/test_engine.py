"""Unit + Regression category: the `ValidationEngine` orchestrator
assembles every component into one `ValidationSnapshot`."""

from __future__ import annotations

import dataclasses
import unittest

from phantom.compliance_engine.models import ComplianceDecision
from phantom.validation_engine.config import ValidationEngineConfig
from phantom.validation_engine.engine import ValidationEngine
from tests.phantom.validation_engine._fixtures import (
    make_execution_record,
    make_repeating_executed_trades,
    make_run,
    make_scenario,
    make_trade_history,
)


class TestValidationEngineEvaluate(unittest.TestCase):
    def test_empty_inputs_produce_a_vacuously_passing_snapshot_with_warnings(self):
        engine = ValidationEngine(ValidationEngineConfig())
        snapshot = engine.evaluate(make_run([]), make_trade_history([]))
        self.assertTrue(snapshot.passed)
        self.assertTrue(snapshot.warnings)

    def test_well_formed_run_passes_end_to_end(self):
        engine = ValidationEngine(ValidationEngineConfig())
        scenario = make_scenario(execution=make_execution_record())
        run = make_run([scenario])
        trades = make_repeating_executed_trades(count=30, win_r=2.0, loss_r=-1.0, win_rate=0.5)
        snapshot = engine.evaluate(run, make_trade_history(trades))
        self.assertTrue(snapshot.passed)
        self.assertTrue(snapshot.strategy_tournament)
        self.assertIsNotNone(snapshot.monte_carlo_validation)

    def test_a_broken_scenario_fails_the_overall_snapshot(self):
        engine = ValidationEngine(ValidationEngineConfig())
        scenario = make_scenario()
        broken = dataclasses.replace(scenario, pair="SOMETHING_ELSE")
        snapshot = engine.evaluate(make_run([broken]), make_trade_history([]))
        self.assertFalse(snapshot.passed)

    def test_recommendations_are_advisory_text_only(self):
        engine = ValidationEngine(ValidationEngineConfig())
        trades = make_repeating_executed_trades(count=30, win_r=2.0, loss_r=-1.0, win_rate=0.5)
        snapshot = engine.evaluate(make_run([]), make_trade_history(trades))
        for recommendation in snapshot.recommendations:
            self.assertIsInstance(recommendation, str)

    def test_build_audit_report_is_pure_text_assembly(self):
        engine = ValidationEngine(ValidationEngineConfig())
        scenario = make_scenario()
        snapshot = engine.evaluate(make_run([scenario]), make_trade_history([]))
        report = engine.build_audit_report(snapshot)
        self.assertIsInstance(report, str)
        self.assertIn("PHANTOM VALIDATION ENGINE", report)


class TestValidationEngineRegression(unittest.TestCase):
    def test_30_trade_50pct_win_rate_2r1r_anchors_expectancy(self):
        engine = ValidationEngine(ValidationEngineConfig())
        trades = make_repeating_executed_trades(count=30, win_r=2.0, loss_r=-1.0, win_rate=0.5)
        snapshot = engine.evaluate(make_run([]), make_trade_history(trades))
        self.assertAlmostEqual(snapshot.strategy_tournament[0].statistics.rolling_expectancy, 0.5, places=6)


if __name__ == "__main__":
    unittest.main()
