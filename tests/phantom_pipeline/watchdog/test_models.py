"""Model-level tests (ADR-011 §5, §6) — immutability and the boundary/
type-level "cannot hold a trading instruction" guarantee (§14)."""

from __future__ import annotations

import dataclasses
import unittest

from phantom_pipeline.watchdog.models import (
    ComponentHealth,
    ComponentKind,
    HealthState,
    SystemHealth,
)
from tests.phantom_pipeline.watchdog._fixtures import T0


class TestSystemHealthImmutability(unittest.TestCase):
    def _make(self) -> SystemHealth:
        return SystemHealth(
            schema_version=1,
            trace_id="abc",
            overall_health=HealthState.HEALTHY,
            component_health=[
                ComponentHealth("scanner", ComponentKind.PIPELINE_STAGE, HealthState.HEALTHY, "ok", T0)
            ],
            heartbeat_statuses=[],
            recovery_statuses=[],
            timestamp=T0,
            system_version="1.0.0-phase1",
        )

    def test_is_frozen(self):
        health = self._make()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            health.overall_health = HealthState.CRITICAL

    def test_list_inputs_coerced_to_tuples(self):
        health = self._make()
        self.assertIsInstance(health.component_health, tuple)
        self.assertIsInstance(health.heartbeat_statuses, tuple)
        self.assertIsInstance(health.recovery_statuses, tuple)

    def test_structurally_cannot_hold_a_trading_instruction_field(self):
        """Boundary/type-level test (ADR-011 §5, §14): no field on
        `SystemHealth` or `ComponentHealth` can represent a trading
        instruction or a modified trading-decision object."""
        forbidden_names = {
            "candidate_trade",
            "score_result",
            "risk_decision",
            "compliance_decision",
            "execution_decision",
            "position_management_decision",
            "lot_size",
            "order_instruction",
            "approval_verdict",
        }
        health_fields = {f.name for f in dataclasses.fields(SystemHealth)}
        component_fields = {f.name for f in dataclasses.fields(ComponentHealth)}
        self.assertEqual(forbidden_names & health_fields, set())
        self.assertEqual(forbidden_names & component_fields, set())


if __name__ == "__main__":
    unittest.main()
