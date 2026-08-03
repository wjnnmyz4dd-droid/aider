"""Attribution grouping (ADR-010 §9).

`group_by_strategy` derives its grouping keys from the Strategy Registry
(`ADR-003` §3) — never a hand-maintained list. This is the deliberate,
explicit architecture requirement ADR-010 §2 states to close the
`phantom/analytics.py` `STRATEGIES` tuple defect flagged in `TEAM.md`'s
backlog: a hand-maintained list silently drifted from the real roster
and crashed on an unlisted playbook. A `strategy_id` on a collected
`CandidateTrade` that is not among the registry's own `registered_ids`
is excluded from attribution rather than fabricating a bucket for it —
`checks.detect_issues` is the mechanism for surfacing that as a defect,
not this module.
"""

from __future__ import annotations

from typing import Dict, Sequence, Tuple

from ..strategy_engine.registry import StrategyRegistry
from .models import TradeProvenanceRecord


def _grouped(records: Sequence[TradeProvenanceRecord], key_fn) -> Dict[str, Tuple[TradeProvenanceRecord, ...]]:
    groups: Dict[str, list] = {}
    for record in records:
        key = key_fn(record)
        if key is None:
            continue
        groups.setdefault(key, []).append(record)
    return {key: tuple(values) for key, values in groups.items()}


def group_by_strategy(
    records: Sequence[TradeProvenanceRecord], registry: StrategyRegistry
) -> Dict[str, Tuple[TradeProvenanceRecord, ...]]:
    known_ids = set(registry.registered_ids)

    def key_fn(record: TradeProvenanceRecord):
        if record.candidate is None or record.candidate.strategy_id not in known_ids:
            return None
        return record.candidate.strategy_id

    return _grouped(records, key_fn)


def group_by_regime(records: Sequence[TradeProvenanceRecord]) -> Dict[str, Tuple[TradeProvenanceRecord, ...]]:
    def key_fn(record: TradeProvenanceRecord):
        if record.scanner_observation is None:
            return None
        return record.scanner_observation.range_structure.value

    return _grouped(records, key_fn)


def group_by_session(records: Sequence[TradeProvenanceRecord]) -> Dict[str, Tuple[TradeProvenanceRecord, ...]]:
    def key_fn(record: TradeProvenanceRecord):
        if record.scanner_observation is None:
            return None
        active = record.scanner_observation.session.active_sessions
        return "+".join(sorted(active)) if active else "NONE"

    return _grouped(records, key_fn)


def group_by_pair(records: Sequence[TradeProvenanceRecord]) -> Dict[str, Tuple[TradeProvenanceRecord, ...]]:
    def key_fn(record: TradeProvenanceRecord):
        if record.candidate is not None:
            return record.candidate.symbol
        if record.risk_decision is not None:
            return record.risk_decision.symbol
        return None

    return _grouped(records, key_fn)
