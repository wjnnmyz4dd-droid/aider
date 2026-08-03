"""Scanner orchestration: determinism, purity, boundary/type-level,
duplicate-computation, replay-determinism, and Amendment 1 UNKNOWN-
handling tests (ADR-002 §2, §14, §15, §18)."""

from __future__ import annotations

import dataclasses
import unittest
from datetime import datetime, timedelta, timezone
from typing import get_type_hints

from phantom_pipeline.data_pipeline.config import PipelineConfig
from phantom_pipeline.data_pipeline.models import DataQuality, MarketSnapshot, NormalizedBar, SCHEMA_VERSION
from phantom_pipeline.data_pipeline.pipeline import DataPipeline
from phantom_pipeline.data_pipeline.replay import replay_through
from phantom_pipeline.scanner import composite, swing
from phantom_pipeline.scanner.config import ScannerConfig
from phantom_pipeline.scanner.models import (
    DataQualityFlag,
    Direction,
    EqualLevel,
    LiquidityEvent,
    MarketPhase,
    RangeStructure,
    ScannerObservation,
    SessionState,
    StructuralSignal,
    StructureConfidence,
    StructureKind,
    StructureTrendState,
    SwingKind,
    SwingPoint,
    SwingSequenceType,
    TrendReading,
    VolatilityLabel,
    VolatilityState,
)
from phantom_pipeline.scanner.scanner import Scanner

T0 = datetime(2026, 7, 4, 12, 0, 0, tzinfo=timezone.utc)

FORBIDDEN_FIELD_NAME_FRAGMENTS = (
    "score",
    "confidence_score",
    "buy",
    "sell",
    "approve",
    "reject",
    "block",
    "size",
    "stop_loss",
    "take_profit",
    "execution",
    "decision",
)


def _bar(i: int, close: float, timeframe: str = "M1") -> NormalizedBar:
    return NormalizedBar(
        schema_version=SCHEMA_VERSION,
        trace_id=f"b{i}",
        symbol="EURUSD",
        timeframe=timeframe,
        timestamp=T0 + timedelta(minutes=i),
        open=close,
        high=close + 0.0007,
        low=close - 0.0007,
        close=close,
        volume=1.0,
        quality=DataQuality.NOMINAL,
        is_repaired=False,
        source="test",
    )


def _healthy_bars(count: int) -> list:
    return [_bar(i, 1.1000 + (i % 24) * 0.0003) for i in range(count)]


def _snapshot(timestamp=None) -> MarketSnapshot:
    return MarketSnapshot(
        schema_version=SCHEMA_VERSION,
        trace_id="s1",
        symbol="EURUSD",
        timestamp=timestamp or T0,
        price=1.1000,
        spread=0.0002,
        market_status="OPEN",
    )


class TestDeterminism(unittest.TestCase):
    def test_identical_input_yields_identical_output(self):
        bars = _healthy_bars(120)
        snapshot = _snapshot(bars[-1].timestamp)
        scanner = Scanner(ScannerConfig())

        obs1 = scanner.scan("EURUSD", {"M1": bars}, snapshot, bars[-1].timestamp, "M1")
        obs2 = scanner.scan("EURUSD", {"M1": bars}, snapshot, bars[-1].timestamp, "M1")

        self.assertEqual(obs1, obs2)
        self.assertEqual(obs1.trace_id, obs2.trace_id)

    def test_different_bars_yield_different_trace_id(self):
        bars_a = _healthy_bars(120)
        bars_b = _healthy_bars(121)
        scanner = Scanner(ScannerConfig())

        obs_a = scanner.scan("EURUSD", {"M1": bars_a}, _snapshot(bars_a[-1].timestamp), bars_a[-1].timestamp, "M1")
        obs_b = scanner.scan("EURUSD", {"M1": bars_b}, _snapshot(bars_b[-1].timestamp), bars_b[-1].timestamp, "M1")

        self.assertNotEqual(obs_a.trace_id, obs_b.trace_id)


class TestPurity(unittest.TestCase):
    def test_mutating_scanner_metrics_after_a_scan_does_not_affect_output(self):
        bars = _healthy_bars(120)
        snapshot = _snapshot(bars[-1].timestamp)
        scanner = Scanner(ScannerConfig())

        obs_before = scanner.scan("EURUSD", {"M1": bars}, snapshot, bars[-1].timestamp, "M1")
        scanner.metrics = "anything"  # not a real ScannerMetrics; should have zero effect on future scans' facts
        scanner.metrics = None
        obs_after = scanner.scan("EURUSD", {"M1": bars}, snapshot, bars[-1].timestamp, "M1")

        self.assertEqual(obs_before, obs_after)

    def test_two_independent_scanner_instances_produce_identical_output(self):
        bars = _healthy_bars(120)
        snapshot = _snapshot(bars[-1].timestamp)

        obs_a = Scanner(ScannerConfig()).scan("EURUSD", {"M1": bars}, snapshot, bars[-1].timestamp, "M1")
        obs_b = Scanner(ScannerConfig()).scan("EURUSD", {"M1": bars}, snapshot, bars[-1].timestamp, "M1")

        self.assertEqual(obs_a, obs_b)

    def test_scan_never_mutates_the_bars_it_is_given(self):
        bars = _healthy_bars(120)
        before = list(bars)
        snapshot = _snapshot(bars[-1].timestamp)
        Scanner(ScannerConfig()).scan("EURUSD", {"M1": bars}, snapshot, bars[-1].timestamp, "M1")
        self.assertEqual(bars, before)


