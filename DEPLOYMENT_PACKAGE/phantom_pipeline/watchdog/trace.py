"""Deterministic health-event trace_id generation (ADR-011 §5, §12).

This is a deliberate, minor duplication of `data_pipeline.trace.
make_trace_id`'s three lines — not an oversight. The Watchdog is built as
a fully standalone package with zero cross-package imports into any other
`phantom_pipeline` subpackage (explicit, user-confirmed constraint), so it
cannot import `data_pipeline.trace` even for a shared utility this small.
The health-event `trace_id` produced here is also a logically distinct
chain from the trading `trace_id` chain `data_pipeline.trace` establishes
(ADR-011 §5: "distinct from a trading trace_id chain") — reusing the same
function across two conceptually separate chains would blur that
distinction even if the import constraint didn't already forbid it.
"""

from __future__ import annotations

import hashlib


def make_health_trace_id(*parts: str) -> str:
    """Return a deterministic health-event trace_id derived from the given
    parts. Never random, never wall-clock dependent on its own — callers
    supply any time-derived part explicitly."""
    canonical = "|".join(parts)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]
