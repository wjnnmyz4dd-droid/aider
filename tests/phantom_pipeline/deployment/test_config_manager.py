"""ConfigurationManager tests — profile loading and pre-startup
validation (missing secrets, invalid MT5 account, wrong broker profile,
LIVE-must-not-paper-trade)."""

from __future__ import annotations

import unittest

from phantom_pipeline.deployment.config_manager import ConfigurationManager
from phantom_pipeline.deployment.models import DeploymentProfile


class TestLoadProfile(unittest.TestCase):
    def test_loads_fields_from_source_mapping(self):
        manager = ConfigurationManager()
        source = {
            "MT5_LOGIN": "12345",
            "MT5_SERVER": "Broker-Live",
            "BROKER_PROFILE": "FTMO",
            "PAPER_TRADING_ENABLED": "false",
            "ALLOWED_BROKER_PROFILES": "FTMO,FundedNext",
        }
        config = manager.load_profile(DeploymentProfile.LIVE, source)
        self.assertEqual(config.mt5_login, "12345")
        self.assertEqual(config.broker_profile_name, "FTMO")
        self.assertFalse(config.paper_trading_enabled)
        self.assertEqual(config.allowed_broker_profiles, ("FTMO", "FundedNext"))


class TestValidate(unittest.TestCase):
    def setUp(self):
        self.manager = ConfigurationManager()

    def test_dev_profile_does_not_require_secrets(self):
        source: dict = {}
        config = self.manager.load_profile(DeploymentProfile.DEV, source)
        result = self.manager.validate(config, source)
        self.assertTrue(result.valid)

    def test_live_profile_missing_secrets_is_invalid(self):
        source: dict = {}
        config = self.manager.load_profile(DeploymentProfile.LIVE, source)
        result = self.manager.validate(config, source)
        self.assertFalse(result.valid)
        fields = {issue.field for issue in result.issues}
        self.assertIn("MT5_LOGIN", fields)
        self.assertIn("MT5_PASSWORD", fields)
        self.assertIn("MT5_SERVER", fields)

    def test_non_numeric_mt5_login_is_invalid(self):
        source = {"MT5_LOGIN": "not-a-number", "MT5_PASSWORD": "x", "MT5_SERVER": "s"}
        config = self.manager.load_profile(DeploymentProfile.LIVE, source)
        result = self.manager.validate(config, source)
        self.assertFalse(result.valid)
        self.assertTrue(any(i.field == "mt5_login" for i in result.issues))

    def test_broker_profile_not_in_allowed_set_is_invalid(self):
        source = {
            "MT5_LOGIN": "12345", "MT5_PASSWORD": "x", "MT5_SERVER": "s",
            "BROKER_PROFILE": "UnknownBroker", "ALLOWED_BROKER_PROFILES": "FTMO,FundedNext",
        }
        config = self.manager.load_profile(DeploymentProfile.LIVE, source)
        result = self.manager.validate(config, source)
        self.assertFalse(result.valid)
        self.assertTrue(any(i.field == "broker_profile_name" for i in result.issues))

    def test_live_profile_with_paper_trading_enabled_is_invalid(self):
        source = {
            "MT5_LOGIN": "12345", "MT5_PASSWORD": "x", "MT5_SERVER": "s",
            "PAPER_TRADING_ENABLED": "true",
        }
        config = self.manager.load_profile(DeploymentProfile.LIVE, source)
        result = self.manager.validate(config, source)
        self.assertFalse(result.valid)
        self.assertTrue(any(i.field == "paper_trading_enabled" for i in result.issues))

    def test_valid_live_configuration_passes(self):
        source = {
            "MT5_LOGIN": "12345", "MT5_PASSWORD": "x", "MT5_SERVER": "s",
            "BROKER_PROFILE": "FTMO", "ALLOWED_BROKER_PROFILES": "FTMO",
            "PAPER_TRADING_ENABLED": "false",
        }
        config = self.manager.load_profile(DeploymentProfile.LIVE, source)
        result = self.manager.validate(config, source)
        self.assertTrue(result.valid)


if __name__ == "__main__":
    unittest.main()
