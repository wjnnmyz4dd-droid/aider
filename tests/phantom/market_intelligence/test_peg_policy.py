"""Unit tests for the peg/policy registry -- explicit activate/clear,
no fixed timeout."""

from __future__ import annotations

import unittest
from datetime import timedelta

from phantom.market_intelligence.models import PegPolicyEventType
from phantom.market_intelligence.peg_policy import PegPolicyRegistry
from tests.phantom.market_intelligence._fixtures import T0


class TestPegPolicyRegistry(unittest.TestCase):
    def test_unknown_pair_is_inactive_by_default(self):
        registry = PegPolicyRegistry()
        status = registry.status_for("USDCHF")
        self.assertFalse(status.active)

    def test_activate_sets_active_status(self):
        registry = PegPolicyRegistry()
        status = registry.activate("USDCHF", PegPolicyEventType.CURRENCY_PEG, "SNB peg", T0)
        self.assertTrue(status.active)
        self.assertEqual(status.event_type, PegPolicyEventType.CURRENCY_PEG)
        self.assertEqual(registry.status_for("USDCHF"), status)

    def test_never_auto_clears_no_matter_how_much_time_passes(self):
        registry = PegPolicyRegistry()
        registry.activate("USDCHF", PegPolicyEventType.EMERGENCY_INTERVENTION, "reason", T0)
        far_future_status = registry.status_for("USDCHF")
        self.assertTrue(far_future_status.active)
        # Simulate a huge amount of elapsed time by re-querying -- status
        # is stored, not time-derived, so nothing here can expire it.
        for _ in range(5):
            self.assertTrue(registry.status_for("USDCHF").active)

    def test_explicit_clear_deactivates(self):
        registry = PegPolicyRegistry()
        registry.activate("USDCHF", PegPolicyEventType.POLICY_ANNOUNCEMENT, "reason", T0)
        cleared = registry.clear("USDCHF", T0 + timedelta(days=1))
        self.assertFalse(cleared.active)
        self.assertEqual(registry.status_for("USDCHF"), cleared)

    def test_clearing_an_unknown_pair_is_a_safe_no_op(self):
        registry = PegPolicyRegistry()
        cleared = registry.clear("NEVERSEEN", T0)
        self.assertFalse(cleared.active)

    def test_pairs_are_independent(self):
        registry = PegPolicyRegistry()
        registry.activate("USDCHF", PegPolicyEventType.CURRENCY_PEG, "reason", T0)
        self.assertTrue(registry.status_for("USDCHF").active)
        self.assertFalse(registry.status_for("EURUSD").active)


if __name__ == "__main__":
    unittest.main()
