"""Self-contained, validated, fail-closed configuration for calendar acquisition.

Kept separate from the core ``runtime.config.RuntimeConfig`` so the acquisition
layer adds NO surface to the heavily-tested producer/manager config. Precedence:
explicit env var > optional JSON file > documented non-safety default. Unknown JSON
keys FAIL CLOSED. There is NO silent provider selection — when acquisition is
enabled the provider must be named explicitly and must be known.

Credentials/API keys (none required by the selected source) must come from
environment variables only and are NEVER stored on this object, echoed to a health
file, logged, or written into a bundle (§8).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from .contract import AcquisitionError, Reason

KNOWN_PROVIDERS = ("forexfactory", "forexfactory_nextweek", "static")

_ENV = {
    "enabled": "SESSION_EDGE_CALENDAR_ENABLED",
    "provider": "SESSION_EDGE_CALENDAR_PROVIDER",
    "refresh_sec": "SESSION_EDGE_CALENDAR_REFRESH_SEC",
    "max_source_age_sec": "SESSION_EDGE_CALENDAR_MAX_SOURCE_AGE_SEC",
    "max_clock_skew_sec": "SESSION_EDGE_CALENDAR_MAX_CLOCK_SKEW_SEC",
    "output_file": "SESSION_EDGE_CALENDAR_OUTPUT_FILE",
    "news_file": "SESSION_EDGE_NEWS_FILE",           # default output target
    "health_file": "SESSION_EDGE_CALENDAR_HEALTH_FILE",
    "source_file": "SESSION_EDGE_CALENDAR_SOURCE_FILE",   # provider-specific (static)
    "static_trusted": "SESSION_EDGE_CALENDAR_STATIC_TRUSTED",
    "timeout_sec": "SESSION_EDGE_CALENDAR_TIMEOUT_SEC",
    "retries": "SESSION_EDGE_CALENDAR_RETRIES",
    "backoff_sec": "SESSION_EDGE_CALENDAR_BACKOFF_SEC",
    "log_file": "SESSION_EDGE_CALENDAR_LOG_FILE",
}
_CONFIG_PATH_ENV = "SESSION_EDGE_CONFIG"


@dataclass(frozen=True)
class CalendarConfig:
    enabled: bool
    provider: str
    output_file: str
    health_file: str
    refresh_sec: int = 1800
    max_source_age_sec: int = 21600         # 6h; source_as_of older than this = stale
    max_clock_skew_sec: int = 120
    source_file: str = None                 # required only for provider == "static"
    static_trusted: bool = False
    timeout_sec: float = 12.0
    retries: int = 2
    backoff_sec: float = 2.0
    log_file: str = None

    def public_dict(self):
        """Redacted, JSON-safe view (no secrets exist on this object by design)."""
        return {
            "enabled": self.enabled, "provider": self.provider,
            "output_file": self.output_file, "health_file": self.health_file,
            "refresh_sec": self.refresh_sec,
            "max_source_age_sec": self.max_source_age_sec,
            "max_clock_skew_sec": self.max_clock_skew_sec,
            "source_file": self.source_file, "static_trusted": self.static_trusted,
            "timeout_sec": self.timeout_sec, "retries": self.retries,
            "backoff_sec": self.backoff_sec,
        }


def _read_json_file(path):
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (FileNotFoundError, OSError) as exc:
        raise AcquisitionError(Reason.CONFIG_ERROR, {"unreadable": path, "error": repr(exc)})
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AcquisitionError(Reason.CONFIG_ERROR, {"bad_json": path, "error": repr(exc)})
    if not isinstance(obj, dict):
        raise AcquisitionError(Reason.CONFIG_ERROR, {"not_object": path})
    unknown = set(obj) - set(_ENV)
    if unknown:
        raise AcquisitionError(Reason.CONFIG_ERROR, {"unknown_keys": sorted(unknown)})
    return obj


def _as_int(key, v):
    try:
        return int(v)
    except (TypeError, ValueError):
        raise AcquisitionError(Reason.CONFIG_ERROR, {key: f"not an integer: {v!r}"})


def _as_float(key, v):
    try:
        return float(v)
    except (TypeError, ValueError):
        raise AcquisitionError(Reason.CONFIG_ERROR, {key: f"not a number: {v!r}"})


def _as_bool(key, v):
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in ("true", "1", "yes"):
        return True
    if s in ("false", "0", "no", ""):
        return False
    raise AcquisitionError(Reason.CONFIG_ERROR, {key: f"not a boolean: {v!r}"})


def load_calendar_config(env=None, config_path=None):
    """Build a validated :class:`CalendarConfig`. Fails closed on any invalid or
    unknown setting, or a missing required value once acquisition is enabled."""
    env = os.environ if env is None else env
    merged = {}
    path = config_path or env.get(_CONFIG_PATH_ENV)
    if path and Path(path).exists():
        merged.update(_read_json_file(path))
    for key, name in _ENV.items():
        if name in env and env[name] != "":
            merged[key] = env[name]

    enabled = _as_bool("enabled", merged.get("enabled", False))

    output_file = merged.get("output_file") or merged.get("news_file")
    provider = merged.get("provider")

    if enabled:
        if not provider:
            raise AcquisitionError(Reason.CONFIG_ERROR,
                                   {"missing": "provider (no silent selection)"})
        if provider not in KNOWN_PROVIDERS:
            raise AcquisitionError(Reason.CONFIG_ERROR,
                                   {"unknown_provider": provider,
                                    "known": list(KNOWN_PROVIDERS)})
        if not output_file:
            raise AcquisitionError(Reason.CONFIG_ERROR,
                                   {"missing": "output_file / news_file"})
        if provider == "static" and not merged.get("source_file"):
            raise AcquisitionError(Reason.CONFIG_ERROR,
                                   {"missing": "source_file (required for static)"})
    else:
        provider = provider or "static"          # inert when disabled
        output_file = output_file or ""

    refresh_sec = _as_int("refresh_sec", merged.get("refresh_sec", 1800))
    max_source_age = _as_int("max_source_age_sec", merged.get("max_source_age_sec", 21600))
    max_skew = _as_int("max_clock_skew_sec", merged.get("max_clock_skew_sec", 120))
    retries = _as_int("retries", merged.get("retries", 2))
    backoff = _as_float("backoff_sec", merged.get("backoff_sec", 2.0))
    timeout = _as_float("timeout_sec", merged.get("timeout_sec", 12.0))
    if refresh_sec <= 0 or max_source_age <= 0 or timeout <= 0:
        raise AcquisitionError(Reason.CONFIG_ERROR, {"positive_required":
                               ["refresh_sec", "max_source_age_sec", "timeout_sec"]})
    if max_skew < 0 or retries < 0 or backoff < 0:
        raise AcquisitionError(Reason.CONFIG_ERROR, {"non_negative_required":
                               ["max_clock_skew_sec", "retries", "backoff_sec"]})

    health_file = merged.get("health_file")
    if not health_file and output_file:
        health_file = str(Path(output_file).parent / "calendar_acq_status.json")

    return CalendarConfig(
        enabled=enabled, provider=provider, output_file=output_file or "",
        health_file=health_file or "", refresh_sec=refresh_sec,
        max_source_age_sec=max_source_age, max_clock_skew_sec=max_skew,
        source_file=(str(merged["source_file"]) if merged.get("source_file") else None),
        static_trusted=_as_bool("static_trusted", merged.get("static_trusted", False)),
        timeout_sec=timeout, retries=retries, backoff_sec=backoff,
        log_file=(str(merged["log_file"]) if merged.get("log_file") else None))
