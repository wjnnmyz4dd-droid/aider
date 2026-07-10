"""Memory and CPU monitoring (ADR-032 SS2 items 6-7). Every sampler is
an injected callable, so `ReliabilityEngine` has no real platform
dependency of its own -- a small stdlib-only, Linux/POSIX-compatible
default is provided; a real deployment injects its own for its actual
platform (mirrors, never imports, `phantom_pipeline/deployment/
monitoring.py`'s own pattern -- ADR-032 SS0). A sampler's failure
degrades that one reading to `None`, never aborts the whole snapshot
(ADR-032 Hard Rule 4)."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Callable, Optional

from .models import ResourceUsage

CpuSampler = Callable[[], Optional[float]]
MemorySampler = Callable[[], Optional[float]]


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


def sample_resource_usage(now: datetime, cpu_sampler: CpuSampler = default_cpu_sampler, memory_sampler: MemorySampler = default_memory_sampler) -> ResourceUsage:
    try:
        cpu_percent = cpu_sampler()
    except Exception:  # noqa: BLE001 -- a sampler failure degrades this one field
        cpu_percent = None
    try:
        memory_percent = memory_sampler()
    except Exception:  # noqa: BLE001
        memory_percent = None
    return ResourceUsage(cpu_percent=cpu_percent, memory_percent=memory_percent, sampled_at=now)


__all__ = ["CpuSampler", "MemorySampler", "default_cpu_sampler", "default_memory_sampler", "sample_resource_usage"]
