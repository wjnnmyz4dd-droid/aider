"""MarketDataAdapter translation tests — a fake `MetaTrader5` module
double stands in for the real, MT5-terminal-only package, mirroring
`mt5_bridge.mt5_adapter`'s own "no live external dependency in unit
tests" discipline. Every test exercises real `DataPipeline` instances,
proving the adapter genuinely drives the existing public ingestion path
rather than reimplementing it."""

from __future__ import annotations

import unittest
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from phantom_pipeline.data_pipeline.config import DEFAULT_CONFIG
from phantom_pipeline.data_pipeline.market_data_adapter import MarketDataAdapter
from phantom_pipeline.data_pipeline.models import DataQuality
from phantom_pipeline.data_pipeline.pipeline import DataPipeline

T0 = datetime(2026, 7, 6, 10, 0, 0, tzinfo=timezone.utc)


@dataclass
class _FakeTick:
    time: float
    bid: float
    ask: float
    last: float = 0.0
    volume: float = 0.0


@dataclass
class _FakeRate:
    time: float
    open: float
    high: float
    low: float
    close: float
    tick_volume: float


class _FakeMT5:
    TIMEFRAME_M1 = "TIMEFRAME_M1"
    TIMEFRAME_M5 = "TIMEFRAME_M5"

    def __init__(self) -> None:
        self.initialize_result = True
        self.shutdown_called = False
        self.ticks: Dict[str, Optional[_FakeTick]] = {}
        self.rates: Dict[Tuple[str, str], List[_FakeRate]] = {}

    def initialize(self) -> bool:
        return self.initialize_result

    def shutdown(self) -> None:
        self.shutdown_called = True

    def symbol_info_tick(self, symbol: str):
        return self.ticks.get(symbol)

    def copy_rates_range(self, symbol: str, timeframe, start, end):
        return self.rates.get((symbol, timeframe), [])


def _pipeline() -> DataPipeline:
    return DataPipeline(config=DEFAULT_CONFIG, base_timeframe="M1")


class TestMarketDataAdapterConnection(unittest.TestCase):
    def test_connect_reflects_client_result(self):
        fake = _FakeMT5()
        fake.initialize_result = False
        adapter = MarketDataAdapter(mt5_module=fake)
        self.assertFalse(adapter.connect())

    def test_disconnect_calls_shutdown(self):
        fake = _FakeMT5()
        adapter = MarketDataAdapter(mt5_module=fake)
        adapter.disconnect()
        self.assertTrue(fake.shutdown_called)

    def test_lazy_import_raises_clear_error_without_injected_module(self):
        adapter = MarketDataAdapter()
        with self.assertRaises(RuntimeError):
            adapter.connect()


class TestMarketDataAdapterLiveTicks(unittest.TestCase):
    def test_poll_ticks_returns_empty_when_no_tick_available(self):
        fake = _FakeMT5()
        adapter = MarketDataAdapter(mt5_module=fake)
        pipeline = _pipeline()
        self.assertEqual(adapter.poll_ticks(pipeline, "EURUSD"), [])

    def test_poll_ticks_feeds_pipeline_and_updates_snapshot(self):
        fake = _FakeMT5()
        fake.ticks["EURUSD"] = _FakeTick(time=T0.timestamp(), bid=1.0995, ask=1.1005)
        adapter = MarketDataAdapter(mt5_module=fake)
        pipeline = _pipeline()
        adapter.poll_ticks(pipeline, "EURUSD")
        snapshot = pipeline.get_snapshot("EURUSD")
        self.assertIsNotNone(snapshot)
        self.assertAlmostEqual(snapshot.price, 1.1000)
        self.assertEqual(pipeline.ticks_processed, 1)

    def test_poll_ticks_is_captured_into_replay(self):
        fake = _FakeMT5()
        fake.ticks["EURUSD"] = _FakeTick(time=T0.timestamp(), bid=1.0995, ask=1.1005)
        adapter = MarketDataAdapter(mt5_module=fake)
        pipeline = _pipeline()
        adapter.poll_ticks(pipeline, "EURUSD")
        replay_series = pipeline.capture_replay("EURUSD")
        self.assertEqual(len(replay_series.ticks), 1)

    def test_poll_ticks_uses_mt5_symbol_override(self):
        fake = _FakeMT5()
        fake.ticks["EURUSD.raw"] = _FakeTick(time=T0.timestamp(), bid=1.0995, ask=1.1005)
        adapter = MarketDataAdapter(mt5_module=fake)
        pipeline = _pipeline()
        adapter.poll_ticks(pipeline, "EURUSD", mt5_symbol="EURUSD.raw")
        self.assertEqual(pipeline.ticks_processed, 1)


