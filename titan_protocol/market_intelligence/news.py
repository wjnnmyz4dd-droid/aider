"""Pair-specific news intelligence (ADR-025 §1 "Pair-Specific News
Intelligence" / "News Classification" / "Blackout Rules").

Every enabled pair gets its own independent analysis, filtered to the
two currencies that make up its symbol -- there is no global news
score anywhere in this module (ADR-025 Hard Rule 2).
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Sequence, Tuple

from .config import MarketIntelligenceConfig
from .models import CENTRAL_BANK_CATEGORIES, NewsEvent, NewsImpact, PairNewsIntelligence


def pair_currencies(pair: str) -> Tuple[str, str]:
    """A pair symbol is always base+quote, three letters each (the
    same fixed convention `titan_protocol/bridge` and `phantom_pipeline`
    already assume for every FX symbol)."""
    return pair[:3].upper(), pair[3:6].upper()


def _is_priority_event(event: NewsEvent, config: MarketIntelligenceConfig) -> bool:
    high_impact = event.impact == NewsImpact.HIGH and config.high_impact_requires_blackout
    central_bank = event.category in CENTRAL_BANK_CATEGORIES and config.central_bank_requires_blackout
    return high_impact or central_bank


def _events_for_pair(pair: str, events: Sequence[NewsEvent]) -> Tuple[NewsEvent, ...]:
    base, quote = pair_currencies(pair)
    return tuple(e for e in events if e.currency in (base, quote))


def _pair_blackout_minutes(pair: str, config: MarketIntelligenceConfig) -> Tuple[float, float]:
    for override_pair, minutes in config.pair_specific_blackout_overrides_minutes:
        if override_pair == pair:
            return minutes, config.post_news_blackout_minutes
    return config.pre_news_blackout_minutes, config.post_news_blackout_minutes


def _event_anchor(event: NewsEvent) -> datetime:
    return event.released_at if (event.released and event.released_at is not None) else event.scheduled_at


def _bucket_for_event(event: NewsEvent, now: datetime, config: MarketIntelligenceConfig) -> Optional[str]:
    if not event.released:
        minutes_until = (event.scheduled_at - now).total_seconds() / 60.0
        if 0.0 <= minutes_until <= config.upcoming_event_window_hours * 60.0:
            return "upcoming"
        if -config.active_event_window_minutes <= minutes_until < 0.0:
            return "active"
        return None

    anchor = _event_anchor(event)
    minutes_since = (now - anchor).total_seconds() / 60.0
    if 0.0 <= minutes_since <= config.active_event_window_minutes:
        return "active"
    if config.active_event_window_minutes < minutes_since <= config.recent_event_window_minutes:
        return "recent"
    return None


def bucket_events(
    pair: str, events: Sequence[NewsEvent], now: datetime, config: MarketIntelligenceConfig
) -> Tuple[Tuple[NewsEvent, ...], Tuple[NewsEvent, ...], Tuple[NewsEvent, ...]]:
    relevant = _events_for_pair(pair, events)
    upcoming: List[NewsEvent] = []
    active: List[NewsEvent] = []
    recent: List[NewsEvent] = []
    for event in relevant:
        bucket = _bucket_for_event(event, now, config)
        if bucket == "upcoming":
            upcoming.append(event)
        elif bucket == "active":
            active.append(event)
        elif bucket == "recent":
            recent.append(event)
    return tuple(upcoming), tuple(active), tuple(recent)


def compute_blackout(
    pair: str, events: Sequence[NewsEvent], now: datetime, config: MarketIntelligenceConfig
) -> Tuple[bool, Optional[str]]:
    """Pre-news window applies only before an event's scheduled time;
    post-news window applies from actual release (or scheduled time, if
    no release timestamp is known yet) onward. Only "priority" events
    (high impact, or a central-bank category) ever trigger a blackout."""
    pre_minutes, post_minutes = _pair_blackout_minutes(pair, config)
    for event in _events_for_pair(pair, events):
        if not _is_priority_event(event, config):
            continue
        if not event.released:
            minutes_until = (event.scheduled_at - now).total_seconds() / 60.0
            if 0.0 <= minutes_until <= pre_minutes:
                return True, f"pre-news blackout: {event.category.value} ({event.impact.value}) for {event.currency} at {event.scheduled_at.isoformat()}"
        anchor = _event_anchor(event)
        minutes_since = (now - anchor).total_seconds() / 60.0
        if 0.0 <= minutes_since <= post_minutes:
            return True, f"post-news blackout: {event.category.value} ({event.impact.value}) for {event.currency} released at {anchor.isoformat()}"
    return False, None


def compute_news_score(
    upcoming: Sequence[NewsEvent], active: Sequence[NewsEvent], recent: Sequence[NewsEvent], config: MarketIntelligenceConfig
) -> float:
    """Deterministic point-deduction score, not a hidden model: active
    priority events cost the most, then upcoming, then recent (already
    settling)."""
    score = 100.0
    for event in active:
        score -= 50.0 if _is_priority_event(event, config) else 15.0
    for event in upcoming:
        score -= 30.0 if _is_priority_event(event, config) else 5.0
    for event in recent:
        score -= 20.0 if _is_priority_event(event, config) else 5.0
    return max(0.0, min(100.0, score))


def build_pair_news_intelligence(
    pair: str, events: Sequence[NewsEvent], now: datetime, config: MarketIntelligenceConfig
) -> PairNewsIntelligence:
    upcoming, active, recent = bucket_events(pair, events, now, config)
    blackout_active, blackout_reason = compute_blackout(pair, events, now, config)
    news_score = compute_news_score(upcoming, active, recent, config)
    return PairNewsIntelligence(
        pair=pair,
        upcoming_events=upcoming,
        active_events=active,
        recent_events=recent,
        news_score=news_score,
        blackout_active=blackout_active,
        blackout_reason=blackout_reason,
    )


__all__ = [
    "pair_currencies",
    "bucket_events",
    "compute_blackout",
    "compute_news_score",
    "build_pair_news_intelligence",
]
