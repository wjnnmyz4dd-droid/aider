"""One test per ADR-002 §9 failure mode."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from phantom_pipeline.data_pipeline.models import DataQuality, MarketSnapshot, NormalizedBar, SCHEMA_VERSION
from phantom_pipeline.scanner.config import ScannerConfig
from phantom_pipeline.scanner.models import DataQualityFlag
from phantom_pipeline.scanner.quality import assess_quality

T0 = datetime(2026, 7, 4, 12, 0, 0, tzinfo=timezone.utc)


def _bar(i: int, close: float = 1.1000, malformed: bool = False) -> NormalizedBar:
    high = close + 0.0005
    low = close - 0.0005
    if malformed:
        low = close + 0.0010  # low > high: impossible OHLC ordering
    return NormalizedBar(
        schema_version=SCHEMA_VERSION,
        trace_id=f"b{i}",
        symbol="EURUSD",
        timeframe="M1",
        timestamp=T0 + timedelta(minutes=i),
        open=close,
        high=high,
        low=low,
        close=close,
        volume=1.0,
        quality=DataQuality.NOMINAL,
        is_repaired=False,
        source="test",
    )


def _snapshot(spread=0.0002, timestamp=None, market_status="OPEN"):
    return MarketSnapshot(
        schema_version=SCHEMA_VERSION,
        trace_id="s1",
        symbol="EURUSD",
        timestamp=timestamp or T0,
        price=1.1000,
        spread=spread,
        market_status=market_status,
    )


class TestQualityFailureModes(unittest.TestCase):
    def setUp(self):
        self.config = ScannerConfig()

    def _nominal_bars(self):
        return [_bar(i) for i in range(self.config.min_bars_for_structure + 5)]

    def test_warm_up_insufficient_bar_history(self):
        bars = [_bar(i) for i in range(3)]
        flag = assess_quality(
            "EURUSD", {"M1": bars}, _snapshot(), T0, "M1", self.config
        )
        self.assertEqual(flag, DataQualityFlag.WARM_UP)

    def test_missing_timeframe_entirely_absent(self):
        flag = assess_quality(
            "EURUSD", {"H1": self._nominal_bars()}, _snapshot(), T0, "M1", self.config
        )
        self.assertEqual(flag, DataQualityFlag.MISSING_TIMEFRAME)

    def test_stale_spread_zero(self):
        flag = assess_quality(
            "EURUSD", {"M1": self._nominal_bars()}, _snapshot(spread=0.0), T0, "M1", self.config
        )
        self.assertEqual(flag, DataQualityFlag.STALE_SPREAD)

    def test_stale_spread_missing_snapshot(self):
        flag = assess_quality(
            "EURUSD", {"M1": self._nominal_bars()}, None, T0, "M1", self.config
        )
        self.assertEqual(flag, DataQualityFlag.STALE_SPREAD)

    def test_stale_spread_by_age(self):
        old_timestamp = T0 - timedelta(seconds=self.config.spread_stale_after_seconds + 1)
        flag = assess_quality(
            "EURUSD",
            {"M1": self._nominal_bars()},
            _snapshot(timestamp=old_timestamp),
            T0,
            "M1",
            self.config,
        )
        self.assertEqual(flag, DataQualityFlag.STALE_SPREAD)

    def test_malformed_candles_impossible_ohlc(self):
        bars = [_bar(i) for i in range(self.config.min_bars_for_structure + 4)] + [
            _bar(self.config.min_bars_for_structure + 4, malformed=True)
        ]
        flag = assess_quality("EURUSD", {"M1": bars}, _snapshot(), T0, "M1", self.config)
        self.assertEqual(flag, DataQualityFlag.MALFORMED_DATA)

    def test_malformed_candles_non_monotonic_timestamps(self):
        bars = self._nominal_bars()
        bars[-1] = NormalizedBar(
            schema_version=SCHEMA_VERSION,
            trace_id="out-of-order",
            symbol="EURUSD",
            timeframe="M1",
            timestamp=bars[-2].timestamp,  # duplicate/non-increasing timestamp
            open=1.1,
            high=1.1005,
            low=1.0995,
            close=1.1002,
            volume=1.0,
            quality=DataQuality.NOMINAL,
            is_repaired=False,
            source="test",
        )
        flag = assess_quality("EURUSD", {"M1": bars}, _snapshot(), T0, "M1", self.config)
        self.assertEqual(flag, DataQualityFlag.MALFORMED_DATA)

    def test_session_ambiguous_naive_timestamp(self):
        naive = T0.replace(tzinfo=None)
        flag = assess_quality(
            "EURUSD",
            {"M1": self._nominal_bars()},
            _snapshot(timestamp=naive),
            naive,
            "M1",
            self.config,
        )
        self.assertEqual(flag, DataQualityFlag.SESSION_AMBIGUOUS)

    def test_symbol_not_recognized(self):
        config = ScannerConfig(recognized_symbols={"GBPUSD": True})
        flag = assess_quality(
            "EURUSD", {"M1": self._nominal_bars()}, _snapshot(), T0, "M1", config
        )
        self.assertEqual(flag, DataQualityFlag.SYMBOL_NOT_RECOGNIZED)

    def test_market_not_tradeable(self):
        flag = assess_quality(
            "EURUSD",
            {"M1": self._nominal_bars()},
            _snapshot(market_status="HALTED"),
            T0,
            "M1",
            self.config,
        )
        self.assertEqual(flag, DataQualityFlag.MARKET_NOT_TRADEABLE)

    def test_nominal_when_everything_is_healthy(self):
        flag = assess_quality(
            "EURUSD", {"M1": self._nominal_bars()}, _snapshot(), T0, "M1", self.config
        )
        self.assertEqual(flag, DataQualityFlag.NOMINAL)


if __name__ == "__main__":
    unittest.main()
