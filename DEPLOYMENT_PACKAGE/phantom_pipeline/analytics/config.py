"""Versioned configuration for Analytics (ADR-010).

Analytics has no tunable numeric thresholds of its own (unlike every
prior decision-making stage) — it collects and derives statistics from
already-decided facts, never gates a live decision. This module exists
for the same versioning discipline every prior stage's config module
establishes (`CLAUDE.md` §7, §3), kept intentionally minimal.
"""

from __future__ import annotations

from dataclasses import dataclass

ANALYTICS_VERSION = "1.0.0-phase1"


@dataclass(frozen=True)
class AnalyticsConfig:
    log_level: int = 20  # logging.INFO, without importing logging here


DEFAULT_CONFIG = AnalyticsConfig()
