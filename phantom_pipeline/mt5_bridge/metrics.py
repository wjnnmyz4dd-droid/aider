"""MT5-Bridge-only metrics surface (ADR-008 §12).

Export-only, additive — recording a metric has zero effect on any
returned output. No Dashboard, no Prometheus, no Analytics here — this
is the MT5 Bridge's own metric surface only, the same discipline every
prior stage's metrics module already established.
"""

from __future__ import annotations

from typing import Dict, List


class MT5BridgeMetrics:
    def __init__(self) -> None:
        self._submission_latencies_seconds: List[float] = []
        self._broker_latencies_seconds: List[float] = []
        self._fill_latencies_seconds: List[float] = []
        self._reconnect_count: int = 0
        self._timeout_count: int = 0
        self._broker_reject_count: int = 0
        self._phantom_side_reject_count: int = 0
        self._heartbeat_status: Dict[str, int] = {}
        self._synchronization_status: Dict[str, int] = {}

    def record_submission_latency(self, seconds: float) -> None:
        self._submission_latencies_seconds.append(seconds)

    def record_broker_latency(self, seconds: float) -> None:
        self._broker_latencies_seconds.append(seconds)

    def record_fill_latency(self, seconds: float) -> None:
        self._fill_latencies_seconds.append(seconds)

    def record_reconnect(self) -> None:
        self._reconnect_count += 1

    def record_timeout(self) -> None:
        self._timeout_count += 1

    def record_broker_reject(self) -> None:
        self._broker_reject_count += 1

    def record_phantom_side_reject(self) -> None:
        self._phantom_side_reject_count += 1

    def record_heartbeat_status(self, ok: bool) -> None:
        key = "ok" if ok else "missed"
        self._heartbeat_status[key] = self._heartbeat_status.get(key, 0) + 1

    def record_synchronization_status(self, in_sync: bool) -> None:
        key = "in_sync" if in_sync else "discrepancy"
        self._synchronization_status[key] = self._synchronization_status.get(key, 0) + 1

    @property
    def average_submission_latency_seconds(self) -> float:
        if not self._submission_latencies_seconds:
            return 0.0
        return sum(self._submission_latencies_seconds) / len(self._submission_latencies_seconds)

    @property
    def average_broker_latency_seconds(self) -> float:
        if not self._broker_latencies_seconds:
            return 0.0
        return sum(self._broker_latencies_seconds) / len(self._broker_latencies_seconds)

    @property
    def average_fill_latency_seconds(self) -> float:
        if not self._fill_latencies_seconds:
            return 0.0
        return sum(self._fill_latencies_seconds) / len(self._fill_latencies_seconds)

    @property
    def reconnect_count(self) -> int:
        return self._reconnect_count

    @property
    def timeout_count(self) -> int:
        return self._timeout_count

    @property
    def broker_reject_count(self) -> int:
        return self._broker_reject_count

    @property
    def phantom_side_reject_count(self) -> int:
        return self._phantom_side_reject_count

    @property
    def heartbeat_status(self) -> Dict[str, int]:
        return dict(self._heartbeat_status)

    @property
    def synchronization_status(self) -> Dict[str, int]:
        return dict(self._synchronization_status)
