"""Producer side (spec §5): write deterministic instruction files atomically.

The Session Edge strategy engine is the producer: it emits instruction dicts
(schema_version 1, incl. signal_id/strategy_id/risk_fraction/news_eligibility).
This module adds the transport ``integrity_digest`` and writes them atomically
into ``outbox/pending/``. No broker logic, no execution logic, no networking.
"""

from __future__ import annotations

from . import serialize
from .contract import REQUIRED_INSTRUCTION_FIELDS
from .atomic import atomic_write_text
from .paths import instruction_name


class ProducerError(ValueError):
    pass


def write_instruction(paths, instruction, now, audit=None):
    """Write one instruction to ``outbox/pending/<signal_id>.json`` atomically.

    ``instruction`` is the engine's instruction dict (without integrity_digest).
    Returns the written Path. Raises ProducerError on a malformed producer input
    (fail fast on our own side — the producer is trusted but not blindly)."""
    if not isinstance(instruction, dict):
        raise ProducerError("instruction must be a dict")
    signal_id = instruction.get("signal_id")
    from .paths import SIGNAL_ID_RE
    if not (isinstance(signal_id, str) and SIGNAL_ID_RE.match(signal_id)):
        raise ProducerError("instruction.signal_id must be 16 lowercase hex chars")
    record = serialize.with_integrity_digest(instruction)
    for field in REQUIRED_INSTRUCTION_FIELDS:
        if field not in record:
            raise ProducerError(f"instruction missing required field: {field}")
    dest = paths.pending / instruction_name(signal_id)
    atomic_write_text(dest, serialize.dumps(record))
    if audit is not None:
        audit.emit(serialize.iso_utc(now), "produce", "WRITTEN", signal_id=signal_id,
                   detail={"path": dest.name})
    return dest


def write_instructions(paths, instructions, now, audit=None):
    """Write many instructions (e.g. an engine run's ``instructions[symbol]``)."""
    return [write_instruction(paths, ins, now, audit=audit) for ins in instructions]
