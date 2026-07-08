"""EA-Bridge-only metrics surface (`ADR-023` §4).

Export-only: recording a metric has zero effect on any returned value —
the same "additive, changes nothing" discipline every prior stage's
metrics module already established.
"""

from __future__ import annotations


class EABridgeMetrics:
    def __init__(self) -> None:
        self._heartbeat_count = 0
        self._account_update_count = 0
        self._tick_count = 0
        self._bar_count = 0
        self._position_update_count = 0
        self._execution_report_count = 0
        self._duplicate_execution_report_count = 0
        self._error_report_count = 0
        self._emergency_stop_count = 0
        self._rejected_command_count = 0

    def record_heartbeat(self) -> None:
        self._heartbeat_count += 1

    def record_account_update(self) -> None:
        self._account_update_count += 1

    def record_tick(self) -> None:
        self._tick_count += 1

    def record_bars(self, count: int) -> None:
        self._bar_count += count

    def record_position_update(self) -> None:
        self._position_update_count += 1

    def record_execution_report(self) -> None:
        self._execution_report_count += 1

    def record_duplicate_execution_report(self) -> None:
        self._duplicate_execution_report_count += 1

    def record_error_report(self) -> None:
        self._error_report_count += 1

    def record_emergency_stop(self) -> None:
        self._emergency_stop_count += 1

    def record_rejected_command(self) -> None:
        self._rejected_command_count += 1

    @property
    def heartbeat_count(self) -> int:
        return self._heartbeat_count

    @property
    def account_update_count(self) -> int:
        return self._account_update_count

    @property
    def tick_count(self) -> int:
        return self._tick_count

    @property
    def bar_count(self) -> int:
        return self._bar_count

    @property
    def position_update_count(self) -> int:
        return self._position_update_count

    @property
    def execution_report_count(self) -> int:
        return self._execution_report_count

    @property
    def duplicate_execution_report_count(self) -> int:
        return self._duplicate_execution_report_count

    @property
    def error_report_count(self) -> int:
        return self._error_report_count

    @property
    def emergency_stop_count(self) -> int:
        return self._emergency_stop_count

    @property
    def rejected_command_count(self) -> int:
        return self._rejected_command_count


__all__ = ["EABridgeMetrics"]
