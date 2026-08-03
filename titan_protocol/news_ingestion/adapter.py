"""The one-way seam to Market Intelligence Engine (ADR-033 SS0/SS4.3):
converts a validated `NormalizedNewsEvent` into `titan_protocol.
market_intelligence.models.NewsEvent` -- the exact, unmodified type MI's
`evaluate()` already accepts. MI's own news/blackout/scoring logic
(`news.py`, `peg_policy.py`) never changes; it keeps consuming only
normalized `NewsEvent`s and a `news_feed_trusted` boolean, exactly as
before this package existed."""

from __future__ import annotations

from titan_protocol.market_intelligence.models import NewsEvent

from .category_mapping import map_category, map_impact
from .models import NewsEventStatus, NormalizedNewsEvent


def to_market_intelligence_event(event: NormalizedNewsEvent) -> NewsEvent:
    released = event.status in (NewsEventStatus.RELEASED, NewsEventStatus.REVISED)
    return NewsEvent(
        event_id=event.event_id,
        currency=event.currency,
        category=map_category(event.category),
        impact=map_impact(event.impact),
        scheduled_at=event.scheduled_time,
        released=released,
        released_at=event.provider_timestamp if released else None,
    )


__all__ = ["to_market_intelligence_event"]
