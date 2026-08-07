"""Economic-calendar acquisition contract (Phase 9D-R1) — DATA ONLY.

Canonical constants, the raw-source value object, the acquisition error type, and
the normalized bundle/event key sets. This module has NO trade authority: it never
approves/rejects a trade, computes a signal, or touches compliance/risk/positions.
It only shapes acquired calendar data into the bundle the EXISTING compliance news
gate already consumes (``compliance/news.py`` remains the sole news authority).

No networking here (that is isolated in the provider layer). All datetimes handled
elsewhere are timezone-aware UTC; this module holds no wall clock.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Bundle schema version emitted by the acquisition layer. The existing gate reads
# only as_of/events/verified + per-event event_id/currency/impact/event_timestamp/
# verification_state; every extra key here (provenance, integrity_digest, event
# result fields) is additive and ignored by the gate.
SCHEMA_VERSION = 2

# Canonical impact vocabulary the compliance gate understands as HIGH via its
# frozenset {"HIGH","H","3"}. We normalize every provider encoding to one of these
# three BEFORE the gate sees it (resolves audit gap D-2).
IMPACT_HIGH = "HIGH"
IMPACT_MEDIUM = "MEDIUM"
IMPACT_LOW = "LOW"
CANONICAL_IMPACTS = (IMPACT_HIGH, IMPACT_MEDIUM, IMPACT_LOW)

# Optional per-event result fields captured when the source supplies them. They are
# INFORMATIONAL ONLY in this phase — no gate/strategy/risk logic reads them.
RESULT_FIELDS = ("previous", "forecast", "actual", "revision")

# Completeness classifications reported honestly (audit gap D-3/F-3). We never claim
# a calendar is complete merely because a fetch succeeded.
COMPLETENESS_UNESTABLISHED = "unestablished"     # source gives no completeness guarantee
COMPLETENESS_SOURCE_DECLARED = "source_declared"  # source explicitly declared it complete
COMPLETENESS_CROSS_VERIFIED = "cross_verified"    # corroborated across >1 source

# Coverage basis: how the calendar's coverage interval was derived (F-2/F-3).
COVERAGE_EVENT_SPAN = "event_span_day_snapped"   # derived from earliest/latest events
COVERAGE_SOURCE_DECLARED = "source_declared"     # source declared coverage_start/end

# Operational health status (F-6). SERVICE_STALE is derived EXTERNALLY (see health.py).
HEALTH_HEALTHY = "HEALTHY"
HEALTH_PROVIDER_FAILURE = "PROVIDER_FAILURE"
HEALTH_SOURCE_STALE = "SOURCE_STALE"
HEALTH_FRESHNESS_UNESTABLISHED = "SOURCE_FRESHNESS_UNESTABLISHED"
HEALTH_FILE_WRITE_FAILURE = "FILE_WRITE_FAILURE"
HEALTH_SERVICE_STALE = "SERVICE_STALE"


# Deterministic acquisition reason codes (fail-closed taxonomy).
class Reason:
    PROVIDER_UNAVAILABLE = "ACQ_PROVIDER_UNAVAILABLE"
    TIMEOUT = "ACQ_TIMEOUT"
    SOURCE_ERROR = "ACQ_SOURCE_ERROR"
    MALFORMED_PAYLOAD = "ACQ_MALFORMED_PAYLOAD"
    EMPTY_PAYLOAD = "ACQ_EMPTY_PAYLOAD"
    MISSING_SOURCE_TIME = "ACQ_MISSING_SOURCE_TIME"
    FUTURE_SOURCE_TIME = "ACQ_FUTURE_SOURCE_TIME"
    STALE_SOURCE = "ACQ_STALE_SOURCE"
    FRESHNESS_UNESTABLISHED = "ACQ_SOURCE_FRESHNESS_UNESTABLISHED"  # F-2
    COVERAGE_INVALID = "ACQ_COVERAGE_INVALID"                      # wrong week (F-2)
    OVERSIZED_RESPONSE = "ACQ_OVERSIZED_RESPONSE"                  # F-5
    BAD_CONTENT_TYPE = "ACQ_BAD_CONTENT_TYPE"                      # F-5
    INSECURE_SCHEME = "ACQ_INSECURE_SCHEME"                        # F-5
    MISSING_FIELD = "ACQ_MISSING_FIELD"
    INVALID_CURRENCY = "ACQ_INVALID_CURRENCY"
    INVALID_IMPACT = "ACQ_INVALID_IMPACT"
    INVALID_TIMESTAMP = "ACQ_INVALID_TIMESTAMP"
    NON_FINITE = "ACQ_NON_FINITE"
    DUPLICATE_CONFLICT = "ACQ_DUPLICATE_CONFLICT"
    WRITE_FAILED = "ACQ_WRITE_FAILED"
    CONFIG_ERROR = "ACQ_CONFIG_ERROR"
    OK = "OK"


class AcquisitionError(Exception):
    """Raised when acquisition cannot produce a trustworthy bundle. Carries a
    deterministic reason code. The service catches this, records the failure in the
    health file, and PRESERVES the last-known-good news file (never fabricates)."""

    def __init__(self, reason, detail=None):
        self.reason = reason
        self.detail = dict(detail or {})
        super().__init__(f"{reason}: {self.detail}")


@dataclass(frozen=True)
class RawCalendar:
    """Provider output: raw upstream rows plus acquisition metadata. Source-specific
    parsing lives in the provider; everything downstream is source-agnostic.

    ``events`` is a tuple of plain dicts exactly as the source presented them
    (already JSON-decoded). ``fetched_at``/``source_as_of`` are tz-aware UTC.
    ``trusted`` marks whether the source is an approved, attested calendar (drives
    per-event verification_state). ``complete`` is the source's own completeness
    claim (None = the source makes no guarantee)."""

    source_name: str
    source_identifier: str
    provider_version: str
    fetched_at: object                 # datetime, tz-aware UTC
    events: tuple = ()
    source_as_of: object = None        # datetime tz-aware UTC or None (upstream generated ts)
    complete: object = None            # True / False / None
    trusted: bool = False
    coverage_start: object = None      # datetime tz-aware UTC or None (source-declared)
    coverage_end: object = None        # datetime tz-aware UTC or None (source-declared)
