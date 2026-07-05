"""Versioned configuration for the Scoring Engine (ADR-004 §11).

Every weight/threshold here is a tunable implementation default, never
architecture, per the same discipline `phantom_pipeline.scanner.config`
and `phantom_pipeline.strategy_engine.config` already established
(`CLAUDE.md` §7, §3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

SCORING_ENGINE_VERSION = "1.0.0-phase1"


@dataclass(frozen=True)
class ScoringEngineConfig:
    """`enabled_rules` maps `rule_id` -> enabled/disabled; per ADR-004
    §11's safe-default rule, **absence means disabled** — the same
    fail-closed default `StrategyEngineConfig.enabled_playbooks` already
    established for playbooks, applied here to scoring rules.

    `rule_weights` maps `rule_id` -> its configured weight (§5: "a rule
    may carry a weight, sourced from configuration, never hardcoded").
    A rule enabled but absent from `rule_weights` uses `default_weight`
    — the weight default is independent of the enable/disable default,
    since an enabled rule with no explicit weight override is still an
    explicit, deliberate enablement, not a silent activation.
    """

    enabled_rules: Mapping[str, bool] = field(default_factory=dict)
    rule_weights: Mapping[str, float] = field(default_factory=dict)
    default_weight: float = 1.0
    max_countable_evidence_items: int = 5  # a placeholder cap, not a final figure
    log_level: int = 20  # logging.INFO, without importing logging here

    def __post_init__(self) -> None:
        object.__setattr__(self, "enabled_rules", MappingProxyType(dict(self.enabled_rules)))
        object.__setattr__(self, "rule_weights", MappingProxyType(dict(self.rule_weights)))

    def is_enabled(self, rule_id: str) -> bool:
        return bool(self.enabled_rules.get(rule_id, False))

    def weight_for(self, rule_id: str) -> float:
        return self.rule_weights.get(rule_id, self.default_weight)


DEFAULT_CONFIG = ScoringEngineConfig()
