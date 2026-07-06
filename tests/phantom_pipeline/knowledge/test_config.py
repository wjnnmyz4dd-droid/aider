"""KnowledgeConfig tests — defaults are sane and immutable."""

from __future__ import annotations

import dataclasses
import unittest

from phantom_pipeline.knowledge.config import DEFAULT_CONFIG, KNOWLEDGE_VERSION, KnowledgeConfig


class TestKnowledgeConfig(unittest.TestCase):
    def test_default_config_has_positive_dimension_and_top_k(self):
        self.assertGreater(DEFAULT_CONFIG.embedding_dimension, 0)
        self.assertGreater(DEFAULT_CONFIG.default_top_k, 0)

    def test_deduplicate_documents_defaults_true(self):
        self.assertTrue(DEFAULT_CONFIG.deduplicate_documents)

    def test_is_frozen(self):
        with self.assertRaises(dataclasses.FrozenInstanceError):
            DEFAULT_CONFIG.default_top_k = 999  # type: ignore[misc]

    def test_custom_config_overrides(self):
        config = KnowledgeConfig(embedding_dimension=512, default_top_k=5)
        self.assertEqual(config.embedding_dimension, 512)
        self.assertEqual(config.default_top_k, 5)

    def test_version_string_is_non_empty(self):
        self.assertTrue(KNOWLEDGE_VERSION)


if __name__ == "__main__":
    unittest.main()
