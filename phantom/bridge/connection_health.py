"""Connection health monitoring for the PhantomBridgeEA bridge.

Deliberately its own file, distinct from `command_queue.py`'s
emergency-stop state: this tracks *liveness* (has the EA proven it is
still there recently), the command queue tracks *authorization to
trade* (has an operator halted issuance). The two must never be merged
into one undifferentiated flag -- a live-but-halted bridge and a
not-yet-heard-from bridge are different facts an operator needs to
distinguish.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Optional

from .config import BridgeConfig


class ConnectionHealth:
    def __init__(self, config: BridgeConfig, clock: Callable[[], datetime]) -> None:
        self._config = config
        self._clock = clock
        self._last_heartbeat_at: Optional[datetime] = None

    def record_heartbeat(self, at: datetime) -> None:
        self._last_heartbeat_at = at

    @property
    def last_heartbeat_at(self) -> Optional[datetime]:
        return self._last_heartbeat_at

    def is_ready(self) -> bool:
        """`True` only if a heartbeat has been recorded and it is within
        the configured timeout -- fail-closed by default, before any
        heartbeat is ever received."""
        if self._last_heartbeat_at is None:
            return False
        elapsed = (self._clock() - self._last_heartbeat_at).total_seconds()
        return elapsed <= self._config.heartbeat_timeout_seconds

    def is_fail_closed(self) -> bool:
        return not self.is_ready()

    def reset(self) -> None:
        self._last_heartbeat_at = None


__all__ = ["ConnectionHealth"]
