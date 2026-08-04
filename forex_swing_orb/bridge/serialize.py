"""Deterministic serialization + integrity digest (spec §3.1).

The single serializer/digest implementation for the bridge — no duplicates. Files
are inert JSON (never executed): read with ``json.loads`` only, never eval/pickle.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

DIGEST_FIELD = "integrity_digest"


def canonical_json(obj):
    """Deterministic JSON text: sorted keys, compact separators, UTF-8, no NaN."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def compute_integrity_digest(record):
    """sha256 (hex) over the canonical serialization of the record WITHOUT its
    own digest field (spec §3.1)."""
    body = {k: v for k, v in record.items() if k != DIGEST_FIELD}
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


def with_integrity_digest(record):
    """Return a copy of ``record`` with a freshly computed ``integrity_digest``."""
    out = {k: v for k, v in record.items() if k != DIGEST_FIELD}
    out[DIGEST_FIELD] = compute_integrity_digest(out)
    return out


def verify_integrity_digest(record):
    """True iff the record carries a digest matching its content."""
    claimed = record.get(DIGEST_FIELD)
    if not isinstance(claimed, str):
        return False
    return claimed == compute_integrity_digest(record)


def dumps(record):
    return canonical_json(record)


def loads(text):
    """Strict JSON parse; returns (ok, obj_or_None)."""
    try:
        obj = json.loads(text)
    except (ValueError, TypeError):
        return False, None
    if not isinstance(obj, dict):
        return False, None
    return True, obj


def iso_utc(dt):
    """Format a tz-aware (or naive-as-UTC) datetime as ISO-8601 Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value):
    """Parse an ISO-8601 timestamp to tz-aware UTC; None if malformed."""
    if not isinstance(value, str) or not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def result_id(signal_id, status):
    """Deterministic result id: sha256(signal_id|status)[:16] (F-C).

    Keyed on (signal_id, terminal outcome) ONLY — not the wall clock — so a
    re-run for the same terminal outcome maps to the SAME artifact name and can
    never mint a second terminal result for one signal_id."""
    payload = f"{signal_id}|{status}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
