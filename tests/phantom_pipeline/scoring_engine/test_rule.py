"""ScoringRule interface contract (ADR-004 §5, §14's rule-consistency
test)."""

from __future__ import annotations

import dataclasses
import unittest

from phantom_pipeline.scoring_engine.registry import discover_rule_classes
from phantom_pipeline.scoring_engine.rule import ScoringRule, ScoringRuleMetadata


class TestScoringRuleInterfaceCannotBeInstantiatedDirectly(unittest.TestCase):
    def test_scoring_rule_abc_cannot_be_instantiated(self):
        with self.assertRaises(TypeError):
            ScoringRule()  # type: ignore[abstract]


class TestScoringRuleMetadataImmutability(unittest.TestCase):
    def test_metadata_is_frozen(self):
        metadata = ScoringRuleMetadata("ID", "1.0.0", "desc", "factor")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            metadata.rule_id = "OTHER"  # type: ignore[misc]


class TestEveryRegisteredRuleSatisfiesTheInterface(unittest.TestCase):
    def test_every_discovered_rule_implements_metadata_and_evaluate(self):
        for cls in discover_rule_classes():
            instance = cls()
            self.assertIsInstance(instance, ScoringRule)
            metadata = instance.metadata
            self.assertIsInstance(metadata, ScoringRuleMetadata)
            self.assertIsInstance(metadata.rule_id, str)
            self.assertTrue(metadata.rule_id)
            self.assertIsInstance(metadata.version, str)
            self.assertIsInstance(metadata.factor, str)
            self.assertTrue(metadata.factor)
            self.assertTrue(callable(instance.evaluate))


if __name__ == "__main__":
    unittest.main()
