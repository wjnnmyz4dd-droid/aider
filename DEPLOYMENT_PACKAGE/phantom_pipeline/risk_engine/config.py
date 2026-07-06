"""Versioned configuration for the Risk Engine (ADR-005 §6).

Every ceiling/threshold/multiplier here is a tunable implementation
default, never architecture, per the same discipline every prior stage's
config module already established (`CLAUDE.md` §7, §3). All percentages
are plain numbers (e.g. `1.0` means "1.0%"), never fractions — a
consistent convention across every field in this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping, Optional, Tuple

RISK_ENGINE_VERSION = "1.0.0-phase1"


@dataclass(frozen=True)
class RiskEngineConfig:
    """`correlation_buckets` maps `symbol` -> a correlation bucket name.
    A symbol absent from this mapping has an unevaluable correlation
    bucket — per ADR-005 §11's Hard Rule, this fails the correlation
    constraint closed to zero, never assumed safe. The empty default
    means every symbol is unevaluable until the deployer configures
    buckets — a conservative, honest safe default, not a placeholder
    pretending to be complete.

    `volatility_multipliers` maps a `VolatilityLabel.value` string to a
    multiplier applied to the per-trade ceiling. A label absent from
    this mapping (including `UNKNOWN`, deliberately never given a
    default entry) resolves to a `0.0` multiplier — fail-closed, since
    Scanner's own `UNKNOWN` volatility means insufficient data, and this
    stage must never assume normal conditions in that case.

    `loss_streak_tiers`/`drawdown_tiers` are `(threshold, multiplier)`
    pairs, evaluated highest-threshold-first (the first tier whose
    threshold the input meets or exceeds wins) — a placeholder,
    monotonically-tightening tier ladder, not a tuned model.
    """

    max_risk_percent_per_trade: float = 1.0
    max_daily_risk_percent: float = 3.0
    max_portfolio_heat_percent: float = 5.0
    max_currency_exposure_percent: float = 4.0
    max_positions_per_correlation_bucket: int = 2
    correlation_buckets: Mapping[str, str] = field(default_factory=dict)
    volatility_multipliers: Mapping[str, float] = field(
        default_factory=lambda: {
            "COMPRESSED": 1.0,
            "NORMAL": 1.0,
            "ELEVATED": 0.5,
            "EXTREME": 0.25,
        }
    )
    loss_streak_tiers: Tuple[Tuple[int, float], ...] = ((5, 0.0), (3, 0.5))
    drawdown_tiers: Tuple[Tuple[float, float], ...] = ((5.0, 0.0), (3.0, 0.5))
    log_level: int = 20  # logging.INFO, without importing logging here

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "correlation_buckets", MappingProxyType(dict(self.correlation_buckets))
        )
        object.__setattr__(
            self,
            "volatility_multipliers",
            MappingProxyType(dict(self.volatility_multipliers)),
        )
        object.__setattr__(self, "loss_streak_tiers", tuple(self.loss_streak_tiers))
        object.__setattr__(self, "drawdown_tiers", tuple(self.drawdown_tiers))

    def volatility_multiplier(self, label: str) -> float:
        return self.volatility_multipliers.get(label, 0.0)

    def correlation_bucket_for(self, symbol: str) -> Optional[str]:
        return self.correlation_buckets.get(symbol)

    def tier_multiplier(self, tiers: Tuple[Tuple[float, float], ...], value: float) -> float:
        """The multiplier of the first tier (sorted highest-threshold-first)
        whose threshold `value` meets or exceeds; `1.0` (no reduction) if
        no tier's threshold is met."""
        for threshold, multiplier in sorted(tiers, key=lambda t: -t[0]):
            if value >= threshold:
                return multiplier
        return 1.0


DEFAULT_CONFIG = RiskEngineConfig()
