"""Loads phantom_config.json and maps its values onto the real,
already-existing, frozen engine config dataclasses (BridgeConfig,
RuntimeConfig, RiskEngineConfig, ComplianceEngineConfig,
MarketIntelligenceConfig, ReliabilityConfig) plus this deployment
layer's own logging/profile settings.

This module contains zero trading logic and zero new engine
behavior -- it only parses a JSON file and calls existing public
dataclass constructors with the values found. Every field name below
was verified against the real config.py it targets (deployment_windows/
config/phantom_config.example.json documents the same trace).

Secrets are never read from the config file directly -- the config
file names an environment variable, and the real value is read from
the environment (or a locally-generated secret file -- see
generated_secret_path below) at call time, never logged, never written
back to disk.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

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

CONFIG_SCHEMA_VERSION = 1


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
    data_dir: Path
    api_key_env_var_name: str


def _section(data: Dict[str, Any], name: str) -> Dict[str, Any]:
    value = data.get(name, {})
    if not isinstance(value, dict):
        raise ConfigError(f"config section '{name}' must be a JSON object")
    return value


def _require_str(section: Dict[str, Any], section_name: str, key: str) -> str:
    value = section.get(key)
    if value is None or not isinstance(value, str) or not value.strip():
        raise ConfigError(f"config missing required key '{key}' in '{section_name}'")
    return value.strip()


def _get_str(section: Dict[str, Any], key: str, default: str) -> str:
    value = section.get(key, default)
    if not isinstance(value, str):
        raise ConfigError(f"config key {key!r} must be a string")
    return value


def _get_int(section: Dict[str, Any], key: str, default: int) -> int:
    value = section.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"config key {key!r} must be an integer")
    return value


def _get_float(section: Dict[str, Any], key: str, default: float) -> float:
    value = section.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"config key {key!r} must be a number")
    return float(value)


def _get_bool(section: Dict[str, Any], key: str, default: bool) -> bool:
    value = section.get(key, default)
    if not isinstance(value, bool):
        raise ConfigError(f"config key {key!r} must be a boolean")
    return value


GENERATED_SECRET_FILENAME = ".bridge_api_key.secret"


def generated_secret_path(config_path: Path) -> Path:
    """Where install.py writes an auto-generated Bridge API key, next to
    phantom_config.json itself. Gitignored -- never committed. This is
    a locally-generated shared secret between this Phantom instance and
    the one EA it talks to (not a third-party credential), so
    generating and storing it locally without user interaction is
    appropriate -- unlike a real external API key, there is nothing to
    "obtain" from anywhere else."""
    return config_path.parent / GENERATED_SECRET_FILENAME


def _read_generated_secret_file(config_path: Path) -> Optional[str]:
    path = generated_secret_path(config_path)
    if not path.exists():
        return None
    value = path.read_text(encoding="utf-8").strip()
    return value or None


def _resolve_secret(bridge_section: Dict[str, Any], env_var_key: str, inline_key: str, secret_label: str, config_path: Path) -> Tuple[str, str]:
    """Three sources, in order, none of which require the operator to
    edit anything by hand for the common case. Returns (value, the
    resolved env_var_name) so callers can report which environment
    variable name governs this secret.

    1. Environment variable named by bridge.env_var_key -- the
       supported, secure path for a real deployment.
    2. A local, gitignored, auto-generated secret file next to the
       config file (written once by install.py) -- covers the
       zero-manual-configuration install flow without ever putting the
       key in a checked-in-shaped config file.
    3. An inline value in the config file itself -- local/dev
       convenience only, rejected if it still equals the shipped
       template placeholder, and always logged as a warning (the
       message, never the value) so a real deployment doesn't silently
       ship a secret in a config file.
    """

    env_var_name = _get_str(bridge_section, env_var_key, "").strip()
    if env_var_name:
        value = os.environ.get(env_var_name)
        if value:
            return value, env_var_name

    generated = _read_generated_secret_file(config_path)
    if generated:
        return generated, env_var_name

    if env_var_name:
        raise ConfigError(
            f"bridge.{env_var_key} names environment variable {env_var_name!r}, "
            f"but it is not set, and no generated secret file was found at "
            f"{generated_secret_path(config_path)}. Set the environment variable, "
            f"or re-run install.py, before starting Phantom."
        )

    inline_value = _get_str(bridge_section, inline_key, "").strip()
    if inline_value and inline_value != "REPLACE_WITH_YOUR_BRIDGE_API_KEY":
        import logging

        logging.getLogger("phantom.deploy.config").warning(
            "%s is set inline in the config file (via bridge.%s), not via an "
            "environment variable -- fine for local testing, not recommended "
            "for a real deployment.", secret_label, inline_key,
        )
        return inline_value, env_var_name

    raise ConfigError(
        f"No {secret_label} configured -- set bridge.{env_var_key} to an "
        f"environment variable name (recommended), let install.py generate one, "
        f"or set bridge.{inline_key} to a real value (local/dev only)."
    )


def load_settings(config_path: Path) -> "DeploymentSettings":
    if not config_path.exists():
        raise ConfigError(
            f"configuration file not found: {config_path}\n"
            "Copy config/phantom_config.example.json to phantom_config.json "
            "(same folder as this script) and edit it before starting Phantom, "
            "or run install.py, which does this for you."
        )

    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{config_path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{config_path} must contain a JSON object at the top level")

    bridge_section = _section(data, "bridge")
    api_key, api_key_env_var_name = _resolve_secret(bridge_section, "api_key_env_var", "api_key", "Bridge API key", config_path)
    raw_symbols = bridge_section.get("allowed_symbols")
    if not isinstance(raw_symbols, list) or not raw_symbols:
        raise ConfigError("bridge.allowed_symbols must be a non-empty JSON array of symbol strings")
    allowed_symbols: Tuple[str, ...] = tuple(str(s).strip().upper() for s in raw_symbols if str(s).strip())
    if not allowed_symbols:
        raise ConfigError("bridge.allowed_symbols must name at least one symbol")

    bridge_config = BridgeConfig(
        api_key=api_key,
        allowed_symbols=allowed_symbols,
        magic_number=_get_int(bridge_section, "magic_number", 20260709),
        max_lot_size=_get_float(bridge_section, "max_lot_size", 5.0),
        max_slippage_points=_get_int(bridge_section, "max_slippage_points", 20),
        heartbeat_timeout_seconds=_get_float(bridge_section, "heartbeat_timeout_seconds", 30.0),
        command_ttl_seconds=_get_float(bridge_section, "command_ttl_seconds", 15.0),
    )
    bridge_host = _get_str(bridge_section, "host", "127.0.0.1")
    bridge_port = _get_int(bridge_section, "port", 8787)

    runtime_section = _section(data, "runtime")
    runtime_config = RuntimeConfig(
        magic_number=_get_int(runtime_section, "magic_number", 20260710),
        max_slippage_points=_get_int(runtime_section, "max_slippage_points", 20),
        max_cycle_duration_ms=_get_float(runtime_section, "max_cycle_duration_ms", 250.0),
        engine_timeout_ms=_get_float(runtime_section, "engine_timeout_ms", 100.0),
        runtime_timeout_ms=_get_float(runtime_section, "runtime_timeout_ms", 250.0),
        snapshot_timeout_ms=_get_float(runtime_section, "snapshot_timeout_ms", 50.0),
        bridge_timeout_ms=_get_float(runtime_section, "bridge_timeout_ms", 100.0),
    )
    if bridge_config.magic_number != runtime_config.magic_number:
        raise ConfigError(
            f"bridge.magic_number ({bridge_config.magic_number}) and "
            f"runtime.magic_number ({runtime_config.magic_number}) must match -- "
            "both are read by the same MT5 EA instance."
        )

    profile_section = _section(data, "trading_profile")
    selected_profile = _require_str(profile_section, "trading_profile", "selected_profile").lower()
    if selected_profile not in _VALID_PROFILES:
        raise ConfigError(
            f"trading_profile.selected_profile {selected_profile!r} is not one of "
            f"the known profiles: {', '.join(_VALID_PROFILES)}"
        )

    risk_section = _section(data, "risk")
    risk_config = RiskEngineConfig(
        minimum_evidence_score=_get_float(risk_section, "minimum_evidence_score", 65.0),
        portfolio_heat_limit_r=_get_float(risk_section, "portfolio_heat_limit_r", 6.0),
        max_concurrent_risk_r=_get_float(risk_section, "max_concurrent_risk_r", 6.0),
        daily_risk_limit_r=_get_float(risk_section, "daily_risk_limit_r", 3.0),
        weekly_risk_limit_r=_get_float(risk_section, "weekly_risk_limit_r", 6.0),
        monthly_risk_limit_r=_get_float(risk_section, "monthly_risk_limit_r", 10.0),
        max_open_positions=_get_int(risk_section, "max_open_positions", 10),
        max_positions_per_pair=_get_int(risk_section, "max_positions_per_pair", 2),
    )

    compliance_section = _section(data, "compliance")
    compliance_config = ComplianceEngineConfig()
    compliance_rule_profile_name = _get_str(compliance_section, "rule_profile_name", "example_generic_profile")
    try:
        compliance_config.profile_for(compliance_rule_profile_name)
    except ValueError as exc:
        raise ConfigError(f"compliance.rule_profile_name: {exc}") from exc

    news_section = _section(data, "news")
    news_config = MarketIntelligenceConfig(
        pre_news_blackout_minutes=_get_float(news_section, "pre_news_blackout_minutes", 30.0),
        post_news_blackout_minutes=_get_float(news_section, "post_news_blackout_minutes", 15.0),
        high_impact_requires_blackout=_get_bool(news_section, "high_impact_requires_blackout", True),
        central_bank_requires_blackout=_get_bool(news_section, "central_bank_requires_blackout", True),
    )
    news_feed_trusted = _get_bool(news_section, "news_feed_trusted", True)

    news_providers_section = _section(data, "news_providers")
    news_provider_settings = NewsProviderSettings(
        trading_economics_api_key_env_var=_get_str(news_providers_section, "trading_economics_api_key_env_var", "PHANTOM_TRADING_ECONOMICS_API_KEY"),
        trading_economics_base_url=_get_str(news_providers_section, "trading_economics_base_url", "https://api.tradingeconomics.com"),
        forex_factory_base_url=_get_str(news_providers_section, "forex_factory_base_url", ""),
    )

    reliability_section = _section(data, "reliability")
    reliability_config = ReliabilityConfig(
        heartbeat_healthy_interval_seconds=_get_float(reliability_section, "heartbeat_healthy_interval_seconds", 5.0),
        heartbeat_degraded_interval_seconds=_get_float(reliability_section, "heartbeat_degraded_interval_seconds", 15.0),
        heartbeat_grace_period_seconds=_get_float(reliability_section, "heartbeat_grace_period_seconds", 30.0),
        snapshot_freshness_threshold_seconds=_get_float(reliability_section, "snapshot_freshness_threshold_seconds", 5.0),
        cpu_degraded_threshold_pct=_get_float(reliability_section, "cpu_degraded_threshold_pct", 70.0),
        cpu_critical_threshold_pct=_get_float(reliability_section, "cpu_critical_threshold_pct", 90.0),
        memory_degraded_threshold_pct=_get_float(reliability_section, "memory_degraded_threshold_pct", 75.0),
        memory_critical_threshold_pct=_get_float(reliability_section, "memory_critical_threshold_pct", 90.0),
        queue_degraded_depth=_get_int(reliability_section, "queue_degraded_depth", 100),
        queue_critical_depth=_get_int(reliability_section, "queue_critical_depth", 500),
    )

    # Relative to the config file's own folder by default -- so Phantom
    # can be installed anywhere and still find its own logs/state/data
    # without an absolute, install-location-specific path baked in.
    logging_section = _section(data, "logging")
    log_dir = Path(_get_str(logging_section, "log_dir", "logs"))
    if not log_dir.is_absolute():
        log_dir = config_path.parent / log_dir
    log_level = _get_str(logging_section, "log_level", "INFO").upper()
    state_dir = Path(_get_str(logging_section, "state_dir", "state"))
    if not state_dir.is_absolute():
        state_dir = config_path.parent / state_dir
    data_dir = Path(_get_str(logging_section, "data_dir", "data"))
    if not data_dir.is_absolute():
        data_dir = config_path.parent / data_dir

    return DeploymentSettings(
        bridge_config=bridge_config, bridge_host=bridge_host, bridge_port=bridge_port,
        runtime_config=runtime_config, selected_profile=selected_profile,
        risk_config=risk_config, compliance_config=compliance_config,
        compliance_rule_profile_name=compliance_rule_profile_name,
        news_config=news_config, news_feed_trusted=news_feed_trusted,
        news_provider_settings=news_provider_settings,
        reliability_config=reliability_config,
        log_dir=log_dir, log_level=log_level, state_dir=state_dir, data_dir=data_dir,
        api_key_env_var_name=api_key_env_var_name,
    )


__all__ = [
    "DeploymentSettings", "NewsProviderSettings", "ConfigError", "load_settings",
    "generated_secret_path", "CONFIG_SCHEMA_VERSION",
]
