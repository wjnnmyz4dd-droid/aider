"""Configuration for the Prop Firm Compliance Engine (Phase 2E).

Every threshold, band, and schedule used anywhere in this package is
named here -- no magic numbers embedded in the rule modules (CLAUDE.md
§3). Rule profiles are fully generic and configurable (ADR-028 Hard
Rule 9) -- never hard-coded to one specific prop firm.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from .models import ComplianceRuleProfile, GraduatedBand

COMPLIANCE_ENGINE_VERSION = "1.0.0-phase2e"

#: Daily Loss Protection -- the task's own worked example, expressed as
#: % of the configured daily loss limit consumed (0-100 scale, not % of
#: account equity -- e.g. "70" here means 70% of whatever
#: `max_daily_loss_pct` the active `ComplianceRuleProfile` sets).
DEFAULT_DAILY_LOSS_BANDS: Tuple[GraduatedBand, ...] = (
    GraduatedBand(min_pct=0.0, max_pct=50.0, multiplier=1.0, label="normal"),
    GraduatedBand(min_pct=50.0, max_pct=70.0, multiplier=0.6, label="reduce_max_position_size"),
    GraduatedBand(min_pct=70.0, max_pct=80.0, multiplier=0.3, min_evidence_score=85.0, label="significant_reduction_exceptional_confidence_only"),
    GraduatedBand(min_pct=80.0, max_pct=90.0, multiplier=0.15, min_strategy_score=90.0, label="highest_quality_only"),
    GraduatedBand(min_pct=90.0, max_pct=100.0, multiplier=0.0, hard_reject=True, label="no_new_trades"),
)

#: Total Drawdown Protection -- same graduated shape, own bands; the
#: final band always hard-rejects (never trades into the hard limit).
DEFAULT_DRAWDOWN_BANDS: Tuple[GraduatedBand, ...] = (
    GraduatedBand(min_pct=0.0, max_pct=50.0, multiplier=1.0, label="normal"),
    GraduatedBand(min_pct=50.0, max_pct=75.0, multiplier=0.5, label="reduce"),
    GraduatedBand(min_pct=75.0, max_pct=90.0, multiplier=0.25, label="significant_reduction"),
    GraduatedBand(min_pct=90.0, max_pct=100.0, multiplier=0.0, hard_reject=True, label="hard_limit"),
)

#: Daily Profit Protection -- the task's own worked example (+2%/+3%/+4%),
#: expressed directly in % of daily starting balance. Reduces only by
#: default; `profit_protection_stop_at_pct` (below) can additionally
#: reject new positions once a configured profit level is reached.
DEFAULT_PROFIT_PROTECTION_BANDS: Tuple[GraduatedBand, ...] = (
    GraduatedBand(min_pct=0.0, max_pct=2.0, multiplier=1.0, label="normal"),
    GraduatedBand(min_pct=2.0, max_pct=3.0, multiplier=0.75, label="protect_gains_mild"),
    GraduatedBand(min_pct=3.0, max_pct=4.0, multiplier=0.5, label="protect_gains_moderate"),
    GraduatedBand(min_pct=4.0, max_pct=1e9, multiplier=0.25, label="protect_gains_aggressive"),
)

DEFAULT_RULE_PROFILE = ComplianceRuleProfile()


@dataclass(frozen=True)
class ComplianceEngineConfig:
    daily_loss_bands: Tuple[GraduatedBand, ...] = DEFAULT_DAILY_LOSS_BANDS
    drawdown_bands: Tuple[GraduatedBand, ...] = DEFAULT_DRAWDOWN_BANDS

    profit_protection_enabled: bool = True
    profit_protection_bands: Tuple[GraduatedBand, ...] = DEFAULT_PROFIT_PROTECTION_BANDS
    #: If set, new positions are rejected once daily profit reaches this
    #: percentage -- "optionally stop opening new positions" per the task.
    profit_protection_stop_at_pct: Optional[float] = None

    consecutive_loss_pause_threshold: int = 3

    disabled_pairs: Tuple[str, ...] = ()

    weekend_restriction_check_enabled: bool = True
    weekend_cutoff_weekday: int = 4  # Friday (Monday=0)
    weekend_cutoff_hour: int = 20  # UTC hour after which new entries are blocked on the cutoff weekday
    weekend_reopen_weekday: int = 0  # Monday -- restriction lifts at/after this weekday

    rule_profiles: Tuple[ComplianceRuleProfile, ...] = (DEFAULT_RULE_PROFILE,)

    def profile_for(self, name: str) -> ComplianceRuleProfile:
        for profile in self.rule_profiles:
            if profile.name == name:
                return profile
        raise ValueError(f"no configured rule profile named {name!r}")


__all__ = [
    "COMPLIANCE_ENGINE_VERSION",
    "DEFAULT_DAILY_LOSS_BANDS",
    "DEFAULT_DRAWDOWN_BANDS",
    "DEFAULT_PROFIT_PROTECTION_BANDS",
    "DEFAULT_RULE_PROFILE",
    "ComplianceEngineConfig",
]
