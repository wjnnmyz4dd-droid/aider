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
"""

from __future__ import annotations

import configparser
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple

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
    closed, per the mission's own setup_phantom.bat requirement)."""


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


def load_settings(config_path: Path) -> "DeploymentSettings":
    if not config_path.exists():
        raise ConfigError(
            f"configuration file not found: {config_path}\n"
            "Copy config/phantom.config.template.ini to phantom.config.ini "
            "and edit it before starting Phantom."
        )

    parser = configparser.ConfigParser()
    parser.read(config_path, encoding="utf-8")

    api_key = _require(parser, "bridge", "api_key")
    if api_key == "REPLACE_WITH_YOUR_BRIDGE_API_KEY":
        raise ConfigError(
            "bridge.api_key is still the template placeholder -- set a "
            "real API key before starting Phantom."
        )
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

    log_dir = Path(parser.get("logging", "log_dir", fallback=str(config_path.parent / "logs")))
    log_level = parser.get("logging", "log_level", fallback="INFO").upper()
    state_dir = Path(parser.get("logging", "state_dir", fallback=str(config_path.parent / "state")))

    return DeploymentSettings(
        bridge_config=bridge_config, bridge_host=bridge_host, bridge_port=bridge_port,
        runtime_config=runtime_config, selected_profile=selected_profile,
        risk_config=risk_config, compliance_config=compliance_config,
        compliance_rule_profile_name=compliance_rule_profile_name,
        news_config=news_config, news_feed_trusted=news_feed_trusted,
        reliability_config=reliability_config,
        log_dir=log_dir, log_level=log_level, state_dir=state_dir,
    )


__all__ = ["DeploymentSettings", "ConfigError", "load_settings"]
