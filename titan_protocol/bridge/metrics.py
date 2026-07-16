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

        # -- ADR-034: socket transport, additive only --
        self._socket_connections_opened_count = 0
        self._socket_connections_closed_count = 0
        self._socket_connections_rejected_count = 0
        self._socket_messages_processed_count = 0
        self._socket_malformed_frame_count = 0
        self._socket_duplicate_or_replayed_seq_count = 0
        self._socket_oversized_frame_count = 0
        self._socket_idle_timeout_count = 0
        self._socket_bytes_received_count = 0
        self._socket_bytes_sent_count = 0

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

    # -- ADR-034: socket transport ----------------------------------

    def record_socket_connection_opened(self) -> None:
        self._socket_connections_opened_count += 1

    def record_socket_connection_closed(self) -> None:
        self._socket_connections_closed_count += 1

    def record_socket_connection_rejected(self) -> None:
        self._socket_connections_rejected_count += 1

    def record_socket_message_processed(self) -> None:
        self._socket_messages_processed_count += 1

    def record_socket_malformed_frame(self) -> None:
        self._socket_malformed_frame_count += 1

    def record_socket_duplicate_or_replayed_seq(self) -> None:
        self._socket_duplicate_or_replayed_seq_count += 1

    def record_socket_oversized_frame(self) -> None:
        self._socket_oversized_frame_count += 1

    def record_socket_idle_timeout(self) -> None:
        self._socket_idle_timeout_count += 1

    def record_socket_bytes_received(self, count: int) -> None:
        self._socket_bytes_received_count += count

    def record_socket_bytes_sent(self, count: int) -> None:
        self._socket_bytes_sent_count += count

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

    # -- ADR-034: socket transport ----------------------------------

    @property
    def socket_connections_opened_count(self) -> int:
        return self._socket_connections_opened_count

    @property
    def socket_connections_closed_count(self) -> int:
        return self._socket_connections_closed_count

    @property
    def socket_connections_rejected_count(self) -> int:
        return self._socket_connections_rejected_count

    @property
    def socket_messages_processed_count(self) -> int:
        return self._socket_messages_processed_count

    @property
    def socket_malformed_frame_count(self) -> int:
        return self._socket_malformed_frame_count

    @property
    def socket_duplicate_or_replayed_seq_count(self) -> int:
        return self._socket_duplicate_or_replayed_seq_count

    @property
    def socket_oversized_frame_count(self) -> int:
        return self._socket_oversized_frame_count

    @property
    def socket_idle_timeout_count(self) -> int:
        return self._socket_idle_timeout_count

    @property
    def socket_bytes_received_count(self) -> int:
        return self._socket_bytes_received_count

    @property
    def socket_bytes_sent_count(self) -> int:
        return self._socket_bytes_sent_count

    def socket_health_snapshot(self) -> dict:
        """One-call observability surface for the socket transport --
        every counter above, in one dict, for `health_check.py`/
        `start.py`'s health snapshot to expose without reaching into
        private attributes."""
        return {
            "connections_opened": self._socket_connections_opened_count,
            "connections_closed": self._socket_connections_closed_count,
            "connections_rejected": self._socket_connections_rejected_count,
            "messages_processed": self._socket_messages_processed_count,
            "malformed_frames": self._socket_malformed_frame_count,
            "duplicate_or_replayed_seq": self._socket_duplicate_or_replayed_seq_count,
            "oversized_frames": self._socket_oversized_frame_count,
            "idle_timeouts": self._socket_idle_timeout_count,
            "bytes_received": self._socket_bytes_received_count,
            "bytes_sent": self._socket_bytes_sent_count,
        }


__all__ = ["BridgeMetrics"]
