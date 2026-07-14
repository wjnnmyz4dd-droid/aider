"""`NewsFailoverEngine` -- the primary/backup provider state machine
(ADR-033 SS4.2). Trading Economics is always attempted first, every
call, regardless of which provider is currently "active" -- this is
what makes recovery genuinely deterministic (`recovery_health_check_
count` *consecutive* Trading Economics successes, observed on real
scheduled fetches, before switching back) rather than a separate
opportunistic background probe. Never merges, never averages, never
votes: `fetch_events()` returns exactly one provider's events at a
time."""

from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Dict, Optional, Tuple

from .config import NewsIngestionConfig
from .logging_sink import log_fetch_result, log_provider_transition
from .metrics import NewsIngestionMetrics
from .models import (
    FailoverState,
    NewsFeedHealthSnapshot,
    NormalizedNewsEvent,
    ProviderAuthenticationFailed,
    ProviderHealth,
    ProviderName,
    ProviderRateLimited,
    ProviderSchemaError,
    ProviderTimeout,
    ProviderUnavailable,
    TrustState,
)
from .providers.base import NewsProvider


class _MutableProviderHealth:
    def __init__(self) -> None:
        self.last_success_at: Optional[datetime] = None
        self.latency_ms: Optional[float] = None
        self.timeout_count: int = 0
        self.parse_failure_count: int = 0
        self.consecutive_successes: int = 0
        self.last_error: Optional[str] = None


class NewsFailoverEngine:
    def __init__(
        self,
        config: NewsIngestionConfig,
        primary: NewsProvider,
        backup: NewsProvider,
        metrics: Optional[NewsIngestionMetrics] = None,
    ) -> None:
        self._config = config
        self._primary = primary
        self._backup = backup
        self._metrics = metrics
        self._lock = threading.Lock()
        self._active = primary.provider_name
        self._health: Dict[ProviderName, _MutableProviderHealth] = {
            primary.provider_name: _MutableProviderHealth(),
            backup.provider_name: _MutableProviderHealth(),
        }
        self._failover_count = 0
        self._recovery_count = 0
        self._last_failover_at: Optional[datetime] = None
        self._last_recovery_at: Optional[datetime] = None

    def _record_success(self, provider_name: ProviderName, now: datetime, latency_ms: float) -> None:
        health = self._health[provider_name]
        health.last_success_at = now
        health.latency_ms = latency_ms
        health.consecutive_successes += 1
        health.last_error = None
        if self._metrics is not None:
            self._metrics.record_fetch_success(provider_name)

    def _record_failure(self, provider_name: ProviderName, error: Exception) -> None:
        health = self._health[provider_name]
        health.consecutive_successes = 0
        health.last_error = repr(error)
        if isinstance(error, ProviderTimeout):
            health.timeout_count += 1
        if isinstance(error, ProviderSchemaError):
            health.parse_failure_count += 1
        if self._metrics is not None:
            self._metrics.record_fetch_failure(provider_name)

    def _switch_active(self, new_active: ProviderName, now: datetime, is_recovery: bool) -> None:
        previous = self._active
        self._active = new_active
        if is_recovery:
            self._recovery_count += 1
            self._last_recovery_at = now
        else:
            self._failover_count += 1
            self._last_failover_at = now
        log_provider_transition(previous, new_active, now, is_recovery)

    def fetch_events(self, now: datetime) -> Tuple[Tuple[NormalizedNewsEvent, ...], bool]:
        """Returns `(events, trusted)`. `trusted=False` (with an empty
        events tuple) only when both providers fail on this call --
        the caller must then treat the news feed as UNTRUSTED (ADR-033
        SS4.2).

        Trading Economics is always probed every call, even while
        Forex Factory is the one actually *serving* events -- this is
        what makes recovery deterministic rather than opportunistic:
        a single lucky primary success never changes which provider's
        data is returned; only `recovery_health_check_count`
        *consecutive* successes does, and even then only on the call
        where that threshold is actually reached."""
        primary_events, primary_ok = self._try_fetch(self._primary, now)
        log_fetch_result(self._primary.provider_name, primary_ok, len(primary_events) if primary_ok else 0)

        with self._lock:
            active = self._active

        if active == self._primary.provider_name:
            if primary_ok:
                return primary_events, True
            with self._lock:
                self._switch_active(self._backup.provider_name, now, is_recovery=False)
            return self._serve_backup(now)

        # Backup is currently the serving provider -- primary was just
        # probed above purely to accumulate consecutive successes.
        if primary_ok:
            consecutive = self._health[self._primary.provider_name].consecutive_successes
            if consecutive >= self._config.recovery_health_check_count:
                with self._lock:
                    self._switch_active(self._primary.provider_name, now, is_recovery=True)
                return primary_events, True
        return self._serve_backup(now)

    def _serve_backup(self, now: datetime) -> Tuple[Tuple[NormalizedNewsEvent, ...], bool]:
        backup_events, backup_ok = self._try_fetch(self._backup, now)
        log_fetch_result(self._backup.provider_name, backup_ok, len(backup_events) if backup_ok else 0)
        if backup_ok:
            return backup_events, True
        # Both providers failed -- fail closed.
        if self._metrics is not None:
            self._metrics.record_dual_outage()
        return (), False

    def _try_fetch(self, provider: NewsProvider, now: datetime) -> Tuple[Tuple[NormalizedNewsEvent, ...], bool]:
        start = time.monotonic()
        try:
            events = provider.fetch(now)
        except (
            ProviderTimeout,
            ProviderUnavailable,
            ProviderRateLimited,
            ProviderAuthenticationFailed,
            ProviderSchemaError,
        ) as exc:
            self._record_failure(provider.provider_name, exc)
            return (), False
        latency_ms = (time.monotonic() - start) * 1000.0
        self._record_success(provider.provider_name, now, latency_ms)
        return events, True

    def health_snapshot(self, now: datetime) -> NewsFeedHealthSnapshot:
        with self._lock:
            active = self._active
            provider_health = tuple(
                self._build_provider_health(name, now)
                for name in (self._primary.provider_name, self._backup.provider_name)
            )
            failover_state = FailoverState(
                active_provider=active,
                failover_count=self._failover_count,
                recovery_count=self._recovery_count,
                last_failover_at=self._last_failover_at,
                last_recovery_at=self._last_recovery_at,
            )
            trusted = self._health[active].last_success_at is not None and not self._is_stale(active, now)
        return NewsFeedHealthSnapshot(
            generated_at=now, active_provider=active, trusted=trusted,
            provider_health=provider_health, failover_state=failover_state,
        )

    def _is_stale(self, provider_name: ProviderName, now: datetime) -> bool:
        health = self._health[provider_name]
        if health.last_success_at is None:
            return True
        age = (now - health.last_success_at).total_seconds()
        return age > self._config.stale_after_seconds

    def _build_provider_health(self, provider_name: ProviderName, now: datetime) -> ProviderHealth:
        health = self._health[provider_name]
        stale = self._is_stale(provider_name, now)
        trust_state = TrustState.UNTRUSTED if stale else TrustState.TRUSTED
        stale_age = (now - health.last_success_at).total_seconds() if health.last_success_at is not None else None
        return ProviderHealth(
            provider=provider_name, trust_state=trust_state, last_success_at=health.last_success_at,
            latency_ms=health.latency_ms, timeout_count=health.timeout_count,
            parse_failure_count=health.parse_failure_count, consecutive_successes=health.consecutive_successes,
            stale_age_seconds=stale_age, last_error=health.last_error,
        )


__all__ = ["NewsFailoverEngine"]
