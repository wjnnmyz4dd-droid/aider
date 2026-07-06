"""Production Deployment Manager (Phase 5) — one-command startup and
shutdown, with automatic dependency-ordered sequencing.

`ServiceDefinition.depends_on` names are resolved into a single
deterministic startup order via topological sort (Kahn's algorithm); the
reverse of that order is used for graceful shutdown, so nothing is ever
stopped before something that depends on it. Dependency verification runs
*before* any service is started (fail-closed: a failed check aborts the
entire startup, starting nothing) — mirroring every pipeline stage's own
"never proceed on a missing/invalid input" posture.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .models import ServiceDefinition, ServiceState, ServiceStatus, ShutdownResult, StartupResult


def _topological_order(services: Sequence[ServiceDefinition]) -> List[ServiceDefinition]:
    by_name: Dict[str, ServiceDefinition] = {s.name: s for s in services}
    visited: Dict[str, int] = {}  # 0=visiting, 1=done
    order: List[ServiceDefinition] = []

    def visit(service: ServiceDefinition) -> None:
        state = visited.get(service.name)
        if state == 1:
            return
        if state == 0:
            raise ValueError(f"circular service dependency detected at {service.name!r}")
        visited[service.name] = 0
        for dep_name in service.depends_on:
            dep = by_name.get(dep_name)
            if dep is not None:
                visit(dep)
        visited[service.name] = 1
        order.append(service)

    for service in services:
        visit(service)
    return order


class ProductionDeploymentManager:
    def __init__(
        self,
        services: Sequence[ServiceDefinition],
        dependency_checks: Sequence[Callable[[], Optional[str]]] = (),
    ) -> None:
        self._startup_order = _topological_order(services)
        self._shutdown_order = list(reversed(self._startup_order))
        self._dependency_checks = tuple(dependency_checks)

    def verify_dependencies(self) -> Tuple[str, ...]:
        failures = []
        for check in self._dependency_checks:
            try:
                result = check()
            except Exception as exc:  # a check must never abort verification itself
                result = f"dependency check raised: {exc!r}"
            if result:
                failures.append(result)
        return tuple(failures)

    def start_all(self, now: datetime) -> StartupResult:
        failures = self.verify_dependencies()
        if failures:
            return StartupResult(statuses=(), all_started=False, aborted_reason="; ".join(failures))

        statuses = []
        all_started = True
        for service in self._startup_order:
            started = self._safe_call(service.start)
            if not started:
                statuses.append(ServiceStatus(service.name, ServiceState.CRASHED, "start failed", now))
                all_started = False
                break
            healthy = self._safe_call(service.health_check)
            state = ServiceState.RUNNING if healthy else ServiceState.DEGRADED
            detail = "started and healthy" if healthy else "started but health check failed"
            statuses.append(ServiceStatus(service.name, state, detail, now))
            if not healthy:
                all_started = False
                break
        return StartupResult(statuses=tuple(statuses), all_started=all_started, aborted_reason=None)

    def stop_all(self, now: datetime) -> ShutdownResult:
        statuses = []
        all_stopped = True
        for service in self._shutdown_order:
            stopped = self._safe_call(service.stop)
            state = ServiceState.STOPPED if stopped else ServiceState.CRASHED
            detail = "stopped gracefully" if stopped else "stop failed"
            statuses.append(ServiceStatus(service.name, state, detail, now))
            if not stopped:
                all_stopped = False
        return ShutdownResult(statuses=tuple(statuses), all_stopped=all_stopped)

    def health_check_all(self, now: datetime) -> Tuple[ServiceStatus, ...]:
        statuses = []
        for service in self._startup_order:
            healthy = self._safe_call(service.health_check)
            state = ServiceState.RUNNING if healthy else ServiceState.DEGRADED
            statuses.append(ServiceStatus(service.name, state, "healthy" if healthy else "unhealthy", now))
        return tuple(statuses)

    @staticmethod
    def _safe_call(callback: Callable[[], bool]) -> bool:
        try:
            return bool(callback())
        except Exception:
            return False


__all__ = ["ProductionDeploymentManager"]
