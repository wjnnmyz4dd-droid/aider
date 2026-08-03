"""Embedding providers for the Knowledge & RAG subsystem (`ADR-020`
Hard Rule 6).

`EmbeddingProvider` is a structural interface; two implementations ship:

- `HashingEmbeddingProvider` — the default, dependency-free, fully
  deterministic option (the "hashing trick": each token contributes a
  signed unit to a fixed-size vector at `hash(token) % dimension`,
  L2-normalized). Produces the *same* vector for the same text
  regardless of corpus size or ingestion order — unlike TF-IDF, whose
  vocabulary/IDF statistics shift as the corpus grows, this is stable
  under incremental indexing, which is why it was chosen over TF-IDF
  (see `docs/plans/knowledge-rag-subsystem.md`). Used by every test and
  by `DEV`/CI.
- `SentenceTransformerEmbeddingProvider` — a real neural-embedding option
  for VPS deployments that want higher retrieval quality, lazily
  importing the optional `sentence-transformers` package (mirrors
  `mt5_bridge.mt5_adapter.MT5Adapter`'s own lazy-import-with-injectable-
  module pattern) — never required for this package to import cleanly.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any, Optional, Protocol, Sequence, Tuple

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


class EmbeddingProvider(Protocol):
    @property
    def model_name(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    def embed(self, text: str) -> Tuple[float, ...]: ...

    def embed_batch(self, texts: Sequence[str]) -> Tuple[Tuple[float, ...], ...]: ...


class HashingEmbeddingProvider:
    def __init__(self, dimension: int = 256) -> None:
        self._dimension = dimension

    @property
    def model_name(self) -> str:
        return f"hashing-{self._dimension}"

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, text: str) -> Tuple[float, ...]:
        tokens = _TOKEN_RE.findall(text.lower())
        vector = [0.0] * self._dimension
        if not tokens:
            return tuple(vector)
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self._dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0.0:
            return tuple(vector)
        return tuple(v / norm for v in vector)

    def embed_batch(self, texts: Sequence[str]) -> Tuple[Tuple[float, ...], ...]:
        return tuple(self.embed(text) for text in texts)


def _import_sentence_transformers() -> Any:
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "SentenceTransformerEmbeddingProvider requires the optional "
            "'sentence-transformers' package; install it or pass model= for testing."
        ) from exc
    return SentenceTransformer


class SentenceTransformerEmbeddingProvider:
    def __init__(self, model_name: str = "all-MiniLM-L6-v2", model: Optional[Any] = None) -> None:
        self._model_name = model_name
        self._model = model
        self._dimension: Optional[int] = None

    def _client(self) -> Any:
        if self._model is None:
            SentenceTransformer = _import_sentence_transformers()
            self._model = SentenceTransformer(self._model_name)
        return self._model

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        if self._dimension is None:
            client = self._client()
            getter = getattr(client, "get_sentence_embedding_dimension", None)
            self._dimension = int(getter()) if getter is not None else len(self.embed("dimension probe"))
        return self._dimension

    def embed(self, text: str) -> Tuple[float, ...]:
        vector = self._client().encode(text)
        return tuple(float(v) for v in vector)

    def embed_batch(self, texts: Sequence[str]) -> Tuple[Tuple[float, ...], ...]:
        vectors = self._client().encode(list(texts))
        return tuple(tuple(float(v) for v in vector) for vector in vectors)


__all__ = ["EmbeddingProvider", "HashingEmbeddingProvider", "SentenceTransformerEmbeddingProvider"]
