"""Loads phantom.config.ini and maps its values onto the real,
already-existing, frozen engine config dataclasses (BridgeConfig,
RuntimeConfig, RiskEngineConfig, ComplianceEngineConfig,
MarketIntelligenceConfig, ReliabilityConfig) plus this deployment
layer's own logging/profile settings.

This module contains zero trading logic and zero new engine
behavior -- it only parses an INI file and calls existing public
dataclass constructors with the values found. Every field name below
was verified against the real config.py it targets (deployment_windows/
config/phantom.config.template.ini documents the same trace).

Secrets are never read from the ini file directly -- the ini file
names an environment variable, and the real value is read from the
environment at call time (never logged, never written back to disk).
"""

from __future__ import annotations

import configparser
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from phantom.bridge.config import BridgeConfig
from phantom.compliance_engine.config import ComplianceEngineConfig
from phantom.market_intelligence.config import MarketIntelligenceConfig
from phantom.risk_engine.config import RiskEngineConfig
from phantom.reliability.config import ReliabilityConfig
from phantom.runtime.config import RuntimeConfig

_VALID_PROFILES = (
    "london_conservative", "london_aggressive",
    "new_york_conservative", "new_york_aggressive",
    "london_and_new_york", "custom",
)


class ConfigError(Exception):
    """Raised for any missing/invalid configuration -- callers must
    treat this as fatal and never continue startup past it (fail
    closed)."""


@dataclass(frozen=True)
class NewsProviderSettings:
    """Reserved for `phantom/news_ingestion/` (ADR-033 Part 2, not yet
    implemented in this repository). Parsed and validated here so the
    config file format is ready for it, but nothing in this deployment
    layer or any frozen engine consumes these values yet -- Market
    Intelligence Engine's only real news-trust input remains the
    single `news_feed_trusted` boolean on `DeploymentSettings`. See
    KNOWN_GAPS.md."""

    trading_economics_api_key_env_var: str
    trading_economics_base_url: str
    forex_factory_base_url: str


@dataclass(frozen=True)
class DeploymentSettings:
    bridge_config: BridgeConfig
    bridge_host: str
    bridge_port: int
    runtime_config: RuntimeConfig
    selected_profile: str
    risk_config: RiskEngineConfig
    compliance_config: ComplianceEngineConfig
    compliance_rule_profile_name: str
    news_config: MarketIntelligenceConfig
    news_feed_trusted: bool
    news_provider_settings: NewsProviderSettings
    reliability_config: ReliabilityConfig
    log_dir: Path
    log_level: str
    state_dir: Path


def _require(parser: configparser.ConfigParser, section: str, key: str) -> str:
    if not parser.has_section(section):
        raise ConfigError(f"config missing required section [{section}]")
    if not parser.has_option(section, key):
        raise ConfigError(f"config missing required key '{key}' in [{section}]")
    value = parser.get(section, key)
    if not value or value.strip() == "":
        raise ConfigError(f"config key '{key}' in [{section}] is empty")
    return value.strip()


def _resolve_secret(parser: configparser.ConfigParser, section: str, env_var_key: str, inline_key: str, secret_label: str) -> str:
    """Environment variable is the supported, secure path: the ini
    file names *which* environment variable to read (never the secret
    itself). An inline fallback value is accepted for local/dev
    convenience only, and is rejected if it still equals the shipped
    template placeholder -- but its use is always logged as a warning
    (the message, never the value) so a real deployment doesn't
    silently ship a secret in a checked-in config file."""

    env_var_name = parser.get(section, env_var_key, fallback="").strip()
    if env_var_name:
        value = os.environ.get(env_var_name)
        if value:
            return value
        raise ConfigError(
            f"[{section}].{env_var_key} names environment variable {env_var_name!r}, "
            f"but it is not set. Set it before starting Phantom -- never put the real "
            f"{secret_label} directly in the config file."
        )

    inline_value = parser.get(section, inline_key, fallback="").strip()
    if inline_value and inline_value != "REPLACE_WITH_YOUR_BRIDGE_API_KEY":
        import logging

        logging.getLogger("phantom.deploy.config").warning(
            "%s is set inline in the config file (via [%s].%s), not via an "
            "environment variable -- fine for local testing, not recommended "
            "for a real deployment.", secret_label, section, inline_key,
        )
        return inline_value

    raise ConfigError(
        f"No {secret_label} configured -- set [{section}].{env_var_key} to an "
        f"environment variable name (recommended) or [{section}].{inline_key} "
        f"to a real value (local/dev only)."
    )


