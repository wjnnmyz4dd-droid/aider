"""Explainability Service (ONE shared service).

Turns the agent outputs + coordinator decision into a single structured
explanation: evidence used, agent outputs, conflicts, final assessment,
confidence, reason codes, missing data, and WHY the setup was allowed, cautioned,
blocked, or ignored. It is NOT a decision-maker — it only explains a decision
already made deterministically by the coordinator.
"""

from __future__ import annotations

from .contract import Advisory, Assessment, SCHEMA_VERSION

_WHY = {
    Advisory.PROCEED: "Strategy qualified the setup and no agent objected; advisory proceed (deterministic gates still apply).",
    Advisory.CAUTION: "Strategy qualified the setup but one or more agents raised caution; heightened scrutiny advised.",
    Advisory.NO_TRADE: "The setup is not advised to proceed (see reason codes).",
}


class ExplainabilityService:
    service_id = "explainability"
    service_version = "0.1.0"

    def explain(self, request, agent_results, decision, data_quality):
        conflicts = self._conflicts(agent_results)
        missing = self._missing(agent_results, data_quality)
        return {
            "schema_version": SCHEMA_VERSION,
            "service_id": self.service_id,
            "service_version": self.service_version,
            "request_id": request.get("request_id"),
            "correlation_id": request.get("correlation_id"),
            "symbol": request.get("symbol"),
            "final_assessment": decision.get("advisory_decision"),
            "confidence": decision.get("confidence"),
            "confidence_band": decision.get("confidence_band"),
            "reason_codes": decision.get("reason_codes"),
            "evidence_used": {n: r.get("evidence") for n, r in agent_results.items()},
            "agent_outputs": {n: {"assessment": r.get("assessment"),
                                  "confidence": r.get("confidence"),
                                  "reason_codes": r.get("reason_codes"),
                                  "model_id": r.get("model_id"),
                                  "prompt_version": r.get("prompt_version")}
                              for n, r in agent_results.items()},
            "conflicts": conflicts,
            "missing_data": missing,
            "why": _WHY.get(decision.get("advisory_decision"),
                            "Decision explained by reason codes."),
            "is_decision_maker": False,
        }

    def _conflicts(self, agent_results):
        seen = {r.get("assessment") for r in agent_results.values()}
        # a conflict exists when agents disagree across the severity scale
        return sorted(a for a in seen if a in Assessment.ALL) if len(seen) > 1 else []

    def _missing(self, agent_results, data_quality):
        out = {}
        for n, r in agent_results.items():
            if r.get("missing_inputs"):
                out[n] = r["missing_inputs"]
        if data_quality is not None and not data_quality.get("ok", True):
            out["data_quality"] = data_quality.get("missing_inputs", [])
        return out
