"""Shared test-only fixtures for the Market Data Ingestion test suite."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from phantom.market_data_ingestion.config import MarketDataIngestionConfig
from phantom.market_data_ingestion.models import RawBar, TickEvent, Timeframe

T0 = datetime(2026, 7, 11, 12, 0, 0, tzinfo=timezone.utc)


def make_config(**overrides) -> MarketDataIngestionConfig:
    defaults = dict(enabled_pairs=("EURUSD", "GBPUSD"), required_timeframes=(Timeframe.M15,))
    defaults.update(overrides)
    return MarketDataIngestionConfig(**defaults)


def make_bar(
    symbol: str = "EURUSD",
    timeframe: Timeframe = Timeframe.M15,
    bar_open_time: datetime = T0,
    sequence_number: int = 1,
    is_closed: bool = True,
    open_: float = 1.1000,
    high: float = 1.1010,
    low: float = 1.0990,
    close: float = 1.1005,
    volume: float = 100.0,
    bid: float = 1.0999,
    ask: float = 1.1001,
    source_timestamp: datetime = T0,
    broker_timestamp: datetime = T0,
) -> RawBar:
    return RawBar(
        symbol=symbol, timeframe=timeframe, broker_timestamp=broker_timestamp, source_timestamp=source_timestamp,
        bar_open_time=bar_open_time, open=open_, high=high, low=low, close=close, volume=volume,
        is_closed=is_closed, sequence_number=sequence_number, bid=bid, ask=ask,
    )


def make_tick(symbol: str = "EURUSD", timestamp: datetime = T0, bid: float = 1.0999, ask: float = 1.1001) -> TickEvent:
    return TickEvent(symbol=symbol, timestamp=timestamp, bid=bid, ask=ask)


def make_bar_sequence(count: int, timeframe: Timeframe = Timeframe.M15, symbol: str = "EURUSD", start: datetime = T0, interval_seconds: int = 900):
    bars = []
    for i in range(count):
        bar_time = start + timedelta(seconds=interval_seconds * i)
        bars.append(make_bar(symbol=symbol, timeframe=timeframe, bar_open_time=bar_time, sequence_number=i + 1, source_timestamp=bar_time, broker_timestamp=bar_time))
    return bars


__all__ = ["T0", "make_config", "make_bar", "make_tick", "make_bar_sequence"]
