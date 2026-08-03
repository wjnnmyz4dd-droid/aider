"""Production Logging (Phase 5) — rotating + JSON-structured logs, daily
archival, crash-dump generation, retention-policy enforcement.

Pure stdlib (`logging`, `gzip`, `json`) — no new dependency. Every
function here operates on caller-supplied directories, never a hardcoded
path, so tests run entirely against temporary directories with no risk to
a real deployment's logs.
"""

from __future__ import annotations

import gzip
import json
import logging
import logging.handlers
import os
import shutil
import traceback
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, sort_keys=True)


def configure_production_logging(
    logger_name: str,
    log_dir: str,
    max_bytes: int = 10_000_000,
    backup_count: int = 5,
    level: int = logging.INFO,
) -> logging.Logger:
    os.makedirs(log_dir, exist_ok=True)
    logger = logging.getLogger(logger_name)
    logger.setLevel(level)
    logger.handlers = [h for h in logger.handlers if not isinstance(h, logging.handlers.RotatingFileHandler)]
    handler = logging.handlers.RotatingFileHandler(
        os.path.join(log_dir, f"{logger_name}.log"), maxBytes=max_bytes, backupCount=backup_count
    )
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    return logger


def archive_daily_logs(log_dir: str, archive_dir: str, now: datetime) -> Tuple[str, ...]:
    """Gzip every non-empty `*.log` file in `log_dir` into `archive_dir`,
    timestamped by `now`'s date, then truncate (never delete) the source
    file so the running process's open file handle stays valid and
    tomorrow starts from an empty log."""
    os.makedirs(archive_dir, exist_ok=True)
    archived = []
    date_str = now.strftime("%Y-%m-%d")
    for name in sorted(os.listdir(log_dir)):
        if not name.endswith(".log"):
            continue
        src = os.path.join(log_dir, name)
        if not os.path.isfile(src) or os.path.getsize(src) == 0:
            continue
        dest = os.path.join(archive_dir, f"{name}.{date_str}.gz")
        with open(src, "rb") as src_file, gzip.open(dest, "wb") as dest_file:
            shutil.copyfileobj(src_file, dest_file)
        with open(src, "w", encoding="utf-8"):
            pass
        archived.append(dest)
    return tuple(archived)


def generate_crash_dump(
    component: str,
    exc: BaseException,
    dump_dir: str,
    now: datetime,
    context: Optional[Dict[str, Any]] = None,
) -> str:
    os.makedirs(dump_dir, exist_ok=True)
    timestamp = now.strftime("%Y%m%dT%H%M%SZ")
    path = os.path.join(dump_dir, f"{component}-{timestamp}.json")
    payload = {
        "component": component,
        "timestamp": now.isoformat(),
        "exception_type": type(exc).__name__,
        "exception_message": str(exc),
        "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
        "context": context or {},
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, sort_keys=True, indent=2)
    return path


def enforce_retention_policy(archive_dir: str, retention_days: int, now: datetime) -> Tuple[str, ...]:
    """Delete archived files whose modification time is older than
    `retention_days`; returns the paths removed."""
    if not os.path.isdir(archive_dir):
        return ()
    removed = []
    cutoff = now - timedelta(days=retention_days)
    for name in sorted(os.listdir(archive_dir)):
        path = os.path.join(archive_dir, name)
        if not os.path.isfile(path):
            continue
        mtime = datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc)
        if mtime < cutoff:
            os.remove(path)
            removed.append(path)
    return tuple(removed)


__all__ = [
    "JsonFormatter",
    "configure_production_logging",
    "archive_daily_logs",
    "generate_crash_dump",
    "enforce_retention_policy",
]
