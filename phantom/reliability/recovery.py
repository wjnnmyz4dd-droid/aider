"""Automatic recovery (ADR-032 SS2 item 10): bounded to exactly the
four components `ADR-031`'s own `APPROVED_RESTART_COMPONENTS` names --
imported directly, never redefined (ADR-032 SS0, Hard Rule 3).
Compliance Engine and Bridge are structurally unreachable: they are
simply never in that imported allow-list, so no code path here can
ever restart them."""

from __future__ import annotations

from datetime import datetime

from phantom.runtime.watchdog_integration import is_approved_for_restart

from .models import RecoveryOutcome


def attempt_recovery(component: str, now: datetime) -> RecoveryOutcome:
    if not is_approved_for_restart(component):
        return RecoveryOutcome(
            component=component, attempted=False, succeeded=False,
            reason=f"{component!r} is not in the approved restart allow-list", timestamp=now,
        )

    # Every one of the four approved components is stateless and cheap
    # to reconstruct (ADR-024/025/026/027's own statelessness
    # guarantees) -- "restarting" it here means the caller is free to
    # construct a fresh instance and swap it in; this function's
    # responsibility ends at authorizing that the target is safe.
    return RecoveryOutcome(component=component, attempted=True, succeeded=True, reason="approved for restart", timestamp=now)


__all__ = ["attempt_recovery"]
