"""Prop-firm rule status reporting for the Paper Trading Runner (Phase 4).

**Advisory only — never a second blocking authority.** Every rule named
here (daily/total drawdown, position limits, news/weekend restrictions)
is already Risk Engine's or Compliance Engine's own exclusive authority
(`ADR-005`/`ADR-006`). `PropFirmValidator` never blocks a trade, never
sizes one, and never evaluates a candidate — it only (a) audits whether
the *deployed configuration* is at least as strict as a named prop firm's
published rule, and (b) reports *already-produced* `RiskDecision`/
`ComplianceDecision` objects' own fields against that same profile, for a
human/dashboard to review. A finding is a report, never an action —
mirroring `TEAM.md`'s Quant Validation Engineer role: "Route findings,
don't implement them."

**Lot-size caps are a genuine gap, not a duplicate.** No existing config
(`RiskEngineConfig`, `ComplianceEngineConfig`) defines a per-trade lot-size
ceiling — prop firms commonly do. `evaluate_lot_sizes` reports already-
produced `RiskDecision.lot_size` values against a profile's cap; it has no
mechanism to prevent one, since preventing one would require modifying
Risk Engine (out of this task's explicit scope).

**News/weekend restriction status is read, never re-evaluated.**
`NEWS_RESTRICTION`/`WEEKEND_RESTRICTION` are already-implemented
Compliance Engine checks (`compliance_engine.checks.news_restriction`/
`weekend_restriction`) — this module reads the already-produced
`CheckEvaluation` for each from an already-produced `ComplianceDecision`,
never recomputing a news blackout or a market-open/closed determination
itself.

**Preset thresholds are public, commonly-known figures, not this file's
invention** — and, like every other stage's config module, tunable
defaults (`CLAUDE.md` §7, §3), not architecture. A deployer must confirm
current published rules before relying on a preset, since prop-firm
terms change over time and are not controlled by this codebase.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Sequence, Tuple

from ..compliance_engine import ComplianceEngineConfig
from ..compliance_engine.models import ComplianceDecision
from ..risk_engine import RiskEngineConfig
from ..risk_engine.models import RiskDecision
from .account_tracker import AccountSnapshot

SCHEMA_VERSION = 1


class RuleStatus(Enum):
    PASS = "PASS"
    WARNING = "WARNING"
    BREACH = "BREACH"
    UNEVALUABLE = "UNEVALUABLE"


_SEVERITY_ORDER = {RuleStatus.PASS: 0, RuleStatus.UNEVALUABLE: 1, RuleStatus.WARNING: 2, RuleStatus.BREACH: 3}


@dataclass(frozen=True)
class RuleFinding:
    rule_name: str
    status: RuleStatus
    detail: str


@dataclass(frozen=True)
class PropFirmProfile:
    """A named prop firm's publicly-documented rule set. Every threshold
    here is a tunable, deployer-supplied value — this module ships two
    commonly-known reference presets below, not a guarantee that they
    match a specific firm's current terms."""

    name: str
    max_daily_drawdown_percent: float
    max_total_drawdown_percent: float
    total_drawdown_basis: str = "INITIAL"  # "INITIAL" or "PEAK"
    max_lot_size: Optional[float] = None
    max_open_positions: Optional[int] = None
    requires_news_restriction: bool = True
    requires_weekend_restriction: bool = True


# Commonly-known reference defaults for two widely-used prop firm
# programs, as of this repository's own last review — a deployer must
# reconfirm against the firm's current published rules before relying on
# either preset (see module docstring).
FTMO_PROFILE = PropFirmProfile(
    name="FTMO", max_daily_drawdown_percent=5.0, max_total_drawdown_percent=10.0,
    total_drawdown_basis="INITIAL", max_lot_size=None, max_open_positions=None,
)
FUNDEDNEXT_PROFILE = PropFirmProfile(
    name="FundedNext", max_daily_drawdown_percent=5.0, max_total_drawdown_percent=10.0,
    total_drawdown_basis="INITIAL", max_lot_size=None, max_open_positions=None,
)


