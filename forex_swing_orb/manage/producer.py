"""Manage-channel producer (Phase 7B-B): atomic write of a manage instruction."""

from __future__ import annotations

from ..bridge import serialize
from ..bridge.atomic import atomic_write_text
from . import contract, paths as P


class ManageProducerError(ValueError):
    pass


def write_manage_instruction(mpaths, instruction, now, audit=None):
    """Write one validated manage instruction atomically to manage/outbox/pending."""
    ok, reason = contract.validate_instruction(instruction)
    if not ok:
        raise ManageProducerError(f"invalid manage instruction: {reason}")
    manage_id = instruction["manage_id"]
    dest = mpaths.pending / P.instruction_name(manage_id)
    atomic_write_text(dest, serialize.dumps(instruction))
    if audit is not None:
        audit.emit({"kind": "manage_produce", "timestamp": serialize.iso_utc(now),
                    "manage_id": manage_id, "signal_id": instruction["signal_id"],
                    "ticket": instruction["ticket"], "action": instruction["action"],
                    "outcome": "WRITTEN"})
    return dest
