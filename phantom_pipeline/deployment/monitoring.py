"""Production Monitoring (Phase 5) — CPU/RAM/disk/network-latency/MT5
connection quality/Python process health/Dashboard health.

Feeds `dashboard.config.DashboardConfig.infrastructure_components`
(`cpu`, `memory`, `disk`, `network`, `vps`, `watchdog`) — Dashboard
already declares that it expects readings for these; no producer existed
for them until this module. `ProductionMonitoring` is that producer, read
by whoever wires the system together and handed to Dashboard the same
way every other already-produced object is — this module never renders a
view itself and is not a second dashboard.

Every sampler is an injected callable so this class has no real
Windows/psutil/MT5 dependency of its own; a small stdlib-only,
Linux/POSIX-compatible default is provided for local testing (a real
Windows deployment injects its own, per the operator docs). Each sampler
call is wrapped so an individual sampler's failure degrades that one
reading to `None` (fail-closed per-field) rather than aborting the whole
snapshot.
"""

from __future__ import annotations

import os
import shutil
import socket
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional

from .models import MonitoringSnapshot, ResourceSample


def default_cpu_sampler() -> Optional[float]:
    try:
        cpu_count = os.cpu_count() or 1
        load1, _, _ = os.getloadavg()
        return min(100.0, (load1 / cpu_count) * 100.0)
    except (OSError, AttributeError):
        return None


def default_memory_sampler() -> Optional[float]:
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as handle:
            values = {}
            for line in handle:
                key, _, rest = line.partition(":")
                values[key.strip()] = int(rest.strip().split()[0])
        total = values.get("MemTotal")
        available = values.get("MemAvailable")
        if not total:
            return None
        used = total - (available if available is not None else 0)
        return (used / total) * 100.0
    except (OSError, ValueError, IndexError):
        return None


def default_disk_sampler(path: str = "/") -> Callable[[], Optional[float]]:
    def _sample() -> Optional[float]:
        try:
            usage = shutil.disk_usage(path)
            return (usage.used / usage.total) * 100.0
        except OSError:
            return None

    return _sample


def default_network_latency_sampler(host: str = "127.0.0.1", port: int = 443, timeout: float = 2.0) -> Callable[[], Optional[float]]:
    def _sample() -> Optional[float]:
        start = time.monotonic()
        try:
            with socket.create_connection((host, port), timeout=timeout):
                pass
        except OSError:
            return None
        return (time.monotonic() - start) * 1000.0

    return _sample


def default_python_process_health_checker(pid: Optional[int] = None) -> Callable[[], bool]:
    target_pid = pid if pid is not None else os.getpid()

    def _check() -> bool:
        try:
            os.kill(target_pid, 0)
            return True
        except OSError:
            return False

    return _check


@dataclass(frozen=True)
class MonitoringThresholds:
    cpu_percent_max: float = 85.0
    memory_percent_max: float = 90.0
    disk_percent_max: float = 90.0
    network_latency_ms_max: float = 500.0


class ProductionMonitoring:
    def __init__(
        self,
        cpu_sampler: Callable[[], Optional[float]] = default_cpu_sampler,
        memory_sampler: Callable[[], Optional[float]] = default_memory_sampler,
        disk_sampler: Callable[[], Optional[float]] = default_disk_sampler(),
        network_latency_sampler: Callable[[], Optional[float]] = default_network_latency_sampler(),
        mt5_connection_checker: Callable[[], bool] = lambda: False,
        python_process_health_checker: Callable[[], bool] = default_python_process_health_checker(),
        dashboard_health_checker: Callable[[], bool] = lambda: False,
    ) -> None:
        self._cpu_sampler = cpu_sampler
        self._memory_sampler = memory_sampler
        self._disk_sampler = disk_sampler
        self._network_latency_sampler = network_latency_sampler
        self._mt5_connection_checker = mt5_connection_checker
        self._python_process_health_checker = python_process_health_checker
        self._dashboard_health_checker = dashboard_health_checker

    def sample(self, now: datetime) -> MonitoringSnapshot:
        resource = ResourceSample(
            cpu_percent=self._safe(self._cpu_sampler),
            memory_percent=self._safe(self._memory_sampler),
            disk_percent=self._safe(self._disk_sampler),
            network_latency_ms=self._safe(self._network_latency_sampler),
            timestamp=now,
        )
        return MonitoringSnapshot(
            resource=resource,
            mt5_connection_healthy=self._safe_bool(self._mt5_connection_checker),
            python_process_healthy=self._safe_bool(self._python_process_health_checker),
            dashboard_healthy=self._safe_bool(self._dashboard_health_checker),
            timestamp=now,
        )

    def evaluate(self, snapshot: MonitoringSnapshot, thresholds: MonitoringThresholds = MonitoringThresholds()) -> tuple:
        breaches = []
        r = snapshot.resource
        if r.cpu_percent is not None and r.cpu_percent > thresholds.cpu_percent_max:
            breaches.append(f"CPU {r.cpu_percent:.1f}% exceeds {thresholds.cpu_percent_max:.1f}%")
        if r.memory_percent is not None and r.memory_percent > thresholds.memory_percent_max:
            breaches.append(f"Memory {r.memory_percent:.1f}% exceeds {thresholds.memory_percent_max:.1f}%")
        if r.disk_percent is not None and r.disk_percent > thresholds.disk_percent_max:
            breaches.append(f"Disk {r.disk_percent:.1f}% exceeds {thresholds.disk_percent_max:.1f}%")
        if r.network_latency_ms is not None and r.network_latency_ms > thresholds.network_latency_ms_max:
            breaches.append(f"Network latency {r.network_latency_ms:.1f}ms exceeds {thresholds.network_latency_ms_max:.1f}ms")
        return tuple(breaches)

    @staticmethod
    def _safe(sampler: Callable[[], Optional[float]]) -> Optional[float]:
        try:
            return sampler()
        except Exception:
            return None

    @staticmethod
    def _safe_bool(checker: Callable[[], bool]) -> Optional[bool]:
        try:
            return bool(checker())
        except Exception:
            return None


__all__ = [
    "ProductionMonitoring",
    "MonitoringThresholds",
    "default_cpu_sampler",
    "default_memory_sampler",
    "default_disk_sampler",
    "default_network_latency_sampler",
    "default_python_process_health_checker",
]
