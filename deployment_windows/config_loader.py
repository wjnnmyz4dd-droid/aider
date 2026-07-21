"""Loads titan_protocol_config.json and maps its values onto the real,
already-existing, frozen engine config dataclasses (BridgeConfig,
RuntimeConfig, RiskEngineConfig, ComplianceEngineConfig,
MarketIntelligenceConfig, ReliabilityConfig) plus this deployment
layer's own logging/profile settings.

This module contains zero trading logic and zero new engine
behavior -- it only parses a JSON file and calls existing public
dataclass constructors with the values found. Every field name below
was verified against the real config.py it targets (deployment_windows/
config/titan_protocol_config.example.json documents the same trace).

Secrets are never read from the config file directly -- the config
file names an environment variable, and the real value is read from
the environment (or a locally-generated secret file -- see
generated_secret_path below) at call time, never logged, never written
back to disk.
"""

from __future__ import annotations

import dataclasses
import json
import os
import platform
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from titan_protocol.bridge.config import VALID_TRANSPORTS, BridgeConfig
from titan_protocol.bridge.symbol_mapping import SymbolMapping
from titan_protocol.compliance_engine.config import ComplianceEngineConfig
from titan_protocol.market_intelligence.config import MarketIntelligenceConfig
from titan_protocol.risk_engine.config import RiskEngineConfig
from titan_protocol.reliability.config import ReliabilityConfig
from titan_protocol.runtime.config import RuntimeConfig
from titan_protocol.runtime.models import TradingProfile
from titan_protocol.runtime import profiles as trading_profiles

_PAIR_NAME_RE = re.compile(r"^[A-Z]{6}$")

_PROFILE_FACTORIES = {
    "london_conservative": trading_profiles.make_london_conservative_profile,
    "london_aggressive": trading_profiles.make_london_aggressive_profile,
    "new_york_conservative": trading_profiles.make_new_york_conservative_profile,
    "new_york_aggressive": trading_profiles.make_new_york_aggressive_profile,
    "london_and_new_york": trading_profiles.make_london_and_new_york_profile,
}

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
    """Backs `titan_protocol/news_ingestion/` (ADR-033 Part 2, Phase 3E).
    `start.py` builds a `NewsIngestionConfig` from these fields and
    constructs the real dual-provider `NewsIngestionEngine`; its
    `fetch_events()` result supersedes the static `news_feed_trusted`
    config value at cycle time (see `_build_news_ingestion_config()`
    and `_live_cycle_loop()` in start.py)."""

    trading_economics_api_key_env_var: str
    trading_economics_base_url: str
    forex_factory_base_url: str
    forex_factory_api_key_env_var: str
    request_timeout_seconds: float
    max_retries: int
    retry_backoff_seconds: float
    stale_after_seconds: float
    recovery_health_check_count: int
    cache_max_entries: int


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
    compliance_daily_reset_hour_utc: int
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


def is_process_alive(pid: int) -> bool:
    """Reliable, cross-platform process-liveness check.

    `os.kill(pid, 0)` is the standard POSIX liveness probe, but it is
    NOT a liveness probe on Windows: CPython maps signal value 0 to
    `CTRL_C_EVENT` there, which `GenerateConsoleCtrlEvent` can only
    deliver to a process sharing the caller's console. Titan Protocol's
    background process is always launched with `CREATE_NEW_CONSOLE`
    (see `start.py`'s `launch_and_report()`) specifically so it survives
    the launching shell closing -- which means it never shares a console
    with whatever later calls `os.kill(pid, 0)` to check on it (a
    separate `start.py`, `stop.py`, or `health_check.py` invocation).
    That call always raises OSError there, so the previous per-script
    `os.kill(pid, 0)`-based checks always reported a perfectly healthy
    background process as dead on Windows -- a real, verified defect
    (Final Release Hardening follow-up), not a hardening feature. This
    is the one, single fix: `tasklist` on Windows, `os.kill(pid, 0)`
    everywhere else."""

    if platform.system() == "Windows":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=10,
            )
            return str(pid) in result.stdout
        except (OSError, subprocess.SubprocessError):
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
    except AttributeError:
        return False  # os.kill unavailable -- treat as unknown/not-confirmed


