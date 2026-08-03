"""Scoring Rule Registry (ADR-004 §5, §15).

No hard-coded rule list: `discover_rule_classes()` finds every concrete
`ScoringRule` subclass under `phantom_pipeline.scoring_engine.rules` via
module introspection — the same discovery mechanism
`phantom_pipeline.strategy_engine.registry` already established for
playbooks (ADR-003 §7), applied here to scoring rules.

Discovered classes are ordered by `rule_id` (a stable, content-derived
key), never by filesystem/import order, so registry behavior is
deterministic regardless of registration order — mirroring the Strategy
Registry's own determinism guarantee.

Duplicate rule IDs are detected here, at construction time, before any
rule runs: registry initialization fails fast and neither conflicting
rule is loaded.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from typing import Dict, List, Optional, Sequence, Type

from .logging_sink import log_duplicate_rule_id, log_registry_initialized
from .rule import ScoringRule


class DuplicateRuleIdError(Exception):
    """Raised when two or more scoring rules register under the same
    `rule_id` (ADR-004 §5). Registry initialization fails fast; neither
    conflicting rule is loaded."""


def discover_rule_classes() -> List[Type[ScoringRule]]:
    """Import-scan `phantom_pipeline.scoring_engine.rules` for every
    concrete `ScoringRule` subclass defined there. Import-only; no
    instantiation. Ordered by class name for a stable, filesystem-
    independent iteration order (final registry ordering is by
    `rule_id`, applied by the caller after instantiation)."""

    from . import rules as package

    found: List[Type[ScoringRule]] = []
    for mod_info in pkgutil.iter_modules(package.__path__):
        module = importlib.import_module(f"{package.__name__}.{mod_info.name}")
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(obj, ScoringRule)
                and obj is not ScoringRule
                and not inspect.isabstract(obj)
                and obj.__module__ == module.__name__
            ):
                found.append(obj)
    return sorted(found, key=lambda c: c.__name__)


class ScoringRuleRegistry:
    """Holds every registered `ScoringRule` instance, keyed by its
    `rule_id`, in deterministic `rule_id`-sorted order.

    `rule_classes`, when supplied, overrides auto-discovery — used only
    by tests to exercise duplicate-ID detection and registry mechanics
    without touching the real `rules/` package (production callers
    never pass this; the engine itself contains no hard-coded list).
    """

    def __init__(self, rule_classes: Optional[Sequence[Type[ScoringRule]]] = None):
        classes = list(rule_classes) if rule_classes is not None else discover_rule_classes()
        instances = [cls() for cls in classes]
        self._check_for_duplicates(instances)
        self.rules: List[ScoringRule] = sorted(instances, key=lambda r: r.metadata.rule_id)
        log_registry_initialized(self.registered_ids)

    def _check_for_duplicates(self, instances: Sequence[ScoringRule]) -> None:
        by_id: Dict[str, List[ScoringRule]] = {}
        for rule in instances:
            by_id.setdefault(rule.metadata.rule_id, []).append(rule)

        duplicates = {rid: group for rid, group in by_id.items() if len(group) > 1}
        if not duplicates:
            return

        conflicts = []
        for rule_id, group in sorted(duplicates.items()):
            for rule in group:
                conflicts.append(
                    {
                        "rule_id": rule_id,
                        "class_name": type(rule).__name__,
                        "version": rule.metadata.version,
                    }
                )

        log_duplicate_rule_id(conflicts)
        raise DuplicateRuleIdError(f"Duplicate rule_id registration(s) detected: {conflicts}")

    @property
    def registered_ids(self) -> List[str]:
        return [r.metadata.rule_id for r in self.rules]

    @property
    def factor_by_rule_id(self) -> Dict[str, str]:
        return {r.metadata.rule_id: r.metadata.factor for r in self.rules}
