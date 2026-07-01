"""Structured logging sink for scanner and ORB decisions.

Writes one JSON object per line (JSONL) so logs are append-only and trivially
parseable. Also retains the most recent records in memory for the API.
"""

from __future__ import annotations

import json
import os
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Deque, Dict, List, Optional


class LogSink:
    def __init__(self, path: Optional[str] = None, memory: int = 500):
        self.path = path
        self._lock = threading.Lock()
        self._recent: Deque[dict] = deque(maxlen=memory)
        if path:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

    def write(self, kind: str, record: dict) -> dict:
        entry = {"ts": datetime.now(timezone.utc).isoformat(), "kind": kind, **record}
        with self._lock:
            self._recent.append(entry)
            if self.path:
                with open(self.path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(entry, default=str) + "\n")
        return entry

    def log_scan(self, record: dict) -> dict:
        return self.write("scan", record)

    def log_orb(self, record: dict) -> dict:
        return self.write("orb", record)

    def recent(self, kind: Optional[str] = None, limit: int = 50) -> List[dict]:
        with self._lock:
            items = [e for e in self._recent if kind is None or e["kind"] == kind]
        return items[-limit:]
