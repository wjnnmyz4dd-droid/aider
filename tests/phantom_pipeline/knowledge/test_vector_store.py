"""InMemoryVectorStore tests — cosine ranking, metadata filtering,
thread safety, dedup-adjacent overwrite semantics (ADR-020 §8)."""

from __future__ import annotations

import threading
import unittest

from phantom_pipeline.knowledge.vector_store import InMemoryVectorStore, _cosine_similarity


class TestCosineSimilarity(unittest.TestCase):
    def test_identical_vectors_score_one(self):
        self.assertAlmostEqual(_cosine_similarity((1.0, 0.0), (1.0, 0.0)), 1.0)

    def test_orthogonal_vectors_score_zero(self):
        self.assertAlmostEqual(_cosine_similarity((1.0, 0.0), (0.0, 1.0)), 0.0)

    def test_opposite_vectors_score_negative_one(self):
        self.assertAlmostEqual(_cosine_similarity((1.0, 0.0), (-1.0, 0.0)), -1.0)

    def test_zero_vector_scores_zero_never_raises(self):
        self.assertEqual(_cosine_similarity((0.0, 0.0), (1.0, 0.0)), 0.0)

    def test_mismatched_dimension_raises(self):
        with self.assertRaises(ValueError):
            _cosine_similarity((1.0, 0.0), (1.0, 0.0, 0.0))


class TestInMemoryVectorStore(unittest.TestCase):
    def test_add_and_search_ranks_by_similarity(self):
        store = InMemoryVectorStore()
        store.add("a", (1.0, 0.0))
        store.add("b", (0.0, 1.0))
        store.add("c", (0.9, 0.1))

        results = store.search((1.0, 0.0), top_k=3)

        self.assertEqual([doc_id for doc_id, _ in results], ["a", "c", "b"])

    def test_top_k_limits_results(self):
        store = InMemoryVectorStore()
        for i in range(5):
            store.add(f"doc-{i}", (1.0, float(i)))
        results = store.search((1.0, 0.0), top_k=2)
        self.assertEqual(len(results), 2)

    def test_metadata_filter_excludes_non_matching(self):
        store = InMemoryVectorStore()
        store.add("a", (1.0, 0.0), metadata={"kind": "ADR"})
        store.add("b", (1.0, 0.0), metadata={"kind": "TRADE"})

        results = store.search((1.0, 0.0), top_k=10, filters={"kind": "ADR"})

        self.assertEqual([doc_id for doc_id, _ in results], ["a"])

    def test_delete_removes_from_search(self):
        store = InMemoryVectorStore()
        store.add("a", (1.0, 0.0))
        store.delete("a")
        self.assertEqual(store.search((1.0, 0.0), top_k=10), ())
        self.assertEqual(store.count, 0)

    def test_contains(self):
        store = InMemoryVectorStore()
        store.add("a", (1.0, 0.0))
        self.assertIn("a", store)
        self.assertNotIn("b", store)

    def test_re_adding_same_id_overwrites_vector(self):
        store = InMemoryVectorStore()
        store.add("a", (1.0, 0.0))
        store.add("a", (0.0, 1.0))
        self.assertEqual(store.count, 1)
        results = store.search((0.0, 1.0), top_k=1)
        self.assertAlmostEqual(results[0][1], 1.0)

    def test_thread_safety_concurrent_add_and_search(self):
        store = InMemoryVectorStore()
        errors = []

        def _writer(n):
            try:
                for i in range(50):
                    store.add(f"doc-{n}-{i}", (1.0, float(i)))
            except Exception as exc:  # pragma: no cover - test fails if this triggers
                errors.append(exc)

        def _reader():
            try:
                for _ in range(50):
                    store.search((1.0, 0.0), top_k=5)
            except Exception as exc:  # pragma: no cover - test fails if this triggers
                errors.append(exc)

        threads = [threading.Thread(target=_writer, args=(n,)) for n in range(4)] + [
            threading.Thread(target=_reader) for _ in range(4)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        self.assertEqual(store.count, 200)


if __name__ == "__main__":
    unittest.main()