@dataclass(frozen=True)
class PropFirmComplianceStatus:
    schema_version: int
    profile_name: str
    generated_at: datetime
    findings: Tuple[RuleFinding, ...]
    overall_status: RuleStatus

    def __post_init__(self) -> None:
        object.__setattr__(self, "findings", tuple(self.findings))


class PropFirmValidator:
    def __init__(self, profile: PropFirmProfile) -> None:
        self.profile = profile

    def audit_configuration(
        self, risk_config: RiskEngineConfig, compliance_config: ComplianceEngineConfig
    ) -> Tuple[RuleFinding, ...]:
        """Is the *deployed* configuration at least as strict as the
        profile's published limit — a one-time (or per-deploy) config
        audit, never a per-trade evaluation."""
        return (
            _config_finding(
                "DAILY_DRAWDOWN_CONFIG", compliance_config.max_daily_drawdown_percent,
                self.profile.max_daily_drawdown_percent, self.profile.name,
            ),
            _config_finding(
                "TOTAL_DRAWDOWN_CONFIG", compliance_config.max_total_drawdown_percent,
                self.profile.max_total_drawdown_percent, self.profile.name,
            ),
        )

    def evaluate_snapshot(self, account_snapshot: Optional[AccountSnapshot]) -> Tuple[RuleFinding, RuleFinding]:
        """Real-time status against the profile's limits, read directly
        from `AccountTracker`'s own already-computed snapshot."""
        if account_snapshot is None:
            return (
                RuleFinding("DAILY_DRAWDOWN_LIVE", RuleStatus.UNEVALUABLE, "no account snapshot available"),
                RuleFinding("TOTAL_DRAWDOWN_LIVE", RuleStatus.UNEVALUABLE, "no account snapshot available"),
            )
        total_dd = (
            account_snapshot.total_drawdown_pct_from_peak
            if self.profile.total_drawdown_basis == "PEAK"
            else account_snapshot.total_drawdown_pct
        )
        return (
            _threshold_finding("DAILY_DRAWDOWN_LIVE", account_snapshot.daily_drawdown_pct, self.profile.max_daily_drawdown_percent),
            _threshold_finding("TOTAL_DRAWDOWN_LIVE", total_dd, self.profile.max_total_drawdown_percent),
        )

    def evaluate_lot_sizes(self, risk_decisions: Sequence[RiskDecision]) -> RuleFinding:
        """Reports whether any already-produced `RiskDecision.lot_size`
        exceeded the profile's cap — advisory only, see module docstring."""
        if self.profile.max_lot_size is None:
            return RuleFinding("LOT_SIZE", RuleStatus.UNEVALUABLE, "profile does not define a lot-size cap")
        violations = [d for d in risk_decisions if d.lot_size is not None and d.lot_size > self.profile.max_lot_size]
        if violations:
            return RuleFinding(
                "LOT_SIZE", RuleStatus.BREACH,
                f"{len(violations)} decision(s) exceeded {self.profile.max_lot_size} lots",
            )
        return RuleFinding("LOT_SIZE", RuleStatus.PASS, "no lot-size violation observed")

    def evaluate_position_count(self, open_position_count: int) -> RuleFinding:
        if self.profile.max_open_positions is None:
            return RuleFinding("POSITION_LIMIT", RuleStatus.UNEVALUABLE, "profile does not define a position-count cap")
        if open_position_count > self.profile.max_open_positions:
            return RuleFinding(
                "POSITION_LIMIT", RuleStatus.BREACH,
                f"{open_position_count} open positions exceeds cap of {self.profile.max_open_positions}",
            )
        if open_position_count == self.profile.max_open_positions:
            return RuleFinding("POSITION_LIMIT", RuleStatus.WARNING, "at the position-count cap")
        return RuleFinding("POSITION_LIMIT", RuleStatus.PASS, f"{open_position_count} open positions, within cap")

    def evaluate_restriction_checks(self, compliance_decisions: Sequence[ComplianceDecision]) -> Tuple[RuleFinding, RuleFinding]:
        """Reads the already-produced `NEWS_RESTRICTION`/
        `WEEKEND_RESTRICTION` `CheckEvaluation`s off already-produced
        `ComplianceDecision`s — never a new news-calendar or market-status
        evaluation of its own."""
        return (
            _restriction_finding(compliance_decisions, "NEWS_RESTRICTION", self.profile.requires_news_restriction),
            _restriction_finding(compliance_decisions, "WEEKEND_RESTRICTION", self.profile.requires_weekend_restriction),
        )

    def build_status(
        self,
        risk_config: RiskEngineConfig,
        compliance_config: ComplianceEngineConfig,
        account_snapshot: Optional[AccountSnapshot],
        risk_decisions: Sequence[RiskDecision],
        open_position_count: int,
        compliance_decisions: Sequence[ComplianceDecision],
        now: datetime,
    ) -> PropFirmComplianceStatus:
        findings = (
            self.audit_configuration(risk_config, compliance_config)
            + self.evaluate_snapshot(account_snapshot)
            + (self.evaluate_lot_sizes(risk_decisions), self.evaluate_position_count(open_position_count))
            + self.evaluate_restriction_checks(compliance_decisions)
        )
        overall = max((f.status for f in findings), key=lambda s: _SEVERITY_ORDER[s], default=RuleStatus.UNEVALUABLE)
        return PropFirmComplianceStatus(
            schema_version=SCHEMA_VERSION,
            profile_name=self.profile.name,
            generated_at=now,
            findings=findings,
            overall_status=overall,
        )


