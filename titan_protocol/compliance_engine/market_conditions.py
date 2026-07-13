"""Session restriction and news/peg/market-safety checks (ADR-028
§5.6-5.7). Reads `MarketIntelligenceSnapshot`/`EvidenceSnapshot`
exactly as computed upstream -- never queries a news/data provider
itself (ADR-028 Hard Rule 5)."""

from __future__ import annotations

from typing import Optional

from titan_protocol.evidence_engine.models import EvidenceSnapshot
from titan_protocol.market_intelligence.models import MarketIntelligenceSnapshot

from .models import ComplianceRuleId, ComplianceRuleProfile


def check_session_restriction(evidence: EvidenceSnapshot, profile: ComplianceRuleProfile) -> bool:
    """`True` if the current session is outside the approved set."""

    return evidence.session.session not in profile.approved_sessions


def check_market_safety(market_intelligence: MarketIntelligenceSnapshot) -> Optional[ComplianceRuleId]:
    """Checked in severity order -- the first true condition wins, since
    any one of them alone is sufficient to block."""

    safety = market_intelligence.pair_safety.market_safety
    if safety.trading_halted:
        return ComplianceRuleId.TRADING_HALTED
    if safety.market_closed:
        return ComplianceRuleId.MARKET_CLOSED
    if safety.broker_maintenance:
        return ComplianceRuleId.BROKER_MAINTENANCE
    if safety.is_holiday:
        return ComplianceRuleId.HOLIDAY
    return None


def check_news_blackout(market_intelligence: MarketIntelligenceSnapshot, profile: ComplianceRuleProfile) -> bool:
    if not profile.news_restriction_enabled:
        return False
    return market_intelligence.pair_safety.news.blackout_active


def check_peg_policy(market_intelligence: MarketIntelligenceSnapshot) -> bool:
    return market_intelligence.pair_safety.peg_policy.active


def check_max_spread(market_intelligence: MarketIntelligenceSnapshot, profile: ComplianceRuleProfile) -> bool:
    return market_intelligence.pair_safety.liquidity.current_spread > profile.max_spread


__all__ = [
    "check_session_restriction",
    "check_market_safety",
    "check_news_blackout",
    "check_peg_policy",
    "check_max_spread",
]
