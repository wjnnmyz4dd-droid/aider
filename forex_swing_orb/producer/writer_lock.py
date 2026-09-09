"""Producer single-writer authority lock (F-3).

Only ONE producer may hold entry-authorization writer authority for a given entry
bridge at a time. A second producer targeting the same bridge MUST fail closed
BEFORE it evaluates a market, authorizes a candidate, or writes an instruction.

Authority domain: the ENTRY BRIDGE ROOT (canonicalized). All producers that write
entry instructions to the same effective bridge share one lock; producers on
genuinely separate bridge roots are independent.

This module is a thin PRODUCER IDENTITY over the ONE canonical process-lock
primitive :class:`forex_swing_orb.bridge.process_lock.ProcessLock` (the same
primitive the manager uses, with a distinct lock name — so producer and manager
never block one another). It does not reimplement the locking algorithm. The
historical public names (``ProducerWriterLock`` / ``ProducerLock*`` / ``canonical_domain``)
are preserved; the exceptions are the canonical process-lock exceptions.
"""

from __future__ import annotations

from ..bridge.process_lock import (ProcessLock, ProcessLockError, ProcessLockHeld,
                                    ProcessLockUnavailable, canonical_domain)

# Backward-compatible producer-facing names (the canonical exceptions, aliased so
# existing ``except ProducerLockHeld`` sites and imports keep working unchanged).
ProducerLockError = ProcessLockError
ProducerLockHeld = ProcessLockHeld
ProducerLockUnavailable = ProcessLockUnavailable

_LOCK_NAME = ".producer_writer.lock"   # dot-file at the bridge root; never an instruction

__all__ = ["ProducerWriterLock", "ProducerLockError", "ProducerLockHeld",
           "ProducerLockUnavailable", "canonical_domain"]


class ProducerWriterLock(ProcessLock):
    """OS-held exclusive single-writer lock, keyed to the entry-bridge root.

    Acquire ONCE at producer startup and hold for the whole authoritative lifetime;
    release on graceful shutdown (a crash releases it automatically at the OS
    level). Thin identity over the canonical :class:`ProcessLock`."""

    def __init__(self, bridge_root):
        super().__init__(bridge_root, lock_name=_LOCK_NAME)
