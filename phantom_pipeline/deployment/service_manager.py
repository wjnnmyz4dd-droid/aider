"""Windows Service Manager (Phase 5) — whole-process/VPS-level service
supervision: auto-start after reboot, crash/hang detection and restart,
restart-reason logging.

**Not a duplicate of `watchdog.real_recovery_executor`.** That module
performs Watchdog's own *in-pipeline* component recovery, decided by
`WatchdogEngine.attempt_recovery`'s eligibility/backoff/freeze logic, and
only runs once Watchdog itself is already up. This manager operates one
layer below that: it is what starts the whole stack (including the
process Watchdog itself runs inside) after a VPS reboot, and detects a
service that has crashed or hung entirely independently of whether
Watchdog is even alive to notice.

Every OS-touching action is an injected per-service callable (`start`/
`stop`/`is_running`/`is_responsive`), the same dependency-injection shape
`RealRecoveryActionExecutor` already proved out — so this module has zero
real Windows/`systemctl`/`nssm` calls of its own and is fully testable on
any host.

**Hard rule (task-mandated): never restart MT5 while a trade is actively
executing.** `trade_in_progress` is an injected, per-check probe (e.g.
backed by `PositionManager`'s own `LifecycleState`s — `FILLED`,
`PROTECTED`, `TRAILING`, `SCALING`, `CLOSING` all mean "a trade is live");
when it returns `True` for the `mt5` service, any restart this manager
would otherwise perform is skipped and logged as a deferred attempt, never
silently dropped.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Dict, List, Tuple

from .models import RestartReason, RestartRecord, ServiceState, ServiceStatus

MT5_SERVICE_NAME = "mt5"


@dataclass
class _ManagedService:
    name: str
    start: Callable[[], bool]
    stop: Callable[[], bool]
    is_running: Callable[[], bool]
    is_responsive: Callable[[], bool]


class WindowsServiceManager:
    def __init__(self, trade_in_progress: Callable[[], bool] = lambda: False) -> None:
        self._services: Dict[str, _ManagedService] = {}
        self._trade_in_progress = trade_in_progress
        self._restart_history: List[RestartRecord] = []

    def register_service(
        self,
        name: str,
        start: Callable[[], bool],
        stop: Callable[[], bool],
        is_running: Callable[[], bool],
        is_responsive: Callable[[], bool],
    ) -> None:
        self._services[name] = _ManagedService(name, start, stop, is_running, is_responsive)

    @property
    def restart_history(self) -> Tuple[RestartRecord, ...]:
        return tuple(self._restart_history)

    def ensure_started_after_reboot(self, now: datetime) -> Tuple[ServiceStatus, ...]:
        statuses = []
        for service in self._services.values():
            if self._safe_call(service.is_running):
                statuses.append(ServiceStatus(service.name, ServiceState.RUNNING, "already running", now))
                continue
            started = self._safe_call(service.start)
            state = ServiceState.RUNNING if started else ServiceState.CRASHED
            detail = "started after reboot" if started else "start failed"
            statuses.append(ServiceStatus(service.name, state, detail, now))
        return tuple(statuses)

    def check_and_restart_crashed(self, now: datetime) -> Tuple[RestartRecord, ...]:
        return self._check_and_restart(now, RestartReason.CRASH_DETECTED, lambda s: not self._safe_call(s.is_running))

    def check_and_restart_hung(self, now: datetime) -> Tuple[RestartRecord, ...]:
        return self._check_and_restart(
            now,
            RestartReason.HANG_DETECTED,
            lambda s: self._safe_call(s.is_running) and not self._safe_call(s.is_responsive),
        )

    def _check_and_restart(
        self, now: datetime, reason: RestartReason, needs_restart: Callable[[_ManagedService], bool]
    ) -> Tuple[RestartRecord, ...]:
        records = []
        for service in self._services.values():
            if not needs_restart(service):
                continue
            if service.name == MT5_SERVICE_NAME and self._safe_call(self._trade_in_progress):
                record = RestartRecord(
                    component=service.name,
                    reason=reason,
                    detail="restart deferred: a trade is actively executing on MT5",
                    timestamp=now,
                    succeeded=False,
                )
                self._restart_history.append(record)
                records.append(record)
                continue
            self._safe_call(service.stop)
            succeeded = self._safe_call(service.start)
            record = RestartRecord(
                component=service.name,
                reason=reason,
                detail="restart succeeded" if succeeded else "restart failed",
                timestamp=now,
                succeeded=succeeded,
            )
            self._restart_history.append(record)
            records.append(record)
        return tuple(records)

    def health_check_all(self, now: datetime) -> Tuple[ServiceStatus, ...]:
        statuses = []
        for service in self._services.values():
            running = self._safe_call(service.is_running)
            if not running:
                statuses.append(ServiceStatus(service.name, ServiceState.CRASHED, "not running", now))
                continue
            responsive = self._safe_call(service.is_responsive)
            state = ServiceState.RUNNING if responsive else ServiceState.DEGRADED
            detail = "healthy" if responsive else "running but unresponsive"
            statuses.append(ServiceStatus(service.name, state, detail, now))
        return tuple(statuses)

    @staticmethod
    def _safe_call(callback: Callable[[], bool]) -> bool:
        try:
            return bool(callback())
        except Exception:
            return False


__all__ = ["WindowsServiceManager", "MT5_SERVICE_NAME"]
