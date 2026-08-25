"""Single-instance lock for the acquisition service -- BACKWARD-COMPAT SHIM.

The single-instance guarantee now lives in :mod:`forex_swing_orb.newsfeed.
acquisition_lock`, a thin identity over the ONE canonical OS process-lock primitive
(:class:`forex_swing_orb.bridge.process_lock.ProcessLock`) shared by the producer and
manager. That primitive proves ownership with a LIVE, kernel-held exclusive lock,
so a dead owner's lock file NEVER blocks startup (self-healing) and a live owner is
NEVER displaced -- fixing the Windows defect where ``os.kill(pid, 0)`` on a dead pid
raised ``OSError`` (not ``ProcessLookupError``) and the old PID-file reclaim treated
the dead owner as alive, refusing startup forever.

This module remains ONLY to preserve the historical import surface
(``SingleInstanceLock`` / ``LockHeld``). Both delegate to the canonical mechanism;
there is exactly one locking algorithm in the codebase. Prefer importing from
``acquisition_lock`` directly in new code.
"""

from __future__ import annotations

from .acquisition_lock import (NewsAcquisitionLock as SingleInstanceLock,
                               NewsAcquisitionLockHeld as LockHeld)

__all__ = ["SingleInstanceLock", "LockHeld"]
