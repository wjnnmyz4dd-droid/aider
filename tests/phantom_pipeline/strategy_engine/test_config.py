"""StrategyEngineConfig immutability and safe-default-disabled semantics
(ADR-003 §13)."""

from __future__ import annotations

import dataclasses
import unittest

from phantom_pipeline.strategy_engine.config import StrategyEngineConfig


class TestStrategyEngineConfigImmutability(unittest.TestCase):
    def test_top_level_fields_cannot_be_reassigned(self):
        config = StrategyEngineConfig()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            config.log_level = 10  # type: ignore[misc]

    def test_enabled_playbooks_mapping_cannot_be_mutated(self):
        config = StrategyEngineConfig(enabled_playbooks={"ORB": True})
        with self.assertRaises(TypeError):
            config.enabled_playbooks["OTHER"] = True  # type: ignore[index]

    def test_mutating_caller_supplied_dict_after_construction_does_not_affect_config(self):
        overrides = {"ORB": True}
        config = StrategyEngineConfig(enabled_playbooks=overrides)
        overrides["OTHER"] = True
        self.assertNotIn("OTHER", config.enabled_playbooks)


class TestSafeDefaultDisabled(unittest.TestCase):
    def test_unconfigured_playbook_is_disabled(self):
        config = StrategyEngineConfig()
        self.assertFalse(config.is_enabled("ANY_STRATEGY_ID"))

    def test_explicitly_enabled_playbook_is_enabled(self):
        config = StrategyEngineConfig(enabled_playbooks={"ORB": True})
        self.assertTrue(config.is_enabled("ORB"))

    def test_explicitly_disabled_playbook_is_disabled(self):
        config = StrategyEngineConfig(enabled_playbooks={"ORB": False})
        self.assertFalse(config.is_enabled("ORB"))


if __name__ == "__main__":
    unittest.main()
