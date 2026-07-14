"""Provider abstraction (ADR-033 SS4.1). A `NewsProvider` owns exactly:
API communication, authentication, response parsing, and schema
conversion -- nothing about event interpretation, blackout windows,
currency filtering, impact classification, session awareness, or trade
gating (all of that stays inside Market Intelligence Engine,
unmodified). `fetch()` must raise one of the five classified errors in
`..models` on failure -- never a bare, unclassified exception."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, Tuple

from ..models import NormalizedNewsEvent, ProviderName


class NewsProvider(Protocol):
    @property
    def provider_name(self) -> ProviderName: ...

    def fetch(self, now: datetime) -> Tuple[NormalizedNewsEvent, ...]:
        """Returns every currently-relevant normalized event. Raises
        `ProviderUnavailable`, `ProviderTimeout`, `ProviderRateLimited`,
        `ProviderAuthenticationFailed`, or `ProviderSchemaError` on any
        failure -- never returns a partial/garbage parse."""
        ...


__all__ = ["NewsProvider"]
