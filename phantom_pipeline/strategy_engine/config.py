"""Versioned configuration for the Strategy Engine (ADR-003 §13).

Every threshold here is a tunable implementation default, never
architecture, per the same discipline `phantom_pipeline.scanner.config`
already established (`CLAUDE.md` §7, §3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

STRATEGY_ENGINE_VERSION = "1.0.0-phase1"


@dataclass(frozen=True)
class StrategyEngineConfig:
    """`enabled_playbooks` maps `strategy_id` -> enabled/disabled.

    Per ADR-003 §13's safe-default rule, **absence from this mapping means
    disabled** — the exact inverse of `ScannerConfig.recognized_symbols`'
    "empty means unrestricted" polarity, because the two configs encode
    different rules from different ADRs: ADR-002 has no opinion on
    default symbol scope, while ADR-003 §13 explicitly mandates
    disabled-by-default for playbooks. Both are fail-closed in their own
    ADR's terms, not inconsistent with each other.
    """

    enabled_playbooks: Mapping[str, bool] = field(default_factory=dict)
    log_level: int = 20  # logging.INFO, without importing logging here

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "enabled_playbooks", MappingProxyType(dict(self.enabled_playbooks))
        )

    def is_enabled(self, strategy_id: str) -> bool:
        return bool(self.enabled_playbooks.get(strategy_id, False))


DEFAULT_CONFIG = StrategyEngineConfig()
