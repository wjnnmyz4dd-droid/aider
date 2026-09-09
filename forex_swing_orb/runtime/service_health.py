"""Service health freshness — the ONE owner of "is the producer / manager process
recently alive?" from its own health artifact (distinct from EA liveness in
runtime/ea_liveness.py and from H5 instruction/ACK health in producer/bridge_health.py).

A health artifact is only CURRENT evidence of a live process when it is (1) structurally
valid, (2) tagged with the expected service identity, (3) carries a valid UTC timestamp,
and (4) that timestamp is within a cadence-derived freshness window. A stale artifact
(the writer stopped refreshing — e.g. the process died) can therefore NEVER read as
current. This mirrors the EA-liveness architecture but is a SEPARATE evidence dimension:

  EA heartbeat      -> EA presence/polling            (runtime.ea_liveness)
  Producer health   -> producer process activity       (this module, service="producer")
  Manager health    -> manager process activity         (this module, service="manager")
  H5 instruction/ACK-> instructions being acknowledged  (producer.bridge_health)

Freshness != eligibility: a producer BLOCKED by NEWS/DATA/anchor, or a manager in
RECONCILIATION_REQUIRED, is still ALIVE and keeps refreshing its artifact — so it reads
FRESH. Only a writer that STOPPED refreshing goes STALE.

The producer/manager write this envelope via :func:`stamp` (merged into their existing
health status). This module has ZERO trade authority: it reads/stamps a file and
classifies freshness; readiness aggregation lives in runtime.operator_status /
runtime.preflight.
"""

from __future__ import annotations

import os
import platform

from ..bridge import serialize

HEALTH_ARTIFACT = "session_edge_service_health"
HEALTH_SCHEMA = 1

# Canonical service identities.
PRODUCER = "producer"
MANAGER = "manager"

# Freshness derived from the writer's own loop cadence (never a huge arbitrary
# timeout): freshness_limit = max(MIN_FRESH_FLOOR_SEC, cadence_sec * FRESH_MULT).
# Producer and manager both refresh once per loop, bounded by cadence_sec (default
# 900s), so the default window is max(60, 2700) = 2700s (~3 missed cycles). A shorter
# configured cadence yields a proportionally shorter window.
MIN_FRESH_FLOOR_SEC = 60.0
FRESH_MULT = 3.0
_DEFAULT_CADENCE_SEC = 900.0

# States (only PASS is fresh/current).
PASS = "PASS"
MISSING = "MISSING"
STALE = "STALE"
MALFORMED = "MALFORMED"
UNKNOWN_SCHEMA = "UNKNOWN_SCHEMA"
WRONG_SERVICE = "WRONG_SERVICE"


class ServiceHealth:
    def __init__(self, state, detail="", age=None, data=None):
        self.state, self.detail, self.age, self.data = state, detail, age, (data or {})

    @property
    def ok(self):
        return self.state == PASS


def _has_explicit_tz(s):
    """True iff ``s`` is an ISO timestamp carrying an explicit timezone (a trailing
    'Z' or a +/- offset in the time part). Naive timestamps are rejected for freshness."""
    if not isinstance(s, str) or "T" not in s:
        return False
    tpart = s.split("T", 1)[1]
    return s.endswith("Z") or ("+" in tpart) or ("-" in tpart)


def _cadence(value):
    try:
        c = float(value)
    except (TypeError, ValueError):
        c = 0.0
    return c if c > 0 else _DEFAULT_CADENCE_SEC


def freshness_limit(cadence_sec):
    """Deterministic freshness window from the writer's loop cadence."""
    return max(MIN_FRESH_FLOOR_SEC, _cadence(cadence_sec) * FRESH_MULT)


def startup_grace_sec(cadence_sec):
    """A bounded window after spawn during which a not-yet-written artifact reads as
    STARTING (launcher display only) rather than a hard failure. One freshness window."""
    return freshness_limit(cadence_sec)


def within_startup_grace(spawned_at, now, cadence_sec):
    """True iff ``now`` is within the startup grace of ``spawned_at`` (both tz-aware).
    Launcher-side helper only; standalone readiness never depends on a process handle."""
    if spawned_at is None or now is None:
        return False
    try:
        elapsed = (now - spawned_at).total_seconds()
    except (TypeError, AttributeError):
        return False
    return 0 <= elapsed <= startup_grace_sec(cadence_sec)


def stamp(service, now, cadence_sec, *, pid=None, host=None):
    """Build the canonical health envelope a writer merges into its health status.
    ``generated_timestamp`` is the freshness field the reader validates."""
    return {
        "health_artifact": HEALTH_ARTIFACT,
        "schema_version": HEALTH_SCHEMA,
        "service": service,
        "generated_timestamp": serialize.iso_utc(now),
        "health_cadence_sec": _cadence(cadence_sec),
        "pid": int(os.getpid()) if pid is None else int(pid),
        "host": (platform.node() or "unknown") if host is None else str(host),
    }


def read_service_health(path, service, now):
    """Classify the freshness of a service health artifact at instant ``now`` (injected).
    Returns a :class:`ServiceHealth` whose ``ok`` is True ONLY for a fresh, well-formed,
    known-schema artifact tagged with the expected ``service``. Never raises; never writes."""
    try:
        text = open(path, "r", encoding="utf-8").read()
    except (FileNotFoundError, OSError):
        return ServiceHealth(MISSING, f"no health artifact at {path}")
    ok, obj = serialize.loads(text)
    if not ok or not isinstance(obj, dict):
        return ServiceHealth(MALFORMED, "unparseable health artifact")
    if obj.get("health_artifact") != HEALTH_ARTIFACT or obj.get("schema_version") != HEALTH_SCHEMA:
        return ServiceHealth(UNKNOWN_SCHEMA,
                             f"artifact/schema mismatch "
                             f"({obj.get('health_artifact')!r}/{obj.get('schema_version')!r})")
    if str(obj.get("service")) != str(service):
        return ServiceHealth(WRONG_SERVICE,
                             f"health service {obj.get('service')!r} != expected {service!r}")
    gen = obj.get("generated_timestamp")
    # Freshness demands an unambiguous UTC instant: a naive (tz-less) timestamp is
    # rejected here rather than silently assumed-UTC. Legitimate writers always emit
    # a trailing 'Z' via serialize.iso_utc.
    if not _has_explicit_tz(gen):
        return ServiceHealth(MALFORMED, "missing/invalid/naive generated_timestamp")
    ts = serialize.parse_iso(gen)
    if ts is None:
        return ServiceHealth(MALFORMED, "missing/invalid generated_timestamp")
    limit = freshness_limit(obj.get("health_cadence_sec"))
    try:
        age = (now - ts).total_seconds()
    except (TypeError, AttributeError):
        return ServiceHealth(MALFORMED, "timestamp not comparable (naive/aware mismatch)")
    if age < -limit:
        return ServiceHealth(STALE, f"health timestamp is in the future ({age:.0f}s)", age=age)
    if age > limit:
        return ServiceHealth(STALE, f"health age {age:.0f}s > limit {limit:.0f}s "
                             f"({service} stalled/stopped?)", age=age)
    return ServiceHealth(PASS, f"fresh {service} health ({age:.0f}s ≤ {limit:.0f}s)",
                         age=age, data=obj)
