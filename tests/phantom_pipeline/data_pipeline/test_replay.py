"""Replay determinism / replay consistency (VALIDATION_MATRIX.md §1 /
ADR-013 §16, Hard Rules)."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from phantom_pipeline.data_pipeline.config import PipelineConfig
from phantom_pipeline.data_pipeline.pipeline import DataPipeline
from phantom_pipeline.data_pipeline.replay import replay_through

T0 = datetime(2026, 7, 4, 12, 0, 0, tzinfo=timezone.utc)


def _feed_ticks(pipeline: DataPipeline, count=12, step_seconds=10):
    for i in range(count):
        pipeline.process_raw_tick(
            raw_symbol="EURUSD",
            raw_timestamp=T0 + timedelta(seconds=i * step_seconds),
            bid=1.1000 + i * 0.0001,
            ask=1.1002 + i * 0.0001,
            last=None,
            volume=1.0,
            source="test",
        )
    pipeline.flush("EURUSD")


class TestReplayDeterminism(unittest.TestCase):
    def test_replay_reproduces_identical_bars(self):
        config = PipelineConfig()

        live = DataPipeline(config)
        _feed_ticks(live)
        live_bars = live.get_historical_series("EURUSD", "M1").bars

        replay_series = live.capture_replay("EURUSD")

        fresh = DataPipeline(config)
        replayed_bars = replay_through(replay_series, fresh)
        fresh.flush("EURUSD")

        self.assertEqual(live_bars, fresh.get_historical_series("EURUSD", "M1").bars)
        self.assertTrue(replayed_bars or fresh.get_historical_series("EURUSD", "M1").bars)

    def test_replay_series_is_immutable_snapshot(self):
        config = PipelineConfig()
        live = DataPipeline(config)
        _feed_ticks(live)
        replay_series = live.capture_replay("EURUSD")
        tick_count_before = len(replay_series.ticks)

        # Continue feeding the live pipeline after capture.
        _feed_ticks(live, count=3)

        self.assertEqual(len(replay_series.ticks), tick_count_before)

    def test_two_independent_replays_of_the_same_series_match(self):
        config = PipelineConfig()
        live = DataPipeline(config)
        _feed_ticks(live)
        replay_series = live.capture_replay("EURUSD")

        p1 = DataPipeline(config)
        p2 = DataPipeline(config)
        bars1 = replay_through(replay_series, p1)
        bars2 = replay_through(replay_series, p2)
        p1.flush("EURUSD")
        p2.flush("EURUSD")

        self.assertEqual(bars1, bars2)
        self.assertEqual(
            p1.get_historical_series("EURUSD", "M1").bars,
            p2.get_historical_series("EURUSD", "M1").bars,
        )

    def test_trace_id_is_stable_across_replay(self):
        config = PipelineConfig()
        live = DataPipeline(config)
        _feed_ticks(live)
        live_bars = live.get_historical_series("EURUSD", "M1").bars

        replay_series = live.capture_replay("EURUSD")
        fresh = DataPipeline(config)
        replay_through(replay_series, fresh)
        fresh.flush("EURUSD")
        replayed_bars = fresh.get_historical_series("EURUSD", "M1").bars

        self.assertEqual(
            [b.trace_id for b in live_bars],
            [b.trace_id for b in replayed_bars],
        )


if __name__ == "__main__":
    unittest.main()
