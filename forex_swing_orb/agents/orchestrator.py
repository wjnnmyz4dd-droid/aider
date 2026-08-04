"""Orchestration skeleton (frozen order; advisory only).

Runs the fixed pipeline and produces one advisory decision plus its explanation,
and writes advisory memory records. It has NO access to the filesystem bridge
producer or the MT5 adapter and cannot place, size, or modify a trade. The
deterministic Session Edge strategy stays OUTSIDE this orchestrator and is
authoritative: ``strategy_candidate`` is an input, never computed here.

Frozen order:
  1 data quality validation
  2 Market Intelligence
  3 Liquidity
  4 News & Compliance
  5 Risk
  6 Critic
  7 Decision Coordinator
  8 Explainability
  9 Memory write
"""

from __future__ import annotations

from ..bridge import serialize
from . import data_quality
from .agents.market_intelligence import MarketIntelligenceAgent
from .agents.liquidity import LiquidityAgent
from .agents.news_compliance import NewsComplianceAgent
from .agents.risk import RiskAgent
from .agents.critic import CriticAgent
from .coordinator import DecisionCoordinator
from .explain import ExplainabilityService

ORCHESTRATION_ORDER = (
    "data_quality", "market_intelligence", "liquidity", "news_compliance",
    "risk", "critic", "decision_coordinator", "explainability", "memory_write",
)


class Orchestrator:
    def __init__(self, memory, audit, llm=None, max_age_sec=900):
        self.memory = memory
        self.audit = audit
        self.llm = llm
        self.max_age_sec = max_age_sec
        # ONE shared LLM instance is injected into LLM-eligible agents; the
        # deterministic agents receive none.
        self.market = MarketIntelligenceAgent(llm=llm)
        self.liquidity = LiquidityAgent(llm=llm)
        self.news = NewsComplianceAgent()
        self.risk = RiskAgent()
        self.critic = CriticAgent(llm=llm)
        self.coordinator = DecisionCoordinator()
        self.explainer = ExplainabilityService()

    def run(self, request, bundle, strategy_candidate, now):
        ts = serialize.iso_utc(now) if now is not None else ""
        stages = []
        agent_results = {}

        # 1. data quality (fail closed)
        dq = data_quality.validate(request, bundle, now, self.max_age_sec)
        self.audit.emit(ts, "orchestrate", "DATA_QUALITY",
                        reason_code=dq.reason_codes[0], signal_id=request.get("request_id"),
                        detail={"ok": dq.ok, "missing": dq.missing_inputs})
        stages.append("data_quality")

        if dq.ok:
            base_ctx = {
                "market": bundle.get("market"), "liquidity": bundle.get("liquidity"),
                "news": bundle.get("news"), "risk": bundle.get("risk"),
                "data_quality": dq.as_dict(),
            }
            for agent in (self.market, self.liquidity, self.news, self.risk):
                res = agent.evaluate(request, base_ctx, now)
                agent_results[agent.agent_id] = res
                self._audit_agent(ts, res)
                stages.append(agent.agent_id)
            critic_ctx = dict(base_ctx)
            critic_ctx["agent_results"] = agent_results
            critic_ctx["critic_flags"] = bundle.get("critic_flags", {})
            cres = self.critic.evaluate(request, critic_ctx, now)
            agent_results["critic"] = cres
            self._audit_agent(ts, cres)
            stages.append("critic")

        # 7. deterministic coordinator (one advisory decision)
        decision = self.coordinator.decide(
            request, agent_results, strategy_candidate, data_quality_ok=dq.ok)
        self.audit.emit(ts, "orchestrate", decision["advisory_decision"],
                        reason_code=(decision["reason_codes"] or ["A_OK"])[0],
                        signal_id=request.get("request_id"))
        stages.append("decision_coordinator")

        # 8. explainability (not a decision-maker)
        explanation = self.explainer.explain(request, agent_results, decision, dq.as_dict())
        stages.append("explainability")

        # 9. memory write (advisory records only; never changes live rules)
        mem_ids = self._write_memory(request, agent_results, decision, dq, ts)
        stages.append("memory_write")

        self.audit.emit(ts, "orchestrate", "DONE",
                        signal_id=request.get("request_id"),
                        detail={"stages": stages})
        return {
            "decision": decision,
            "agent_results": agent_results,
            "explanation": explanation,
            "data_quality": dq.as_dict(),
            "stages": stages,
            "memory_ids": mem_ids,
        }

    # -- helpers ------------------------------------------------------------
    def _audit_agent(self, ts, res):
        self.audit.emit(ts, "agent", res.get("assessment", "BLOCK"),
                        reason_code=(res.get("reason_codes") or ["A_OK"])[0],
                        signal_id=res.get("request_id"),
                        detail={"agent": res.get("agent_id")})

    def _write_memory(self, request, agent_results, decision, dq, ts):
        subject = request.get("symbol")
        corr = request.get("correlation_id")
        ids = []
        for name, res in agent_results.items():
            ids.append(self.memory.write_raw(
                "agent_assessment", subject, res,
                source=f"{name}/{res.get('agent_version')}", timestamp=ts,
                correlation_id=corr))
            if res.get("model_id"):
                ids.append(self.memory.write_raw(
                    "model_prompt_version", subject,
                    {"agent": name, "model_id": res["model_id"],
                     "prompt_version": res["prompt_version"]},
                    source=f"{name}/{res.get('agent_version')}", timestamp=ts,
                    correlation_id=corr))
        ids.append(self.memory.write_raw(
            "strategy_decision", subject,
            {"advisory_decision": decision["advisory_decision"],
             "strategy_candidate": decision["strategy_candidate"],
             "reason_codes": decision["reason_codes"], "is_order": False},
            source=f"{self.coordinator.agent_id}/{self.coordinator.agent_version}",
            timestamp=ts, correlation_id=corr))
        return ids
