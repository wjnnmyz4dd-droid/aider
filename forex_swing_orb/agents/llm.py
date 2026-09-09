"""Shared LLM provider abstraction (ONE interface for all agents).

There is a single model-provider abstraction; agents never construct their own
client. In this phase only a deterministic, offline mock provider ships — it does
NO networking. Real providers (added in a later phase) implement the same
``LLMProvider`` interface. Deterministic safety-critical components must never
route through this module.

Every completion returns the ``model_id`` and ``prompt_version`` used, so agents
can capture provenance in their structured result.
"""

from __future__ import annotations

import hashlib

from ..bridge import serialize


class LLMResponse:
    __slots__ = ("text", "model_id", "prompt_version", "usage", "structured")

    def __init__(self, text, model_id, prompt_version, usage=None, structured=None):
        self.text = text
        self.model_id = model_id
        self.prompt_version = prompt_version
        self.usage = usage or {}
        self.structured = structured or {}


class LLMProvider:
    """Interface every model provider implements. Deterministic-only components
    must not use it. Implementations MUST NOT be constructed per-agent — one
    shared instance is injected into the orchestrator."""

    model_id = "abstract"

    def complete(self, prompt, *, prompt_version, max_tokens=512, temperature=0.0):
        raise NotImplementedError

    def summarize(self, prompt, *, prompt_version):
        return self.complete(prompt, prompt_version=prompt_version)


class MockLLMProvider(LLMProvider):
    """Deterministic, offline stand-in. Same input -> same output; no network.

    The 'reasoning' is a stable hash-derived digest of the prompt so tests are
    reproducible. It carries model_id/prompt_version for provenance capture.
    """

    def __init__(self, model_id="mock-llm.v1"):
        self.model_id = model_id
        self.calls = []

    def complete(self, prompt, *, prompt_version, max_tokens=512, temperature=0.0):
        payload = serialize.canonical_json(
            {"prompt": prompt, "pv": prompt_version, "mt": max_tokens, "t": temperature})
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        self.calls.append({"prompt_version": prompt_version, "digest": digest[:16]})
        text = f"[mock:{self.model_id}:{prompt_version}] deterministic-summary#{digest[:12]}"
        return LLMResponse(text=text, model_id=self.model_id,
                           prompt_version=prompt_version,
                           usage={"prompt_chars": len(str(prompt))},
                           structured={"digest": digest[:16]})
