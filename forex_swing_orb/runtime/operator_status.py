"""Operator status — the ONE place that maps raw component facts into the
operator-facing readiness vocabulary, and aggregates the end-to-end SYSTEM state.

This module is a PURE LEAF: it imports only the Python stdlib. It owns NO authority
over trading, risk, compliance, or the bridge — it neither reads MT5, nor writes a
bridge file, nor mutates any state. It only *classifies* facts that its callers
gathered from the real owners:

  * producer last-cycle outcome/reason   <- producer.runner / producer.dashboard
  * manager health facts                 <- manage.service.status()
  * H5 instruction/ACK health            <- producer.bridge_health
  * EA liveness state                    <- runtime.ea_liveness.read_ea_status()
  * bridge filesystem probe              <- runtime.launcher.bridge_handshake()

Two anti-false-green invariants are enforced HERE, once, for every operator surface
(launcher startup screen, preflight, dashboards):

  1. BRIDGE_END_TO_END_READY requires BOTH the Python-side filesystem probe AND a
     fresh, same-bridge EA heartbeat (ea_liveness PASS). Python R/W alone is NOT
     end-to-end and must never read as such.
  2. SYSTEM_READY requires end-to-end bridge readiness (hence fresh EA liveness),
     a producer that is not BLOCKED/ERROR/STOPPED, and a manager that is not
     ERROR/DISCONNECTED/RECONCILIATION_REQUIRED. SYSTEM_READY means "correctly
     wired and unblocked" — NOT "a trade should exist".

Reason/outcome codes are the ones produced by producer.contract.CycleOutcome; they
are referenced here as data literals (not re-declared authority) so this module has
no import coupling to the producer package. If CycleOutcome changes, the
categorization sets below and the parity test in the readiness suite must be updated
together.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Producer state vocabulary (spec §B: PRODUCER_RUNNING / WAITING / BLOCKED / READY)
# ---------------------------------------------------------------------------
PRODUCER_STOPPED = "PRODUCER_STOPPED"      # process not running
PRODUCER_RUNNING = "PRODUCER_RUNNING"      # running, no diagnostic cycle recorded yet
PRODUCER_WAITING = "PRODUCER_WAITING"      # healthy steady state — waiting for conditions
PRODUCER_BLOCKED = "PRODUCER_BLOCKED"      # a hard gate rejected the last cycle
PRODUCER_READY = "PRODUCER_READY"          # last cycle wrote an instruction end-to-end
PRODUCER_ERROR = "PRODUCER_ERROR"          # isolated unit fault last cycle

# CycleOutcome -> producer state. Source of truth for the strings:
# producer.contract.CycleOutcome (kept in sync by the readiness parity test).
_BLOCKED_OUTCOMES = frozenset({
    "KILL_SWITCH", "DATA_REJECTED", "ACCOUNT_REJECTED", "NEWS_REJECTED",
    "COMPLIANCE_REJECT",
})
_WAITING_OUTCOMES = frozenset({
    "NO_NEW_BAR", "SESSION_INELIGIBLE", "NO_CANDIDATE", "DUPLICATE_SUPPRESSED",
})
_READY_OUTCOMES = frozenset({"INSTRUCTION_WRITTEN"})
_ERROR_OUTCOMES = frozenset({"UNIT_ERROR"})

# The full set this module knows how to classify (parity-checked against
# CycleOutcome.ALL + UNIT_ERROR in the test suite).
KNOWN_OUTCOMES = _BLOCKED_OUTCOMES | _WAITING_OUTCOMES | _READY_OUTCOMES | _ERROR_OUTCOMES

# Producer states that do NOT block the system (healthy / benign).
_PRODUCER_OK_STATES = frozenset({PRODUCER_RUNNING, PRODUCER_WAITING, PRODUCER_READY})

# ---------------------------------------------------------------------------
# Manager state vocabulary
# ---------------------------------------------------------------------------
MANAGER_STOPPED = "MANAGER_STOPPED"                          # process not running
MANAGER_DISCONNECTED = "MANAGER_DISCONNECTED"                # terminal not connected
MANAGER_ERROR = "MANAGER_ERROR"                              # last_error present
MANAGER_RECONCILIATION_REQUIRED = "MANAGER_RECONCILIATION_REQUIRED"
MANAGER_MANAGING = "MANAGER_MANAGING"                        # tracking/managing positions
MANAGER_IDLE = "MANAGER_IDLE"                                # connected, nothing to manage

_MANAGER_OK_STATES = frozenset({MANAGER_MANAGING, MANAGER_IDLE})

# ---------------------------------------------------------------------------
# Bridge end-to-end vocabulary (spec §H)
# ---------------------------------------------------------------------------
BRIDGE_END_TO_END_READY = "BRIDGE_END_TO_END_READY"
BRIDGE_END_TO_END_NOT_READY = "BRIDGE_END_TO_END_NOT_READY"

# ---------------------------------------------------------------------------
# System vocabulary (spec §B)
# ---------------------------------------------------------------------------
SYSTEM_READY = "SYSTEM_READY"
SYSTEM_NOT_READY = "SYSTEM_NOT_READY"


def _outcome_of(last_cycle):
    """Extract the outcome string from a last-cycle record (dict or CycleResult)."""
    if last_cycle is None:
        return None
    if isinstance(last_cycle, dict):
        return last_cycle.get("outcome")
    return getattr(last_cycle, "outcome", None)


def _reasons_of(last_cycle):
    if last_cycle is None:
        return ()
    if isinstance(last_cycle, dict):
        return tuple(last_cycle.get("reason_codes") or ())
    return tuple(getattr(last_cycle, "reason_codes", ()) or ())


def producer_state(running, last_cycle):
    """Map (process running?, last cycle record) -> producer state record.

    ``last_cycle`` may be a dict (dashboard/JSON) or a CycleResult (has .outcome /
    .reason_codes), or None when no cycle has completed. Never raises.
    """
    if not running:
        return {"state": PRODUCER_STOPPED, "outcome": None, "reason_codes": (),
                "detail": "producer process not running"}
    outcome = _outcome_of(last_cycle)
    reasons = _reasons_of(last_cycle)
    if outcome is None:
        return {"state": PRODUCER_RUNNING, "outcome": None, "reason_codes": (),
                "detail": "running; no completed cycle yet"}
    if outcome in _BLOCKED_OUTCOMES:
        state = PRODUCER_BLOCKED
    elif outcome in _WAITING_OUTCOMES:
        state = PRODUCER_WAITING
    elif outcome in _READY_OUTCOMES:
        state = PRODUCER_READY
    elif outcome in _ERROR_OUTCOMES:
        state = PRODUCER_ERROR
    else:
        # Unknown outcome: fail toward visibility, not a false green.
        state = PRODUCER_BLOCKED
    return {"state": state, "outcome": outcome, "reason_codes": reasons,
            "detail": f"last cycle {outcome} ({','.join(reasons) or '-'})"}


def manager_state(running, facts):
    """Map manager health facts -> manager state record. ``facts`` is the dict from
    manage.service.status() (terminal_connected, tracked_tickets, in_flight_count,
    unresolved_reconciliation_count, recovery_reconciliation_count, last_error).
    Never raises."""
    if not running:
        return {"state": MANAGER_STOPPED, "detail": "manager process not running"}
    facts = facts or {}
    if facts.get("last_error"):
        return {"state": MANAGER_ERROR, "detail": f"last_error: {facts.get('last_error')}"}
    if not facts.get("terminal_connected"):
        return {"state": MANAGER_DISCONNECTED, "detail": "MT5 terminal not connected"}
    unresolved = facts.get("unresolved_reconciliation_count") or 0
    if unresolved:
        return {"state": MANAGER_RECONCILIATION_REQUIRED,
                "detail": f"{unresolved} unresolved reconciliation item(s)"}
    tracked = facts.get("tracked_tickets") or 0
    in_flight = facts.get("in_flight_count") or 0
    if tracked or in_flight:
        return {"state": MANAGER_MANAGING,
                "detail": f"tracking {tracked} ticket(s), {in_flight} in-flight"}
    return {"state": MANAGER_IDLE, "detail": "connected; no open positions to manage"}


def bridge_end_to_end(filesystem_ok, ea_liveness_state):
    """End-to-end bridge readiness (spec §H): Python filesystem probe AND a fresh,
    same-bridge EA heartbeat. Python R/W alone is deliberately NOT sufficient.

    ``ea_liveness_state`` is a runtime.ea_liveness state string (PASS is the only
    liveness state that satisfies end-to-end)."""
    from . import ea_liveness  # leaf import; only for the PASS sentinel string
    ready = bool(filesystem_ok) and ea_liveness_state == ea_liveness.PASS
    blockers = []
    if not filesystem_ok:
        blockers.append("bridge filesystem probe did not pass (Python cannot R/W the bridge)")
    if ea_liveness_state != ea_liveness.PASS:
        blockers.append(f"EA liveness is {ea_liveness_state} (no fresh same-bridge EA heartbeat)")
    return {"state": BRIDGE_END_TO_END_READY if ready else BRIDGE_END_TO_END_NOT_READY,
            "ready": ready, "filesystem_ok": bool(filesystem_ok),
            "ea_liveness_state": ea_liveness_state, "blockers": tuple(blockers)}


def system_readiness(*, bridge_e2e, producer, manager, anchor_available=None):
    """Aggregate the end-to-end SYSTEM state (spec §B).

    SYSTEM_READY requires:
      * bridge end-to-end ready (which itself requires fresh EA liveness), AND
      * producer not BLOCKED/ERROR/STOPPED, AND
      * manager not ERROR/DISCONNECTED/RECONCILIATION_REQUIRED, AND
      * daily anchor available when that fact is supplied (None = not evaluated here;
        the producer's own ACCOUNT_ANCHOR gate is the authority and already shows up
        as PRODUCER_BLOCKED — this is visibility only, never a second authority).

    SYSTEM_READY means "correctly wired and unblocked", NOT "a trade should exist".
    Returns {state, ready, blockers, components}. Never raises.
    """
    blockers = list(bridge_e2e.get("blockers") or ())
    if not bridge_e2e.get("ready"):
        if not blockers:
            blockers.append("bridge is not end-to-end ready")
    p_state = producer.get("state")
    if p_state not in _PRODUCER_OK_STATES:
        blockers.append(f"producer is {p_state} ({producer.get('detail','')})".rstrip(" ()"))
    m_state = manager.get("state")
    if m_state not in _MANAGER_OK_STATES:
        blockers.append(f"manager is {m_state} ({manager.get('detail','')})".rstrip(" ()"))
    if anchor_available is False:
        blockers.append("daily anchor unavailable (mid-day cold start; producer fails closed)")
    ready = not blockers
    return {"state": SYSTEM_READY if ready else SYSTEM_NOT_READY,
            "ready": ready, "blockers": tuple(blockers),
            "components": {"bridge_end_to_end": bridge_e2e.get("state"),
                           "producer": p_state, "manager": m_state,
                           "anchor_available": anchor_available}}
