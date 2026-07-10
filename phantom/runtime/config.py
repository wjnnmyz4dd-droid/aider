"""Configuration for the Runtime Orchestrator (Phase 3A, ADR-031)."""

from __future__ import annotations

from dataclasses import dataclass

RUNTIME_VERSION = "1.0.0"


@dataclass(frozen=True)
class RuntimeConfig:
    magic_number: int = 20260710
    max_slippage_points: int = 20

    # Performance targets (ADR-031 SS10).
    max_cycle_duration_ms: float = 250.0

    # Watchdog integration thresholds (ADR-031 SS9) -- per-stage duration
    # above these is reported as a timeout signal, never silently ignored.
    engine_timeout_ms: float = 100.0
    runtime_timeout_ms: float = 250.0
    snapshot_timeout_ms: float = 50.0
    bridge_timeout_ms: float = 100.0


__all__ = ["RUNTIME_VERSION", "RuntimeConfig"]
