"""Bridge-only metrics surface (Phase 1).

Export-only: recording a metric has zero effect on any returned value.
"""

from __future__ import annotations


class BridgeMetrics:
    def __init__(self) -> None:
        self._heartbeat_count = 0
        self._account_update_count = 0
        self._position_update_count = 0
        self._pending_order_update_count = 0
        self._command_submitted_count = 0
        self._command_rejected_count = 0
        self._execution_report_count = 0
        self._duplicate_execution_report_count = 0
        self._trade_transaction_count = 0
        self._trade_transaction_drift_count = 0
        self._error_report_count = 0
        self._emergency_stop_count = 0

    def record_heartbeat(self) -> None:
        self._heartbeat_count += 1

    def record_account_update(self) -> None:
        self._account_update_count += 1

    def record_position_update(self) -> None:
        self._position_update_count += 1

    def record_pending_order_update(self) -> None:
        self._pending_order_update_count += 1

    def record_command_submitted(self) -> None:
        self._command_submitted_count += 1

    def record_command_rejected(self) -> None:
        self._command_rejected_count += 1

    def record_execution_report(self) -> None:
        self._execution_report_count += 1

    def record_duplicate_execution_report(self) -> None:
        self._duplicate_execution_report_count += 1

    def record_trade_transaction(self) -> None:
        self._trade_transaction_count += 1

    def record_trade_transaction_drift(self) -> None:
        self._trade_transaction_drift_count += 1

    def record_error_report(self) -> None:
        self._error_report_count += 1

    def record_emergency_stop(self) -> None:
        self._emergency_stop_count += 1

    @property
    def heartbeat_count(self) -> int:
        return self._heartbeat_count

    @property
    def account_update_count(self) -> int:
        return self._account_update_count

    @property
    def position_update_count(self) -> int:
        return self._position_update_count

    @property
    def pending_order_update_count(self) -> int:
        return self._pending_order_update_count

    @property
    def command_submitted_count(self) -> int:
        return self._command_submitted_count

    @property
    def command_rejected_count(self) -> int:
        return self._command_rejected_count

    @property
    def execution_report_count(self) -> int:
        return self._execution_report_count

    @property
    def duplicate_execution_report_count(self) -> int:
        return self._duplicate_execution_report_count

    @property
    def trade_transaction_count(self) -> int:
        return self._trade_transaction_count

    @property
    def trade_transaction_drift_count(self) -> int:
        return self._trade_transaction_drift_count

    @property
    def error_report_count(self) -> int:
        return self._error_report_count

    @property
    def emergency_stop_count(self) -> int:
        return self._emergency_stop_count


__all__ = ["BridgeMetrics"]
