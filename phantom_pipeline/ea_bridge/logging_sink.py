"""Structured logging for the EA Bridge (`ADR-023` §4).

Mirrors every prior stage's `logging_sink.py` pattern: one structured
record per event, every field read directly off the object, a logging
failure never propagates into or alters this package's return value.
"""

from __future__ import annotations

import logging

from .models import (
    EAAccountState,
    EmergencyStopState,
    ErrorReport,
    ExecutionReport,
    HeartbeatMessage,
    PositionReport,
    TickMessage,
)

logger = logging.getLogger("phantom_pipeline.ea_bridge")


def _safe_log(level: int, message: str, extra: dict) -> None:
    try:
        logger.log(level, message, extra=extra)
    except Exception:
        # Logging is observability, not a gate (the same discipline every
        # prior stage established) -- a logging failure must never
        # propagate into or alter this package's return value.
        pass


def log_heartbeat(message: HeartbeatMessage) -> None:
    _safe_log(
        logging.DEBUG,
        "ea_bridge.heartbeat",
        {"magic_number": message.magic_number, "connected": message.connected},
    )


def log_account_state(state: EAAccountState) -> None:
    _safe_log(
        logging.INFO,
        "ea_bridge.account_state",
        {"magic_number": state.magic_number, "equity": state.equity, "balance": state.balance},
    )


def log_tick(tick: TickMessage) -> None:
    _safe_log(logging.DEBUG, "ea_bridge.tick", {"symbol": tick.symbol, "bid": tick.bid, "ask": tick.ask})


def log_position_report(position: PositionReport) -> None:
    _safe_log(
        logging.INFO,
        "ea_bridge.position",
        {"position_id": position.position_id, "symbol": position.symbol, "volume": position.volume},
    )


def log_execution_report(report: ExecutionReport, newly_recorded: bool) -> None:
    _safe_log(
        logging.INFO,
        "ea_bridge.execution_report",
        {
            "execution_id": report.execution_id,
            "success": report.success,
            "newly_recorded": newly_recorded,
        },
    )


def log_error_report(error: ErrorReport) -> None:
    _safe_log(
        logging.WARNING,
        "ea_bridge.error_report",
        {"code": error.code, "message": error.message},
    )


def log_emergency_stop(state: EmergencyStopState) -> None:
    _safe_log(logging.CRITICAL, "ea_bridge.emergency_stop", {"active": state.active, "reason": state.reason})


__all__ = [
    "log_heartbeat",
    "log_account_state",
    "log_tick",
    "log_position_report",
    "log_execution_report",
    "log_error_report",
    "log_emergency_stop",
]
