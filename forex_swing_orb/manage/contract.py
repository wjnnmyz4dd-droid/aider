"""Manage-channel contract (Phase 7B-B) — frozen Option C revised contract.

A SEPARATE, additive stop-management channel between the accepted Python
PositionManager and the MQL5 EA. It reuses ``bridge.serialize`` (canonical JSON +
integrity digest) and reimplements no Position-Management arithmetic. Distinct
from the ENTER channel: its own ids, schema, paths, dedup, lifecycle, and audit.

Determinism: content-addressed ``manage_id`` (no UUID, no wall-clock randomness).
Fail closed on unknown schema/version/fields.
"""

from __future__ import annotations

import hashlib

from ..bridge import serialize

SCHEMA_VERSION = 1
SOURCE_COMPONENT = "session_edge_manager/1.0"


class ManageAction:
    MODIFY_STOP = "MODIFY_STOP"
    PROTECTIVE_CLOSE = "PROTECTIVE_CLOSE"
    ALL = (MODIFY_STOP, PROTECTIVE_CLOSE)


# R3: PROTECTIVE_CLOSE is authorized ONLY for these frozen PositionManager
# reasons (PMReason values). The EA/consumer independently enforce this set; a
# PROTECTIVE_CLOSE carrying any other pm_reason is rejected fail-closed. (A future
# "capital-preservation remediation" PMReason is added here when defined.)
PROTECTIVE_CLOSE_REASONS = frozenset({
    "PM_KILL_SWITCH", "PM_WEEKEND_EXIT", "PM_MAX_DURATION_EXIT",
})


def protective_close_authorized(pm_reason):
    return pm_reason in PROTECTIVE_CLOSE_REASONS


class ManageStatus:
    APPLIED = "APPLIED"
    ALREADY_APPLIED = "ALREADY_APPLIED"
    REJECTED_STALE = "REJECTED_STALE"
    REJECTED_LOOSEN = "REJECTED_LOOSEN"
    REJECTED_WIDEN = "REJECTED_WIDEN"
    REJECTED_BROKER_CONSTRAINT = "REJECTED_BROKER_CONSTRAINT"
    REJECTED_EXPIRED = "REJECTED_EXPIRED"
    REJECTED_INVALID = "REJECTED_INVALID"
    NO_POSITION = "NO_POSITION"
    NO_OP_CLOSED = "NO_OP_CLOSED"
    BROKER_REJECTED = "BROKER_REJECTED"
    TERMINAL_DISCONNECTED = "TERMINAL_DISCONNECTED"
    UNCERTAIN = "UNCERTAIN"
    ERROR = "ERROR"
    QUARANTINED = "QUARANTINED"

    ALL = (APPLIED, ALREADY_APPLIED, REJECTED_STALE, REJECTED_LOOSEN, REJECTED_WIDEN,
           REJECTED_BROKER_CONSTRAINT, REJECTED_EXPIRED, REJECTED_INVALID, NO_POSITION,
           NO_OP_CLOSED, BROKER_REJECTED, TERMINAL_DISCONNECTED, UNCERTAIN, ERROR,
           QUARANTINED)
    # terminal families -> archive subdir
    APPLIED_FAMILY = frozenset({APPLIED, ALREADY_APPLIED})
    CLOSED_FAMILY = frozenset({NO_OP_CLOSED})
    REJECTED_FAMILY = frozenset({REJECTED_STALE, REJECTED_LOOSEN, REJECTED_WIDEN,
                                 REJECTED_BROKER_CONSTRAINT, REJECTED_EXPIRED,
                                 REJECTED_INVALID, NO_POSITION, BROKER_REJECTED})
    # NOT terminal for dedup purposes (retry allowed only via a NEW manage_id after
    # fresh truth): TERMINAL_DISCONNECTED, UNCERTAIN are non-terminal.
    NON_TERMINAL = frozenset({TERMINAL_DISCONNECTED, UNCERTAIN})

    @staticmethod
    def effective_status(status):
        """The canonical EFFECTIVE terminal class for a raw status — what happened,
        not which report variant reported it. APPLIED and ALREADY_APPLIED are the
        SAME effective outcome (the modification is in place), so a recover re-run
        that re-emits ALREADY_APPLIED resolves to the APPLIED artifact (M-4).
        REJECTED_* collapse to a single REJECTED class (all leave the position
        untouched); NO_OP_CLOSED is CLOSED. ERROR/QUARANTINED (and any non-terminal)
        pass through unchanged."""
        if status in ManageStatus.APPLIED_FAMILY:
            return "APPLIED"
        if status in ManageStatus.CLOSED_FAMILY:
            return "CLOSED"
        if status in ManageStatus.REJECTED_FAMILY:
            return "REJECTED"
        return status


