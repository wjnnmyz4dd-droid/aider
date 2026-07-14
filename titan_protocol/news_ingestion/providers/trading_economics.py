"""Trading Economics adapter (ADR-033 SS4.1) -- owns exactly: API
communication, authentication, response parsing, schema conversion.
Owns no event interpretation, blackout, currency-filtering, impact-
classification, session-awareness, or trade-gating logic (all of that
stays inside Market Intelligence Engine, unmodified)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from ..config import NewsIngestionConfig
from ..http import HttpGet, default_http_get
from ..models import (
    NewsEventStatus,
    NormalizedNewsEvent,
    ProviderAuthenticationFailed,
    ProviderName,
    ProviderRateLimited,
    ProviderSchemaError,
    ProviderTimeout,
    ProviderUnavailable,
)
from ..retry import fetch_with_retries

_REQUIRED_FIELDS = ("CalendarId", "Country", "Currency", "Category", "Importance", "Date")


def _parse_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_event(raw: Dict[str, Any], now: datetime) -> NormalizedNewsEvent:
    for field in _REQUIRED_FIELDS:
        if field not in raw:
            raise ProviderSchemaError(f"missing required field {field!r} in Trading Economics event")
    try:
        scheduled_time = datetime.fromisoformat(str(raw["Date"]).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProviderSchemaError(f"unparseable Date field: {raw['Date']!r}") from exc
    if scheduled_time.tzinfo is None:
        scheduled_time = scheduled_time.replace(tzinfo=timezone.utc)

    actual = _parse_float(raw.get("Actual"))
    status = NewsEventStatus.RELEASED if actual is not None else NewsEventStatus.SCHEDULED
    importance = int(raw.get("Importance", 0) or 0)
    impact = "high" if importance >= 3 else "medium" if importance == 2 else "low"

    provider_timestamp = now
    return NormalizedNewsEvent(
        event_id=f"te:{raw['CalendarId']}",
        currency=str(raw["Currency"]).upper(),
        country=str(raw["Country"]),
        event_name=str(raw.get("Event", "")),
        category=str(raw["Category"]),
        impact=impact,
        scheduled_time=scheduled_time,
        actual=actual,
        forecast=_parse_float(raw.get("Forecast")),
        previous=_parse_float(raw.get("Previous")),
        revision=_parse_float(raw.get("Revision")),
        source="tradingeconomics.com",
        provider=ProviderName.TRADING_ECONOMICS,
        provider_timestamp=provider_timestamp,
        ingestion_timestamp=now,
        freshness=(now - provider_timestamp).total_seconds(),
        confidence=1.0,
        status=status,
    )


class TradingEconomicsProvider:
    def __init__(self, config: NewsIngestionConfig, http_get: HttpGet = default_http_get) -> None:
        self._config = config
        self._http_get = http_get

    @property
    def provider_name(self) -> ProviderName:
        return ProviderName.TRADING_ECONOMICS

    def fetch(self, now: datetime) -> Tuple[NormalizedNewsEvent, ...]:
        api_key = os.environ.get(self._config.trading_economics_api_key_env_var)
        if not api_key:
            raise ProviderAuthenticationFailed(
                f"environment variable {self._config.trading_economics_api_key_env_var!r} is not set"
            )
        url = f"{self._config.trading_economics_base_url}/calendar?c={api_key}&f=json"

        def _fetch_once():
            try:
                response = self._http_get(url, self._config.request_timeout_seconds, {"Accept": "application/json"})
            except TimeoutError as exc:
                raise ProviderTimeout(str(exc)) from exc
            except OSError as exc:
                raise ProviderUnavailable(str(exc)) from exc

            if response.status in (401, 403):
                raise ProviderAuthenticationFailed(f"authentication failed: status={response.status}")
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


__all__ = ["TradingEconomicsProvider"]
