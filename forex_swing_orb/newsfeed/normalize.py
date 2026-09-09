"""Deterministic normalization of raw calendar rows -> canonical events.

Pure and source-agnostic: given identical raw input + config it yields identical
output. No wall clock (timestamps come from the row / injected ``now``), no
networking, no trade authority. Resolves audit gaps D-2 (impact normalization) and
D-3 (honest completeness — handled in ``acquire``).

Missing OPTIONAL values become explicit ``None`` — never invented. Missing/invalid
REQUIRED values fail closed via :class:`AcquisitionError`.
"""

from __future__ import annotations

import hashlib
import math

from ..bridge import serialize
from .contract import (CANONICAL_IMPACTS, IMPACT_HIGH, IMPACT_LOW, IMPACT_MEDIUM,
                       RESULT_FIELDS, AcquisitionError, Reason)

# Provider-specific impact encodings -> canonical. Matched case-insensitively on
# the trimmed string. Anything NOT here is treated CONSERVATIVELY as HIGH (never
# silently downgraded) and flagged as a normalization warning.
_IMPACT_MAP = {
    "HIGH": IMPACT_HIGH, "H": IMPACT_HIGH, "3": IMPACT_HIGH, "3.0": IMPACT_HIGH,
    "RED": IMPACT_HIGH, "CRITICAL": IMPACT_HIGH,
    "MEDIUM": IMPACT_MEDIUM, "MED": IMPACT_MEDIUM, "M": IMPACT_MEDIUM,
    "2": IMPACT_MEDIUM, "2.0": IMPACT_MEDIUM, "ORANGE": IMPACT_MEDIUM,
    "LOW": IMPACT_LOW, "L": IMPACT_LOW, "1": IMPACT_LOW, "1.0": IMPACT_LOW,
    "YELLOW": IMPACT_LOW, "GRAY": IMPACT_LOW, "GREY": IMPACT_LOW,
    # explicitly-known non-market-moving categories (known, so not "unknown"):
    "HOLIDAY": IMPACT_LOW, "NON-ECONOMIC": IMPACT_LOW, "NONE": IMPACT_LOW,
}


def normalize_impact(raw):
    """Map a provider impact encoding to canonical HIGH/MEDIUM/LOW.

    Returns ``(impact, warning_or_None)``. An UNKNOWN encoding is mapped to HIGH
    (conservative over-block, never a silent downgrade) with a warning string so the
    provenance/health record shows exactly what happened."""
    if raw is None:
        return IMPACT_HIGH, "impact_missing_mapped_to_HIGH"
    key = str(raw).strip().upper()
    if key in _IMPACT_MAP:
        return _IMPACT_MAP[key], None
    if key in CANONICAL_IMPACTS:
        return key, None
    return IMPACT_HIGH, f"unknown_impact_{key}_mapped_to_HIGH"


def normalize_currency(raw):
    """Upper-case 3-letter alpha currency code, else fail closed."""
    if raw is None:
        raise AcquisitionError(Reason.MISSING_FIELD, {"field": "currency"})
    cur = str(raw).strip().upper()
    if len(cur) != 3 or not cur.isalpha():
        raise AcquisitionError(Reason.INVALID_CURRENCY, {"currency": str(raw)})
    return cur


