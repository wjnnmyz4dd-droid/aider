"""Thread-safe counters for News Provider Failover (mirrors every
other engine's `metrics.py` this session -- observability only, never
a decision input)."""

from __future__ import annotations

import threading
from typing import Dict

from .models import ProviderName


class NewsIngestionMetrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._fetch_successes: Dict[ProviderName, int] = {}
        self._fetch_failures: Dict[ProviderName, int] = {}
        self._dual_outage_count = 0

    def record_fetch_success(self, provider: ProviderName) -> None:
        with self._lock:
            self._fetch_successes[provider] = self._fetch_successes.get(provider, 0) + 1

    def record_fetch_failure(self, provider: ProviderName) -> None:
        with self._lock:
            self._fetch_failures[provider] = self._fetch_failures.get(provider, 0) + 1

    def record_dual_outage(self) -> None:
        with self._lock:
            self._dual_outage_count += 1

    def fetch_success_count(self, provider: ProviderName) -> int:
        with self._lock:
            return self._fetch_successes.get(provider, 0)

    def fetch_failure_count(self, provider: ProviderName) -> int:
        with self._lock:
            return self._fetch_failures.get(provider, 0)

    @property
    def dual_outage_count(self) -> int:
        with self._lock:
            return self._dual_outage_count


__all__ = ["NewsIngestionMetrics"]
