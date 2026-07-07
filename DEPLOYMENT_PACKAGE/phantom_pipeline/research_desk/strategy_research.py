"""Strategy Research Agent (`ADR-021` §3, item 6).

Reuses `AnalyticsEngine.group_by_pair/session/regime` for best/worst
pair/session/regime — never a second grouping implementation
(`ADR-021` §2). Rule-combination frequency is genuinely new analysis:
co-occurring `reason_codes` across risk/compliance/execution decisions,
counted directly over already-recorded fields. Parameter sensitivity is
honestly flagged as unavailable — no backtest/parameter-sweep module
exists anywhere in `phantom_pipeline` (`ADR-021` Hard Rule 5).
"""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, Optional, Sequence, Tuple

from ..analytics import AnalyticsEngine, TradeProvenanceRecord
from ..analytics.models import OutcomeKind
from .config import DEFAULT_CONFIG, ResearchDeskConfig
from .models import ParameterSensitivityResult, RuleCombinationFinding


def _all_reason_codes(record: TradeProvenanceRecord) -> Tuple[str, ...]:
    codes = []
    if record.risk_decision is not None:
        codes.extend(record.risk_decision.reason_codes)
    if record.compliance_decision is not None:
        codes.extend(record.compliance_decision.reason_codes)
    if record.execution_decision is not None:
        codes.extend(record.execution_decision.reason_codes)
    return tuple(sorted(set(codes)))


def _record_pnl(record: TradeProvenanceRecord) -> Optional[float]:
    if record.final_outcome is None or record.final_outcome.outcome_kind != OutcomeKind.CLOSED:
        return None
    return record.final_outcome.realized_pnl


class StrategyResearchAgent:
    def __init__(self, analytics: AnalyticsEngine, config: ResearchDeskConfig = DEFAULT_CONFIG) -> None:
        self._analytics = analytics
        self._config = config

    def best_worst_pairs(self, records: Sequence[TradeProvenanceRecord]) -> Tuple[Optional[str], Optional[str]]:
        return self._rank(self._analytics.group_by_pair(records))

    def best_worst_sessions(self, records: Sequence[TradeProvenanceRecord]) -> Tuple[Optional[str], Optional[str]]:
        return self._rank(self._analytics.group_by_session(records))

    def best_worst_regimes(self, records: Sequence[TradeProvenanceRecord]) -> Tuple[Optional[str], Optional[str]]:
        return self._rank(self._analytics.group_by_regime(records))

    def _rank(self, groups: Dict[str, Tuple[TradeProvenanceRecord, ...]]) -> Tuple[Optional[str], Optional[str]]:
        totals = {}
        for key, group_records in groups.items():
            pnls = [p for p in (_record_pnl(r) for r in group_records) if p is not None]
            if pnls:
                totals[key] = sum(pnls)
        if not totals:
            return None, None
        return max(totals, key=lambda k: totals[k]), min(totals, key=lambda k: totals[k])

    def analyze_rule_combinations(self, records: Sequence[TradeProvenanceRecord]) -> Tuple[RuleCombinationFinding, ...]:
        by_combination: Dict[Tuple[str, ...], list] = defaultdict(list)
        for record in records:
            codes = _all_reason_codes(record)
            if codes:
                by_combination[codes].append(record)

        findings = []
        eligible = {
            codes: group for codes, group in by_combination.items()
            if len(group) >= self._config.rule_combination_min_occurrences
        }
        if not eligible:
            return ()

        averages = {}
        for codes, group in eligible.items():
            pnls = [p for p in (_record_pnl(r) for r in group) if p is not None]
            averages[codes] = (sum(pnls) / len(pnls)) if pnls else None

        ranked = [codes for codes in eligible if averages[codes] is not None]
        if ranked:
            best = max(ranked, key=lambda c: averages[c])
            worst = min(ranked, key=lambda c: averages[c])
        else:
            best = worst = None

        for codes, group in eligible.items():
            classification = "STRONGEST" if codes == best else "WEAKEST" if codes == worst else "NEUTRAL"
            findings.append(
                RuleCombinationFinding(
                    rule_codes=codes,
                    occurrence_count=len(group),
                    average_pnl=averages[codes],
                    classification=classification,
                )
            )
        return tuple(sorted(findings, key=lambda f: f.rule_codes))

    def analyze_parameter_sensitivity(self, parameter_name: str) -> ParameterSensitivityResult:
        return ParameterSensitivityResult(
            parameter_name=parameter_name,
            available=False,
            detail=(
                "No backtest or parameter-sweep module exists anywhere in phantom_pipeline yet — "
                "parameter sensitivity cannot be honestly computed from live/paper trade history alone."
            ),
        )


__all__ = ["StrategyResearchAgent"]
