"""Session intelligence (ADR-025 §1 "Session Intelligence").

Reuses `titan_protocol.evidence_engine.session.analyze_session()` directly for
session-boundary classification -- this module never re-derives hour
boundaries a second time (ADR-025 §0, "never duplicate Evidence Engine
responsibilities"). What it adds on top is new, non-duplicate logic:
Market-Intelligence-specific *preference* weighting (prefer London/
Overlap/Early NY, downweight Asian unless explicitly enabled) -- a
different concern from Evidence Engine's generic session-quality score.
"""

from __future__ import annotations

from datetime import datetime

from titan_protocol.evidence_engine.models import SessionName
from titan_protocol.evidence_engine.session import analyze_session

from .config import MarketIntelligenceConfig
from .models import SessionIntelligence


def evaluate_session(now: datetime, config: MarketIntelligenceConfig) -> SessionIntelligence:
    state = analyze_session(now, config.evidence_engine_config)
    preferred = state.session in config.preferred_sessions

    score = state.quality_score
    if state.session == SessionName.ASIAN and not config.asian_session_enabled:
        score *= config.asian_session_penalty_multiplier

    if preferred:
        reason = f"{state.session.value} is a preferred session (base quality {state.quality_score:.1f})"
    elif state.session == SessionName.ASIAN and not config.asian_session_enabled:
        reason = f"{state.session.value} is not enabled and is down-weighted (base quality {state.quality_score:.1f})"
    else:
        reason = f"{state.session.value} is not a preferred session (base quality {state.quality_score:.1f})"

    return SessionIntelligence(
        session=state.session,
        session_score=max(0.0, min(100.0, score)),
        preferred=preferred,
        reason=reason,
    )


__all__ = ["evaluate_session"]