class TestBoundaryTypeLevel(unittest.TestCase):
    """ScannerObservation (and every sub-structure) must be structurally
    incapable of representing a score, decision, size, or approval
    (ADR-002 §3, §6, §8, §18)."""

    ALL_TYPES = (
        ScannerObservation,
        TrendReading,
        StructuralSignal,
        VolatilityState,
        SessionState,
        LiquidityEvent,
        SwingPoint,
        EqualLevel,
        StructureTrendState,
    )

    def test_no_field_name_resembles_a_score_decision_size_or_approval(self):
        for cls in self.ALL_TYPES:
            for f in dataclasses.fields(cls):
                lowered = f.name.lower()
                for forbidden in FORBIDDEN_FIELD_NAME_FRAGMENTS:
                    self.assertNotIn(
                        forbidden,
                        lowered,
                        f"{cls.__name__}.{f.name} resembles a forbidden decision/score field",
                    )

    def test_no_field_is_a_bare_numeric_confidence_score(self):
        # structure_confidence must be an enum (qualitative), never numeric.
        hints = get_type_hints(ScannerObservation)
        self.assertIs(hints["structure_confidence"], StructureConfidence)

    def test_observation_is_frozen(self):
        bars = _healthy_bars(120)
        snapshot = _snapshot(bars[-1].timestamp)
        obs = Scanner(ScannerConfig()).scan("EURUSD", {"M1": bars}, snapshot, bars[-1].timestamp, "M1")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            obs.symbol = "GBPUSD"  # type: ignore[misc]


class TestDuplicateComputation(unittest.TestCase):
    """Each structural computation must execute exactly once per scan
    (ADR-002 §13, §15) — verified via call-count spies on the shared
    swing/structure helpers a naive implementation would be tempted to
    call more than once."""

    def test_swing_points_called_exactly_once_per_scan(self):
        bars = _healthy_bars(120)
        snapshot = _snapshot(bars[-1].timestamp)
        scanner = Scanner(ScannerConfig())

        original = swing.swing_points
        call_count = {"n": 0}

        def spy(*args, **kwargs):
            call_count["n"] += 1
            return original(*args, **kwargs)

        import phantom_pipeline.scanner.scanner as scanner_module

        scanner_module.swing_mod.swing_points = spy
        try:
            scanner.scan("EURUSD", {"M1": bars}, snapshot, bars[-1].timestamp, "M1")
        finally:
            scanner_module.swing_mod.swing_points = original

        self.assertEqual(call_count["n"], 1)

    def test_atr_computed_at_most_twice_current_and_baseline_never_a_third_time(self):
        """`volatility.atr()` is legitimately called twice inside
        `compute_volatility` (current-period and baseline-period windows)
        — that is one computation each, not a duplicate. No other module
        may call it again for the same current-period value; they must
        reuse `VolatilityComputation.atr_current` instead."""
        bars = _healthy_bars(120)
        snapshot = _snapshot(bars[-1].timestamp)
        scanner = Scanner(ScannerConfig())

        from phantom_pipeline.scanner import volatility as volatility_mod

        original = volatility_mod.atr
        calls = []

        def spy(bars_arg, period):
            calls.append(period)
            return original(bars_arg, period)

        volatility_mod.atr = spy
        try:
            scanner.scan("EURUSD", {"M1": bars}, snapshot, bars[-1].timestamp, "M1")
        finally:
            volatility_mod.atr = original

        # Exactly one call for the current-period window and one for the
        # baseline-period window — never a repeat of either.
        self.assertEqual(calls.count(scanner.config.atr_period), 1)
        self.assertEqual(calls.count(scanner.config.atr_baseline_period), 1)


