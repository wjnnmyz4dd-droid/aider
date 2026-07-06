"""Configuration Manager (Phase 5) — validates a deployment profile
*before* any service is started; never starts a service against an
unvalidated or invalid configuration (fail-closed, matching every
pipeline stage's own "never proceed on missing/invalid input" posture).

Reads from an **injected mapping**, never `os.environ` directly, so no
test here ever touches the real process environment and no real secret
value is ever read by this module's own code path — the caller (whoever
wires the real deployment together) is the only place that touches
`os.environ`. This mirrors the claude-mem priming session's own
established practice in this repository of never opening a real
credential source directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional, Tuple

from .models import ConfigValidationIssue, ConfigValidationResult, DeploymentProfile

REQUIRED_SECRET_KEYS: Tuple[str, ...] = ("MT5_LOGIN", "MT5_PASSWORD", "MT5_SERVER")


@dataclass(frozen=True)
class ProfileConfig:
    profile: DeploymentProfile
    mt5_login: Optional[str]
    mt5_server: Optional[str]
    broker_profile_name: Optional[str]
    paper_trading_enabled: bool
    allowed_broker_profiles: Tuple[str, ...] = ()


class ConfigurationManager:
    def load_profile(self, profile: DeploymentProfile, source: Mapping[str, str]) -> ProfileConfig:
        return ProfileConfig(
            profile=profile,
            mt5_login=source.get("MT5_LOGIN"),
            mt5_server=source.get("MT5_SERVER"),
            broker_profile_name=source.get("BROKER_PROFILE"),
            paper_trading_enabled=source.get("PAPER_TRADING_ENABLED", "false").strip().lower() == "true",
            allowed_broker_profiles=tuple(
                p.strip() for p in source.get("ALLOWED_BROKER_PROFILES", "").split(",") if p.strip()
            ),
        )

    def validate(self, config: ProfileConfig, source: Mapping[str, str]) -> ConfigValidationResult:
        issues = []

        if config.profile != DeploymentProfile.DEV:
            for key in REQUIRED_SECRET_KEYS:
                value = source.get(key)
                if value is None or value.strip() == "":
                    issues.append(ConfigValidationIssue(key, f"missing required secret: {key}", is_error=True))

        if config.mt5_login is not None and not config.mt5_login.strip().isdigit():
            issues.append(
                ConfigValidationIssue("mt5_login", "MT5 account login must be a positive integer", is_error=True)
            )
        elif config.profile != DeploymentProfile.DEV and not config.mt5_login:
            issues.append(ConfigValidationIssue("mt5_login", "MT5 account login is not configured", is_error=True))

        if config.allowed_broker_profiles and config.broker_profile_name not in config.allowed_broker_profiles:
            issues.append(
                ConfigValidationIssue(
                    "broker_profile_name",
                    f"broker profile {config.broker_profile_name!r} is not in the allowed set for this deployment",
                    is_error=True,
                )
            )

        if config.profile == DeploymentProfile.LIVE and config.paper_trading_enabled:
            issues.append(
                ConfigValidationIssue(
                    "paper_trading_enabled", "paper trading must be disabled in the LIVE profile", is_error=True
                )
            )

        return ConfigValidationResult(profile=config.profile, issues=tuple(issues))


__all__ = ["ProfileConfig", "ConfigurationManager", "REQUIRED_SECRET_KEYS"]
