"""Reporting (ADR-029 §5): Daily/Weekly/Monthly/Quarterly/Custom period
filtering. One period, one full `ResearchSnapshot` per `evaluate()`
call -- filtering happens before every other computation runs."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional, Sequence, Tuple

from .models import ClosedTrade, ReportPeriod


def period_bounds(
    period: ReportPeriod, now: datetime, custom_start: Optional[datetime] = None, custom_end: Optional[datetime] = None,
) -> Tuple[datetime, datetime]:
    if period is ReportPeriod.CUSTOM:
        if custom_start is None or custom_end is None:
            raise ValueError("CUSTOM period requires both custom_start and custom_end")
        return custom_start, custom_end

    if period is ReportPeriod.DAILY:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start, now

    if period is ReportPeriod.WEEKLY:
        start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        return start, now

    if period is ReportPeriod.MONTHLY:
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return start, now

    if period is ReportPeriod.QUARTERLY:
        quarter_start_month = ((now.month - 1) // 3) * 3 + 1
        start = now.replace(month=quarter_start_month, day=1, hour=0, minute=0, second=0, microsecond=0)
        return start, now

    raise ValueError(f"unhandled report period: {period}")


def filter_trades_by_period(trades: Sequence[ClosedTrade], start: datetime, end: datetime) -> Tuple[ClosedTrade, ...]:
    return tuple(t for t in trades if start <= t.evaluated_at <= end)


__all__ = ["period_bounds", "filter_trades_by_period"]
