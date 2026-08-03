"""Forex Factory adapter (ADR-033 SS4.1) -- owns exactly: calendar feed
communication, response parsing, schema conversion. Owns no event
interpretation, blackout, currency-filtering, impact-classification,
session-awareness, or trade-gating logic (all of that stays inside
Market Intelligence Engine, unmodified). Targets the widely-mirrored
public JSON calendar shape (`title`/`country`/`date`/`impact`/
`forecast`/`previous`/`actual`) -- if the operator's configured
`forex_factory_base_url` serves a different shape, `fetch()` raises
`ProviderSchemaError` rather than guessing."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from ..config import NewsIngestionConfig
from ..http import HttpGet, default_http_get
from ..models import (
    NewsEventStatus,
    NormalizedNewsEvent,
    ProviderName,
    ProviderRateLimited,
    ProviderSchemaError,
    ProviderTimeout,
    ProviderUnavailable,
)
from ..retry import fetch_with_retries

_REQUIRED_FIELDS = ("title", "country", "date", "impact")


def _parse_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(str(value).rstrip("%KMB"))
    except (TypeError, ValueError):
        return None


def _country_to_currency(country: str) -> str:
    # Forex Factory's own calendar already labels events by currency-
    # bearing country/region name; the widely-mirrored feed shape uses
    # the 3-letter currency code directly in this field despite the
    # "country" key name (a pre-existing quirk of the source format,
    # not something this adapter invents).
    return country.strip().upper()


def _parse_event(raw: Dict[str, Any], now: datetime) -> NormalizedNewsEvent:
    for field in _REQUIRED_FIELDS:
        if field not in raw:
            raise ProviderSchemaError(f"missing required field {field!r} in Forex Factory event")
    try:
        scheduled_time = datetime.fromisoformat(str(raw["date"]).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProviderSchemaError(f"unparseable date field: {raw['date']!r}") from exc
    if scheduled_time.tzinfo is None:
        scheduled_time = scheduled_time.replace(tzinfo=timezone.utc)

    actual = _parse_float(raw.get("actual"))
    status = NewsEventStatus.RELEASED if actual is not None else NewsEventStatus.SCHEDULED
    event_id = str(raw.get("id") or f"{raw['title']}:{raw['date']}")

    provider_timestamp = now
    return NormalizedNewsEvent(
        event_id=f"ff:{event_id}",
        currency=_country_to_currency(str(raw["country"])),
        country=str(raw["country"]),
        event_name=str(raw["title"]),
        category=str(raw.get("category", raw["title"])),
        impact=str(raw["impact"]),
        scheduled_time=scheduled_time,
        actual=actual,
        forecast=_parse_float(raw.get("forecast")),
        previous=_parse_float(raw.get("previous")),
        revision=None,  # Forex Factory's public calendar does not carry a revision field
        source="forexfactory.com",
        provider=ProviderName.FOREX_FACTORY,
        provider_timestamp=provider_timestamp,
        ingestion_timestamp=now,
        freshness=(now - provider_timestamp).total_seconds(),
        confidence=0.9,  # backup provider -- slightly lower confidence than the primary
        status=status,
    )


class ForexFactoryProvider:
    def __init__(self, config: NewsIngestionConfig, http_get: HttpGet = default_http_get) -> None:
        self._config = config
        self._http_get = http_get

    @property
    def provider_name(self) -> ProviderName:
        return ProviderName.FOREX_FACTORY

    def fetch(self, now: datetime) -> Tuple[NormalizedNewsEvent, ...]:
        if not self._config.forex_factory_base_url:
            raise ProviderUnavailable("forex_factory_base_url is not configured")
        url = self._config.forex_factory_base_url

        def _fetch_once():
            try:
                response = self._http_get(url, self._config.request_timeout_seconds, {"Accept": "application/json"})
            except TimeoutError as exc:
                raise ProviderTimeout(str(exc)) from exc
            except OSError as exc:
                raise ProviderUnavailable(str(exc)) from exc

            if response.status == 429:
                raise ProviderRateLimited(f"rate limited: status={response.status}")
            if response.status != 200:
                raise ProviderUnavailable(f"unexpected status={response.status}")
            if response.content_type is not None and "json" not in response.content_type.lower():
                raise ProviderSchemaError(f"unexpected content-type: {response.content_type!r}")

            try:
                payload = json.loads(response.body.decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as exc:
                raise ProviderSchemaError(f"invalid JSON body: {exc}") from exc
            if not isinstance(payload, list):
                raise ProviderSchemaError("expected a JSON array of calendar events")
            return tuple(_parse_event(raw, now) for raw in payload if isinstance(raw, dict))

        return fetch_with_retries(_fetch_once, self._config.max_retries, self._config.retry_backoff_seconds)


__all__ = ["ForexFactoryProvider"]