def load_settings(config_path: Path) -> "DeploymentSettings":
    if not config_path.exists():
        raise ConfigError(
            f"configuration file not found: {config_path}\n"
            "Copy config/phantom.config.template.ini to phantom.config.ini "
            "(same folder as this script) and edit it before starting Phantom."
        )

    parser = configparser.ConfigParser()
    parser.read(config_path, encoding="utf-8")

    api_key = _resolve_secret(parser, "bridge", "api_key_env_var", "api_key", "Bridge API key")
    allowed_symbols: Tuple[str, ...] = tuple(
        s.strip().upper() for s in _require(parser, "bridge", "allowed_symbols").split(",") if s.strip()
    )
    if not allowed_symbols:
        raise ConfigError("bridge.allowed_symbols must name at least one symbol")

    bridge_config = BridgeConfig(
        api_key=api_key,
        allowed_symbols=allowed_symbols,
        magic_number=parser.getint("bridge", "magic_number", fallback=20260709),
        max_lot_size=parser.getfloat("bridge", "max_lot_size", fallback=5.0),
        max_slippage_points=parser.getint("bridge", "max_slippage_points", fallback=20),
        heartbeat_timeout_seconds=parser.getfloat("bridge", "heartbeat_timeout_seconds", fallback=30.0),
        command_ttl_seconds=parser.getfloat("bridge", "command_ttl_seconds", fallback=15.0),
    )
    bridge_host = parser.get("bridge", "host", fallback="127.0.0.1")
    bridge_port = parser.getint("bridge", "port", fallback=8787)

    runtime_config = RuntimeConfig(
        magic_number=parser.getint("runtime", "magic_number", fallback=20260710),
        max_slippage_points=parser.getint("runtime", "max_slippage_points", fallback=20),
        max_cycle_duration_ms=parser.getfloat("runtime", "max_cycle_duration_ms", fallback=250.0),
        engine_timeout_ms=parser.getfloat("runtime", "engine_timeout_ms", fallback=100.0),
        runtime_timeout_ms=parser.getfloat("runtime", "runtime_timeout_ms", fallback=250.0),
        snapshot_timeout_ms=parser.getfloat("runtime", "snapshot_timeout_ms", fallback=50.0),
        bridge_timeout_ms=parser.getfloat("runtime", "bridge_timeout_ms", fallback=100.0),
    )
    if bridge_config.magic_number != runtime_config.magic_number:
        raise ConfigError(
            f"[bridge].magic_number ({bridge_config.magic_number}) and "
            f"[runtime].magic_number ({runtime_config.magic_number}) must match -- "
            "both are read by the same MT5 EA instance."
        )

    selected_profile = _require(parser, "trading_profile", "selected_profile").lower()
    if selected_profile not in _VALID_PROFILES:
        raise ConfigError(
            f"trading_profile.selected_profile {selected_profile!r} is not one of "
            f"the known profiles: {', '.join(_VALID_PROFILES)}"
        )

    risk_config = RiskEngineConfig(
        minimum_evidence_score=parser.getfloat("risk", "minimum_evidence_score", fallback=65.0),
        portfolio_heat_limit_r=parser.getfloat("risk", "portfolio_heat_limit_r", fallback=6.0),
        max_concurrent_risk_r=parser.getfloat("risk", "max_concurrent_risk_r", fallback=6.0),
        daily_risk_limit_r=parser.getfloat("risk", "daily_risk_limit_r", fallback=3.0),
        weekly_risk_limit_r=parser.getfloat("risk", "weekly_risk_limit_r", fallback=6.0),
        monthly_risk_limit_r=parser.getfloat("risk", "monthly_risk_limit_r", fallback=10.0),
        max_open_positions=parser.getint("risk", "max_open_positions", fallback=10),
        max_positions_per_pair=parser.getint("risk", "max_positions_per_pair", fallback=2),
    )

    compliance_config = ComplianceEngineConfig()
    compliance_rule_profile_name = parser.get("compliance", "rule_profile_name", fallback="example_generic_profile")
    try:
        compliance_config.profile_for(compliance_rule_profile_name)
    except ValueError as exc:
        raise ConfigError(f"compliance.rule_profile_name: {exc}") from exc

    news_config = MarketIntelligenceConfig(
        pre_news_blackout_minutes=parser.getfloat("news", "pre_news_blackout_minutes", fallback=30.0),
        post_news_blackout_minutes=parser.getfloat("news", "post_news_blackout_minutes", fallback=15.0),
        high_impact_requires_blackout=parser.getboolean("news", "high_impact_requires_blackout", fallback=True),
        central_bank_requires_blackout=parser.getboolean("news", "central_bank_requires_blackout", fallback=True),
    )
    news_feed_trusted = parser.getboolean("news", "news_feed_trusted", fallback=True)

    news_provider_settings = NewsProviderSettings(
        trading_economics_api_key_env_var=parser.get("news_providers", "trading_economics_api_key_env_var", fallback="PHANTOM_TRADING_ECONOMICS_API_KEY"),
        trading_economics_base_url=parser.get("news_providers", "trading_economics_base_url", fallback="https://api.tradingeconomics.com"),
        forex_factory_base_url=parser.get("news_providers", "forex_factory_base_url", fallback=""),
    )

    reliability_config = ReliabilityConfig(
        heartbeat_healthy_interval_seconds=parser.getfloat("reliability", "heartbeat_healthy_interval_seconds", fallback=5.0),
        heartbeat_degraded_interval_seconds=parser.getfloat("reliability", "heartbeat_degraded_interval_seconds", fallback=15.0),
        heartbeat_grace_period_seconds=parser.getfloat("reliability", "heartbeat_grace_period_seconds", fallback=30.0),
        snapshot_freshness_threshold_seconds=parser.getfloat("reliability", "snapshot_freshness_threshold_seconds", fallback=5.0),
        cpu_degraded_threshold_pct=parser.getfloat("reliability", "cpu_degraded_threshold_pct", fallback=70.0),
        cpu_critical_threshold_pct=parser.getfloat("reliability", "cpu_critical_threshold_pct", fallback=90.0),
        memory_degraded_threshold_pct=parser.getfloat("reliability", "memory_degraded_threshold_pct", fallback=75.0),
        memory_critical_threshold_pct=parser.getfloat("reliability", "memory_critical_threshold_pct", fallback=90.0),
        queue_degraded_depth=parser.getint("reliability", "queue_degraded_depth", fallback=100),
        queue_critical_depth=parser.getint("reliability", "queue_critical_depth", fallback=500),
    )

    # Relative to the config file's own folder by default -- so Phantom
    # can be installed anywhere and still find its own logs/state
    # without an absolute, install-location-specific path baked in.
    log_dir = Path(parser.get("logging", "log_dir", fallback="logs"))
    if not log_dir.is_absolute():
        log_dir = config_path.parent / log_dir
    log_level = parser.get("logging", "log_level", fallback="INFO").upper()
    state_dir = Path(parser.get("logging", "state_dir", fallback="state"))
    if not state_dir.is_absolute():
        state_dir = config_path.parent / state_dir

    return DeploymentSettings(
        bridge_config=bridge_config, bridge_host=bridge_host, bridge_port=bridge_port,
        runtime_config=runtime_config, selected_profile=selected_profile,
        risk_config=risk_config, compliance_config=compliance_config,
        compliance_rule_profile_name=compliance_rule_profile_name,
        news_config=news_config, news_feed_trusted=news_feed_trusted,
        news_provider_settings=news_provider_settings,
        reliability_config=reliability_config,
        log_dir=log_dir, log_level=log_level, state_dir=state_dir,
    )


__all__ = ["DeploymentSettings", "NewsProviderSettings", "ConfigError", "load_settings"]
