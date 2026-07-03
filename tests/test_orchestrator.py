"""Tests for the StrategyOrchestrator.

Proves:
  * Auto-discovery finds every playbook in the canonical order.
  * With all playbooks enabled, the orchestrator is behaviourally IDENTICAL to
    StrategyEngine — both at the strategy-layer level (StrategyOutcome) and at
    the full-scan level (ScoreResult).
  * Configuration disables individual playbooks; disabling a playbook that
    contributes no signal leaves the outcome unchanged.
"""

from __future__ import annotations

import unittest
from dataclasses import replace

from phantom.config import DEFAULT_CONFIG
from phantom.scanner import Scanner
from phantom.strategies.base import StrategyContext
from phantom.strategies.engine import StrategyEngine
from phantom.strategies.orchestrator import (
    StrategyOrchestrator,
    discover_strategy_classes,
)
from phantom.structure import StructureSignal
from phantom.types import Direction, Regime

from tests.fixtures import (
    approve_long_snapshot,
    guard_blocked_snapshot,
    ranging_snapshot,
    strong_approve_snapshot,
)

CANONICAL = ["ORB", "Liquidity Reversal", "Session Breakout",
             "S&R Bounce", "Momentum Continuation"]


def _ctx(**over):
    base = dict(
        regime=Regime.TRENDING_UP, h4_dir=Direction.LONG, d1_dir=Direction.LONG,
        bias=Direction.LONG, bos=StructureSignal(), choch=StructureSignal(),
        sweep=StructureSignal(), fvg=StructureSignal(), ob=StructureSignal(),
        news_safe=True, spread_safe=True, correlation_safe=True,
        exposure_safe={Direction.LONG: True, Direction.SHORT: True},
        atr=0.0010, exec_candles=[],
    )
    base.update(over)
    return StrategyContext(**base)


class TestDiscovery(unittest.TestCase):
    def test_discovers_all_playbooks_in_canonical_order(self):
        names = [c.__name__ for c in discover_strategy_classes()]
        self.assertEqual(names, [
            "ORBStrategy", "LiquiditySweepReversal", "SessionBreakoutContinuation",
            "SupportResistanceBounce", "MomentumContinuation",
        ])

    def test_default_registration_matches_engine_order(self):
        orch = StrategyOrchestrator()
        self.assertEqual(orch.registered_names, CANONICAL)
        # same order the StrategyEngine registers
        self.assertEqual([s.name for s in StrategyEngine().strategies], CANONICAL)


class TestIdentityWhenAllEnabled(unittest.TestCase):
    SNAPS = [approve_long_snapshot, strong_approve_snapshot,
             ranging_snapshot, guard_blocked_snapshot]

    def test_strategy_outcome_identical(self):
        # Same snapshot + same ctx through both -> identical consolidated outcome.
        for make in self.SNAPS:
            snap = make()
            for over in ({}, {"regime": Regime.RANGING, "h4_dir": Direction.NONE},
                         {"news_safe": False}):
                ctx = _ctx(**over)
                a = StrategyEngine().evaluate(snap, ctx).as_dict()
                b = StrategyOrchestrator().evaluate(snap, ctx).as_dict()
                self.assertEqual(a, b, f"{make.__name__} {over}")

    def test_full_scoreresult_identical(self):
        # The ultimate proof: a full scan with the orchestrator injected yields a
        # byte-identical ScoreResult to the default StrategyEngine-based scan.
        for make in self.SNAPS:
            snap = make()
            base = Scanner().scan_symbol(make()).as_dict()
            orch = Scanner(strategy_engine=StrategyOrchestrator()).scan_symbol(make()).as_dict()
            self.assertEqual(base, orch, make.__name__)


class TestConfigGating(unittest.TestCase):
    def _cfg(self, overrides):
        sp = replace(DEFAULT_CONFIG.strategies, enabled_overrides=overrides)
        return replace(DEFAULT_CONFIG, strategies=sp)

    def test_disable_one_removes_it(self):
        orch = StrategyOrchestrator(self._cfg({"Momentum Continuation": False}))
        self.assertNotIn("Momentum Continuation", orch.registered_names)
        self.assertEqual(len(orch.registered_names), 4)
        self.assertIn("Momentum Continuation", orch.disabled_names)

    def test_disable_silent_playbook_preserves_outcome(self):
        # Momentum contributes nothing on the approve fixture, so disabling it
        # must not change the consolidated outcome.
        snap = strong_approve_snapshot()
        ctx = _ctx()
        full = StrategyOrchestrator().evaluate(snap, ctx).as_dict()
        without = StrategyOrchestrator(
            self._cfg({"Momentum Continuation": False, "S&R Bounce": False})
        ).evaluate(snap, ctx).as_dict()
        # net score/direction/conflict identical; only the silent signals dropped
        self.assertEqual(full["net_score"], without["net_score"])
        self.assertEqual(full["direction"], without["direction"])
        self.assertEqual(full["conflict"], without["conflict"])

    def test_disable_all_yields_no_confirmation(self):
        cfg = self._cfg({n: False for n in CANONICAL})
        orch = StrategyOrchestrator(cfg)
        self.assertEqual(orch.registered_names, [])
        out = orch.evaluate(strong_approve_snapshot(), _ctx())
        self.assertEqual(out.net_score, 0.0)
        self.assertEqual(out.direction, Direction.NONE)


if __name__ == "__main__":
    unittest.main()
