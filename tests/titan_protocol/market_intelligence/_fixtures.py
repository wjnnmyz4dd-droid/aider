"""Shared test-only fixtures for the Market Intelligence Engine test
suite."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Tuple

from titan_protocol.evidence_engine.config import EvidenceEngineConfig
from titan_protocol.evidence_engine.engine import EvidenceEngine
from titan_protocol.evidence_engine.models import Bar, EvidenceReport
from titan_protocol.market_intelligence.config import MarketIntelligenceConfig
from titan_protocol.market_intelligence.models import MarketSafetyInputs

T0 = datetime(2026, 7, 10, 13, 0, 0, tzinfo=timezone.utc)  # Friday, London/NY overlap


def make_config(**overrides) -> MarketIntelligenceConfig:
    return MarketIntelligenceConfig(**overrides)


def make_bars(pair: str = "EURUSD", start: datetime = T0, count: int = 20) -> Tuple[Bar, ...]:
    bars = []
    price = 1.10
    for i in range(count):
        o = price
        c = price + 0.0005 * ((-1) ** i)
        h = max(o, c) + 0.0005
        l = min(o, c) - 0.0005
        bars.append(Bar(pair, start + timedelta(minutes=i), o, h, l, c, 1000.0))
        price = c
    return tuple(bars)


def make_evidence_report(pair: str = "EURUSD", now: datetime = T0) -> EvidenceReport:
    engine = EvidenceEngine(EvidenceEngineConfig())
    return engine.evaluate(pair, make_bars(pair, now - timedelta(minutes=19)), now=now)


def make_market_safety_inputs(**overrides) -> MarketSafetyInputs:
    return MarketSafetyInputs(**overrides)
