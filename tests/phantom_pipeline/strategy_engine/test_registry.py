"""Strategy Registry: auto-discovery, deterministic ordering, and
duplicate Strategy ID handling (ADR-003 §7, §16)."""

from __future__ import annotations

import logging
import unittest

from phantom_pipeline.strategy_engine.logging_sink import logger
from phantom_pipeline.strategy_engine.playbook import Playbook, PlaybookMetadata
from phantom_pipeline.strategy_engine.registry import (
    DuplicateStrategyIdError,
    StrategyRegistry,
    discover_playbook_classes,
)


def _playbook_class(strategy_id: str, version: str = "1.0.0", class_name: str = "P"):
    metadata = PlaybookMetadata(strategy_id, version, "test", (), (), (1,))

    class _P(Playbook):
        @property
        def metadata(self) -> PlaybookMetadata:
            return metadata

        def evaluate(self, observation, config):
            return ()

    _P.__name__ = class_name
    return _P


class TestAutoDiscovery(unittest.TestCase):
    def test_no_hard_coded_list_discovers_the_five_reserved_playbooks(self):
        classes = discover_playbook_classes()
        ids = {cls().metadata.strategy_id for cls in classes}
        self.assertEqual(
            ids,
            {
                "ORB",
                "LIQUIDITY_REVERSAL",
                "SESSION_BREAKOUT",
                "TREND_CONTINUATION",
                "RANGE_REVERSAL",
            },
        )

    def test_default_registry_construction_uses_auto_discovery(self):
        registry = StrategyRegistry()
        self.assertEqual(len(registry.playbooks), 5)


class TestDeterministicOrdering(unittest.TestCase):
    def test_registry_order_is_by_strategy_id_regardless_of_input_order(self):
        a = _playbook_class("ZEBRA", class_name="A")
        b = _playbook_class("ALPHA", class_name="B")
        c = _playbook_class("MIKE", class_name="C")

        forward = StrategyRegistry(playbook_classes=[a, b, c])
        reversed_order = StrategyRegistry(playbook_classes=[c, b, a])

        self.assertEqual(forward.registered_ids, ["ALPHA", "MIKE", "ZEBRA"])
        self.assertEqual(forward.registered_ids, reversed_order.registered_ids)


class TestDuplicateStrategyIdHandling(unittest.TestCase):
    def setUp(self):
        self.handler = logging.Handler()
        self.records = []
        self.handler.emit = self.records.append
        logger.addHandler(self.handler)
        logger.setLevel(logging.DEBUG)
        self.previous_propagate = logger.propagate
        logger.propagate = False

    def tearDown(self):
        logger.removeHandler(self.handler)
        logger.propagate = self.previous_propagate

    def test_duplicate_strategy_id_raises_and_loads_neither(self):
        a = _playbook_class("DUP", version="1.0.0", class_name="A")
        b = _playbook_class("DUP", version="2.0.0", class_name="B")

        with self.assertRaises(DuplicateStrategyIdError):
            StrategyRegistry(playbook_classes=[a, b])

    def test_duplicate_detection_is_order_independent(self):
        a = _playbook_class("DUP", version="1.0.0", class_name="A")
        b = _playbook_class("DUP", version="2.0.0", class_name="B")

        with self.assertRaises(DuplicateStrategyIdError):
            StrategyRegistry(playbook_classes=[a, b])
        with self.assertRaises(DuplicateStrategyIdError):
            StrategyRegistry(playbook_classes=[b, a])

    def test_structured_error_log_contains_both_conflicting_ids_names_and_versions(self):
        a = _playbook_class("DUP", version="1.0.0", class_name="ClassA")
        b = _playbook_class("DUP", version="2.0.0", class_name="ClassB")
        self.records.clear()

        with self.assertRaises(DuplicateStrategyIdError):
            StrategyRegistry(playbook_classes=[a, b])

        self.assertEqual(len(self.records), 1)
        conflicts = self.records[0].conflicts
        self.assertEqual(len(conflicts), 2)
        class_names = {c["class_name"] for c in conflicts}
        versions = {c["version"] for c in conflicts}
        strategy_ids = {c["strategy_id"] for c in conflicts}
        self.assertEqual(class_names, {"ClassA", "ClassB"})
        self.assertEqual(versions, {"1.0.0", "2.0.0"})
        self.assertEqual(strategy_ids, {"DUP"})

    def test_non_conflicting_registration_succeeds(self):
        a = _playbook_class("A_ID", class_name="A")
        b = _playbook_class("B_ID", class_name="B")
        registry = StrategyRegistry(playbook_classes=[a, b])
        self.assertEqual(sorted(registry.registered_ids), ["A_ID", "B_ID"])

    def test_real_playbooks_package_has_no_duplicate_ids(self):
        # Sanity check on production content: must not raise.
        StrategyRegistry()


if __name__ == "__main__":
    unittest.main()
