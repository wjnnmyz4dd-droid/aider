"""Recovery category (ADR-031 SS9): Watchdog integration -- timeout
detection and a bounded restart allow-list that structurally excludes
Compliance Engine ("never bypass Compliance")."""

from __future__ import annotations

import unittest

from titan_protocol.runtime.models import CycleStage, StageTiming, WatchdogTimeoutKind
from titan_protocol.runtime.watchdog_integration import (
    APPROVED_RESTART_COMPONENTS,
    detect_snapshot_timeout,
    detect_timeouts,
    is_approved_for_restart,
)
from tests.titan_protocol.runtime._fixtures import make_config


class TestTimeoutDetection(unittest.TestCase):
    def test_slow_engine_stage_produces_engine_timeout_signal(self):
        config = make_config(engine_timeout_ms=10.0)
        timings = (StageTiming(CycleStage.EVIDENCE, 50.0),)
        signals = detect_timeouts(timings, total_duration_ms=50.0, config=config)
        self.assertTrue(any(s.kind == WatchdogTimeoutKind.ENGINE for s in signals))

    def test_slow_bridge_stage_produces_bridge_timeout_signal(self):
        config = make_config(bridge_timeout_ms=10.0)
        timings = (StageTiming(CycleStage.BRIDGE, 50.0),)
        signals = detect_timeouts(timings, total_duration_ms=50.0, config=config)
        self.assertTrue(any(s.kind == WatchdogTimeoutKind.BRIDGE for s in signals))

    def test_slow_total_cycle_produces_runtime_timeout_signal(self):
        config = make_config(runtime_timeout_ms=10.0)
        signals = detect_timeouts((), total_duration_ms=50.0, config=config)
        self.assertTrue(any(s.kind == WatchdogTimeoutKind.RUNTIME for s in signals))

    def test_fast_cycle_produces_no_signals(self):
        config = make_config()
        timings = (StageTiming(CycleStage.EVIDENCE, 1.0),)
        signals = detect_timeouts(timings, total_duration_ms=1.0, config=config)
        self.assertEqual(signals, ())

    def test_stale_snapshot_produces_snapshot_timeout_signal(self):
        config = make_config(snapshot_timeout_ms=10.0)
        signals = detect_snapshot_timeout("evidence_engine", snapshot_age_ms=50.0, config=config)
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].kind, WatchdogTimeoutKind.SNAPSHOT)


class TestRestartAllowList(unittest.TestCase):
    def test_compliance_engine_is_never_approved_for_restart(self):
        self.assertNotIn("compliance_engine", APPROVED_RESTART_COMPONENTS)
        self.assertFalse(is_approved_for_restart("compliance_engine"))

    def test_the_four_stateless_engines_are_approved(self):
        for component in ("evidence_engine", "market_intelligence", "strategy_engine", "risk_engine"):
            self.assertTrue(is_approved_for_restart(component))

    def test_bridge_is_not_in_the_restart_allow_list(self):
        self.assertFalse(is_approved_for_restart("bridge"))


if __name__ == "__main__":
    unittest.main()
