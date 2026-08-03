"""Replay determinism / replay consistency (VALIDATION_MATRIX.md §1 /
ADR-013 §16, Hard Rules)."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from phantom_pipeline.data_pipeline.config import PipelineConfig
from phantom_pipeline.data_pipeline.pipeline import DataPipeline
from phantom_pipeline.data_pipeline.replay import ReplayRecorder, replay_through

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


class TestReplayRecorderBoundedMemory(unittest.TestCase):
    """Remediation for the audit finding: ReplayRecorder previously grew
    unboundedly. Eviction must be deterministic (oldest-first, FIFO) and
    must not affect replay ordering or output for anything still within
    the bound."""

    def test_pipeline_level_capture_is_also_bounded(self):
        # The bound applies end-to-end through DataPipeline, not only to
        # a directly-constructed ReplayRecorder.
        config = PipelineConfig(replay_max_ticks_per_symbol=3)
        pipeline = DataPipeline(config)
        for i in range(5):
            pipeline.process_raw_tick(
                "EURUSD", T0 + timedelta(seconds=i), 1.1000 + i * 0.0001,
                1.1002 + i * 0.0001, None, 1.0, "test",
            )
        series = pipeline.capture_replay("EURUSD")
        self.assertEqual(len(series.ticks), 3)

    def test_recorder_bounds_ticks_to_configured_maximum(self):
        config = PipelineConfig(replay_max_ticks_per_symbol=3)
        recorder = ReplayRecorder("EURUSD", config)
        for i in range(5):
            tick_result = _make_tick(i)
            recorder.record_tick(tick_result)
        series = recorder.to_replay_series()
        self.assertEqual(len(series.ticks), 3)
        # Deterministic FIFO: the *oldest* two (index 0, 1) are evicted;
        # the newest three (index 2, 3, 4) remain, in order.
        self.assertEqual([t.volume for t in series.ticks], [2.0, 3.0, 4.0])

    def test_recorder_bounds_bars_to_configured_maximum(self):
        config = PipelineConfig(replay_max_bars_per_symbol=2)
        recorder = ReplayRecorder("EURUSD", config)
        pipeline = DataPipeline(config)
        for minute in range(4):
            pipeline.process_raw_tick(
                "EURUSD",
                T0 + timedelta(minutes=minute),
                1.1000 + minute * 0.0005,
                1.1002 + minute * 0.0005,
                None,
                1.0,
                "test",
            )
        pipeline.flush("EURUSD")
        for bar in pipeline.get_historical_series("EURUSD", "M1").bars:
            recorder.record_bar(bar)
        series = recorder.to_replay_series()
        self.assertEqual(len(series.bars), 2)

    def test_eviction_does_not_affect_replay_output_within_bound(self):
        # A generous bound (the default) must behave identically to the
        # unbounded implementation for any run that never exceeds it —
        # existing replay-determinism tests above already prove this for
        # the default config; this test pins that guarantee explicitly.
        config = PipelineConfig()
        live = DataPipeline(config)
        _feed_ticks(live)
        replay_series = live.capture_replay("EURUSD")
        self.assertEqual(len(replay_series.ticks), 12)

        fresh = DataPipeline(config)
        replay_through(replay_series, fresh)
        fresh.flush("EURUSD")
        self.assertEqual(
            live.get_historical_series("EURUSD", "M1").bars,
            fresh.get_historical_series("EURUSD", "M1").bars,
        )

    def test_recorder_ignores_ticks_for_a_different_symbol(self):
        config = PipelineConfig()
        recorder = ReplayRecorder("EURUSD", config)
        recorder.record_tick(_make_tick(0, symbol="GBPUSD"))
        series = recorder.to_replay_series()
        self.assertEqual(len(series.ticks), 0)


def _make_tick(index: int, symbol: str = "EURUSD"):
    from phantom_pipeline.data_pipeline.models import NormalizedTick, SCHEMA_VERSION

    return NormalizedTick(
        schema_version=SCHEMA_VERSION,
        trace_id=f"trace-{index}",
        symbol=symbol,
        timestamp=T0 + timedelta(seconds=index),
        bid=1.1000 + index * 0.0001,
        ask=1.1002 + index * 0.0001,
        last=None,
        volume=float(index),
        source="test",
    )


if __name__ == "__main__":
    unittest.main()
