"""Validated runtime configuration (Phase 8D) — fail-closed env/JSON loader.

The producer and manager production entry points build every live dependency from
this configuration. Loading is STRICT and FAILS CLOSED: any missing or invalid
required field raises :class:`ConfigError` — there are no silent defaults for
safety-relevant values (bridge root, symbols, FTMO profile, initial balance,
reset timezone, news file). Secrets (the MT5 password) are never stored on the
config object and never echoed to a health/status file.

Precedence for each key: explicit env var > JSON config file > (only for a small
set of non-safety operational knobs) a documented default. No networking.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from ..compliance import mapping
from ..compliance.contract import _tz_loadable


class ConfigError(RuntimeError):
    """Raised when the runtime configuration is missing or invalid. Fail closed."""


# canonical key -> environment variable name
_ENV = {
    "bridge_root": "SESSION_EDGE_BRIDGE_ROOT",
    "runtime_dir": "SESSION_EDGE_RUNTIME_DIR",
    "symbols": "SESSION_EDGE_SYMBOLS",
    "symbol_suffix": "SESSION_EDGE_SYMBOL_SUFFIX",
    "initial_balance": "SESSION_EDGE_INITIAL_BALANCE",
    "account_currency": "SESSION_EDGE_ACCOUNT_CURRENCY",
    "daily_loss_pct": "SESSION_EDGE_DAILY_LOSS_PCT",
    "maximum_loss_pct": "SESSION_EDGE_MAX_LOSS_PCT",
    "reset_timezone": "SESSION_EDGE_RESET_TIMEZONE",
    "ftmo_rule_source": "SESSION_EDGE_FTMO_RULE_SOURCE",
    "ftmo_rule_source_verified_at": "SESSION_EDGE_FTMO_RULE_VERIFIED_AT",
    "ftmo_profile_verified": "SESSION_EDGE_FTMO_PROFILE_VERIFIED",
    "news_file": "SESSION_EDGE_NEWS_FILE",
    "cadence_sec": "SESSION_EDGE_CADENCE_SEC",
    "mt5_terminal_path": "SESSION_EDGE_MT5_TERMINAL_PATH",
    "mt5_login": "SESSION_EDGE_MT5_LOGIN",
    "mt5_server": "SESSION_EDGE_MT5_SERVER",
    # -- Phase 9A: canonical session / overlap framework -------------------
    "enabled_sessions": "SESSION_EDGE_ENABLED_SESSIONS",
    "enabled_overlaps": "SESSION_EDGE_ENABLED_OVERLAPS",
    "overlap_mode": "SESSION_EDGE_OVERLAP_MODE",
    "session_priority": "SESSION_EDGE_SESSION_PRIORITY",
    "friday_close_min": "SESSION_EDGE_FRIDAY_CLOSE_MIN",
    "sunday_open_min": "SESSION_EDGE_SUNDAY_OPEN_MIN",
    "strategy_session_policy": "SESSION_EDGE_STRATEGY_SESSION_POLICY",
    # -- Phase 9A: advisory shadow layer ----------------------------------
    "advisory_enabled": "SESSION_EDGE_ADVISORY_ENABLED",
    "advisory_mode": "SESSION_EDGE_ADVISORY_MODE",
    "advisory_provider": "SESSION_EDGE_ADVISORY_PROVIDER",
    "advisory_output_path": "SESSION_EDGE_ADVISORY_OUTPUT_PATH",
    # -- user risk configuration (front-end only; PR-3J stays the sole sizer) ---
    "risk_profile": "SESSION_EDGE_RISK_PROFILE",
    "risk_fraction": "SESSION_EDGE_RISK_FRACTION",
    "sizing_mode": "SESSION_EDGE_SIZING_MODE",
}
_CONFIG_PATH_ENV = "SESSION_EDGE_CONFIG"
_PASSWORD_ENV = "SESSION_EDGE_MT5_PASSWORD"     # secret; never stored on the config


@dataclass(frozen=True)
class RuntimeConfig:
    bridge_root: str
    runtime_dir: str
    symbols: tuple
    initial_balance: float
    account_currency: str
    ftmo_rule_source: str
    ftmo_rule_source_verified_at: str
    ftmo_profile_verified: bool
    news_file: str
    symbol_suffix: str = ""
    daily_loss_pct: float = 0.05        # FTMO 2-Step: 5% of INITIAL capital
    maximum_loss_pct: float = 0.10      # FTMO 2-Step: static 10% of INITIAL capital
    reset_timezone: str = "Europe/Prague"
    cadence_sec: int = 900              # M15
    mt5_terminal_path: str = None
    mt5_login: int = None
    mt5_server: str = None
    # -- Phase 9A: canonical session framework (validated in _validate) ------
    enabled_sessions: tuple = ()
    enabled_overlaps: tuple = ()
    overlap_mode: str = "ALLOW"
    session_priority: tuple = ("SYDNEY", "TOKYO", "LONDON", "NEW_YORK")
    friday_close_min: int = None
    sunday_open_min: int = None
    strategy_session_policy: str = "FAIL_CLOSED"
    # -- Phase 9A: advisory shadow layer ------------------------------------
    advisory_enabled: bool = False
    advisory_mode: str = "SHADOW_ONLY"
    advisory_provider: str = "mock"
    advisory_output_path_override: str = None
    # -- user risk configuration (front-end only; PR-3J is the sole sizer) ----
    # risk_profile/sizing_mode are informational (reporting); risk_fraction is the
    # resolved per-trade risk cap the producer applies as the sizing POLICY input.
    # None -> no override (use the engine instruction's risk_fraction; backward
    # compatible). Always <= max_risk_per_trade_pct (validated + re-enforced by the
    # compliance RISK gate).
    risk_profile: str = "MODERATE"
    risk_fraction: float = None
    sizing_mode: str = "ADAPTIVE"

    # -- canonical session model (single source of truth) -------------------
    def session_model(self):
        from ..session.model import SessionModel
        return SessionModel(
            enabled_sessions=tuple(self.enabled_sessions),
            enabled_overlaps=tuple(self.enabled_overlaps),
            overlap_mode=self.overlap_mode,
            friday_close_policy=self.friday_close_min,
            sunday_open_policy=self.sunday_open_min,
            session_priority=tuple(self.session_priority),
            strategy_session_policy=self.strategy_session_policy).validate()

    @property
    def advisory_output_path(self):
        return self.advisory_output_path_override or str(self._rt / "advisory_shadow.jsonl")

    @property
    def session_status_path(self):
        return str(self._rt / "session_status.json")

    # -- derived runtime file locations (all under runtime_dir) --------------
    @property
    def _rt(self):
        return Path(self.runtime_dir)

    @property
    def anchor_path(self):
        return str(self._rt / "daily_anchor.json")

    @property
    def producer_state_path(self):
        return str(self._rt / "producer_state.json")

    @property
    def runner_audit_path(self):
        return str(self._rt / "runner_audit.jsonl")

    @property
    def compliance_audit_path(self):
        return str(self._rt / "compliance_audit.jsonl")

    @property
    def producer_health_path(self):
        return str(self._rt / "producer_health.json")

    @property
    def compliance_status_path(self):
        return str(self._rt / "compliance_status.json")

    @property
    def producer_log_path(self):
        return str(self._rt / "producer.log")

    @property
    def manager_health_path(self):
        return str(self._rt / "manager_health.json")

    @property
    def pm_audit_path(self):
        return str(self._rt / "pm_audit.jsonl")

    @property
    def manager_log_path(self):
        return str(self._rt / "manager.log")

    def public_dict(self):
        """A redacted, JSON-safe view for health/status files. Never includes any
        secret (the MT5 password is never stored on this object)."""
        return {
            "bridge_root": self.bridge_root,
            "runtime_dir": self.runtime_dir,
            "symbols": list(self.symbols),
            "symbol_suffix": self.symbol_suffix,
            "account_currency": self.account_currency,
            "initial_balance": self.initial_balance,
            "daily_loss_pct": self.daily_loss_pct,
            "maximum_loss_pct": self.maximum_loss_pct,
            "reset_timezone": self.reset_timezone,
            "ftmo_rule_source": self.ftmo_rule_source,
            "ftmo_rule_source_verified_at": self.ftmo_rule_source_verified_at,
            "ftmo_profile_verified": self.ftmo_profile_verified,
            "news_file": self.news_file,
            "cadence_sec": self.cadence_sec,
            "mt5_server": self.mt5_server,
            "risk_profile": self.risk_profile,
            "risk_fraction": self.risk_fraction,
            "sizing_mode": self.sizing_mode,
            # deliberately omitted: mt5_login (identity), password (secret)
        }

    def ensure_runtime_dir(self):
        Path(self.runtime_dir).mkdir(parents=True, exist_ok=True)
        return self


# --------------------------------------------------------------------------- #
# Loading + validation (fail closed)
# --------------------------------------------------------------------------- #
def load_config(env=None, config_path=None):
    """Build a validated :class:`RuntimeConfig`. Merges an optional JSON file with
    environment overrides, then validates every required field. Fails closed."""
    env = os.environ if env is None else env
    merged = {}

    path = config_path or env.get(_CONFIG_PATH_ENV)
    if path:
        merged.update(_read_json_file(path))

    for key, name in _ENV.items():
        if name in env and env[name] != "":
            merged[key] = env[name]

    return _validate(merged)


def _read_json_file(path):
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (FileNotFoundError, OSError) as exc:
        raise ConfigError(f"config file unreadable: {path} ({exc})")
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"config file is not valid JSON: {path} ({exc})")
    if not isinstance(obj, dict):
        raise ConfigError(f"config file must be a JSON object: {path}")
    unknown = set(obj) - set(_ENV)
    if unknown:
        raise ConfigError(f"unknown config keys: {sorted(unknown)}")
    return obj


def _require(merged, key):
    v = merged.get(key)
    if v is None or (isinstance(v, str) and v.strip() == ""):
        raise ConfigError(f"missing required config: {key} (env {_ENV[key]})")
    return v


def _as_float(key, v):
    try:
        return float(v)
    except (TypeError, ValueError):
        raise ConfigError(f"{key} must be a number, got {v!r}")


def _as_int(key, v):
    try:
        return int(v)
    except (TypeError, ValueError):
        raise ConfigError(f"{key} must be an integer, got {v!r}")


def _as_bool(key, v):
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in ("true", "1", "yes"):
        return True
    if s in ("false", "0", "no", ""):
        return False
    raise ConfigError(f"{key} must be a boolean, got {v!r}")


def _validate(merged):
    bridge_root = str(_require(merged, "bridge_root"))
    runtime_dir = str(_require(merged, "runtime_dir"))

    raw_symbols = _require(merged, "symbols")
    symbols = _parse_symbols(raw_symbols)
    if not symbols:
        raise ConfigError("symbols must list at least one Forex pair")
    for s in symbols:
        if not mapping.is_forex_symbol(s):
            raise ConfigError(f"symbol not Forex (FTMO-forex-only): {s!r}")

    initial_balance = _as_float("initial_balance", _require(merged, "initial_balance"))
    if initial_balance <= 0:
        raise ConfigError("initial_balance must be > 0")

    account_currency = str(_require(merged, "account_currency"))
    rule_source = str(_require(merged, "ftmo_rule_source"))
    rule_verified_at = str(_require(merged, "ftmo_rule_source_verified_at"))

    profile_verified = _as_bool("ftmo_profile_verified",
                                _require(merged, "ftmo_profile_verified"))
    if not profile_verified:
        # never silently proceed unverified; the operator must attest explicitly
        raise ConfigError("ftmo_profile_verified must be true (attest the verified "
                           "FTMO 2-Step Swing profile before running)")

    reset_timezone = str(merged.get("reset_timezone") or "Europe/Prague")
    if not _tz_loadable(reset_timezone):
        raise ConfigError(f"reset_timezone not loadable: {reset_timezone!r}")

    news_file = str(_require(merged, "news_file"))

    daily_loss_pct = _as_float("daily_loss_pct", merged.get("daily_loss_pct", 0.05))
    maximum_loss_pct = _as_float("maximum_loss_pct", merged.get("maximum_loss_pct", 0.10))
    if not (0 < daily_loss_pct < 1) or not (0 < maximum_loss_pct < 1):
        raise ConfigError("loss percentages must be fractions in (0, 1)")

    cadence_sec = _as_int("cadence_sec", merged.get("cadence_sec", 900))
    if cadence_sec <= 0:
        raise ConfigError("cadence_sec must be > 0")

    symbol_suffix = str(merged.get("symbol_suffix") or "")

    mt5_login = merged.get("mt5_login")
    mt5_login = _as_int("mt5_login", mt5_login) if mt5_login not in (None, "") else None

    # -- Phase 9A/PR-4A: canonical session framework (fail closed) ----------
    from ..session.model import SessionModel, SessionConfigError, OverlapMode
    # Default remains LONDON when the operator does not select sessions (§13/§15).
    _raw_sessions = merged.get("enabled_sessions")
    enabled_sessions = (_parse_list(_raw_sessions) if _raw_sessions not in (None, "", ())
                        else ("LONDON",))
    # PR-4A: 'ALL' is a convenience that expands deterministically to every supported
    # session. Expanded here (single authority) so launcher/config/env all agree.
    if "ALL" in enabled_sessions:
        from ..session.profiles import SUPPORTED_SESSION_IDS
        enabled_sessions = SUPPORTED_SESSION_IDS
    enabled_overlaps = _parse_list(merged.get("enabled_overlaps", ()))
    overlap_mode = str(_require(merged, "overlap_mode")).upper()
    if overlap_mode not in OverlapMode.ALL:
        raise ConfigError(f"overlap_mode must be one of {OverlapMode.ALL}, got {overlap_mode!r}")
    session_priority = _parse_list(merged.get("session_priority", ())) or \
        ("SYDNEY", "TOKYO", "LONDON", "NEW_YORK")
    friday_close_min = (_as_int("friday_close_min", merged["friday_close_min"])
                        if merged.get("friday_close_min") not in (None, "") else None)
    sunday_open_min = (_as_int("sunday_open_min", merged["sunday_open_min"])
                       if merged.get("sunday_open_min") not in (None, "") else None)
    strategy_session_policy = str(merged.get("strategy_session_policy") or "FAIL_CLOSED").upper()
    try:                                                # fail closed on invalid combos
        SessionModel(enabled_sessions=enabled_sessions, enabled_overlaps=enabled_overlaps,
                     overlap_mode=overlap_mode, friday_close_policy=friday_close_min,
                     sunday_open_policy=sunday_open_min, session_priority=session_priority,
                     strategy_session_policy=strategy_session_policy).validate()
    except SessionConfigError as exc:
        raise ConfigError(f"invalid session configuration: {exc}")

    # -- Phase 9A: advisory shadow (SHADOW_ONLY only) -----------------------
    advisory_enabled = _as_bool("advisory_enabled", merged.get("advisory_enabled", False))
    advisory_mode = str(merged.get("advisory_mode") or "SHADOW_ONLY").upper()
    if advisory_mode != "SHADOW_ONLY":
        raise ConfigError("advisory_mode must be SHADOW_ONLY in this phase")
    advisory_provider = str(merged.get("advisory_provider") or "mock")

    # -- user risk configuration (front-end only; PR-3J stays the sole sizer) --
    # risk_profile/sizing_mode are informational. risk_fraction, if provided, is the
    # resolved per-trade risk cap; it MUST be a finite fraction in (0, ceiling]. The
    # compliance RISK gate re-enforces the same ceiling at runtime (defense in depth).
    from .risk_profile import CEILING_RISK_FRACTION
    risk_profile = str(merged.get("risk_profile") or "MODERATE").upper()
    sizing_mode = str(merged.get("sizing_mode") or "ADAPTIVE").upper()
    risk_fraction = merged.get("risk_fraction")
    if risk_fraction in (None, ""):
        risk_fraction = None
    else:
        risk_fraction = _as_float("risk_fraction", risk_fraction)
        if not (0 < risk_fraction <= CEILING_RISK_FRACTION + 1e-12):
            raise ConfigError(
                f"risk_fraction must be in (0, {CEILING_RISK_FRACTION}] "
                f"(max_risk_per_trade_pct), got {risk_fraction}")

    return RuntimeConfig(
        bridge_root=bridge_root, runtime_dir=runtime_dir, symbols=symbols,
        initial_balance=initial_balance, account_currency=account_currency,
        ftmo_rule_source=rule_source, ftmo_rule_source_verified_at=rule_verified_at,
        ftmo_profile_verified=profile_verified, news_file=news_file,
        symbol_suffix=symbol_suffix, daily_loss_pct=daily_loss_pct,
        maximum_loss_pct=maximum_loss_pct, reset_timezone=reset_timezone,
        cadence_sec=cadence_sec,
        mt5_terminal_path=(str(merged["mt5_terminal_path"])
                           if merged.get("mt5_terminal_path") else None),
        mt5_login=mt5_login,
        mt5_server=(str(merged["mt5_server"]) if merged.get("mt5_server") else None),
        enabled_sessions=enabled_sessions, enabled_overlaps=enabled_overlaps,
        overlap_mode=overlap_mode, session_priority=session_priority,
        friday_close_min=friday_close_min, sunday_open_min=sunday_open_min,
        strategy_session_policy=strategy_session_policy,
        advisory_enabled=advisory_enabled, advisory_mode=advisory_mode,
        advisory_provider=advisory_provider,
        advisory_output_path_override=(str(merged["advisory_output_path"])
                                       if merged.get("advisory_output_path") else None),
        risk_profile=risk_profile, risk_fraction=risk_fraction, sizing_mode=sizing_mode)


def _parse_symbols(raw):
    if isinstance(raw, (list, tuple)):
        items = [str(x).strip() for x in raw]
    else:
        items = [p.strip() for p in str(raw).split(",")]
    return tuple(s for s in items if s)


def _parse_list(raw):
    """Parse a comma-separated string / list into an upper-cased tuple (session and
    overlap ids). Empty -> ()."""
    if raw in (None, ""):
        return ()
    if isinstance(raw, (list, tuple)):
        items = [str(x).strip().upper() for x in raw]
    else:
        items = [p.strip().upper() for p in str(raw).split(",")]
    return tuple(s for s in items if s)


def password_from_env(env=None):
    """Return the MT5 password from the environment (secret; never stored on the
    config, never written to a health file). Empty/absent -> None."""
    env = os.environ if env is None else env
    pw = env.get(_PASSWORD_ENV)
    return pw if pw else None
