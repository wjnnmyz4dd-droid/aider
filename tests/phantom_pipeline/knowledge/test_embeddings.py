"""EmbeddingProvider tests — determinism, dimension stability,
corpus-order independence (ADR-020 §6), and the SentenceTransformer
provider's lazy-import/injectable-model seam."""

from __future__ import annotations

import math
import unittest

from phantom_pipeline.knowledge.embeddings import HashingEmbeddingProvider, SentenceTransformerEmbeddingProvider


class TestHashingEmbeddingProviderDeterminism(unittest.TestCase):
    def test_identical_text_yields_identical_vector(self):
        provider = HashingEmbeddingProvider(dimension=64)
        v1 = provider.embed("Risk approved at 1.00%")
        v2 = provider.embed("Risk approved at 1.00%")
        self.assertEqual(v1, v2)

    def test_dimension_matches_configured_value(self):
        provider = HashingEmbeddingProvider(dimension=128)
        vector = provider.embed("some text")
        self.assertEqual(len(vector), 128)
        self.assertEqual(provider.dimension, 128)

    def test_empty_text_yields_zero_vector(self):
        provider = HashingEmbeddingProvider(dimension=32)
        vector = provider.embed("")
        self.assertEqual(vector, tuple(0.0 for _ in range(32)))

    def test_vector_is_l2_normalized(self):
        provider = HashingEmbeddingProvider(dimension=64)
        vector = provider.embed("a fairly long piece of text with many different tokens in it")
        norm = math.sqrt(sum(v * v for v in vector))
        self.assertAlmostEqual(norm, 1.0, places=6)

    def test_different_text_yields_different_vector(self):
        provider = HashingEmbeddingProvider(dimension=64)
        self.assertNotEqual(provider.embed("EURUSD trade won"), provider.embed("GBPUSD trade lost"))

    def test_embedding_is_stable_regardless_of_prior_calls(self):
        """The hashing trick has no corpus-order dependence (unlike
        TF-IDF) — embedding many other texts first must not change a
        later call's result for the same text."""
        provider = HashingEmbeddingProvider(dimension=64)
        before = provider.embed("stable text")
        for i in range(50):
            provider.embed(f"unrelated document {i}")
        after = provider.embed("stable text")
        self.assertEqual(before, after)

    def test_model_name_reflects_dimension(self):
        provider = HashingEmbeddingProvider(dimension=100)
        self.assertIn("100", provider.model_name)

    def test_embed_batch_matches_individual_embed_calls(self):
        provider = HashingEmbeddingProvider(dimension=32)
        texts = ["alpha", "beta", "gamma"]
        batch = provider.embed_batch(texts)
        individual = tuple(provider.embed(t) for t in texts)
        self.assertEqual(batch, individual)


class _FakeSentenceTransformerModel:
    def encode(self, texts):
        if isinstance(texts, str):
            return [float(len(texts)), 1.0, 2.0]
        return [[float(len(t)), 1.0, 2.0] for t in texts]

    def get_sentence_embedding_dimension(self):
        return 3


class TestSentenceTransformerEmbeddingProviderInjection(unittest.TestCase):
    def test_uses_injected_model_without_importing_the_real_package(self):
        provider = SentenceTransformerEmbeddingProvider(model=_FakeSentenceTransformerModel())
        vector = provider.embed("hi")
        self.assertEqual(vector, (2.0, 1.0, 2.0))

    def test_dimension_uses_model_reported_dimension(self):
        provider = SentenceTransformerEmbeddingProvider(model=_FakeSentenceTransformerModel())
        self.assertEqual(provider.dimension, 3)

    def test_embed_batch(self):
        provider = SentenceTransformerEmbeddingProvider(model=_FakeSentenceTransformerModel())
        batch = provider.embed_batch(["a", "bb"])
        self.assertEqual(batch, ((1.0, 1.0, 2.0), (2.0, 1.0, 2.0)))

    def test_raises_a_clear_error_when_package_not_installed_and_no_model_injected(self):
        provider = SentenceTransformerEmbeddingProvider()
        with self.assertRaises(RuntimeError):
            provider.embed("hi")


if __name__ == "__main__":
    unittest.main()