class TestMarketDataAdapterHistorical(unittest.TestCase):
    def test_load_historical_populates_cache_and_never_touches_replay(self):
        fake = _FakeMT5()
        fake.rates[("EURUSD", "TIMEFRAME_M1")] = [
            _FakeRate(time=T0.timestamp(), open=1.10, high=1.11, low=1.09, close=1.105, tick_volume=100.0),
            _FakeRate(time=T0.timestamp() + 60, open=1.105, high=1.115, low=1.095, close=1.11, tick_volume=90.0),
        ]
        adapter = MarketDataAdapter(mt5_module=fake)
        pipeline = _pipeline()
        series = adapter.load_historical(pipeline, "EURUSD", "M1", T0, T0)
        self.assertEqual(len(series.bars), 2)
        self.assertEqual(series.bars[0].quality, DataQuality.NOMINAL)
        self.assertFalse(series.bars[0].is_repaired)
        replay_series = pipeline.capture_replay("EURUSD")
        self.assertEqual(len(replay_series.bars), 0)

    def test_load_historical_unsupported_timeframe_raises(self):
        fake = _FakeMT5()
        adapter = MarketDataAdapter(mt5_module=fake)
        pipeline = _pipeline()
        with self.assertRaises(ValueError):
            adapter.load_historical(pipeline, "EURUSD", "M2", T0, T0)

    def test_load_historical_empty_rates_produces_empty_series(self):
        fake = _FakeMT5()
        adapter = MarketDataAdapter(mt5_module=fake)
        pipeline = _pipeline()
        series = adapter.load_historical(pipeline, "EURUSD", "M1", T0, T0)
        self.assertEqual(series.bars, ())

    def test_warm_start_loads_multiple_symbol_timeframe_pairs(self):
        fake = _FakeMT5()
        fake.rates[("EURUSD", "TIMEFRAME_M1")] = [
            _FakeRate(time=T0.timestamp(), open=1.10, high=1.11, low=1.09, close=1.105, tick_volume=100.0),
        ]
        fake.rates[("GBPUSD", "TIMEFRAME_M1")] = [
            _FakeRate(time=T0.timestamp(), open=1.30, high=1.31, low=1.29, close=1.305, tick_volume=80.0),
        ]
        adapter = MarketDataAdapter(mt5_module=fake)
        pipeline = _pipeline()
        adapter.warm_start(pipeline, [("EURUSD", "M1"), ("GBPUSD", "M1")], T0, T0)
        self.assertEqual(len(pipeline.get_historical_series("EURUSD", "M1").bars), 1)
        self.assertEqual(len(pipeline.get_historical_series("GBPUSD", "M1").bars), 1)

    def test_warm_start_respects_mt5_symbol_override(self):
        fake = _FakeMT5()
        fake.rates[("EURUSD.raw", "TIMEFRAME_M1")] = [
            _FakeRate(time=T0.timestamp(), open=1.10, high=1.11, low=1.09, close=1.105, tick_volume=100.0),
        ]
        adapter = MarketDataAdapter(mt5_module=fake)
        pipeline = _pipeline()
        adapter.warm_start(pipeline, [("EURUSD", "M1")], T0, T0, mt5_symbols={"EURUSD": "EURUSD.raw"})
        self.assertEqual(len(pipeline.get_historical_series("EURUSD", "M1").bars), 1)


if __name__ == "__main__":
    unittest.main()
