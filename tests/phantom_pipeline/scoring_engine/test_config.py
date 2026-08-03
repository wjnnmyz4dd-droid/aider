"""ScoringEngineConfig immutability and safe-default-disabled semantics
(ADR-004 §11)."""

from __future__ import annotations

import dataclasses
import unittest

from phantom_pipeline.scoring_engine.config import ScoringEngineConfig


class TestScoringEngineConfigImmutability(unittest.TestCase):
    def test_top_level_fields_cannot_be_reassigned(self):
        config = ScoringEngineConfig()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            config.default_weight = 5.0  # type: ignore[misc]

    def test_enabled_rules_mapping_cannot_be_mutated(self):
        config = ScoringEngineConfig(enabled_rules={"R1": True})
        with self.assertRaises(TypeError):
            config.enabled_rules["R2"] = True  # type: ignore[index]

    def test_rule_weights_mapping_cannot_be_mutated(self):
        config = ScoringEngineConfig(rule_weights={"R1": 2.0})
        with self.assertRaises(TypeError):
            config.rule_weights["R2"] = 3.0  # type: ignore[index]

    def test_mutating_caller_supplied_dicts_after_construction_does_not_affect_config(self):
        enabled = {"R1": True}
        weights = {"R1": 2.0}
        config = ScoringEngineConfig(enabled_rules=enabled, rule_weights=weights)
        enabled["R2"] = True
        weights["R2"] = 9.0
        self.assertNotIn("R2", config.enabled_rules)
        self.assertNotIn("R2", config.rule_weights)


class TestSafeDefaults(unittest.TestCase):
    def test_unconfigured_rule_is_disabled(self):
        config = ScoringEngineConfig()
        self.assertFalse(config.is_enabled("ANY_RULE_ID"))

    def test_explicitly_enabled_rule_is_enabled(self):
        config = ScoringEngineConfig(enabled_rules={"R1": True})
        self.assertTrue(config.is_enabled("R1"))

    def test_explicitly_disabled_rule_is_disabled(self):
        config = ScoringEngineConfig(enabled_rules={"R1": False})
        self.assertFalse(config.is_enabled("R1"))

    def test_unconfigured_weight_uses_default_weight(self):
        config = ScoringEngineConfig(default_weight=3.0)
        self.assertEqual(config.weight_for("ANY_RULE_ID"), 3.0)

    def test_explicit_weight_override(self):
        config = ScoringEngineConfig(rule_weights={"R1": 7.5}, default_weight=1.0)
        self.assertEqual(config.weight_for("R1"), 7.5)
        self.assertEqual(config.weight_for("OTHER"), 1.0)


if __name__ == "__main__":
    unittest.main()
