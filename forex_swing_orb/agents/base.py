"""Base agent: versioned envelope handling, fail-closed, structured output.

Every agent accepts a versioned request + a read-only context and returns a
versioned structured result. Agents are advisory: they cannot place trades,
write bridge instructions, or reach the network. The base enforces the contract
and fails closed (BLOCK, zero confidence) on any contract violation.

Subclasses implement ``_assess`` and return a dict with the structured verdict.
LLM-eligible agents may call ``self.llm`` for a natural-language explanation and
MUST capture ``model_id``/``prompt_version`` — the structured assessment itself
stays deterministic.
"""

from __future__ import annotations

from ..bridge import serialize
from .contract import (Assessment, ReasonCode, build_result, validate_request,
                       validate_result, LLM_ELIGIBLE_AGENTS, DETERMINISTIC_ONLY)


class Agent:
    agent_id = "base"
    agent_version = "0.1.0"
    uses_llm = False

    def __init__(self, llm=None):
        # A deterministic-only agent must never hold an LLM provider.
        if self.agent_id in DETERMINISTIC_ONLY and llm is not None:
            raise ValueError(f"{self.agent_id} is deterministic-only; no LLM allowed")
        if self.uses_llm and self.agent_id not in LLM_ELIGIBLE_AGENTS:
            raise ValueError(f"{self.agent_id} is not LLM-eligible")
        self.llm = llm if self.uses_llm else None

    # -- public API ---------------------------------------------------------
    def evaluate(self, request, context, now=None):
        ts = serialize.iso_utc(now) if now is not None else None
        ok, reason, detail = validate_request(request)
        if not ok:
            return self._fail_closed(request if isinstance(request, dict) else {},
                                     [reason], ts, detail)
        try:
            out = self._assess(request, context, now)
        except Exception as exc:                      # fail closed on any error
            return self._fail_closed(request, [ReasonCode.INSUFFICIENT_EVIDENCE],
                                     ts, {"error": type(exc).__name__})
        result = build_result(
            self.agent_id, self.agent_version, request,
            assessment=out.get("assessment", Assessment.BLOCK),
            confidence=out.get("confidence", 0.0),
            evidence=out.get("evidence"),
            reason_codes=out.get("reason_codes"),
            data_freshness=out.get("data_freshness"),
            missing_inputs=out.get("missing_inputs"),
            model_id=out.get("model_id"),
            prompt_version=out.get("prompt_version"),
            generated_timestamp=ts,
        )
        valid, vreason, vdetail = validate_result(result)
        if not valid:
            return self._fail_closed(request, [vreason], ts, vdetail)
        return result

    # -- helpers ------------------------------------------------------------
    def _fail_closed(self, request, reason_codes, ts, detail=None):
        return build_result(
            self.agent_id, self.agent_version, request,
            assessment=Assessment.BLOCK, confidence=0.0,
            evidence={"fail_closed": True, "detail": detail or {}},
            reason_codes=list(reason_codes), missing_inputs=[],
            generated_timestamp=ts,
        )

    def _assess(self, request, context, now):
        raise NotImplementedError
