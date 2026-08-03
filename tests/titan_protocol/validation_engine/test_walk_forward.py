"""Unit category (ADR-030 §5.8): Walk-Forward Testing."""

from __future__ import annotations

import unittest
from datetime import timedelta

from titan_protocol.research_engine.config import ResearchEngineConfig
from titan_protocol.validation_engine.walk_forward import run_walk_forward
from tests.titan_protocol.validation_engine._fixtures import T0, make_config, make_executed_trade


class TestWalkForward(unittest.TestCase):
    def test_splits_into_three_sequential_buckets_by_count(self):
        config = make_config(research_config=ResearchEngineConfig(bucket_statistics_min_sample_size=1))
        trades = [make_executed_trade(index=i, won=(i % 2 == 0), r_multiple=(2.0 if i % 2 == 0 else -1.0)) for i in range(30)]
        result = run_walk_forward(trades, config)
        self.assertEqual(result.train_sample_size + result.validation_sample_size + result.out_of_sample_sample_size, 30)
        self.assertEqual(result.train_sample_size, 10)
        self.assertEqual(result.out_of_sample_sample_size, 10)

    def test_explicit_boundaries_are_respected(self):
        config = make_config(research_config=ResearchEngineConfig(bucket_statistics_min_sample_size=1))
        trades = [make_executed_trade(index=i, opened_at=T0 + timedelta(days=i)) for i in range(9)]
        train_end = T0 + timedelta(days=3)
        validation_end = T0 + timedelta(days=6)
        result = run_walk_forward(trades, config, train_end=train_end, validation_end=validation_end)
        self.assertEqual(result.train_sample_size, 3)
        self.assertEqual(result.validation_sample_size, 3)
        self.assertEqual(result.out_of_sample_sample_size, 3)

    def test_degradation_detected_when_out_of_sample_much_worse(self):
        config = make_config(
            research_config=ResearchEngineConfig(bucket_statistics_min_sample_size=1),
            min_sample_size_for_walk_forward_bucket=3,
            degradation_expectancy_delta_threshold=0.3,
        )
        train = [make_executed_trade(index=i, won=True, r_multiple=3.0, opened_at=T0 + timedelta(hours=i)) for i in range(10)]
        out_of_sample = [make_executed_trade(index=i + 20, won=False, r_multiple=-1.0, opened_at=T0 + timedelta(hours=i + 20)) for i in range(10)]
        result = run_walk_forward(train + out_of_sample, config, train_end=T0 + timedelta(hours=10), validation_end=T0 + timedelta(hours=15))
        self.assertTrue(result.degradation_detected)


if __name__ == "__main__":
    unittest.main()
