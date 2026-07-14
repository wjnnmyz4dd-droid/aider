"""Bounded retry helper shared by both providers (CLAUDE.md security
model / ADR-033 SS6: "Use bounded retries"). Only retries the two
genuinely transient failure classes (`ProviderTimeout`,
`ProviderUnavailable`) -- retrying a rate-limited, authentication, or
schema failure would either make the problem worse (hammering a
rate-limited endpoint) or is simply pointless (a malformed response
won't parse differently on retry). Never an unbounded loop: after
`max_retries` attempts, the last exception propagates so the failover
engine can act on it."""

from __future__ import annotations

import time
from typing import Callable, TypeVar

from .models import ProviderTimeout, ProviderUnavailable

T = TypeVar("T")

_RETRYABLE = (ProviderTimeout, ProviderUnavailable)


def fetch_with_retries(
    fetch_once: Callable[[], T],
    max_retries: int,
    retry_backoff_seconds: float,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    attempt = 0
    while True:
        try:
            return fetch_once()
        except _RETRYABLE:
            if attempt >= max_retries:
                raise
            attempt += 1
            sleep(retry_backoff_seconds)


__all__ = ["fetch_with_retries"]
