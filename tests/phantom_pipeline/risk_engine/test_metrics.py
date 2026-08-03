"""Risk-Engine-only metrics surface (ADR-005 §17) — export-only,
additive, zero effect on returned decisions."""

from __future__ import annotations

import unittest

from phantom_pipeline.risk_engine.config import RiskEngineConfig
from phantom_pipeline.risk_engine.engine import RiskEngine
from phantom_pipeline.risk_engine.metrics import RiskEngineMetrics
from tests.phantom_pipeline.risk_engine._fixtures import (
    SYMBOL,
    make_account_state,
    make_candidate,
    make_score_result,
    nominal_observation,
)


class TestRiskEngineMetrics(unittest.TestCase):
    def test_decisions_counted_by_tier(self):
        metrics = RiskEngineMetrics()
        candidate = make_candidate()
        score_result = make_score_result(candidate)
        observation = nominal_observation()
        engine = RiskEngine(
            RiskEngineConfig(correlation_buckets={SYMBOL: "MAJORS"}), metrics=metrics
        )

        decision = engine.decide(score_result, candidate, observation, make_account_state())

        self.assertEqual(metrics.decisions_by_tier.get(decision.risk_tier.value), 1)

    def test_awarded_risk_percentages_recorded(self):
        metrics = RiskEngineMetrics()
        candidate = make_candidate()
        score_result = make_score_result(candidate)
        observation = nominal_observation()
        engine = RiskEngine(
            RiskEngineConfig(correlation_buckets={SYMBOL: "MAJORS"}), metrics=metrics
        )

        decision = engine.decide(score_result, candidate, observation, make_account_state())

        self.assertEqual(metrics.awarded_risk_percentages, [decision.approved_risk_percent])

    def test_zero_risk_decisions_counted_by_reason(self):
        metrics = RiskEngineMetrics()
        candidate = make_candidate()
        score_result = make_score_result(candidate)
        observation = nominal_observation()
        engine = RiskEngine(metrics=metrics)

        engine.decide(score_result, candidate, observation, None)

        self.assertEqual(metrics.zero_risk_by_reason.get("missing_account_state"), 1)

    def test_recording_metrics_never_alters_returned_decision(self):
        candidate = make_candidate()
        score_result = make_score_result(candidate)
        observation = nominal_observation()
        config = RiskEngineConfig(correlation_buckets={SYMBOL: "MAJORS"})
        account = make_account_state()

        without_metrics = RiskEngine(config).decide(score_result, candidate, observation, account)
        with_metrics = RiskEngine(config, metrics=RiskEngineMetrics()).decide(
            score_result, candidate, observation, account
        )

        self.assertEqual(without_metrics, with_metrics)

    def test_snapshots_are_copies_not_live_views(self):
        metrics = RiskEngineMetrics()
        candidate = make_candidate()
        score_result = make_score_result(candidate)
        observation = nominal_observation()
        engine = RiskEngine(metrics=metrics)
        engine.decide(score_result, candidate, observation, make_account_state())

        snapshot = metrics.decisions_by_tier
        snapshot["INJECTED"] = 999
        self.assertNotIn("INJECTED", metrics.decisions_by_tier)


if __name__ == "__main__":
    unittest.main()
