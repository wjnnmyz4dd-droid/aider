"""Versioned configuration for the Execution Validator (ADR-007 §6, §9).

Every threshold/tolerance here is a tunable implementation default,
never architecture (`CLAUDE.md` §7, §3) — the same discipline every
prior stage's config module already established.

Symbols absent from `max_spread` are unevaluable, not assumed safe — the
same fail-closed treatment `compliance_engine.config`'s
`spread_thresholds` already established for an unconfigured symbol.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

EXECUTION_VALIDATOR_VERSION = "1.0.0-phase1"


@dataclass(frozen=True)
class ExecutionValidatorConfig:
    """`max_spread` maps `symbol` -> a maximum allowed current spread
    (price units). A symbol absent from this mapping has an unevaluable
    spread threshold — fails `SPREAD_UNCHANGED` closed, never assumed
    safe. The empty default means every symbol is unevaluable until the
    deployer configures thresholds.

    `warning_threshold_ratio` is the fraction of a hard drift tolerance
    (spread, slippage) at or above which a still-`PASSED` check emits an
    advisory warning (ADR-007 §4's "warnings" output) — never affects
    the check's own `PASSED`/`FAILED` status.
    """

    max_order_age_seconds: float = 5.0
    max_price_drift: float = 0.0010
    max_spread: Mapping[str, float] = field(default_factory=dict)
    min_risk_reward_ratio: float = 1.5
    account_drift_tolerance_ratio: float = 0.02
    warning_threshold_ratio: float = 0.8
    idempotency_ttl_seconds: float = 300.0
    log_level: int = 20  # logging.INFO, without importing logging here

    def __post_init__(self) -> None:
        object.__setattr__(self, "max_spread", MappingProxyType(dict(self.max_spread)))

    def max_spread_for(self, symbol: str):
        return self.max_spread.get(symbol)


DEFAULT_CONFIG = ExecutionValidatorConfig()