def manage_result_id(manage_id, status):
    """Deterministic, clock-free manage result id: ``sha256(manage_id|effective)[:16]``
    where ``effective`` is :meth:`ManageStatus.effective_status`.

    Keyed on (manage_id, EFFECTIVE terminal outcome) ONLY — never the wall clock —
    so a recover re-run for the same logical outcome (including the APPLIED ->
    ALREADY_APPLIED report variant) maps to the SAME artifact name and can never
    mint a second terminal result file for one management outcome. This mirrors the
    entry channel's ``serialize.result_id(signal_id, status)`` principle; the manage
    channel keys on ``manage_id`` (its per-action identity) instead of ``signal_id``
    because one signal_id has many management actions."""
    payload = f"{manage_id}|{ManageStatus.effective_status(status)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


# ---- instruction / result field contracts (frozen) ------------------------
INSTRUCTION_FIELDS = (
    "schema_version", "manage_id", "signal_id", "ticket", "symbol", "direction",
    "action", "target_stop", "expected_current_stop", "prior_stop", "pm_phase",
    "pm_reason", "structure_reference", "market_reference", "point", "digits",
    "broker_min_stop_distance", "per_ticket_sequence", "generated_timestamp",
    "expiration_timestamp", "source_component", "integrity_digest",
)

RESULT_FIELDS = (
    "schema_version", "manage_id", "signal_id", "ticket", "symbol", "action",
    "requested_stop", "expected_current_stop", "observed_stop_before",
    "observed_stop_after", "per_ticket_sequence", "status", "reason_code",
    "broker_retcode", "broker_message", "claimed_timestamp", "applied_timestamp",
    "completed_timestamp", "reconciliation_state", "integrity_digest",
)

# fields (ordered) that content-address one intended broker action
_MANAGE_ID_FIELDS = (
    "schema_version", "ticket", "signal_id", "symbol", "action", "target_stop",
    "expected_current_stop", "pm_reason", "per_ticket_sequence",
    "generated_timestamp", "expiration_timestamp", "structure_reference",
    "pm_phase", "initial_r_digest",
)


def initial_r_digest(direction, entry, initial_stop):
    """Immutable content digest of the position's initial-risk reference."""
    payload = serialize.canonical_json(
        [str(direction), round(float(entry), 10), round(float(initial_stop), 10)])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def compute_manage_id(fields):
    """Content-addressed 16-hex manage_id over the frozen digest tuple."""
    body = {k: fields.get(k) for k in _MANAGE_ID_FIELDS}
    payload = serialize.canonical_json(body)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def build_instruction(fields):
    """Assemble a MANAGE_STOP/PROTECTIVE_CLOSE instruction with manage_id +
    integrity_digest. ``fields`` must supply every non-derived field."""
    rec = dict(fields)
    rec["schema_version"] = SCHEMA_VERSION
    rec.setdefault("source_component", SOURCE_COMPONENT)
    rec["manage_id"] = compute_manage_id({**rec, "initial_r_digest": fields["initial_r_digest"]})
    rec.pop("initial_r_digest", None)          # captured into the id; not a wire field
    return serialize.with_integrity_digest(rec)


def validate_instruction(rec):
    """Deterministic fail-closed structural validation. Returns (ok, reason)."""
    if not isinstance(rec, dict):
        return (False, "malformed")
    if rec.get("schema_version") != SCHEMA_VERSION:
        return (False, "schema_version")
    for f in INSTRUCTION_FIELDS:
        if f not in rec:
            return (False, f"missing:{f}")
    if rec["action"] not in ManageAction.ALL:
        return (False, "action")
    if not serialize.verify_integrity_digest(rec):
        return (False, "integrity_digest")
    if rec["action"] == ManageAction.MODIFY_STOP:
        if rec.get("target_stop") is None or rec.get("expected_current_stop") is None:
            return (False, "modify_requires_target_and_expected")
    exp = serialize.parse_iso(rec.get("expiration_timestamp"))
    gen = serialize.parse_iso(rec.get("generated_timestamp"))
    if exp is None or gen is None or not (exp > gen):
        return (False, "expiration")
    return (True, "ok")


def build_result(fields):
    rec = dict(fields)
    rec["schema_version"] = SCHEMA_VERSION
    return serialize.with_integrity_digest(rec)