def _finite_or_none(value):
    """Preserve a provider result value (previous/forecast/actual/revision) as-is
    when it is a finite number or non-empty string; empty/absent -> None. A
    non-finite number (NaN/Inf) fails closed (never persisted)."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if not math.isfinite(value):
            raise AcquisitionError(Reason.NON_FINITE, {"value": repr(value)})
        return value
    s = str(value).strip()
    return s if s != "" else None


def stable_event_id(source_name, currency, name, ts_iso):
    """Deterministic, stable per-event identity across refreshes: sha256 of the
    immutable (source, currency, name, scheduled-time) tuple, truncated. Stable id
    is what makes conflict detection meaningful (same id + changed content =
    conflict, per §4)."""
    payload = f"{source_name}|{currency}|{name}|{ts_iso}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _get(row, *keys):
    """First present, non-None value among ``keys`` (source rows vary in naming)."""
    for k in keys:
        if isinstance(row, dict) and row.get(k) is not None:
            return row.get(k)
    return None


def normalize_event(row, source_name, trusted):
    """Normalize one raw row into a canonical event dict. Fail closed on any
    missing/invalid required field. Returns ``(event, warning_or_None)``."""
    if not isinstance(row, dict):
        raise AcquisitionError(Reason.MALFORMED_PAYLOAD, {"row": repr(row)[:80]})

    name = _get(row, "event_name", "title", "name")
    if name is None or str(name).strip() == "":
        raise AcquisitionError(Reason.MISSING_FIELD, {"field": "event_name"})
    name = str(name).strip()

    # ForexFactory's "country" field carries the currency code; accept either name.
    currency = normalize_currency(_get(row, "currency", "country"))
    country = _get(row, "country")
    country = str(country).strip().upper() if country is not None else currency

    ts_raw = _get(row, "event_timestamp", "date", "timestamp")
    if ts_raw is None:
        raise AcquisitionError(Reason.MISSING_FIELD, {"field": "event_timestamp"})
    et = serialize.parse_iso(ts_raw)
    if et is None:
        raise AcquisitionError(Reason.INVALID_TIMESTAMP, {"event_timestamp": str(ts_raw)})
    ts_iso = serialize.iso_utc(et)

    impact, warning = normalize_impact(_get(row, "impact"))

    eid = _get(row, "event_id") or stable_event_id(source_name, currency, name, ts_iso)
    eid = str(eid)

    event = {
        "event_id": eid,
        "event_name": name,
        "country": country,
        "currency": currency,
        "impact": impact,
        "event_timestamp": ts_iso,
        "verification_state": "VERIFIED" if trusted else "UNVERIFIED",
        "source_event_key": stable_event_id(source_name, currency, name, ts_iso),
    }
    for f in RESULT_FIELDS:                       # informational only in this phase
        event[f] = _finite_or_none(row.get(f))
    return event, warning


def normalize_events(raw_calendar):
    """Normalize + de-duplicate all rows. Identical duplicates collapse; a repeated
    ``event_id`` with a DIFFERING LOCKOUT-IDENTITY (timestamp/impact/currency/name)
    fails closed — never silently merged in a way that could weaken the HIGH lockout
    (§4/§8). A repeated id whose lockout-identity matches but whose INFORMATIONAL
    result field (previous/forecast/actual/revision) differs is recorded as a
    deterministic conflict (F-7): the conflicting field is nulled on the retained
    event and a warning is emitted — it never affects the lockout. Returns
    ``(events_sorted, warnings)``."""
    by_id = {}
    warnings = []
    for row in raw_calendar.events:
        ev, warning = normalize_event(row, raw_calendar.source_name, raw_calendar.trusted)
        if warning:
            warnings.append(warning)
        eid = ev["event_id"]
        prior = by_id.get(eid)
        if prior is None:
            by_id[eid] = ev
            continue
        if _content_key(prior) != _content_key(ev):
            # lockout-relevant conflict -> fail closed (never weaken the lockout)
            raise AcquisitionError(Reason.DUPLICATE_CONFLICT, {"event_id": eid})
        # same lockout identity: reconcile informational result fields deterministically
        for f in RESULT_FIELDS:
            if prior.get(f) != ev.get(f):
                prior[f] = None                    # do not silently pick a winner
                warnings.append(f"result_conflict_{f}_{eid}")
    events = sorted(by_id.values(), key=lambda e: (e["event_timestamp"], e["event_id"]))
    return events, warnings


def _content_key(ev):
    """The LOCKOUT-defining identity of an event for conflict detection (excludes the
    informational result fields, which cannot affect the news lockout)."""
    return (ev["event_timestamp"], ev["impact"], ev["currency"], ev["event_name"])
