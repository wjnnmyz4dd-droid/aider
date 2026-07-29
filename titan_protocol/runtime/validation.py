"""Startup configuration validation (ADR-031 SS11). Every check here
reads an already-existing engine config's own fields/methods -- never a
second validation of what an engine already enforces at evaluation
time. An invalid profile is rejected before trading, never silently
coerced."""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

from titan_protocol.compliance_engine.config import ComplianceEngineConfig
from titan_protocol.evidence_engine.config import EvidenceEngineConfig
from titan_protocol.opportunity_selection_engine.config import OpportunitySelectionEngineConfig
from titan_protocol.strategy_engine.config import StrategyEngineConfig
from titan_protocol.strategy_engine.models import StrategyId

from .models import ConfigValidationIssue, ConfigValidationResult, TradingProfile

_PAIR_PATTERN = re.compile(r"^[A-Z]{6}$")


def validate_profile(
    profile: TradingProfile,
    strategy_config: StrategyEngineConfig,
    compliance_config: ComplianceEngineConfig,
    evidence_config: Optional[EvidenceEngineConfig] = None,
    opportunity_selection_config: Optional[OpportunitySelectionEngineConfig] = None,
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

    # Opportunity Selection Engine structural readiness (ADR-037 SS11,
    # Plan SS5) -- runs only when both new parameters are supplied;
    # existing callers passing only the first three parameters are
    # entirely unaffected, and the four invariants below never inspect
    # any live QualificationResult/scan outcome/per-cycle state.
    if evidence_config is not None and opportunity_selection_config is not None:
        anchor_keys = {(hour, minute) for _session, hour, minute in evidence_config.opening_range_anchors}
        anchor_session_by_key = {(hour, minute): session for session, hour, minute in evidence_config.opening_range_anchors}
        enabled_keys = {
            (w.anchor_hour_utc, w.anchor_minute_utc) for w in opportunity_selection_config.enabled_windows
        }

        # Check 1: unconditional -- every enabled window must reference a
        # real Gate B anchor, and its session_name must match that
        # anchor's own declared SessionName.
        for window in opportunity_selection_config.enabled_windows:
            key = (window.anchor_hour_utc, window.anchor_minute_utc)
            if key not in anchor_keys:
                issues.append(ConfigValidationIssue(
                    "opportunity_selection_config.enabled_windows",
                    f"anchor {key} is not a configured evidence_config.opening_range_anchors entry",
                ))
            elif anchor_session_by_key[key] != window.session_name:
                issues.append(ConfigValidationIssue(
                    "opportunity_selection_config.enabled_windows",
                    f"anchor {key} is declared as {anchor_session_by_key[key].value!r} in "
                    f"evidence_config.opening_range_anchors but {window.session_name.value!r} here",
                ))

        if opportunity_selection_config.cross_pair_selection_enabled:
            # Check 2: every Gate B anchor must be referenced by some
            # enabled window.
            for key in anchor_keys - enabled_keys:
                issues.append(ConfigValidationIssue(
                    "opportunity_selection_config.enabled_windows",
                    f"evidence_config.opening_range_anchors entry {key} is not referenced by any enabled window",
                ))

            # Check 3: enabled_windows must be non-empty.
            if not opportunity_selection_config.enabled_windows:
                issues.append(ConfigValidationIssue(
                    "opportunity_selection_config.enabled_windows",
                    "cross_pair_selection_enabled is True but enabled_windows is empty",
                ))

            # Check 4: Gate A must be broad enough for selection to be
            # meaningful.
            orb_pairs = strategy_config.approved_pairs_for(StrategyId.OPENING_RANGE_BREAKOUT)
            if len(orb_pairs) <= 1:
                issues.append(ConfigValidationIssue(
                    "opportunity_selection_config.cross_pair_selection_enabled",
                    f"cross_pair_selection_enabled is True but Gate A approves only {len(orb_pairs)} "
                    f"ORB pair(s) -- cross-pair selection would be a structural no-op",
                ))

    return ConfigValidationResult(valid=not issues, issues=tuple(issues))


def validate_profiles(
    profiles: Tuple[TradingProfile, ...],
    strategy_config: StrategyEngineConfig,
    compliance_config: ComplianceEngineConfig,
    evidence_config: Optional[EvidenceEngineConfig] = None,
    opportunity_selection_config: Optional[OpportunitySelectionEngineConfig] = None,
) -> Tuple[ConfigValidationResult, ...]:
    return tuple(
        validate_profile(p, strategy_config, compliance_config, evidence_config, opportunity_selection_config)
        for p in profiles
    )


__all__ = ["validate_profile", "validate_profiles"]
