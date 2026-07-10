"""Unit category (ADR-030 §5.10): Drift Detection -- current vs.
historical baseline, per strategy/pair/session/regime and execution
quality."""

from __future__ import annotations

import unittest

from phantom.research_engine.config import ResearchEngineConfig
from phantom.strategy_engine.models import StrategyId
from phantom.validation_engine.drift_detection import detect_drift
from tests.phantom.validation_engine._fixtures import make_config, make_executed_trade


class TestDriftDetection(unittest.TestCase):
    def test_no_degradation_when_performance_is_stable(self):
        config = make_config(
            research_config=ResearchEngineConfig(bucket_statistics_min_sample_size=1),
            min_sample_size_for_drift_bucket=5,
        )
        baseline = [make_executed_trade(index=i, won=True, r_multiple=1.0) for i in range(10)]
        current = [make_executed_trade(index=i + 20, won=True, r_multiple=1.0) for i in range(10)]
        analysis = detect_drift(baseline, current, config)
        self.assertFalse(analysis.any_degradation_detected)

    def test_degradation_detected_when_strategy_expectancy_collapses(self):
        config = make_config(
            research_config=ResearchEngineConfig(bucket_statistics_min_sample_size=1),
            min_sample_size_for_drift_bucket=5,
            degradation_expectancy_delta_threshold=0.3,
        )
        baseline = [make_executed_trade(index=i, strategy_id=StrategyId.TREND_CONTINUATION, won=True, r_multiple=3.0) for i in range(10)]
        current = [make_executed_trade(index=i + 20, strategy_id=StrategyId.TREND_CONTINUATION, won=False, r_multiple=-2.0) for i in range(10)]
        analysis = detect_drift(baseline, current, config)
        self.assertTrue(analysis.any_degradation_detected)
        strategy_findings = [f for f in analysis.findings if f.dimension == "STRATEGY"]
        self.assertTrue(any(f.degraded for f in strategy_findings))

    def test_insufficient_sample_size_produces_no_delta(self):
        config = make_config(min_sample_size_for_drift_bucket=50)
        baseline = [make_executed_trade(index=i) for i in range(5)]
        current = [make_executed_trade(index=i + 20) for i in range(5)]
        analysis = detect_drift(baseline, current, config)
        self.assertFalse(analysis.any_degradation_detected)
        self.assertTrue(all(f.delta is None for f in analysis.findings))


if __name__ == "__main__":
    unittest.main()
