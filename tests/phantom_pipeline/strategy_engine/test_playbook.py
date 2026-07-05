"""Playbook interface contract (ADR-003 §5, §16's interface-compatibility
test)."""

from __future__ import annotations

import dataclasses
import unittest

from phantom_pipeline.strategy_engine.config import StrategyEngineConfig
from phantom_pipeline.strategy_engine.playbook import HealthStatus, Playbook, PlaybookMetadata
from phantom_pipeline.strategy_engine.registry import discover_playbook_classes


class TestPlaybookInterfaceCannotBeInstantiatedDirectly(unittest.TestCase):
    def test_playbook_abc_cannot_be_instantiated(self):
        with self.assertRaises(TypeError):
            Playbook()  # type: ignore[abstract]


class TestPlaybookMetadataImmutability(unittest.TestCase):
    def test_metadata_is_frozen(self):
        metadata = PlaybookMetadata("ID", "1.0.0", "desc", (), (), (1,))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            metadata.strategy_id = "OTHER"  # type: ignore[misc]


class TestHealthStatusDefault(unittest.TestCase):
    def test_disabled_by_default_when_unconfigured(self):
        class _P(Playbook):
            _m = PlaybookMetadata("HEALTH_TEST", "1.0.0", "d", (), (), (1,))

            @property
            def metadata(self):
                return self._m

            def evaluate(self, observation, config):
                return ()

        instance = _P()
        self.assertEqual(instance.health_status(StrategyEngineConfig()), HealthStatus.DISABLED)

    def test_healthy_when_explicitly_enabled(self):
        class _P(Playbook):
            _m = PlaybookMetadata("HEALTH_TEST_2", "1.0.0", "d", (), (), (1,))

            @property
            def metadata(self):
                return self._m

            def evaluate(self, observation, config):
                return ()

        instance = _P()
        config = StrategyEngineConfig(enabled_playbooks={"HEALTH_TEST_2": True})
        self.assertEqual(instance.health_status(config), HealthStatus.HEALTHY)


class TestEveryRegisteredPlaybookSatisfiesTheInterface(unittest.TestCase):
    def test_every_discovered_playbook_implements_metadata_and_evaluate(self):
        for cls in discover_playbook_classes():
            instance = cls()
            self.assertIsInstance(instance, Playbook)
            metadata = instance.metadata
            self.assertIsInstance(metadata, PlaybookMetadata)
            self.assertIsInstance(metadata.strategy_id, str)
            self.assertTrue(metadata.strategy_id)
            self.assertIsInstance(metadata.version, str)
            self.assertIsInstance(metadata.supported_symbols, tuple)
            self.assertIsInstance(metadata.supported_timeframes, tuple)
            self.assertIsInstance(metadata.schema_versions_supported, tuple)
            self.assertTrue(callable(instance.evaluate))


if __name__ == "__main__":
    unittest.main()
