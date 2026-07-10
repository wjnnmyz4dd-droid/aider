"""Shared test-only fixtures for the Evidence Engine test suite."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Sequence, Tuple

from phantom.evidence_engine.config import EvidenceEngineConfig
from phantom.evidence_engine.models import Bar

T0 = datetime(2026, 7, 10, 13, 0, 0, tzinfo=timezone.utc)  # London/NY overlap hour


def make_config(**overrides) -> EvidenceEngineConfig:
    return EvidenceEngineConfig(**overrides)


def make_bars(ohlc: Sequence[Tuple[float, float, float, float]], symbol: str = "EURUSD", start: datetime = T0) -> Tuple[Bar, ...]:
    return tuple(
        Bar(symbol=symbol, timestamp=start + timedelta(minutes=i), open=o, high=h, low=l, close=c, volume=1000.0)
        for i, (o, h, l, c) in enumerate(ohlc)
    )


def make_bar(o: float, h: float, l: float, c: float, symbol: str = "EURUSD", timestamp: datetime = T0) -> Bar:
    return Bar(symbol=symbol, timestamp=timestamp, open=o, high=h, low=l, close=c, volume=1000.0)


#: A generic 17-bar series with a clean swing-high (idx3, idx14), swing-low
#: (idx9) shape and a genuine BOS break at idx13 -- reused across several
#: structure/liquidity/trend tests so the same known-good shape backs
#: multiple assertions instead of being redefined per test.
STRUCTURE_SAMPLE = (
    (1.09, 1.10, 1.08, 1.095), (1.095, 1.11, 1.09, 1.105), (1.105, 1.12, 1.10, 1.115),
    (1.115, 1.15, 1.11, 1.13),
    (1.13, 1.14, 1.12, 1.125), (1.125, 1.13, 1.11, 1.12), (1.12, 1.125, 1.10, 1.108),
    (1.108, 1.11, 1.08, 1.085), (1.085, 1.09, 1.06, 1.07),
    (1.07, 1.075, 1.05, 1.06),
    (1.06, 1.08, 1.055, 1.075), (1.075, 1.10, 1.065, 1.09), (1.09, 1.13, 1.085, 1.12),
    (1.12, 1.16, 1.115, 1.155),
    (1.155, 1.17, 1.15, 1.165),
    (1.165, 1.168, 1.14, 1.145), (1.145, 1.15, 1.12, 1.13),
)
