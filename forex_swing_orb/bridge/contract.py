"""Instruction/result contracts, reason codes, and result states (spec §3, §9).

Single source for what a valid on-disk instruction looks like and how results are
shaped. No execution, no broker fields are ever populated by the bridge.
"""

from __future__ import annotations

# Required instruction fields (spec §3). integrity_digest is the bridge transport
# field; the rest come from the strategy engine's instruction (schema_version 1).
REQUIRED_INSTRUCTION_FIELDS = (
    "schema_version", "signal_id", "session_id", "strategy_id", "strategy_version",
    "symbol", "direction", "entry_price", "stop_loss", "take_profit", "risk_fraction",
    "generated_timestamp", "expiration_timestamp", "evidence_summary",
    "news_eligibility", "integrity_digest",
)

# session_id transport form: a short uppercase token (the bridge validates shape
# only; which sessions are ENABLED is the producer's authority, never the bridge's).
SESSION_ID_RE = r"^[A-Z][A-Z_]{1,19}$"

DIRECTIONS = ("LONG", "SHORT")


class ResultState:
    """Terminal result states the BRIDGE emits (spec §2.1). EXECUTED /
    EXECUTION_FAILED are reserved for the downstream execution layer."""

    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    DUPLICATE = "DUPLICATE"
    FAILED = "FAILED"
    ERROR = "ERROR"
    # Execution-layer terminal states (Phase 3 EA). Reserved by the bridge until
    # an execution consumer exists; now populated by the MT5 Execution Adapter.
    EXECUTED = "EXECUTED"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    # M1: a NON-TERMINAL, consumer-internal signal returned by an execution hook when
    # a broker outcome is transient/ambiguous and MUST NOT be terminalized as a
    # failure (a resend could duplicate, or the order may actually have executed).
    # It is NEVER written to a result file and never appears in the on-disk result
    # vocabulary: the consumer routes it to mark_reconciliation_required so the
    # claimed instruction stays outstanding (capacity-reserved, ACK'd, no resend)
    # until broker-truth reconciliation resolves it.
    RETRY_PENDING = "RETRY_PENDING"


class HookPosture:
    """Declared capability of the injected decision hook (F-S). Governs whether
    reconciliation may safely re-run the hook for a non-terminal claimed item."""

    VALIDATION_ONLY = "VALIDATION_ONLY"          # no side effects (Phase-2 default)
    IDEMPOTENT = "IDEMPOTENT"                     # side effects, safe to repeat
    NON_IDEMPOTENT_EXECUTION = "NON_IDEMPOTENT_EXECUTION"  # e.g. real order placement

    RERUNNABLE = frozenset({VALIDATION_ONLY, IDEMPOTENT})


# Terminal states archived to archive/accepted vs archive/rejected. EXECUTED joins
# the accepted family so a completed execution is treated as accepted terminal
# evidence by the shared resolver (dedup / no-double-order); EXECUTION_FAILED is a
# terminal failure and archives with the rejected family.
ACCEPTED_FAMILY = frozenset({ResultState.ACCEPTED, ResultState.EXECUTED})


def terminal_family(state):
    """Map any terminal state to its archive family ('ACCEPTED' | 'REJECTED')."""
    return "ACCEPTED" if state in ACCEPTED_FAMILY else "REJECTED"


