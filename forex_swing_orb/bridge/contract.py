"""Instruction/result contracts, reason codes, and result states (spec §3, §9).

Single source for what a valid on-disk instruction looks like and how results are
shaped. No execution, no broker fields are ever populated by the bridge.
"""

from __future__ import annotations

# Required instruction fields (spec §3). integrity_digest is the bridge transport
# field; the rest come from the strategy engine's instruction (schema_version 1).
REQUIRED_INSTRUCTION_FIELDS = (
    "schema_version", "signal_id", "strategy_id", "strategy_version", "symbol",
    "direction", "entry_price", "stop_loss", "take_profit", "risk_fraction",
    "generated_timestamp", "expiration_timestamp", "evidence_summary",
    "news_eligibility", "integrity_digest",
)

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


def build_result(signal_id, result_id_value, status, reason_code, received_iso,
                 processed_iso, instruction=None, detail=None):
    """Construct a result record (spec §9), transport-only.

    Execution-only fields (broker_order_id, filled_*, slippage, execution_error,
    compliance_decision) are set to null here — they are populated by the future
    execution layer, never by the bridge.
    """
    stop_loss = take_profit = None
    if isinstance(instruction, dict):
        stop_loss = instruction.get("stop_loss")
        take_profit = instruction.get("take_profit")
    return {
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
        # downstream/execution-only (never set by the bridge):
        "broker_order_id": None,
        "requested_price": None,
        "filled_price": None,
        "requested_volume": None,
        "filled_volume": None,
        "slippage": None,
        "compliance_decision": None,
        "execution_error": None,
    }
