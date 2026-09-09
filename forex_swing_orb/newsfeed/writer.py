"""Atomic news-file writer with last-known-good preservation (§6).

Uses the repository's accepted atomic-write discipline (``bridge.atomic``:
temp -> flush -> fsync -> atomic rename -> dir fsync). A failed refresh NEVER calls
``write_bundle``, so a partial/corrupt file can never replace the last-known-good
one. Staleness of that preserved file is still surfaced to the existing compliance
freshness rule via the bundle's ``as_of`` (which the acquirer stamps at acquisition
time), so preservation cannot keep trading alive on silently stale news.
"""

from __future__ import annotations

from pathlib import Path

from ..bridge import serialize
from ..bridge.atomic import atomic_write_text


def write_bundle(path, bundle):
    """Atomically (temp+fsync+rename) write the normalized bundle as canonical JSON.
    Returns the written path. Raises on I/O failure so the caller records the
    failure and keeps the previous file (last-known-good)."""
    return atomic_write_text(path, serialize.canonical_json(bundle))


def read_last_good(path):
    """Return the currently persisted bundle dict, or None if absent/unreadable.
    Used only to report the last-known-good bundle_as_of in health — never to
    fabricate or re-emit data."""
    try:
        ok, obj = serialize.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError):
        return None
    return obj if ok else None
