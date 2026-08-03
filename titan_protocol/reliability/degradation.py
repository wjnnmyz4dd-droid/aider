"""Graceful degradation (ADR-032 SS2 item 11): a four-level
`DegradationLevel` derived deterministically from aggregate component
health, resource usage, and queue depths -- never from a single noisy
sample."""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from .config import ReliabilityConfig
from .models import ComponentHealth, DegradationLevel, HealthState, QueueDepth, ResourceUsage


def derive_degradation_level(
    component_health: Sequence[ComponentHealth],
    resource_usage: Optional[ResourceUsage],
    queue_depths: Sequence[QueueDepth],
    config: ReliabilityConfig,
) -> Tuple[DegradationLevel, Tuple[str, ...]]:
    reasons: List[str] = []

    unknown_count = sum(1 for c in component_health if c.state == HealthState.UNKNOWN)
    unhealthy_count = sum(1 for c in component_health if c.state == HealthState.UNHEALTHY)
    degraded_count = sum(1 for c in component_health if c.state == HealthState.DEGRADED)

    if unknown_count >= config.unknown_components_for_halted:
        reasons.append(f"{unknown_count} component(s) UNKNOWN (health cannot be established)")
        return DegradationLevel.HALTED, tuple(reasons)

    if resource_usage is not None:
        if resource_usage.cpu_percent is not None and resource_usage.cpu_percent >= config.cpu_critical_threshold_pct:
            reasons.append(f"CPU at {resource_usage.cpu_percent:.1f}% (critical threshold {config.cpu_critical_threshold_pct}%)")
        if resource_usage.memory_percent is not None and resource_usage.memory_percent >= config.memory_critical_threshold_pct:
            reasons.append(f"memory at {resource_usage.memory_percent:.1f}% (critical threshold {config.memory_critical_threshold_pct}%)")

    for queue in queue_depths:
        if queue.depth >= config.queue_critical_depth:
            reasons.append(f"queue {queue.name!r} depth {queue.depth} >= critical threshold {config.queue_critical_depth}")

    if unhealthy_count >= config.unhealthy_components_for_critical or reasons:
        if unhealthy_count:
            reasons.insert(0, f"{unhealthy_count} component(s) UNHEALTHY")
        return DegradationLevel.CRITICAL, tuple(reasons)

    if resource_usage is not None:
        if resource_usage.cpu_percent is not None and resource_usage.cpu_percent >= config.cpu_degraded_threshold_pct:
            reasons.append(f"CPU at {resource_usage.cpu_percent:.1f}% (degraded threshold {config.cpu_degraded_threshold_pct}%)")
        if resource_usage.memory_percent is not None and resource_usage.memory_percent >= config.memory_degraded_threshold_pct:
            reasons.append(f"memory at {resource_usage.memory_percent:.1f}% (degraded threshold {config.memory_degraded_threshold_pct}%)")

    for queue in queue_depths:
        if queue.depth >= config.queue_degraded_depth:
            reasons.append(f"queue {queue.name!r} depth {queue.depth} >= degraded threshold {config.queue_degraded_depth}")

    if degraded_count or reasons:
        if degraded_count:
            reasons.insert(0, f"{degraded_count} component(s) DEGRADED")
        return DegradationLevel.DEGRADED, tuple(reasons)

    return DegradationLevel.NORMAL, ()


__all__ = ["derive_degradation_level"]
