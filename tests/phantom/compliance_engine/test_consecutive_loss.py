"""Unit tests: Consecutive Loss Protection (ADR-028 §5.4)."""

from __future__ import annotations

import unittest

from phantom.compliance_engine.consecutive_loss import consecutive_loss_pause_triggered
from tests.phantom.compliance_engine._fixtures import make_account_state, make_config


class TestConsecutiveLossProtection(unittest.TestCase):
    def test_below_threshold_not_triggered(self):
        config = make_config(consecutive_loss_pause_threshold=3)
        account = make_account_state(consecutive_losses=2)
        self.assertFalse(consecutive_loss_pause_triggered(account, config))

    def test_at_threshold_triggered(self):
        config = make_config(consecutive_loss_pause_threshold=3)
        account = make_account_state(consecutive_losses=3)
        self.assertTrue(consecutive_loss_pause_triggered(account, config))

    def test_above_threshold_triggered(self):
        config = make_config(consecutive_loss_pause_threshold=3)
        account = make_account_state(consecutive_losses=5)
        self.assertTrue(consecutive_loss_pause_triggered(account, config))

    def test_zero_losses_not_triggered(self):
        config = make_config(consecutive_loss_pause_threshold=3)
        account = make_account_state(consecutive_losses=0)
        self.assertFalse(consecutive_loss_pause_triggered(account, config))


if __name__ == "__main__":
    unittest.main()
