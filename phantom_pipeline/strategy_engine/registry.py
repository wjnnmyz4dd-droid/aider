"""Strategy Registry (ADR-003 §7).

No hard-coded playbook list: `discover_playbook_classes()` finds every
concrete `Playbook` subclass under `phantom_pipeline.strategy_engine.
playbooks` via module introspection, the same discovery idea
`phantom/strategies/orchestrator.py`'s `discover_strategy_classes()`
gestures at (ADR-003 §7, §20) — not authoritative, adapted here.

Discovered classes are ordered by `strategy_id` (a stable, content-derived
key), never by filesystem/import order, so registry behavior is
deterministic regardless of registration order (ADR-003 §7's Duplicate
Strategy ID Handling: "the same set of playbook modules, registered in
any order, produces the same ... outcome").

Duplicate Strategy IDs are detected here, at construction time, before
any playbook runs: registry initialization fails fast and neither
conflicting playbook is loaded (ADR-003 §7).
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from typing import Dict, List, Optional, Sequence, Type

from .logging_sink import log_duplicate_strategy_id, log_registry_initialized
from .playbook import Playbook


class DuplicateStrategyIdError(Exception):
    """Raised when two or more playbooks register under the same
    `strategy_id` (ADR-003 §7). Registry initialization fails fast;
    neither conflicting playbook is loaded."""


def discover_playbook_classes() -> List[Type[Playbook]]:
    """Import-scan `phantom_pipeline.strategy_engine.playbooks` for every
    concrete `Playbook` subclass defined there. Import-only; no
    instantiation. Ordered by class name for a stable, filesystem-
    independent iteration order (final registry ordering is by
    `strategy_id`, applied by the caller after instantiation)."""

    from . import playbooks as package

    found: List[Type[Playbook]] = []
    for mod_info in pkgutil.iter_modules(package.__path__):
        module = importlib.import_module(f"{package.__name__}.{mod_info.name}")
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(obj, Playbook)
                and obj is not Playbook
                and not inspect.isabstract(obj)
                and obj.__module__ == module.__name__
            ):
                found.append(obj)
    return sorted(found, key=lambda c: c.__name__)


class StrategyRegistry:
    """Holds every registered `Playbook` instance, keyed by its
    `strategy_id`, in deterministic `strategy_id`-sorted order.

    `playbook_classes`, when supplied, overrides auto-discovery — used
    only by tests to exercise duplicate-ID detection and registry
    mechanics without touching the real `playbooks/` package (production
    callers never pass this; the engine itself contains no hard-coded
    list, per ADR-003 §7).
    """

    def __init__(self, playbook_classes: Optional[Sequence[Type[Playbook]]] = None):
        classes = (
            list(playbook_classes)
            if playbook_classes is not None
            else discover_playbook_classes()
        )
        instances = [cls() for cls in classes]
        self._check_for_duplicates(instances)
        self.playbooks: List[Playbook] = sorted(
            instances, key=lambda p: p.metadata.strategy_id
        )
        log_registry_initialized(self.registered_ids)

    def _check_for_duplicates(self, instances: Sequence[Playbook]) -> None:
        by_id: Dict[str, List[Playbook]] = {}
        for playbook in instances:
            by_id.setdefault(playbook.metadata.strategy_id, []).append(playbook)

        duplicates = {sid: group for sid, group in by_id.items() if len(group) > 1}
        if not duplicates:
            return

        conflicts = []
        for strategy_id, group in sorted(duplicates.items()):
            for playbook in group:
                conflicts.append(
                    {
                        "strategy_id": strategy_id,
                        "class_name": type(playbook).__name__,
                        "version": playbook.metadata.version,
                    }
                )

        log_duplicate_strategy_id(conflicts)
        raise DuplicateStrategyIdError(
            f"Duplicate strategy_id registration(s) detected: {conflicts}"
        )

    @property
    def registered_ids(self) -> List[str]:
        return [p.metadata.strategy_id for p in self.playbooks]