class TestFailureModesFailClosed(unittest.TestCase):
    def test_warm_up_yields_unknown_observation(self):
        bars = _healthy_bars(3)
        snapshot = _snapshot(bars[-1].timestamp)
        obs = Scanner(ScannerConfig()).scan("EURUSD", {"M1": bars}, snapshot, bars[-1].timestamp, "M1")

        self.assertEqual(obs.data_quality_flag, DataQualityFlag.WARM_UP)
        self.assertEqual(obs.trend, {})
        self.assertEqual(obs.structure, ())
        self.assertEqual(obs.volatility, VolatilityState(VolatilityLabel.UNKNOWN, None))
        self.assertEqual(obs.swing_hierarchy, ())
        self.assertEqual(obs.phase, MarketPhase.UNKNOWN)
        self.assertEqual(obs.structure_confidence, StructureConfidence.UNKNOWN)
        self.assertIsNone(obs.trend_acceleration)
        self.assertIsNone(obs.trend_exhaustion)

    def test_missing_timeframe_yields_unknown_observation(self):
        bars = _healthy_bars(120)
        snapshot = _snapshot(bars[-1].timestamp)
        obs = Scanner(ScannerConfig()).scan(
            "EURUSD", {"H1": bars}, snapshot, bars[-1].timestamp, "M1"
        )
        self.assertEqual(obs.data_quality_flag, DataQualityFlag.MISSING_TIMEFRAME)
        self.assertEqual(obs.trend, {})

    def test_never_raises_on_malformed_bars(self):
        bars = _healthy_bars(120)
        malformed = NormalizedBar(
            schema_version=SCHEMA_VERSION,
            trace_id="malformed",
            symbol="EURUSD",
            timeframe="M1",
            timestamp=bars[-1].timestamp + timedelta(minutes=1),
            open=1.1,
            high=1.05,  # low > high: impossible OHLC ordering
            low=1.2,
            close=1.1,
            volume=1.0,
            quality=DataQuality.MALFORMED,
            is_repaired=False,
            source="test",
        )
        bars_with_malformed = bars + [malformed]
        snapshot = _snapshot(bars_with_malformed[-1].timestamp)

        try:
            obs = Scanner(ScannerConfig()).scan(
                "EURUSD", {"M1": bars_with_malformed}, snapshot, bars_with_malformed[-1].timestamp, "M1"
            )
        except Exception as exc:  # pragma: no cover - test fails if this triggers
            self.fail(f"scan() must never raise on malformed input, but raised: {exc!r}")

        self.assertEqual(obs.data_quality_flag, DataQualityFlag.MALFORMED_DATA)


class TestAmendment1UnknownHandling(unittest.TestCase):
    def test_insufficient_swing_history_yields_insufficient_data_confidence(self):
        # Enough bars for a NOMINAL top-level flag, but a flat series
        # produces no swing points at all.
        bars = [_bar(i, 1.1000) for i in range(120)]
        snapshot = _snapshot(bars[-1].timestamp)
        obs = Scanner(ScannerConfig()).scan("EURUSD", {"M1": bars}, snapshot, bars[-1].timestamp, "M1")

        self.assertEqual(obs.data_quality_flag, DataQualityFlag.NOMINAL)
        self.assertEqual(obs.structure_confidence, StructureConfidence.INSUFFICIENT_DATA)
        self.assertEqual(obs.phase, MarketPhase.UNKNOWN)

    def test_composite_fields_never_fabricated_when_top_level_flag_is_not_nominal(self):
        bars = _healthy_bars(3)  # WARM_UP
        snapshot = _snapshot(bars[-1].timestamp)
        obs = Scanner(ScannerConfig()).scan("EURUSD", {"M1": bars}, snapshot, bars[-1].timestamp, "M1")

        self.assertEqual(obs.external_structure, StructureTrendState(Direction.UNKNOWN, SwingSequenceType.UNKNOWN))
        self.assertEqual(obs.internal_structure, StructureTrendState(Direction.UNKNOWN, SwingSequenceType.UNKNOWN))
        self.assertEqual(obs.range_structure, RangeStructure.UNKNOWN)
        self.assertEqual(obs.equal_highs, ())
        self.assertEqual(obs.equal_lows, ())


class TestReplayDeterminism(unittest.TestCase):
    """Replay must consume `ReplaySeries` from ADR-013 (task instruction).
    `ReplaySeries.bars` only ever carries the base-timeframe (M1) bars
    ADR-013 Phase 1 actually captures — so this test's `bars_by_timeframe`
    is honestly single-timeframe, matching ADR-013's real capture
    granularity rather than assuming multi-timeframe capture that
    doesn't exist yet."""

    def test_replaying_captured_ticks_reproduces_the_original_observation(self):
        pipeline = DataPipeline(PipelineConfig())
        for minute in range(130):
            pipeline.process_raw_tick(
                "EURUSD",
                T0 + timedelta(minutes=minute),
                1.1000 + (minute % 20) * 0.0002,
                1.1002 + (minute % 20) * 0.0002,
                None,
                1.0,
                "test",
            )
        pipeline.flush("EURUSD")

        original_series = pipeline.get_historical_series("EURUSD", "M1")
        snapshot = _snapshot(original_series.bars[-1].timestamp)
        scanner = Scanner(ScannerConfig())
        original_observation = scanner.scan(
            "EURUSD", {"M1": original_series.bars}, snapshot, original_series.bars[-1].timestamp, "M1"
        )

        replay_series = pipeline.capture_replay("EURUSD")

        fresh_pipeline = DataPipeline(PipelineConfig())
        replay_through(replay_series, fresh_pipeline)
        fresh_pipeline.flush("EURUSD")
        reconstructed_series = fresh_pipeline.get_historical_series("EURUSD", "M1")

        self.assertEqual(reconstructed_series.bars, original_series.bars)

        replayed_observation = scanner.scan(
            "EURUSD", {"M1": reconstructed_series.bars}, snapshot, reconstructed_series.bars[-1].timestamp, "M1"
        )

        self.assertEqual(original_observation, replayed_observation)


if __name__ == "__main__":
    unittest.main()
