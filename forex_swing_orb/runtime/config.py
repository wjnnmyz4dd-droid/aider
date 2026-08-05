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
        mt5_server=(str(merged["mt5_server"]) if merged.get("mt5_server") else None))


def _parse_symbols(raw):
    if isinstance(raw, (list, tuple)):
        items = [str(x).strip() for x in raw]
    else:
        items = [p.strip() for p in str(raw).split(",")]
    return tuple(s for s in items if s)


def password_from_env(env=None):
    """Return the MT5 password from the environment (secret; never stored on the
    config, never written to a health file). Empty/absent -> None."""
    env = os.environ if env is None else env
    pw = env.get(_PASSWORD_ENV)
    return pw if pw else None
