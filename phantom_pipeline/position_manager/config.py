"""Versioned configuration for the Position Manager (ADR-009 §4, §8).

Every distance/duration/threshold here is a tunable implementation
default, never architecture (`CLAUDE.md` §7, §3) — the same discipline
every prior stage's config module already established. Distances are
expressed in price units (consistent with `RiskEngine.decide`'s
`stop_distance` convention), not percentages or fractions of account
equity — a legitimate, documented Phase 1 simplification since no
upstream object persists a dollar-denominated position size this stage
could otherwise use (see `models.LivePositionState`'s docstring).
"""

from __future__ import annotations

from dataclasses import dataclass

POSITION_MANAGER_VERSION = "1.0.0-phase1"


@dataclass(frozen=True)
class PositionManagerConfig:
    """`cooldown_seconds` throttles every action-producing rule except
    `EMERGENCY_CLOSE`, which must never be throttled — it is the
    ultimate safety valve and always remains available regardless of
    recent activity (a deliberate, documented precedence decision, not
    dictated verbatim by ADR-009's text)."""

    breakeven_trigger_distance: float = 0.0020
    breakeven_buffer: float = 0.0002
    trailing_start_distance: float = 0.0030
    trailing_distance: float = 0.0020
    partial_close_trigger_distance: float = 0.0050
    partial_close_fraction: float = 0.5
    max_duration_seconds: float = 86400.0
    max_market_data_age_seconds: float = 30.0
    cooldown_seconds: float = 5.0
    log_level: int = 20  # logging.INFO, without importing logging here


DEFAULT_CONFIG = PositionManagerConfig()
