"""Session awareness (ADR-024 §1 "Session Awareness").

Classifies a UTC timestamp into a named trading session and a session
quality score. Never makes a trading decision -- session context is one
of seven independent Evidence Score inputs, nothing more.
"""

from __future__ import annotations

from datetime import datetime

from .config import EvidenceEngineConfig
from .models import SessionName, SessionState

# Relative liquidity/quality by session, 0-100. A single named table,
# not per-call magic numbers -- reflects the well-established FX
# liquidity ordering (London/New York overlap highest, Asian lowest of
# the open sessions).
SESSION_QUALITY_SCORES = {
    SessionName.LONDON_NEW_YORK_OVERLAP: 100.0,
    SessionName.LONDON: 80.0,
    SessionName.EARLY_NEW_YORK: 75.0,
    SessionName.LATE_NEW_YORK: 55.0,
    SessionName.ASIAN: 40.0,
    SessionName.CLOSED: 10.0,
}


def session_for_hour(hour: int, config: EvidenceEngineConfig) -> SessionName:
    if config.london_new_york_overlap_start_hour <= hour < config.london_new_york_overlap_end_hour:
        return SessionName.LONDON_NEW_YORK_OVERLAP
    if config.london_new_york_overlap_end_hour <= hour < config.early_new_york_end_hour:
        return SessionName.EARLY_NEW_YORK
    if config.early_new_york_end_hour <= hour < config.new_york_session_end_hour:
        return SessionName.LATE_NEW_YORK
    if config.london_session_start_hour <= hour < config.london_session_end_hour:
        return SessionName.LONDON
    if config.asian_session_start_hour <= hour < config.asian_session_end_hour:
        return SessionName.ASIAN
    return SessionName.CLOSED


def analyze_session(timestamp: datetime, config: EvidenceEngineConfig) -> SessionState:
    session = session_for_hour(timestamp.hour, config)
    return SessionState(session=session, quality_score=SESSION_QUALITY_SCORES[session])


__all__ = ["SESSION_QUALITY_SCORES", "session_for_hour", "analyze_session"]