class ReasonCode:
    """Deterministic bridge reason codes (spec §7 transport subset + §2.1)."""

    OK = "OK"
    E_SERDE = "E_SERDE"            # unreadable / invalid JSON
    E_TOO_LARGE = "E_TOO_LARGE"   # exceeds size cap
    E_UNSAFE_PATH = "E_UNSAFE_PATH"  # symlink / escape / bad name
    E_SCHEMA = "E_SCHEMA"         # unknown schema_version
    E_INTEGRITY = "E_INTEGRITY"   # digest mismatch
    E_FIELDS = "E_FIELDS"         # missing / mistyped required field
    E_STRATEGY = "E_STRATEGY"     # unknown strategy_id / strategy_version
    E_ID = "E_ID"                 # malformed signal_id / filename mismatch
    E_DUP = "E_DUP"               # already processed
    E_EXPIRED = "E_EXPIRED"       # past expiration_timestamp
    E_FUTURE = "E_FUTURE"         # generated_timestamp implausibly in the future
    E_SYMBOL = "E_SYMBOL"         # symbol not canonical [A-Z]{6}.FX
    E_STRUCT = "E_STRUCT"         # bad direction / prices / stop-target geometry
    E_HOOK = "E_HOOK"             # decision hook raised (FAILED)
    E_INTERNAL = "E_INTERNAL"     # bridge-internal error (ERROR)
    E_CONFLICT = "E_CONFLICT"     # conflicting persistent evidence for one signal_id
    E_MOVE = "E_MOVE"             # a filesystem move failed (F-2)
    ADOPTED = "ADOPTED"           # existing terminal result adopted on recovery
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"  # non-idempotent, needs broker state (F-S)


# reason_code -> result state for a denied instruction
DENY_STATE = {
    ReasonCode.E_DUP: ResultState.DUPLICATE,
    ReasonCode.E_EXPIRED: ResultState.EXPIRED,
    ReasonCode.E_SCHEMA: ResultState.REJECTED,
    ReasonCode.E_INTEGRITY: ResultState.REJECTED,
    ReasonCode.E_FIELDS: ResultState.REJECTED,
    ReasonCode.E_STRATEGY: ResultState.REJECTED,
    ReasonCode.E_ID: ResultState.REJECTED,
    ReasonCode.E_FUTURE: ResultState.REJECTED,
    ReasonCode.E_SYMBOL: ResultState.REJECTED,
    ReasonCode.E_STRUCT: ResultState.REJECTED,
}


# Execution-only result fields. Null for every bridge/transport terminal state; an
# execution consumer may populate them by passing an ``execution`` mapping — the
# bridge itself never fills them (it has no broker).
EXECUTION_RESULT_FIELDS = (
    "broker_order_id", "requested_price", "filled_price", "requested_volume",
    "filled_volume", "slippage", "compliance_decision", "execution_error",
)


def build_result(signal_id, result_id_value, status, reason_code, received_iso,
                 processed_iso, instruction=None, detail=None, execution=None):
    """Construct a result record (spec §9).

    Transport-only by default: execution fields (broker_order_id, filled_*,
    slippage, execution_error, …) are null. They are populated ONLY when an
    execution consumer passes an ``execution`` mapping — the bridge never fills
    them, having no broker of its own (interface compatibility for Phase 3).
    """
    stop_loss = take_profit = None
    if isinstance(instruction, dict):
        stop_loss = instruction.get("stop_loss")
        take_profit = instruction.get("take_profit")
    result = {
        "result_schema_version": 1,
        "signal_id": signal_id,
        "result_id": result_id_value,
        "status": status,
        "reason_code": reason_code,
        "reason_detail": detail or {},
        "received_timestamp": received_iso,
        "processed_timestamp": processed_iso,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
    }
    # execution-only fields: null unless an execution consumer supplied them
    for field in EXECUTION_RESULT_FIELDS:
        result[field] = None
    if isinstance(execution, dict):
        for field in EXECUTION_RESULT_FIELDS:
            if field in execution:
                result[field] = execution[field]
    return result


def build_ack(signal_id, ack_id, received_iso, instruction=None, detail=None):
    """Construct a non-terminal acknowledgement record (Phase 3 execution layer).

    An ack records that a validated instruction was received and execution is
    about to be attempted. It is NOT a terminal result — it never decides an
    outcome and never carries broker fills. It exists so a restart can tell that
    an execution attempt was in flight for this ``signal_id``.
    """
    symbol = direction = None
    if isinstance(instruction, dict):
        symbol = instruction.get("symbol")
        direction = instruction.get("direction")
    return {
        "ack_schema_version": 1,
        "signal_id": signal_id,
        "ack_id": ack_id,
        "status": "ACK",
        "received_timestamp": received_iso,
        "symbol": symbol,
        "direction": direction,
        "detail": detail or {},
    }
