"""Deterministic trace_id generation (ADR-013 §14).

Per ADR-013's Hard Rules, historical loading and replay production must
be byte-for-byte reproducible given identical inputs — so trace_id
generation must never depend on randomness or wall-clock time. A
trace_id here is a stable hash of the event's own identifying fields:
replaying the same tick/bar twice produces the same trace_id both times.
"""

from __future__ import annotations

import hashlib


def make_trace_id(*parts: str) -> str:
    """Return a deterministic trace_id derived from the given parts.

    Never random, never wall-clock dependent — the same parts always
    produce the same trace_id.
    """
    canonical = "|".join(parts)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]