GENERATED_SECRET_FILENAME = ".bridge_api_key.secret"


def generated_secret_path(config_path: Path) -> Path:
    """Where install.py writes an auto-generated Bridge API key, next to
    titan_protocol_config.json itself. Gitignored -- never committed. This is
    a locally-generated shared secret between this Titan Protocol instance and
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
            f"or re-run install.py, before starting Titan Protocol."
        )

    inline_value = _get_str(bridge_section, inline_key, "").strip()
    if inline_value and inline_value != "REPLACE_WITH_YOUR_BRIDGE_API_KEY":
        import logging

        logging.getLogger("titan_protocol.deploy.config").warning(
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
            "Copy config/titan_protocol_config.example.json to titan_protocol_config.json "
            "(same folder as this script) and edit it before starting Titan Protocol, "
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
    cleaned_symbols = [str(s).strip().upper() for s in raw_symbols if str(s).strip()]
    if not cleaned_symbols:
        raise ConfigError("bridge.allowed_symbols must name at least one symbol")
    # Symbol-universe consistency (Final Release Hardening): a duplicate
    # or malformed entry here is a configuration mistake worth catching
    # at startup, not a silent no-op -- every downstream comparison
    # (pair_currencies()'s 3+3 slicing, enabled_pairs membership) assumes
    # each canonical pair name is a distinct, well-formed 6-letter code.
    seen: set = set()
    duplicates = sorted({s for s in cleaned_symbols if s in seen or seen.add(s)})
    if duplicates:
        raise ConfigError(f"bridge.allowed_symbols contains duplicate pair(s): {duplicates}")
    malformed = [s for s in cleaned_symbols if not _PAIR_NAME_RE.match(s)]
    if malformed:
        raise ConfigError(
            f"bridge.allowed_symbols contains invalid pair name(s) {malformed} -- "
            "every canonical pair must be exactly 6 letters (e.g. 'EURUSD'). If your "
            "broker reports symbols with a suffix/prefix (e.g. 'EURUSD.a'), configure "
            "bridge.symbol_mapping instead of putting the broker-native name here."
        )
    allowed_symbols: Tuple[str, ...] = tuple(cleaned_symbols)

    symbol_mapping_section = _section(bridge_section, "symbol_mapping")
    raw_explicit_map = symbol_mapping_section.get("explicit_map", {})
    if not isinstance(raw_explicit_map, dict):
        raise ConfigError("bridge.symbol_mapping.explicit_map must be a JSON object")
    symbol_mapping = SymbolMapping(
        broker_suffix=_get_str(symbol_mapping_section, "broker_suffix", ""),
        broker_prefix=_get_str(symbol_mapping_section, "broker_prefix", ""),
        explicit_map={str(k).strip().upper(): str(v).strip() for k, v in raw_explicit_map.items()},
    )

    # ADR-034: transport substrate selector -- "http" (default,
    # Amendment 4) or "socket" (a fully-supported explicit opt-in).
    # Exactly one is ever active; see start.py. Falls back to
    # BridgeConfig's own default rather than a second hardcoded literal
    # here, so this module can never drift from the dataclass it's
    # populating.
    transport = _get_str(bridge_section, "transport", BridgeConfig.transport).strip().lower()
    if transport not in VALID_TRANSPORTS:
        raise ConfigError(
            f"bridge.transport must be one of {VALID_TRANSPORTS}, got {transport!r}"
        )

    bridge_config = BridgeConfig(
        api_key=api_key,
        allowed_symbols=allowed_symbols,
        symbol_mapping=symbol_mapping,
        # Canonical default sourced from BridgeConfig itself (single
        # source of truth) -- never a second hardcoded literal that
        # could silently drift from it.
        magic_number=_get_int(bridge_section, "magic_number", BridgeConfig.magic_number),
        max_lot_size=_get_float(bridge_section, "max_lot_size", 5.0),
        max_slippage_points=_get_int(bridge_section, "max_slippage_points", 20),
        heartbeat_timeout_seconds=_get_float(bridge_section, "heartbeat_timeout_seconds", 30.0),
        command_ttl_seconds=_get_float(bridge_section, "command_ttl_seconds", 15.0),
        transport=transport,
        socket_port=_get_int(bridge_section, "socket_port", 8788),
        socket_max_message_bytes=_get_int(bridge_section, "socket_max_message_bytes", 65536),
        socket_idle_timeout_seconds=_get_float(bridge_section, "socket_idle_timeout_seconds", 60.0),
        socket_max_connections=_get_int(bridge_section, "socket_max_connections", 8),
    )
    bridge_host = _get_str(bridge_section, "host", "127.0.0.1")
    bridge_port = _get_int(bridge_section, "port", 8787)

    runtime_section = _section(data, "runtime")
    runtime_config = RuntimeConfig(
        # Same single-source-of-truth pattern as bridge_config above.
        magic_number=_get_int(runtime_section, "magic_number", RuntimeConfig.magic_number),
        max_slippage_points=_get_int(runtime_section, "max_slippage_points", 20),
        max_cycle_duration_ms=_get_float(runtime_section, "max_cycle_duration_ms", 250.0),
        engine_timeout_ms=_get_float(runtime_section, "engine_timeout_ms", 100.0),
        runtime_timeout_ms=_get_float(runtime_section, "runtime_timeout_ms", 250.0),
        snapshot_timeout_ms=_get_float(runtime_section, "snapshot_timeout_ms", 50.0),
        bridge_timeout_ms=_get_float(runtime_section, "bridge_timeout_ms", 100.0),
        position_confirmation_timeout_seconds=_get_float(
            runtime_section, "position_confirmation_timeout_seconds",
            RuntimeConfig.position_confirmation_timeout_seconds,
        ),
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
    compliance_rule_profile_name = _get_str(compliance_section, "rule_profile_name", "example_generic_profile")
    # Production invariant: at most one open position per pair. Configurable
    # (never hard-coded past this point) so an operator can deliberately
    # widen it, but the field must be an integer >= 1 -- anything else fails
    # closed at startup rather than silently falling back to a permissive
    # default.
    max_positions_per_pair = _get_int(compliance_section, "max_positions_per_pair", 1)
    if max_positions_per_pair < 1:
        raise ConfigError(
            f"compliance.max_positions_per_pair must be an integer >= 1, got {max_positions_per_pair}"
        )
    # Fail-closed freshness bound on the account balance daily-loss/
    # drawdown/profit-protection are evaluated against (ACCOUNT_STATE_STALE).
    # Must be strictly positive -- zero or negative would either reject
    # every cycle unconditionally or accept unconditionally, neither of
    # which is a real threshold.
    max_account_state_age_seconds = _get_float(compliance_section, "max_account_state_age_seconds", 30.0)
    if max_account_state_age_seconds <= 0:
        raise ConfigError(
            f"compliance.max_account_state_age_seconds must be > 0, got {max_account_state_age_seconds}"
        )
    _base_compliance_config = ComplianceEngineConfig()
    try:
        _base_rule_profile = _base_compliance_config.profile_for(compliance_rule_profile_name)
    except ValueError as exc:
        raise ConfigError(f"compliance.rule_profile_name: {exc}") from exc
    compliance_config = dataclasses.replace(
        _base_compliance_config,
        rule_profiles=tuple(
            dataclasses.replace(
                p, max_positions_per_pair=max_positions_per_pair,
                max_account_state_age_seconds=max_account_state_age_seconds,
            )
            if p.name == compliance_rule_profile_name else p
            for p in _base_compliance_config.rule_profiles
        ),
    )
    compliance_daily_reset_hour_utc = _get_int(compliance_section, "daily_reset_hour_utc", 0)
    if not (0 <= compliance_daily_reset_hour_utc <= 23):
        raise ConfigError(
            f"compliance.daily_reset_hour_utc must be between 0 and 23, got {compliance_daily_reset_hour_utc}"
        )

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
        trading_economics_api_key_env_var=_get_str(news_providers_section, "trading_economics_api_key_env_var", "TITAN_PROTOCOL_TRADING_ECONOMICS_API_KEY"),
        trading_economics_base_url=_get_str(news_providers_section, "trading_economics_base_url", "https://api.tradingeconomics.com"),
        forex_factory_base_url=_get_str(news_providers_section, "forex_factory_base_url", ""),
        forex_factory_api_key_env_var=_get_str(news_providers_section, "forex_factory_api_key_env_var", ""),
        request_timeout_seconds=_get_float(news_providers_section, "request_timeout_seconds", 10.0),
        max_retries=_get_int(news_providers_section, "max_retries", 2),
        retry_backoff_seconds=_get_float(news_providers_section, "retry_backoff_seconds", 1.0),
        stale_after_seconds=_get_float(news_providers_section, "stale_after_seconds", 900.0),
        recovery_health_check_count=_get_int(news_providers_section, "recovery_health_check_count", 3),
        cache_max_entries=_get_int(news_providers_section, "cache_max_entries", 200),
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

    # Relative to the config file's own folder by default -- so Titan Protocol
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
        compliance_daily_reset_hour_utc=compliance_daily_reset_hour_utc,
        news_config=news_config, news_feed_trusted=news_feed_trusted,
        news_provider_settings=news_provider_settings,
        reliability_config=reliability_config,
        log_dir=log_dir, log_level=log_level, state_dir=state_dir, data_dir=data_dir,
        api_key_env_var_name=api_key_env_var_name,
    )


def build_trading_profile(settings: "DeploymentSettings") -> TradingProfile:
    """Symbol-universe consistency (Final Release Hardening): the single
    shared place `start.py` and `health_check.py` both build the actual
    `TradingProfile` object, so the override-and-validate logic below
    exists exactly once, not duplicated across two files.

    Makes `bridge.allowed_symbols` the one canonical pair-universe
    source: every named profile's own `allowed_pairs` default
    (`_TRADEABLE_PAIR_UNIVERSE`, a strategy-eligibility union that predates
    this deployment layer) is overridden here to exactly the Bridge's
    configured symbols via `dataclasses.replace()` -- `titan_protocol/
    runtime/profiles.py` itself is never modified. This makes the
    "every profile pair must be Bridge-accepted" check below trivially
    true for every named profile today; it is kept anyway as fail-closed
    defense in depth, per this phase's explicit "do not silently skip an
    unsupported pair" requirement, and because it still means something
    real if `titan_protocol/runtime/profiles.py` ever changes upstream of
    this deployment layer.

    Raises `ConfigError` -- never silently skips -- for `selected_profile
    == "custom"` (a pre-existing, explicit dead end requiring a direct
    code edit; unchanged from before this phase) or if any profile pair
    is not in `bridge.allowed_symbols` after the override (today this can
    only happen via that same manual custom-profile code edit)."""
    if settings.selected_profile == "custom":
        raise ConfigError(
            "trading_profile.selected_profile is 'custom' -- a custom TradingProfile "
            "cannot be built from the config file alone (it needs an explicit "
            "allowed_pairs/allowed_strategies list). Edit deployment code to call "
            "titan_protocol.runtime.profiles.make_custom_profile(...) directly."
        )
    profile = _PROFILE_FACTORIES[settings.selected_profile]()
    profile = dataclasses.replace(profile, allowed_pairs=settings.bridge_config.allowed_symbols)
    unsupported = [pair for pair in profile.allowed_pairs if pair not in settings.bridge_config.allowed_symbols]
    if unsupported:
        raise ConfigError(
            f"Trading profile {profile.profile_id!r} allows pair(s) {unsupported} not present in "
            f"bridge.allowed_symbols ({list(settings.bridge_config.allowed_symbols)}). Startup refuses "
            "to silently skip an unsupported pair -- add it to bridge.allowed_symbols (configuring "
            "bridge.symbol_mapping if your broker uses a suffixed/prefixed symbol name) or remove it "
            "from the trading profile."
        )
    return profile


__all__ = [
    "DeploymentSettings", "NewsProviderSettings", "ConfigError", "load_settings",
    "generated_secret_path", "CONFIG_SCHEMA_VERSION", "build_trading_profile",
    "is_process_alive",
]
