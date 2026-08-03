"""Tests for the two concrete provider adapters -- API communication,
authentication, response parsing, and schema conversion only (ADR-033
SS4.1 ownership split). Every test injects a fake `http_get`; none
performs a real network call."""

from __future__ import annotations

import json
import os
import unittest
from datetime import datetime, timezone

from titan_protocol.news_ingestion.config import NewsIngestionConfig
from titan_protocol.news_ingestion.http import HttpResponse
from titan_protocol.news_ingestion.models import (
    ProviderAuthenticationFailed,
    ProviderName,
    ProviderRateLimited,
    ProviderSchemaError,
    ProviderUnavailable,
)
from titan_protocol.news_ingestion.providers.forex_factory import ForexFactoryProvider
from titan_protocol.news_ingestion.providers.trading_economics import TradingEconomicsProvider

T0 = datetime(2026, 7, 14, 12, 0, 0, tzinfo=timezone.utc)
_ENV_VAR = "TITAN_PROTOCOL_TEST_TE_API_KEY"


class TestTradingEconomicsProvider(unittest.TestCase):
    def setUp(self):
        os.environ[_ENV_VAR] = "test-key-value"
        self.addCleanup(os.environ.pop, _ENV_VAR, None)
        self.config = NewsIngestionConfig(trading_economics_api_key_env_var=_ENV_VAR, max_retries=0)

    def test_success_parses_events(self):
        payload = [{
            "CalendarId": "123", "Country": "United States", "Currency": "USD",
            "Category": "CPI", "Importance": 3, "Date": "2026-07-14T12:30:00",
            "Event": "CPI y/y", "Actual": "3.1", "Forecast": "3.0", "Previous": "2.9",
        }]
        def fake_http_get(url, timeout, headers):
            self.assertIn("test-key-value", url)  # key is used, not logged
            return HttpResponse(status=200, content_type="application/json", body=json.dumps(payload).encode())

        provider = TradingEconomicsProvider(self.config, http_get=fake_http_get)
        events = provider.fetch(T0)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].currency, "USD")
        self.assertEqual(events[0].impact, "high")
        self.assertEqual(events[0].actual, 3.1)
        self.assertEqual(events[0].provider, ProviderName.TRADING_ECONOMICS)

    def test_missing_api_key_raises_authentication_failed(self):
        del os.environ[_ENV_VAR]
        provider = TradingEconomicsProvider(self.config, http_get=lambda *a: HttpResponse(200, "application/json", b"[]"))
        with self.assertRaises(ProviderAuthenticationFailed):
            provider.fetch(T0)

    def test_401_raises_authentication_failed(self):
        provider = TradingEconomicsProvider(self.config, http_get=lambda *a: HttpResponse(401, "application/json", b"{}"))
        with self.assertRaises(ProviderAuthenticationFailed):
            provider.fetch(T0)

    def test_429_raises_rate_limited(self):
        provider = TradingEconomicsProvider(self.config, http_get=lambda *a: HttpResponse(429, "application/json", b"{}"))
        with self.assertRaises(ProviderRateLimited):
            provider.fetch(T0)

    def test_non_200_raises_unavailable(self):
        provider = TradingEconomicsProvider(self.config, http_get=lambda *a: HttpResponse(503, "application/json", b"{}"))
        with self.assertRaises(ProviderUnavailable):
            provider.fetch(T0)

    def test_wrong_content_type_raises_schema_error(self):
        provider = TradingEconomicsProvider(self.config, http_get=lambda *a: HttpResponse(200, "text/html", b"<html/>"))
        with self.assertRaises(ProviderSchemaError):
            provider.fetch(T0)

    def test_malformed_json_raises_schema_error(self):
        provider = TradingEconomicsProvider(self.config, http_get=lambda *a: HttpResponse(200, "application/json", b"not json{"))
        with self.assertRaises(ProviderSchemaError):
            provider.fetch(T0)

    def test_missing_required_field_raises_schema_error(self):
        payload = [{"Country": "United States"}]  # missing CalendarId, Currency, etc.
        provider = TradingEconomicsProvider(self.config, http_get=lambda *a: HttpResponse(200, "application/json", json.dumps(payload).encode()))
        with self.assertRaises(ProviderSchemaError):
            provider.fetch(T0)

    def test_unparseable_date_raises_schema_error(self):
        payload = [{
            "CalendarId": "1", "Country": "US", "Currency": "USD", "Category": "CPI",
            "Importance": 1, "Date": "not-a-date",
        }]
        provider = TradingEconomicsProvider(self.config, http_get=lambda *a: HttpResponse(200, "application/json", json.dumps(payload).encode()))
        with self.assertRaises(ProviderSchemaError):
            provider.fetch(T0)


class TestForexFactoryProvider(unittest.TestCase):
    def setUp(self):
        self.config = NewsIngestionConfig(forex_factory_base_url="https://example.invalid/calendar.json", max_retries=0)

    def test_success_parses_events(self):
        payload = [{
            "id": "42", "title": "Retail Sales m/m", "country": "GBP",
            "date": "2026-07-14T08:30:00", "impact": "medium", "forecast": "0.3", "previous": "0.1",
        }]
        provider = ForexFactoryProvider(self.config, http_get=lambda *a: HttpResponse(200, "application/json", json.dumps(payload).encode()))
        events = provider.fetch(T0)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].currency, "GBP")
        self.assertEqual(events[0].impact, "medium")
        self.assertEqual(events[0].provider, ProviderName.FOREX_FACTORY)

    def test_no_base_url_raises_unavailable(self):
        config = NewsIngestionConfig(forex_factory_base_url="", max_retries=0)
        provider = ForexFactoryProvider(config, http_get=lambda *a: HttpResponse(200, "application/json", b"[]"))
        with self.assertRaises(ProviderUnavailable):
            provider.fetch(T0)

    def test_missing_required_field_raises_schema_error(self):
        payload = [{"title": "Something"}]  # missing country/date/impact
        provider = ForexFactoryProvider(self.config, http_get=lambda *a: HttpResponse(200, "application/json", json.dumps(payload).encode()))
        with self.assertRaises(ProviderSchemaError):
            provider.fetch(T0)

    def test_429_raises_rate_limited(self):
        provider = ForexFactoryProvider(self.config, http_get=lambda *a: HttpResponse(429, "application/json", b"{}"))
        with self.assertRaises(ProviderRateLimited):
            provider.fetch(T0)


if __name__ == "__main__":
    unittest.main()
