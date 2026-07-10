"""Structured logging for the PhantomBridgeEA bridge.

One structured record per event, every field read directly off the
object, a logging failure never propagates into or alters this
package's return value. Covers the "structured logging," "error
codes," "execution reports," and "trade lifecycle logging" Phase 1
requirements in one place.
"""

from __future__ import annotations

import logging

from .models import (
    AccountState,
    EmergencyStopState,
    ErrorReport,
    ExecutionReport,
    HeartbeatMessage,
    PendingOrderReport,
    PositionReport,
    TradeCommand,
    TradeTransactionReport,
)

logger = logging.getLogger("phantom.bridge")


def _safe_log(level: int, message: str, extra: dict) -> None:
    try:
        logger.log(level, message, extra=extra)
    except Exception:
        # Logging is observability, not a gate -- a logging failure
        # must never propagate into or alter this package's behavior.
        pass


def log_heartbeat(message: HeartbeatMessage) -> None:
    _safe_log(
        logging.DEBUG,
        "bridge.heartbeat",
        {"magic_number": message.magic_number, "terminal_connected": message.terminal_connected},
    )


def log_account_state(state: AccountState) -> None:
    _safe_log(
        logging.INFO,
        "bridge.account_state",
        {"magic_number": state.magic_number, "equity": state.equity, "balance": state.balance},
    )


def log_positions(positions_count: int, magic_number: int) -> None:
    _safe_log(logging.DEBUG, "bridge.positions", {"count": positions_count, "magic_number": magic_number})


def log_pending_orders(orders_count: int, magic_number: int) -> None:
    _safe_log(logging.DEBUG, "bridge.pending_orders", {"count": orders_count, "magic_number": magic_number})


def log_command_submitted(command: TradeCommand, rejected_reason: str) -> None:
    _safe_log(
        logging.INFO,
        "bridge.command_submitted",
        {
            "correlation_id": command.correlation_id,
            "command_kind": command.command_kind.value,
            "rejected_reason": rejected_reason,
        },
    )


def log_command_delivered(correlation_id: str) -> None:
    _safe_log(logging.INFO, "bridge.command_delivered", {"correlation_id": correlation_id})


def log_execution_report(report: ExecutionReport, newly_recorded: bool) -> None:
    _safe_log(
        logging.INFO,
        "bridge.execution_report",
        {
            "correlation_id": report.correlation_id,
            "success": report.success,
            "error_code": report.error_code,
            "newly_recorded": newly_recorded,
        },
    )


def log_trade_transaction(report: TradeTransactionReport, matched: bool) -> None:
    _safe_log(
        logging.INFO if matched else logging.WARNING,
        "bridge.trade_transaction",
        {
            "deal_ticket": report.deal_ticket,
            "order_ticket": report.order_ticket,
            "transaction_type": report.transaction_type,
            "matched_known_execution": matched,
        },
    )


def log_error_report(error: ErrorReport) -> None:
    _safe_log(
        logging.WARNING,
        "bridge.error_report",
        # "message" collides with a `logging.LogRecord`'s own reserved
        # attribute -- passing it via `extra` raises `KeyError: "Attempt
        # to overwrite 'message' in LogRecord"`, silently swallowed by
        # `_safe_log`'s bare except, so every error report was logged as
        # a no-op. Renamed to avoid the collision (confirmed via Phase
        # 1.5 validation: this event never appeared in captured logs).
        {"error_code": error.error_code, "error_message": error.message},
    )


def log_emergency_stop(state: EmergencyStopState) -> None:
    _safe_log(
        logging.CRITICAL,
        "bridge.emergency_stop",
        {"active": state.active, "reason": state.reason},
    )


__all__ = [
    "log_heartbeat",
    "log_account_state",
    "log_positions",
    "log_pending_orders",
    "log_command_submitted",
    "log_command_delivered",
    "log_execution_report",
    "log_trade_transaction",
    "log_error_report",
    "log_emergency_stop",
]
