"""`NewsIngestionEngine` -- the News Provider Failover layer's public
orchestrator (Phase 3E, ADR-033 Part 2). Wraps `NewsFailoverEngine` +
`adapter.to_market_intelligence_event()` into the one call the
deployment layer needs: `fetch_events(now) -> (events, trusted)`, where
`events` is already the exact, unmodified `titan_protocol.market_intelligence.
models.NewsEvent` type Market Intelligence Engine's `evaluate()`
accepts. Market Intelligence Engine never knows which provider is
active -- it only ever sees this call's two return values."""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Tuple

from titan_protocol.market_intelligence.models import NewsEvent

from .adapter import to_market_intelligence_event
from .config import NewsIngestionConfig
from .failover import NewsFailoverEngine
from .metrics import NewsIngestionMetrics
from .models import NewsFeedHealthSnapshot
from .providers.base import NewsProvider


class NewsIngestionEngine:
    def __init__(
        self,
        config: NewsIngestionConfig,
        primary: NewsProvider,
        backup: NewsProvider,
        metrics: Optional[NewsIngestionMetrics] = None,
    ) -> None:
        self.config = config
        self.metrics = metrics
        self._failover = NewsFailoverEngine(config, primary, backup, metrics)

    def fetch_events(self, now: datetime) -> Tuple[Tuple[NewsEvent, ...], bool]:
        """Returns `(events, trusted)`. `trusted=False` (with an empty
        events tuple) when both providers have failed -- the caller
        must treat this the same as "not ready" and skip Runtime
        entirely for this cycle (ADR-033 SS4.2; Runtime itself is
        frozen and has no `news_feed_trusted` passthrough of its own,
        so this gate must live at the deployment-loop call site, the
        same place `market_data_not_ready`/`no_account_state_reported_
        yet` are already gated -- see deployment_windows/start.py)."""
        normalized_events, trusted = self._failover.fetch_events(now)
        if not trusted:
            return (), False
        return tuple(to_market_intelligence_event(event) for event in normalized_events), True

    def health_snapshot(self, now: datetime) -> NewsFeedHealthSnapshot:
        return self._failover.health_snapshot(now)


__all__ = ["NewsIngestionEngine"]