def _config_finding(rule_name: str, configured: float, limit: float, profile_name: str) -> RuleFinding:
    if configured > limit:
        return RuleFinding(
            rule_name, RuleStatus.BREACH,
            f"configured {configured}% exceeds {profile_name}'s {limit}% limit",
        )
    return RuleFinding(rule_name, RuleStatus.PASS, f"configured {configured}% within {profile_name}'s {limit}% limit")


def _threshold_finding(rule_name: str, observed: float, limit: float) -> RuleFinding:
    if observed >= limit:
        return RuleFinding(rule_name, RuleStatus.BREACH, f"observed {observed:.2f}% at/above limit {limit}%")
    if observed >= limit * 0.8:
        return RuleFinding(rule_name, RuleStatus.WARNING, f"observed {observed:.2f}% approaching limit {limit}%")
    return RuleFinding(rule_name, RuleStatus.PASS, f"observed {observed:.2f}% within limit {limit}%")


def _restriction_finding(decisions: Sequence[ComplianceDecision], check_name: str, required: bool) -> RuleFinding:
    if not required:
        return RuleFinding(check_name, RuleStatus.UNEVALUABLE, "not required by this profile")
    evaluations = [
        evaluation
        for decision in decisions
        for evaluation in decision.check_evaluations
        if evaluation.check == check_name
    ]
    if not evaluations:
        return RuleFinding(check_name, RuleStatus.UNEVALUABLE, "no recorded evaluation for this check")
    latest = evaluations[-1]
    if latest.status.value == "PASSED":
        return RuleFinding(check_name, RuleStatus.PASS, latest.detail)
    if latest.status.value == "UNEVALUABLE":
        return RuleFinding(check_name, RuleStatus.UNEVALUABLE, latest.detail)
    return RuleFinding(check_name, RuleStatus.BREACH, latest.detail)


__all__ = [
    "RuleStatus", "RuleFinding", "PropFirmProfile", "FTMO_PROFILE", "FUNDEDNEXT_PROFILE",
    "PropFirmComplianceStatus", "PropFirmValidator",
]
