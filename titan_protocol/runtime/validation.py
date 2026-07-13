"""Startup configuration validation (ADR-031 SS11). Every check here
reads an already-existing engine config's own fields/methods -- never a
second validation of what an engine already enforces at evaluation
time. An invalid profile is rejected before trading, never silently
coerced."""

from __future__ import annotations

import re
from typing import List, Tuple

from titan_protocol.compliance_engine.config import ComplianceEngineConfig
from titan_protocol.strategy_engine.config import StrategyEngineConfig

from .models import ConfigValidationIssue, ConfigValidationResult, TradingProfile

_PAIR_PATTERN = re.compile(r"^[A-Z]{6}$")


def validate_profile(
    profile: TradingProfile,
    strategy_config: StrategyEngineConfig,
    compliance_config: ComplianceEngineConfig,
) -> ConfigValidationResult:
    issues: List[ConfigValidationIssue] = []

    # Trading window.
    window = profile.trading_window
    if not (0 <= window.start_hour_utc < 24) or not (0 <= window.end_hour_utc <= 24):
        issues.append(ConfigValidationIssue("trading_window", "start/end hour must be within [0, 24]"))
    elif window.start_hour_utc >= window.end_hour_utc:
        issues.append(ConfigValidationIssue("trading_window", "start_hour_utc must be before end_hour_utc"))
    if not window.days_of_week:
        issues.append(ConfigValidationIssue("trading_window.days_of_week", "must name at least one weekday"))

    # Allowed pairs.
    if not profile.allowed_pairs:
        issues.append(ConfigValidationIssue("allowed_pairs", "must be non-empty"))
    for pair in profile.allowed_pairs:
        if not _PAIR_PATTERN.match(pair):
            issues.append(ConfigValidationIssue("allowed_pairs", f"{pair!r} is not a valid 6-character pair"))

    # Allowed strategies.
    if not profile.allowed_strategies:
        issues.append(ConfigValidationIssue("allowed_strategies", "must be non-empty"))

    # Strategy eligibility: every allowed pair must be tradeable by at
    # least one of the profile's allowed strategies (StrategyEngineConfig
    # is the single source of truth for per-strategy pair eligibility --
    # never re-derived here).
    tradeable_pairs = set()
    for strategy_id in profile.allowed_strategies:
        tradeable_pairs.update(strategy_config.approved_pairs_for(strategy_id))
    for pair in profile.allowed_pairs:
        if pair not in tradeable_pairs:
            issues.append(ConfigValidationIssue(
                "allowed_pairs", f"{pair!r} is not eligible for any of this profile's allowed strategies",
            ))

    # Sessions -- empty session_rules is a valid, deliberate "no session
    # restriction" configuration (the sequencing engine's own semantics,
    # `run_cycle_for_pair`'s `if profile.session_rules and ...` check);
    # nothing to validate beyond the type system already guaranteeing
    # every element is a real `SessionName`.

    # News configuration.
    news = profile.news_policy
    if news.pre_news_blackout_minutes < 0 or news.post_news_blackout_minutes < 0:
        issues.append(ConfigValidationIssue("news_policy", "blackout minutes must be non-negative"))

    # Risk configuration.
    risk = profile.risk_profile
    if risk.daily_risk_limit_r <= 0 or risk.portfolio_heat_limit_r <= 0 or risk.max_open_positions <= 0:
        issues.append(ConfigValidationIssue("risk_profile", "risk limits and max_open_positions must be positive"))

    # Compliance configuration -- the referenced rule profile must exist.
    try:
        compliance_config.profile_for(profile.compliance_rule_profile_name)
    except ValueError:
        issues.append(ConfigValidationIssue(
            "compliance_rule_profile_name", f"{profile.compliance_rule_profile_name!r} is not a known compliance rule profile",
        ))

    return ConfigValidationResult(valid=not issues, issues=tuple(issues))


def validate_profiles(
    profiles: Tuple[TradingProfile, ...],
    strategy_config: StrategyEngineConfig,
    compliance_config: ComplianceEngineConfig,
) -> Tuple[ConfigValidationResult, ...]:
    return tuple(validate_profile(p, strategy_config, compliance_config) for p in profiles)


__all__ = ["validate_profile", "validate_profiles"]
