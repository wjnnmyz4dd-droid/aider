"""DataPipeline orchestration: snapshot generation, health signal, and
end-to-end wiring (VALIDATION_MATRIX.md §1)."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from phantom_pipeline.data_pipeline.config import PipelineConfig
from phantom_pipeline.data_pipeline.pipeline import DataPipeline

T0 = datetime(2026, 7, 4, 12, 0, 0, tzinfo=timezone.utc)


class TestMarketSnapshot(unittest.TestCase):
    def test_snapshot_reflects_latest_tick(self):
        pipeline = DataPipeline(PipelineConfig())
        pipeline.process_raw_tick("EURUSD", T0, 1.1000, 1.1002, None, 1.0, "test")
        pipeline.process_raw_tick(
            "EURUSD", T0 + timedelta(seconds=1), 1.1005, 1.1007, None, 1.0, "test"
        )
        snapshot = pipeline.get_snapshot("EURUSD")
        self.assertIsNotNone(snapshot)
        self.assertAlmostEqual(snapshot.price, (1.1005 + 1.1007) / 2.0)
        self.assertAlmostEqual(snapshot.spread, 1.1007 - 1.1005)

    def test_no_snapshot_before_first_tick(self):
        pipeline = DataPipeline(PipelineConfig())
        self.assertIsNone(pipeline.get_snapshot("EURUSD"))

    def test_symbol_normalization_applies_to_snapshot_key(self):
        config = PipelineConfig(symbol_aliases={"EURUSD.a": "EURUSD"})
        pipeline = DataPipeline(config)
        pipeline.process_raw_tick("EURUSD.a", T0, 1.1000, 1.1002, None, 1.0, "test")
        self.assertIsNotNone(pipeline.get_snapshot("EURUSD"))
        self.assertIsNone(pipeline.get_snapshot("EURUSD.a"))


class TestPipelineHealth(unittest.TestCase):
    def test_healthy_when_no_gaps(self):
        pipeline = DataPipeline(PipelineConfig())
        pipeline.process_raw_tick("EURUSD", T0, 1.1000, 1.1002, None, 1.0, "test")
        health = pipeline.get_health(now=T0, gap_count=0)
        self.assertEqual(health.status, "HEALTHY")
        self.assertIsNone(health.reason)
        self.assertEqual(health.ticks_processed, 1)

    def test_degraded_when_gaps_present(self):
        pipeline = DataPipeline(PipelineConfig())
        health = pipeline.get_health(now=T0, gap_count=2)
        self.assertEqual(health.status, "DEGRADED")
        self.assertIsNotNone(health.reason)


class TestEndToEndDeterminism(unittest.TestCase):
    def test_identical_tick_sequence_produces_identical_full_pipeline_state(self):
        config = PipelineConfig()

        def run():
            pipeline = DataPipeline(config)
            for i in range(20):
                pipeline.process_raw_tick(
                    "EURUSD",
                    T0 + timedelta(seconds=i * 15),
                    1.1000 + i * 0.00005,
                    1.1002 + i * 0.00005,
                    None,
                    1.0,
                    "test",
                )
            pipeline.flush("EURUSD")
            return pipeline

        p1 = run()
        p2 = run()

        self.assertEqual(
            p1.get_historical_series("EURUSD", "M1").bars,
            p2.get_historical_series("EURUSD", "M1").bars,
        )
        self.assertEqual(p1.get_snapshot("EURUSD"), p2.get_snapshot("EURUSD"))
        self.assertEqual(p1.ticks_processed, p2.ticks_processed)
        self.assertEqual(p1.bars_produced, p2.bars_produced)


if __name__ == "__main__":
    unittest.main()
