"""Connection health monitoring for the TitanProtocolEA bridge.

Deliberately its own file, distinct from `command_queue.py`'s
emergency-stop state: this tracks *liveness* (has the EA proven it is
still there recently), the command queue tracks *authorization to
trade* (has an operator halted issuance). The two must never be merged
into one undifferentiated flag -- a live-but-halted bridge and a
not-yet-heard-from bridge are different facts an operator needs to
distinguish.
"""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Callable, Optional

from .config import BridgeConfig


class ConnectionHealth:
    """Thread safety: reached both from `POST /bridge/heartbeat`
    (`record_heartbeat`) and from every command-submission/poll path
    (`is_ready`) via `titan_protocol/bridge/server.py`'s
    `http.server.ThreadingHTTPServer` -- one thread per request -- so
    reads and writes of `_last_heartbeat_at` can overlap across
    threads. A single non-reentrant lock guards every access; the
    shared read logic lives in `_is_ready_locked`, called only while
    the lock is already held, so `is_fail_closed`'s call into it never
    needs a second acquisition and no `RLock` is required."""

    def __init__(self, config: BridgeConfig, clock: Callable[[], datetime]) -> None:
        self._config = config
        self._clock = clock
        self._lock = threading.Lock()
        self._last_heartbeat_at: Optional[datetime] = None

    def record_heartbeat(self, at: datetime) -> None:
        with self._lock:
            self._last_heartbeat_at = at

    @property
    def last_heartbeat_at(self) -> Optional[datetime]:
        with self._lock:
            return self._last_heartbeat_at

    def is_ready(self) -> bool:
        """`True` only if a heartbeat has been recorded and it is within
        the configured timeout -- fail-closed by default, before any
        heartbeat is ever received."""
        with self._lock:
            return self._is_ready_locked()

    def is_fail_closed(self) -> bool:
        with self._lock:
            return not self._is_ready_locked()

    def _is_ready_locked(self) -> bool:
        """Same check `is_ready()` exposes publicly, factored out so
        `is_fail_closed()` can reuse it without a second lock
        acquisition. Callers must already hold `self._lock`."""
        if self._last_heartbeat_at is None:
            return False
        elapsed = (self._clock() - self._last_heartbeat_at).total_seconds()
        return elapsed <= self._config.heartbeat_timeout_seconds

    def reset(self) -> None:
        with self._lock:
            self._last_heartbeat_at = None


__all__ = ["ConnectionHealth"]
