"""Peg / policy event tracking (ADR-025 §1 "Peg / Policy Events").

A currency peg, emergency intervention, policy announcement, exchange
control, or unexpected intervention has no fixed timeout -- once
activated for a pair, it stays active until an explicit `clear()` call,
never inferred from elapsed time (ADR-025 Hard Rule 3). This mirrors
the shape of `phantom.bridge`'s `EmergencyStopState` (explicit
activate/deactivate, no auto-timeout) without importing or depending on
that frozen package -- the pattern is reused, not the code.
"""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Dict

from .models import PegPolicyEventType, PegPolicyStatus

_INACTIVE = PegPolicyStatus(active=False)


class PegPolicyRegistry:
    """Thread-safe pair -> `PegPolicyStatus`. A pair with no recorded
    event is implicitly inactive."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._status: Dict[str, PegPolicyStatus] = {}

    def activate(self, pair: str, event_type: PegPolicyEventType, reason: str, at: datetime) -> PegPolicyStatus:
        with self._lock:
            status = PegPolicyStatus(active=True, event_type=event_type, reason=reason, detected_at=at, cleared_at=None)
            self._status[pair] = status
            return status

    def clear(self, pair: str, at: datetime) -> PegPolicyStatus:
        """Explicit, manual clear -- the only way an active status ever
        becomes inactive again."""
        with self._lock:
            previous = self._status.get(pair, _INACTIVE)
            status = PegPolicyStatus(
                active=False, event_type=previous.event_type, reason=previous.reason,
                detected_at=previous.detected_at, cleared_at=at,
            )
            self._status[pair] = status
            return status

    def status_for(self, pair: str) -> PegPolicyStatus:
        with self._lock:
            return self._status.get(pair, _INACTIVE)


__all__ = ["PegPolicyRegistry"]
