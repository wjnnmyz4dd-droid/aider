"""Watchdog integration (ADR-031 SS9): a fresh, minimal module mirroring
`ADR-011`'s vocabulary (component/kind/timeout detection) -- it never
imports `phantom_pipeline.watchdog` (ADR-031 SS0: doing so would make a
reference-only tree a live dependency of this pipeline, the one
exception this session has never made). Detects four timeout kinds by
comparing recorded stage durations against configured thresholds, and
exposes a bounded, explicit restart allow-list that structurally
excludes Compliance Engine -- "never bypass Compliance" is enforced by
Compliance never appearing in the list, not by a runtime check."""

from __future__ import annotations

from typing import List, Tuple

from .config import RuntimeConfig
from .models import CycleStage, StageTiming, WatchdogSignal, WatchdogTimeoutKind

# Compliance Engine is deliberately absent -- restarting it would mean
# constructing a fresh instance mid-cycle, which could reset its own
# internal state in a way that bypasses a decision already in flight.
# Restarting any of these four is safe: every one is a stateless,
# cheap-to-reconstruct engine (ADR-024/025/026/027's own statelessness
# guarantees).
APPROVED_RESTART_COMPONENTS: Tuple[str, ...] = (
    "evidence_engine", "market_intelligence", "strategy_engine", "risk_engine",
)

_ENGINE_STAGES = (CycleStage.EVIDENCE, CycleStage.MARKET_INTELLIGENCE, CycleStage.STRATEGY, CycleStage.RISK)


def detect_timeouts(
    stage_timings: Tuple[StageTiming, ...], total_duration_ms: float, config: RuntimeConfig,
) -> Tuple[WatchdogSignal, ...]:
    signals: List[WatchdogSignal] = []

    for timing in stage_timings:
        if timing.stage in _ENGINE_STAGES and timing.duration_ms > config.engine_timeout_ms:
            signals.append(WatchdogSignal(
                kind=WatchdogTimeoutKind.ENGINE, component=timing.stage.value,
                duration_ms=timing.duration_ms, threshold_ms=config.engine_timeout_ms,
            ))
        if timing.stage is CycleStage.BRIDGE and timing.duration_ms > config.bridge_timeout_ms:
            signals.append(WatchdogSignal(
                kind=WatchdogTimeoutKind.BRIDGE, component="bridge",
                duration_ms=timing.duration_ms, threshold_ms=config.bridge_timeout_ms,
            ))

    if total_duration_ms > config.runtime_timeout_ms:
        signals.append(WatchdogSignal(
            kind=WatchdogTimeoutKind.RUNTIME, component="runtime",
            duration_ms=total_duration_ms, threshold_ms=config.runtime_timeout_ms,
        ))

    return tuple(signals)


def detect_snapshot_timeout(component: str, snapshot_age_ms: float, config: RuntimeConfig) -> Tuple[WatchdogSignal, ...]:
    if snapshot_age_ms > config.snapshot_timeout_ms:
        return (WatchdogSignal(
            kind=WatchdogTimeoutKind.SNAPSHOT, component=component,
            duration_ms=snapshot_age_ms, threshold_ms=config.snapshot_timeout_ms,
        ),)
    return ()


def is_approved_for_restart(component: str) -> bool:
    return component in APPROVED_RESTART_COMPONENTS


__all__ = ["APPROVED_RESTART_COMPONENTS", "detect_timeouts", "detect_snapshot_timeout", "is_approved_for_restart"]
