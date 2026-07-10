"""Trading Profile factories (ADR-031 SS4): configuration only -- every
value here references an existing engine's own config type
(`RiskEngineConfig`, `MarketIntelligenceConfig`, a named Compliance
`ComplianceRuleProfile`) or a plain list of pairs/sessions/strategies.
No risk/compliance/news logic is reimplemented here."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Tuple

from phantom.evidence_engine.models import SessionName
from phantom.market_intelligence.config import MarketIntelligenceConfig
from phantom.risk_engine.config import RiskEngineConfig
from phantom.strategy_engine.config import DEFAULT_APPROVED_PAIRS_BY_STRATEGY
from phantom.strategy_engine.models import StrategyId

from .models import TradingProfile, TradingWindow

# An illustrative, operator-tunable major-pair universe (ADR-031's own
# performance target names "28 pairs") -- not every pair here is
# eligible for every strategy (or any), so it is offered as a starting
# point for a Custom profile, never as the default `allowed_pairs`
# (which must always pass SS11's eligibility-intersection check).
MAJOR_FOREX_UNIVERSE: Tuple[str, ...] = (
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD",
    "EURGBP", "EURJPY", "EURCHF", "EURCAD", "EURAUD", "EURNZD",
    "GBPJPY", "GBPCHF", "GBPCAD", "GBPAUD", "GBPNZD",
    "AUDJPY", "AUDCHF", "AUDCAD", "AUDNZD",
    "NZDJPY", "NZDCHF", "NZDCAD",
    "CADJPY", "CADCHF", "CHFJPY",
)

_ALL_STRATEGIES: Tuple[StrategyId, ...] = tuple(StrategyId)

# The default `allowed_pairs` for every named profile below: the union
# of every strategy's own approved-pair universe (StrategyEngineConfig's
# single source of truth, ADR-026 SS3) -- never an independently-invented
# list that could silently drift from what strategies actually support
# (the exact gap SS11's eligibility-intersection validation exists to
# catch).
_TRADEABLE_PAIR_UNIVERSE: Tuple[str, ...] = tuple(sorted({
    pair for _strategy_id, pairs in DEFAULT_APPROVED_PAIRS_BY_STRATEGY for pair in pairs
}))

_LONDON_SESSIONS: Tuple[SessionName, ...] = (SessionName.LONDON, SessionName.LONDON_NEW_YORK_OVERLAP)
_NEW_YORK_SESSIONS: Tuple[SessionName, ...] = (
    SessionName.LONDON_NEW_YORK_OVERLAP, SessionName.EARLY_NEW_YORK, SessionName.LATE_NEW_YORK,
)

_CONSERVATIVE_RISK = RiskEngineConfig(
    portfolio_heat_limit_r=3.0, max_concurrent_risk_r=3.0, max_correlated_risk_r=1.5,
    daily_risk_limit_r=1.5, weekly_risk_limit_r=3.0, monthly_risk_limit_r=5.0,
    max_open_positions=5, max_positions_per_pair=1,
)
_AGGRESSIVE_RISK = RiskEngineConfig()  # engine defaults


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _base_profile(
    profile_id: str,
    description: str,
    trading_window: TradingWindow,
    session_rules: Tuple[SessionName, ...],
    risk_profile: RiskEngineConfig,
    allowed_pairs: Tuple[str, ...] = _TRADEABLE_PAIR_UNIVERSE,
    allowed_strategies: Tuple[StrategyId, ...] = _ALL_STRATEGIES,
    news_policy: Optional[MarketIntelligenceConfig] = None,
    compliance_rule_profile_name: str = "example_generic_profile",
    author: str = "operator",
    version: int = 1,
) -> TradingProfile:
    now = _now()
    return TradingProfile(
        profile_id=profile_id, version=version, created_at=now, modified_at=now,
        author=author, description=description,
        trading_window=trading_window, allowed_pairs=allowed_pairs, allowed_strategies=allowed_strategies,
        session_rules=session_rules, news_policy=news_policy or MarketIntelligenceConfig(),
        risk_profile=risk_profile, compliance_rule_profile_name=compliance_rule_profile_name,
    )


def make_london_conservative_profile() -> TradingProfile:
    return _base_profile(
        profile_id="london_conservative",
        description="London session only, reduced risk limits.",
        trading_window=TradingWindow(start_hour_utc=7, end_hour_utc=16),
        session_rules=_LONDON_SESSIONS,
        risk_profile=_CONSERVATIVE_RISK,
    )


def make_london_aggressive_profile() -> TradingProfile:
    return _base_profile(
        profile_id="london_aggressive",
        description="London session only, engine-default risk limits.",
        trading_window=TradingWindow(start_hour_utc=7, end_hour_utc=16),
        session_rules=_LONDON_SESSIONS,
        risk_profile=_AGGRESSIVE_RISK,
    )


def make_new_york_conservative_profile() -> TradingProfile:
    return _base_profile(
        profile_id="new_york_conservative",
        description="New York session only, reduced risk limits.",
        trading_window=TradingWindow(start_hour_utc=12, end_hour_utc=21),
        session_rules=_NEW_YORK_SESSIONS,
        risk_profile=_CONSERVATIVE_RISK,
    )


def make_new_york_aggressive_profile() -> TradingProfile:
    return _base_profile(
        profile_id="new_york_aggressive",
        description="New York session only, engine-default risk limits.",
        trading_window=TradingWindow(start_hour_utc=12, end_hour_utc=21),
        session_rules=_NEW_YORK_SESSIONS,
        risk_profile=_AGGRESSIVE_RISK,
    )


def make_london_and_new_york_profile() -> TradingProfile:
    return _base_profile(
        profile_id="london_and_new_york",
        description="London through New York close, engine-default risk limits.",
        trading_window=TradingWindow(start_hour_utc=7, end_hour_utc=21),
        session_rules=_LONDON_SESSIONS + _NEW_YORK_SESSIONS,
        risk_profile=_AGGRESSIVE_RISK,
    )


def make_custom_profile(
    profile_id: str,
    description: str,
    trading_window: TradingWindow,
    session_rules: Tuple[SessionName, ...],
    risk_profile: RiskEngineConfig,
    allowed_pairs: Tuple[str, ...] = _TRADEABLE_PAIR_UNIVERSE,
    allowed_strategies: Tuple[StrategyId, ...] = _ALL_STRATEGIES,
    news_policy: Optional[MarketIntelligenceConfig] = None,
    compliance_rule_profile_name: str = "example_generic_profile",
    author: str = "operator",
    version: int = 1,
) -> TradingProfile:
    return _base_profile(
        profile_id=profile_id, description=description, trading_window=trading_window,
        session_rules=session_rules, risk_profile=risk_profile, allowed_pairs=allowed_pairs,
        allowed_strategies=allowed_strategies, news_policy=news_policy,
        compliance_rule_profile_name=compliance_rule_profile_name, author=author, version=version,
    )


__all__ = [
    "MAJOR_FOREX_UNIVERSE",
    "make_london_conservative_profile",
    "make_london_aggressive_profile",
    "make_new_york_conservative_profile",
    "make_new_york_aggressive_profile",
    "make_london_and_new_york_profile",
    "make_custom_profile",
]
