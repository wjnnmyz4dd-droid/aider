"""Trading-day identity -- a pure function of `now` and the configured
broker-time reset hour, no state of its own (Final Release Hardening,
requirement 2)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def trading_day_id_for(now: datetime, daily_reset_hour_utc: int) -> str:
    """A stable, sortable identifier for "the trading day `now` falls
    in", where a new trading day begins at `daily_reset_hour_utc` UTC
    each calendar day -- e.g. with `daily_reset_hour_utc=17`, both
    2026-07-14T16:59:59Z and 2026-07-13T17:00:01Z belong to trading day
    "2026-07-13"."""

    now_utc = now.astimezone(timezone.utc) if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    shifted = now_utc - timedelta(hours=daily_reset_hour_utc)
    return shifted.date().isoformat()


__all__ = ["trading_day_id_for"]
