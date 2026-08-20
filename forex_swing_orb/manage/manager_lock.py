"""Manager single-owner authority lock (F1).

At most ONE manager process may own management authority for a Session Edge
management domain at a time. A second manager MUST fail closed BEFORE it evaluates
positions, runs orphan recovery, reconciles, emits a manage instruction, or writes
its health artifact.

This is a thin MANAGER IDENTITY over the ONE canonical process-lock primitive
:class:`forex_swing_orb.bridge.process_lock.ProcessLock` — the SAME primitive the
producer uses (``producer/writer_lock.py``), with a DISTINCT lock name so a producer
and a manager on the same bridge domain never block one another while two managers
do. It adds NO management-decision, bridge, broker-action, or reconciliation
authority: PositionManager remains the sole management decision owner. This module
only proves process ownership.
"""

from __future__ import annotations

from ..bridge.process_lock import (ProcessLock, ProcessLockError, ProcessLockHeld,
                                    ProcessLockUnavailable, canonical_domain)

# Manager-facing names (the canonical exceptions, aliased for readable call sites).
ManagerLockError = ProcessLockError
ManagerLockHeld = ProcessLockHeld
ManagerLockUnavailable = ProcessLockUnavailable

_LOCK_NAME = ".manager.lock"           # distinct from the producer's .producer_writer.lock

__all__ = ["ManagerLock", "ManagerLockError", "ManagerLockHeld",
           "ManagerLockUnavailable", "canonical_domain"]


class ManagerLock(ProcessLock):
    """OS-held exclusive single-owner lock, keyed to the management domain root.

    Acquire ONCE at manager startup (before any management work) and hold for the
    whole authoritative lifetime; release on graceful shutdown (a crash releases it
    automatically at the OS level). Thin identity over the canonical
    :class:`ProcessLock`."""

    def __init__(self, domain_root):
        super().__init__(domain_root, lock_name=_LOCK_NAME)
