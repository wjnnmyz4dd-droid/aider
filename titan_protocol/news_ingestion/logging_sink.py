"""Structured logging for News Provider Failover. A logging failure
never propagates into or alters this package's return value (same
discipline as every other engine's logging_sink this session). Never
logs an API key or any header/query value that could carry one
(CLAUDE.md security model / ADR-033 SS6) -- only provider names,
counts, and status are logged here."""

from __future__ import annotations

import logging
from datetime import datetime

from .models import ProviderName

logger = logging.getLogger("titan_protocol.news_ingestion")


def _safe_log(level: int, message: str, extra: dict) -> None:
    try:
        logger.log(level, message, extra=extra)
    except Exception:
        pass


def log_fetch_result(provider: ProviderName, success: bool, event_count: int) -> None:
    level = logging.INFO if success else logging.WARNING
    _safe_log(level, "news_provider_fetch_result", {"provider": provider.value, "success": success, "event_count": event_count})


def log_provider_transition(previous: ProviderName, new: ProviderName, now: datetime, is_recovery: bool) -> None:
    _safe_log(
        logging.WARNING if not is_recovery else logging.INFO,
        "news_provider_transition",
        {
            "previous_provider": previous.value, "new_provider": new.value,
            "is_recovery": is_recovery, "at": now.isoformat(),
        },
    )


__all__ = ["log_fetch_result", "log_provider_transition"]
