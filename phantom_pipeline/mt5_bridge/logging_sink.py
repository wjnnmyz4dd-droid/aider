"""Structured logging (ADR-008 §11). Structured logging only — no
`print()`.

Every event is logged: submission, acknowledgement, execution, reject,
fill, disconnect, reconnect, timeout, synchronization (status change).
Every logged event carries `trace_id` and `execution_id` (§7, §11),
making every broker interaction attributable to a specific decision
without re-running anything. A logging failure never propagates into or
alters engine behavior (logging is observability, not a gate) — the
same discipline every prior stage's logging sink already established.
"""

from __future__ import annotations

import logging

from .models import (
    BrokerAcknowledgement,
    BrokerError,
    ConnectionStatus,
    ExecutionReceipt,
    FillReport,
    SynchronizationStatus,
)

logger = logging.getLogger("phantom_pipeline.mt5_bridge")


def _safe_log(level: int, msg: str, extra: dict) -> None:
    try:
        logger.log(level, msg, extra=extra)
    except Exception:
        pass


def log_submission(execution_id: str, trace_id: str, request_kind: str, level: int = logging.INFO) -> None:
    _safe_log(
        level,
        "mt5_bridge.submission",
        {"execution_id": execution_id, "trace_id": trace_id, "request_kind": request_kind},
    )


def log_acknowledgement(ack: BrokerAcknowledgement, level: int = logging.INFO) -> None:
    _safe_log(
        level,
        "mt5_bridge.acknowledgement",
        {
            "execution_id": ack.execution_id,
            "trace_id": ack.trace_id,
            "request_kind": ack.request_kind.value,
            "broker_ref": ack.broker_ref,
        },
    )


def log_execution(receipt: ExecutionReceipt, level: int = logging.INFO) -> None:
    _safe_log(
        level,
        "mt5_bridge.execution",
        {
            "execution_id": receipt.execution_id,
            "trace_id": receipt.trace_id,
            "request_kind": receipt.request_kind.value,
            "filled_price": receipt.filled_price,
            "filled_size": receipt.filled_size,
        },
    )


def log_reject(error: BrokerError, level: int = logging.WARNING) -> None:
    _safe_log(
        level,
        "mt5_bridge.reject",
        {
            "execution_id": error.execution_id,
            "trace_id": error.trace_id,
            "request_kind": error.request_kind.value,
            "reason": error.reason,
        },
    )


def log_phantom_side_reject(
    execution_id: str, trace_id: str, reason: str, level: int = logging.WARNING
) -> None:
    """A Phantom-side reject never reaches the broker at all — distinct
    from `log_reject`'s broker-returned `BrokerError` (ADR-008 §5)."""
    _safe_log(
        level,
        "mt5_bridge.phantom_side_reject",
        {"execution_id": execution_id, "trace_id": trace_id, "reason": reason},
    )


def log_fill(fill: FillReport, level: int = logging.INFO) -> None:
    _safe_log(
        level,
        "mt5_bridge.fill",
        {
            "execution_id": fill.execution_id,
            "trace_id": fill.trace_id,
            "fill_price": fill.fill_price,
            "fill_size": fill.fill_size,
        },
    )


def log_disconnect(status: ConnectionStatus, level: int = logging.WARNING) -> None:
    _safe_log(level, "mt5_bridge.disconnect", {"state": status.state.value, "detail": status.detail})


def log_reconnect(status: ConnectionStatus, level: int = logging.INFO) -> None:
    _safe_log(level, "mt5_bridge.reconnect", {"state": status.state.value, "detail": status.detail})


def log_timeout(execution_id: str, trace_id: str, stage: str, level: int = logging.WARNING) -> None:
    _safe_log(level, "mt5_bridge.timeout", {"execution_id": execution_id, "trace_id": trace_id, "stage": stage})


def log_synchronization(status: SynchronizationStatus, level: int = logging.INFO) -> None:
    _safe_log(
        level,
        "mt5_bridge.synchronization",
        {"in_sync": status.in_sync, "discrepancies": list(status.discrepancies)},
    )
