"""Configuration for the Market Intelligence Engine (Phase 2B).

Every threshold and weight used anywhere in this package is named here
-- no magic numbers embedded in the computation modules (CLAUDE.md §3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Tuple

from phantom.evidence_engine.config import EvidenceEngineConfig
from phantom.evidence_engine.models import SessionName

MARKET_INTELLIGENCE_ENGINE_VERSION = "1.0.0-phase2b"


@dataclass(frozen=True)
class MarketIntelligenceConfig:
    # -- News / blackout --
    pre_news_blackout_minutes: float = 30.0
    post_news_blackout_minutes: float = 15.0
    #: Per-pair overrides of the two windows above -- (pair, minutes)
    #: pairs, not a dict, so the frozen config stays genuinely immutable
    #: (a dict field's contents could still be mutated in place). Empty
    #: by default -- opt-in only. See `_pair_blackout_override_minutes()`
    #: in news.py for the lookup helper.
    pair_specific_blackout_overrides_minutes: Tuple[Tuple[str, float], ...] = ()
    high_impact_requires_blackout: bool = True
    central_bank_requires_blackout: bool = True
    #: How long a released event still counts as "active" (still
    #: settling) before it moves to "recent."
    active_event_window_minutes: float = 5.0
    #: How far back a released event still counts as "recent."
    recent_event_window_minutes: float = 60.0
    #: How far ahead an unreleased event still counts as "upcoming."
    upcoming_event_window_hours: float = 24.0

    # -- Session --
    preferred_sessions: Tuple[SessionName, ...] = (
        SessionName.LONDON,
        SessionName.LONDON_NEW_YORK_OVERLAP,
        SessionName.EARLY_NEW_YORK,
    )
    asian_session_enabled: bool = False
    asian_session_penalty_multiplier: float = 0.4  # applied when not enabled
    evidence_engine_config: EvidenceEngineConfig = field(default_factory=EvidenceEngineConfig)

    # -- Liquidity / spread --
    spread_widening_ratio: float = 1.5  # current/average above this = widening
    spread_score_floor_ratio: float = 3.0  # ratio at/above which liquidity_score bottoms at 0

    # -- Market safety --
    weekend_approach_hours: float = 3.0
    holiday_penalty: float = 100.0
    early_close_penalty: float = 40.0
    weekend_approaching_penalty: float = 30.0
    broker_maintenance_penalty: float = 100.0
    trading_halted_penalty: float = 100.0
    market_closed_penalty: float = 100.0

    # -- Pair Safety weights (must sum to 1.0) --
    pair_safety_news_weight: float = 0.35
    pair_safety_liquidity_weight: float = 0.20
    pair_safety_session_weight: float = 0.20
    pair_safety_market_safety_weight: float = 0.25

    # -- Trade Readiness weights (must sum to 1.0) --
    readiness_pair_safety_weight: float = 0.40
    readiness_session_weight: float = 0.15
    readiness_liquidity_weight: float = 0.15
    readiness_news_weight: float = 0.20
    readiness_market_safety_weight: float = 0.10

    # -- Cache --
    news_feed_cache_max_entries: int = 512

    def __post_init__(self) -> None:
        pair_safety_total = (
            self.pair_safety_news_weight
            + self.pair_safety_liquidity_weight
            + self.pair_safety_session_weight
            + self.pair_safety_market_safety_weight
        )
        if abs(pair_safety_total - 1.0) > 1e-9:
            raise ValueError(f"Pair Safety weights must sum to 1.0, got {pair_safety_total}")

        readiness_total = (
            self.readiness_pair_safety_weight
            + self.readiness_session_weight
            + self.readiness_liquidity_weight
            + self.readiness_news_weight
            + self.readiness_market_safety_weight
        )
        if abs(readiness_total - 1.0) > 1e-9:
            raise ValueError(f"Trade Readiness weights must sum to 1.0, got {readiness_total}")


__all__ = ["MARKET_INTELLIGENCE_ENGINE_VERSION", "MarketIntelligenceConfig"]
