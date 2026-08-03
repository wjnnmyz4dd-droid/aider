"""Compliance-Engine-only metrics surface (ADR-006 §17) — export-only,
additive, zero effect on returned decisions."""

from __future__ import annotations

import unittest

from phantom_pipeline.compliance_engine.config import ComplianceEngineConfig
from phantom_pipeline.compliance_engine.engine import ComplianceEngine
from phantom_pipeline.compliance_engine.metrics import ComplianceEngineMetrics
from phantom_pipeline.compliance_engine.models import NewsCalendarState
from phantom_pipeline.compliance_engine.state_store import InMemoryComplianceStateStore
from tests.phantom_pipeline.compliance_engine._fixtures import (
    SYMBOL,
    make_account_state,
    make_candidate,
    make_market_snapshot,
    make_risk_decision,
    make_score_result,
)

NOMINAL_CONFIG = ComplianceEngineConfig(
    spread_thresholds={SYMBOL: 0.0005}, slippage_thresholds={SYMBOL: 0.0005}
)


def _nominal_inputs():
    candidate = make_candidate()
    score_result = make_score_result(candidate)
    risk_decision = make_risk_decision(candidate, score_result)
    account = make_account_state()
    snapshot = make_market_snapshot()
    news = NewsCalendarState(feed_stale=False, blackout_windows=())
    return risk_decision, candidate, score_result, account, snapshot, news


class TestComplianceEngineMetrics(unittest.TestCase):
    def test_decisions_counted_by_verdict(self):
        metrics = ComplianceEngineMetrics()
        engine = ComplianceEngine(InMemoryComplianceStateStore(), NOMINAL_CONFIG, metrics=metrics)

        decision = engine.evaluate(*_nominal_inputs(), expected_slippage=0.0001)

        self.assertEqual(metrics.decisions_by_verdict.get(decision.verdict.value), 1)

    def test_blocks_counted_by_every_triggering_check_not_only_the_first(self):
        metrics = ComplianceEngineMetrics()
        engine = ComplianceEngine(InMemoryComplianceStateStore(), NOMINAL_CONFIG, metrics=metrics)
        risk_decision, candidate, score_result, _, snapshot, news = _nominal_inputs()
        # Breach both daily and total drawdown simultaneously.
        account = make_account_state(daily_drawdown_pct=5.0, total_drawdown_pct=9.0)

        engine.evaluate(risk_decision, candidate, score_result, account, snapshot, news)

        self.assertEqual(metrics.blocks_by_check.get("DAILY_DRAWDOWN"), 1)
        self.assertEqual(metrics.blocks_by_check.get("TOTAL_DRAWDOWN"), 1)

    def test_kill_switch_gauge_reflects_latched_state(self):
        metrics = ComplianceEngineMetrics()
        engine = ComplianceEngine(InMemoryComplianceStateStore(), NOMINAL_CONFIG, metrics=metrics)
        risk_decision, candidate, score_result, _, snapshot, news = _nominal_inputs()
        account = make_account_state(total_drawdown_pct=9.0)

        self.assertFalse(metrics.kill_switch_active)
        engine.evaluate(risk_decision, candidate, score_result, account, snapshot, news)
        self.assertTrue(metrics.kill_switch_active)

    def test_recording_metrics_never_alters_returned_decision(self):
        inputs = _nominal_inputs()
        without_metrics = ComplianceEngine(InMemoryComplianceStateStore(), NOMINAL_CONFIG).evaluate(
            *inputs, expected_slippage=0.0001
        )
        with_metrics = ComplianceEngine(
            InMemoryComplianceStateStore(), NOMINAL_CONFIG, metrics=ComplianceEngineMetrics()
        ).evaluate(*inputs, expected_slippage=0.0001)

        self.assertEqual(without_metrics, with_metrics)

    def test_snapshots_are_copies_not_live_views(self):
        metrics = ComplianceEngineMetrics()
        engine = ComplianceEngine(InMemoryComplianceStateStore(), NOMINAL_CONFIG, metrics=metrics)
        engine.evaluate(*_nominal_inputs(), expected_slippage=0.0001)

        snapshot = metrics.decisions_by_verdict
        snapshot["INJECTED"] = 999
        self.assertNotIn("INJECTED", metrics.decisions_by_verdict)


if __name__ == "__main__":
    unittest.main()
