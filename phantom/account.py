"""Live account snapshot feed (MT5 / broker).

Holds the most recent account snapshot and answers freshness questions. It does
NOT execute or size; it is a data holder consulted by compliance/risk/sizing.

Staleness is measured from the snapshot's own ``timestamp`` (how old the account
data is). The feed is *inactive* until the first snapshot arrives — in that state
nothing is considered stale, preserving advisory-only behaviour. Once active, a
snapshot older than the TTL marks the feed stale and sizing refuses.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


def parse_timestamp(s: Optional[str]) -> datetime:
    """Parse an ISO-8601 timestamp; fall back to now (UTC) on any problem."""
    if not s:
        return datetime.now(timezone.utc)
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


@dataclass
class AccountSnapshot:
    balance: float
    equity: float
    margin: float
    free_margin: float
    positions_open: int
    timestamp: datetime

    def as_dict(self) -> dict:
        return {
            "balance": self.balance,
            "equity": self.equity,
            "margin": self.margin,
            "free_margin": self.free_margin,
            "positions_open": self.positions_open,
            "timestamp": self.timestamp.isoformat(),
        }


class AccountFeed:
    def __init__(self, ttl_seconds: int = 60):
        self.ttl_seconds = ttl_seconds
        self._lock = threading.Lock()
        self._last: Optional[AccountSnapshot] = None

    def update(self, snap: AccountSnapshot) -> None:
        with self._lock:
            self._last = snap

    def last(self) -> Optional[AccountSnapshot]:
        with self._lock:
            return self._last

    def is_active(self) -> bool:
        with self._lock:
            return self._last is not None

    def age_seconds(self, now: Optional[datetime] = None) -> Optional[float]:
        now = now or datetime.now(timezone.utc)
        with self._lock:
            if self._last is None:
                return None
            return (now - self._last.timestamp).total_seconds()

    def is_stale(self, now: Optional[datetime] = None) -> bool:
        age = self.age_seconds(now)
        return age is not None and age > self.ttl_seconds
