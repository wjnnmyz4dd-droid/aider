"""StrategyOrchestrator — the single manager of every trading playbook.

Responsibilities:
  1. Discover every ``Strategy`` subclass under ``phantom.strategies``.
  2. Register them automatically, in a stable canonical order.
  3. Execute only the strategies enabled by configuration
     (``config.strategies.enabled_overrides``; absent name == enabled).
  4. Combine their signals into one Strategy Confidence, resolve conflicts, and
     apply the existing hard confidence cap.

Behaviour preservation: consolidation (conflict resolution + ``layer_cap``) is
delegated to the existing :class:`StrategyEngine` — the orchestrator does NOT
reimplement the scoring math. With the default config (all playbooks enabled)
it registers exactly the same strategy instances in exactly the same order as
``StrategyEngine``, so the consolidated result is identical. It is a duck-typed
drop-in for ``StrategyEngine`` (same ``evaluate`` / ``resolve`` / ``orb_engine``
surface) and can be injected into ``Scanner``/``Scorer`` unchanged.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from typing import List, Optional

from ..config import Config, DEFAULT_CONFIG
from ..orb import ORBEngine
from .base import Strategy
from .engine import StrategyEngine, StrategyOutcome
from .orb_strategy import ORBStrategy

# Canonical registration order == the current StrategyEngine ordering, so an
# all-enabled orchestrator is byte-for-byte behaviourally identical. Any newly
# added playbook not listed here is appended deterministically (stable-sorted by
# class name) AFTER the known ones.
_CANONICAL_ORDER = {
    "ORBStrategy": 0,
    "LiquiditySweepReversal": 1,
    "SessionBreakoutContinuation": 2,
    "SupportResistanceBounce": 3,
    "MomentumContinuation": 4,
}


def discover_strategy_classes() -> List[type]:
    """Return every concrete ``Strategy`` subclass defined under
    ``phantom.strategies``, ordered by :data:`_CANONICAL_ORDER` (unknown extras
    appended, stable-sorted by class name). Import-only; no instantiation."""
    import phantom.strategies as pkg

    found = {}
    for mod_info in pkgutil.iter_modules(pkg.__path__):
        mod = importlib.import_module(f"{pkg.__name__}.{mod_info.name}")
        for _, obj in inspect.getmembers(mod, inspect.isclass):
            if (
                issubclass(obj, Strategy)
                and obj is not Strategy
                and not inspect.isabstract(obj)
                and obj.__module__ == mod.__name__  # defined here, not re-exported
            ):
                found[obj.__name__] = obj
    return sorted(
        found.values(),
        key=lambda c: (_CANONICAL_ORDER.get(c.__name__, 100), c.__name__),
    )


class StrategyOrchestrator:
    """Single manager for the strategy layer. Drop-in for ``StrategyEngine``."""

    def __init__(self, config: Config = DEFAULT_CONFIG, orb_engine: Optional[ORBEngine] = None):
        self.config = config
        # Reuse StrategyEngine for consolidation (identical resolve/gate/cap) and
        # for the stateful ORB instance it constructs.
        self._engine = StrategyEngine(config, orb_engine=orb_engine)
        self.strategies = self._register()
        self._engine.strategies = self.strategies  # execute only enabled playbooks

    # -- registration -------------------------------------------------------

    def _is_enabled(self, name: str) -> bool:
        return self.config.strategies.enabled_overrides.get(name, True)

    def _instantiate(self, cls: type) -> Strategy:
        # ORB owns a stateful ORBEngine + last_decision; reuse the engine's
        # instance so the ORB decision wiring keeps working.
        if cls.__name__ == "ORBStrategy":
            return self._engine.orb_strategy
        return cls(self.config)

    def _register(self) -> List[Strategy]:
        registered: List[Strategy] = []
        for cls in discover_strategy_classes():
            inst = self._instantiate(cls)
            if self._is_enabled(inst.name):
                registered.append(inst)
        return registered

    # -- StrategyEngine-compatible surface ----------------------------------

    @property
    def orb_strategy(self) -> ORBStrategy:
        return self._engine.orb_strategy

    @property
    def orb_engine(self) -> ORBEngine:
        return self._engine.orb_engine

    @property
    def registered_names(self) -> List[str]:
        return [s.name for s in self.strategies]

    @property
    def disabled_names(self) -> List[str]:
        """Strategy ``.name`` values that discovery found but config disabled."""
        enabled = set(self.registered_names)
        out = []
        for c in discover_strategy_classes():
            name = getattr(c, "name", c.__name__)
            if name not in enabled:
                out.append(name)
        return out

    def resolve(self, signals):
        return self._engine.resolve(signals)

    def evaluate(self, snap, ctx) -> StrategyOutcome:
        return self._engine.evaluate(snap, ctx)
