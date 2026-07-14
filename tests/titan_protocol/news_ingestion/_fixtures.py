"""Shared test-only fixtures for the News Provider Failover test suite."""

from __future__ import annotations

from datetime import datetime, timezone

from titan_protocol.news_ingestion.config import NewsIngestionConfig
from titan_protocol.news_ingestion.models import NewsEventStatus, NormalizedNewsEvent, ProviderName

T0 = datetime(2026, 7, 14, 12, 0, 0, tzinfo=timezone.utc)


def make_config(**overrides) -> NewsIngestionConfig:
    defaults = dict(recovery_health_check_count=3)
    defaults.update(overrides)
    return NewsIngestionConfig(**defaults)


def make_normalized_event(
    event_id: str = "e1",
    currency: str = "USD",
    category: str = "cpi",
    impact: str = "high",
    scheduled_time: datetime = T0,
    actual=None,
    provider: ProviderName = ProviderName.TRADING_ECONOMICS,
    status: NewsEventStatus = NewsEventStatus.SCHEDULED,
    country: str = "United States",
) -> NormalizedNewsEvent:
    return NormalizedNewsEvent(
        event_id=event_id, currency=currency, country=country, event_name="Test Event",
        category=category, impact=impact, scheduled_time=scheduled_time,
        actual=actual, forecast=1.0, previous=0.9, revision=None,
        source="test-source", provider=provider, provider_timestamp=T0,
        ingestion_timestamp=T0, freshness=0.0, confidence=1.0, status=status,
    )


class FakeProvider:
    """A scripted provider: each `fetch()` call pops and executes/raises
    the next scripted action. Used to drive deterministic failover/
    recovery scenarios without any real network call."""

    def __init__(self, name: ProviderName, script):
        self._name = name
        self._script = list(script)
        self.call_count = 0

    @property
    def provider_name(self) -> ProviderName:
        return self._name

    def fetch(self, now: datetime):
        self.call_count += 1
        if not self._script:
            raise AssertionError(f"{self._name} fetch() called more times than scripted")
        action = self._script.pop(0)
        if isinstance(action, BaseException):
            raise action
        return action
