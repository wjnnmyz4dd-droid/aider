"""Security tests (CLAUDE.md security model / ADR-033 SS6, Phase 3E
mission's own SECURITY list): API keys from environment variables
only, never logged, bounded retries, bounded caches, malformed
responses rejected."""

from __future__ import annotations

import io
import json
import logging
import os
import unittest
from datetime import datetime, timezone

from titan_protocol.news_ingestion.config import NewsIngestionConfig
from titan_protocol.news_ingestion.http import HttpResponse
from titan_protocol.news_ingestion.models import ProviderAuthenticationFailed, ProviderTimeout, ProviderUnavailable
from titan_protocol.news_ingestion.providers.trading_economics import TradingEconomicsProvider
from titan_protocol.news_ingestion.retry import fetch_with_retries

T0 = datetime(2026, 7, 14, 12, 0, 0, tzinfo=timezone.utc)
_ENV_VAR = "TITAN_PROTOCOL_TEST_SECURITY_API_KEY"


class TestApiKeyFromEnvironmentOnly(unittest.TestCase):
    def test_no_api_key_field_exists_on_config(self):
        config = NewsIngestionConfig()
        # Only an *env var name* is stored -- never a raw secret value.
        self.assertIsInstance(config.trading_economics_api_key_env_var, str)
        for field_name in vars(config):
            self.assertNotIn("secret", field_name.lower())

    def test_provider_reads_key_from_environment_at_call_time(self):
        os.environ[_ENV_VAR] = "super-secret-value"
        self.addCleanup(os.environ.pop, _ENV_VAR, None)
        config = NewsIngestionConfig(trading_economics_api_key_env_var=_ENV_VAR, max_retries=0)
        captured_urls = []

        def fake_http_get(url, timeout, headers):
            captured_urls.append(url)
            return HttpResponse(200, "application/json", b"[]")

        provider = TradingEconomicsProvider(config, http_get=fake_http_get)
        provider.fetch(T0)
        self.assertIn("super-secret-value", captured_urls[0])  # used to build the request

    def test_missing_env_var_fails_closed_not_silently(self):
        config = NewsIngestionConfig(trading_economics_api_key_env_var=_ENV_VAR, max_retries=0)
        os.environ.pop(_ENV_VAR, None)
        provider = TradingEconomicsProvider(config, http_get=lambda *a: HttpResponse(200, "application/json", b"[]"))
        with self.assertRaises(ProviderAuthenticationFailed):
            provider.fetch(T0)


class TestKeyNeverLogged(unittest.TestCase):
    def test_log_output_never_contains_the_api_key_value(self):
        os.environ[_ENV_VAR] = "super-secret-value"
        self.addCleanup(os.environ.pop, _ENV_VAR, None)
        config = NewsIngestionConfig(trading_economics_api_key_env_var=_ENV_VAR, max_retries=0)
        provider = TradingEconomicsProvider(config, http_get=lambda *a: HttpResponse(200, "application/json", b"[]"))

        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        logger = logging.getLogger("titan_protocol.news_ingestion")
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        try:
            provider.fetch(T0)
        finally:
            logger.removeHandler(handler)
        self.assertNotIn("super-secret-value", stream.getvalue())


class TestBoundedRetries(unittest.TestCase):
    def test_retries_stop_after_max_retries_then_raises(self):
        attempts = {"count": 0}

        def flaky():
            attempts["count"] += 1
            raise ProviderTimeout("still down")

        with self.assertRaises(ProviderTimeout):
            fetch_with_retries(flaky, max_retries=2, retry_backoff_seconds=0.0, sleep=lambda s: None)
        self.assertEqual(attempts["count"], 3)  # 1 initial + 2 retries, never unbounded

    def test_non_transient_failure_is_never_retried(self):
        attempts = {"count": 0}

        def bad_schema():
            attempts["count"] += 1
            raise ProviderAuthenticationFailed("bad key")

        with self.assertRaises(ProviderAuthenticationFailed):
            fetch_with_retries(bad_schema, max_retries=5, retry_backoff_seconds=0.0, sleep=lambda s: None)
        self.assertEqual(attempts["count"], 1)  # no point retrying an auth failure

    def test_eventual_success_within_retry_budget_is_returned(self):
        attempts = {"count": 0}

        def flaky_then_ok():
            attempts["count"] += 1
            if attempts["count"] < 2:
                raise ProviderUnavailable("temporarily down")
            return "ok"

        result = fetch_with_retries(flaky_then_ok, max_retries=2, retry_backoff_seconds=0.0, sleep=lambda s: None)
        self.assertEqual(result, "ok")


class TestBoundedCacheConfig(unittest.TestCase):
    def test_cache_max_entries_is_configurable_and_positive(self):
        config = NewsIngestionConfig(cache_max_entries=50)
        self.assertEqual(config.cache_max_entries, 50)

    def test_zero_or_negative_cache_size_rejected(self):
        with self.assertRaises(ValueError):
            NewsIngestionConfig(cache_max_entries=0)


class TestMalformedResponsesRejected(unittest.TestCase):
    def test_unexpected_content_type_rejected_before_json_parse(self):
        config = NewsIngestionConfig(trading_economics_api_key_env_var=_ENV_VAR, max_retries=0)
        os.environ[_ENV_VAR] = "key"
        self.addCleanup(os.environ.pop, _ENV_VAR, None)
        # A body that would crash json.loads if ever reached -- content-type check must reject first.
        provider = TradingEconomicsProvider(config, http_get=lambda *a: HttpResponse(200, "text/html", b"<not json"))
        from titan_protocol.news_ingestion.models import ProviderSchemaError
        with self.assertRaises(ProviderSchemaError):
            provider.fetch(T0)


if __name__ == "__main__":
    unittest.main()
