"""Versioned configuration for the Dashboard (ADR-012 §5).

Every per-view component list here is a tunable implementation default
naming *which already-exported components that view selects*, never new
architecture (`CLAUDE.md` §7, §3) — the view definitions themselves
(§5) are ADR-012's own authority; this just wires stage names to them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

DASHBOARD_VERSION = "1.0.0-phase1"


@dataclass(frozen=True)
class DashboardConfig:
    """Component-name filters per view (§5). `OVERVIEW`/`ALERTS`/
    `ANALYTICS`/`AUDIT`/`RESEARCH` intentionally have no stage filter —
    they select by data kind (all components, all alerts, performance
    statistics, trade records, and nothing yet, respectively), not by a
    stage-name subset."""

    trading_components: Tuple[str, ...] = ("scanner", "strategy_engine", "scoring_engine")
    risk_components: Tuple[str, ...] = ("risk_engine",)
    compliance_components: Tuple[str, ...] = ("compliance_engine",)
    execution_components: Tuple[str, ...] = ("execution_validator", "mt5_bridge")
    infrastructure_components: Tuple[str, ...] = ("cpu", "memory", "disk", "network", "vps", "watchdog")


DEFAULT_CONFIG = DashboardConfig()
