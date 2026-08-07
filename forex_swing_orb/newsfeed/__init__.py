"""Session Edge autonomous economic-calendar acquisition layer (Phase 9D-R1).

DEMO-ONLY, DATA-ONLY. Closes audit gap D-1: Session Edge can now autonomously
obtain, normalize, verify, persist, refresh, and health-check the economic-calendar
data the EXISTING compliance news gate consumes.

Architecture (data flows one way; the acquisition layer never decides trades):

    external source -> CalendarProvider (the ONLY networking seam)
        -> freshness/validation -> normalization (impact/currency/ids, D-2)
        -> provenance + integrity digest -> atomic news_file (last-known-good)
        -> existing FileNewsDataProvider -> existing compliance/news.py -> decision

``compliance/news.py`` remains the SOLE trade-blocking news authority. This layer
never approves/rejects trades, computes signals, changes risk/compliance/positions,
writes bridge instructions, calls MT5, or grants AI/LLM trade authority.
"""

from __future__ import annotations

from .acquire import CalendarAcquirer
from .config import CalendarConfig, load_calendar_config
from .contract import (CANONICAL_IMPACTS, SCHEMA_VERSION, AcquisitionError,
                       RawCalendar, Reason)
from .provider import (CalendarProvider, InjectableCalendarProvider,
                       StaticFileCalendarProvider)
from .service import CalendarAcquisitionService, build_from_env, build_provider

__all__ = [
    "CalendarAcquirer", "CalendarConfig", "load_calendar_config",
    "AcquisitionError", "RawCalendar", "Reason", "SCHEMA_VERSION",
    "CANONICAL_IMPACTS", "CalendarProvider", "StaticFileCalendarProvider",
    "InjectableCalendarProvider", "CalendarAcquisitionService", "build_from_env",
    "build_provider",
]
