"""Scoring Rule Registry: auto-discovery, deterministic ordering, and
duplicate rule ID handling (ADR-004 §5, §14, §15)."""

from __future__ import annotations

import logging
import unittest

from phantom_pipeline.scoring_engine.logging_sink import logger
from phantom_pipeline.scoring_engine.registry import (
    DuplicateRuleIdError,
    ScoringRuleRegistry,
    discover_rule_classes,
)
from phantom_pipeline.scoring_engine.rule import ScoringRule, ScoringRuleMetadata


def _rule_class(rule_id: str, version: str = "1.0.0", class_name: str = "R"):
    metadata = ScoringRuleMetadata(rule_id, version, "test", "test_factor")

    class _R(ScoringRule):
        @property
        def metadata(self) -> ScoringRuleMetadata:
            return metadata

        def evaluate(self, candidate, config):
            raise NotImplementedError

    _R.__name__ = class_name
    return _R


class TestAutoDiscovery(unittest.TestCase):
    def test_no_hard_coded_list_discovers_the_four_real_rules(self):
        classes = discover_rule_classes()
        ids = {cls().metadata.rule_id for cls in classes}
        self.assertEqual(
            ids,
            {
                "SUPPORTING_OBSERVATION_COUNT",
                "EVIDENCE_COUNT",
                "REASON_CODE_PRESENCE",
                "DIRECTIONAL_CLARITY",
            },
        )

    def test_default_registry_construction_uses_auto_discovery(self):
        registry = ScoringRuleRegistry()
        self.assertEqual(len(registry.rules), 4)


class TestDeterministicOrdering(unittest.TestCase):
    def test_registry_order_is_by_rule_id_regardless_of_input_order(self):
        a = _rule_class("ZEBRA", class_name="A")
        b = _rule_class("ALPHA", class_name="B")
        c = _rule_class("MIKE", class_name="C")

        forward = ScoringRuleRegistry(rule_classes=[a, b, c])
        reversed_order = ScoringRuleRegistry(rule_classes=[c, b, a])

        self.assertEqual(forward.registered_ids, ["ALPHA", "MIKE", "ZEBRA"])
        self.assertEqual(forward.registered_ids, reversed_order.registered_ids)


class TestDuplicateRuleIdHandling(unittest.TestCase):
    def setUp(self):
        self.records = []
        self.handler = logging.Handler()
        self.handler.emit = self.records.append
        logger.addHandler(self.handler)
        logger.setLevel(logging.DEBUG)
        self.previous_propagate = logger.propagate
        logger.propagate = False

    def tearDown(self):
        logger.removeHandler(self.handler)
        logger.propagate = self.previous_propagate

    def test_duplicate_rule_id_raises_and_loads_neither(self):
        a = _rule_class("DUP", version="1.0.0", class_name="A")
        b = _rule_class("DUP", version="2.0.0", class_name="B")
        with self.assertRaises(DuplicateRuleIdError):
            ScoringRuleRegistry(rule_classes=[a, b])

    def test_duplicate_detection_is_order_independent(self):
        a = _rule_class("DUP", version="1.0.0", class_name="A")
        b = _rule_class("DUP", version="2.0.0", class_name="B")
        with self.assertRaises(DuplicateRuleIdError):
            ScoringRuleRegistry(rule_classes=[a, b])
        with self.assertRaises(DuplicateRuleIdError):
            ScoringRuleRegistry(rule_classes=[b, a])

    def test_structured_error_log_contains_both_conflicting_ids_names_and_versions(self):
        a = _rule_class("DUP", version="1.0.0", class_name="ClassA")
        b = _rule_class("DUP", version="2.0.0", class_name="ClassB")
        self.records.clear()

        with self.assertRaises(DuplicateRuleIdError):
            ScoringRuleRegistry(rule_classes=[a, b])

        self.assertEqual(len(self.records), 1)
        conflicts = self.records[0].conflicts
        self.assertEqual(len(conflicts), 2)
        self.assertEqual({c["class_name"] for c in conflicts}, {"ClassA", "ClassB"})
        self.assertEqual({c["version"] for c in conflicts}, {"1.0.0", "2.0.0"})
        self.assertEqual({c["rule_id"] for c in conflicts}, {"DUP"})

    def test_non_conflicting_registration_succeeds(self):
        a = _rule_class("A_ID", class_name="A")
        b = _rule_class("B_ID", class_name="B")
        registry = ScoringRuleRegistry(rule_classes=[a, b])
        self.assertEqual(sorted(registry.registered_ids), ["A_ID", "B_ID"])

    def test_real_rules_package_has_no_duplicate_ids(self):
        ScoringRuleRegistry()  # must not raise


class TestFactorByRuleId(unittest.TestCase):
    def test_maps_every_registered_rule_to_its_declared_factor(self):
        registry = ScoringRuleRegistry()
        mapping = registry.factor_by_rule_id
        self.assertEqual(mapping["DIRECTIONAL_CLARITY"], "directional_clarity")
        self.assertEqual(mapping["EVIDENCE_COUNT"], "evidence_strength")
        self.assertEqual(mapping["SUPPORTING_OBSERVATION_COUNT"], "evidence_strength")
        self.assertEqual(mapping["REASON_CODE_PRESENCE"], "traceability")


if __name__ == "__main__":
    unittest.main()
