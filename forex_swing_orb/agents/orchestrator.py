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
from .contract import (Advisory, Assessment, ReasonCode, StrategyCandidate,
                       confidence_band, validate_request, validate_result)
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

# Phase 4B live-active pipeline. Risk / Critic / Coordinator authority remain
# INACTIVE placeholders (their Phase 4A skeleton is unchanged).
ADVISORY_ORDER = (
    "data_quality", "market_intelligence", "liquidity", "news_compliance",
    "explainability", "memory_write",
)
LIVE_AGENTS_4B = ("market_intelligence", "liquidity", "news_compliance")


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

    # -- Phase 4B: three-agent live advisory pipeline -----------------------
    def run_advisory(self, request, bundle, strategy_candidate, now):
        """Run only the three implemented live agents (Market Intelligence,
        Liquidity, News & Compliance) plus data-quality, explainability and
        memory. Risk/Critic/Coordinator authority stay INACTIVE. Produces an
        advisory summary only — never an order, never a bridge instruction."""
        ts = serialize.iso_utc(now) if now is not None else ""
        stages = ["data_quality"]
        agent_results = {}
        fail = None

        rok, rreason, _ = validate_request(request)
        dq = data_quality.validate(request, bundle, now, self.max_age_sec)
        self.audit.emit(ts, "orchestrate", "DATA_QUALITY",
                        reason_code=dq.reason_codes[0],
                        signal_id=request.get("request_id"),
                        detail={"ok": dq.ok, "missing": dq.missing_inputs})
        if not rok:
            fail = ("schema", [rreason])
        elif not dq.ok:
            fail = ("data_quality", [ReasonCode.COORD_BLOCK_DATA_QUALITY])

        if fail is None:
            live = {"market_intelligence": self.market, "liquidity": self.liquidity,
                    "news_compliance": self.news}
            ctx = {"market": bundle.get("market"), "liquidity": bundle.get("liquidity"),
                   "news": bundle.get("news"),
                   "strategy_candidate_direction": bundle.get("strategy_candidate_direction"),
                   "data_quality": dq.as_dict()}
            for name in LIVE_AGENTS_4B:
                res = live[name].evaluate(request, ctx, now)
                vok, _, _ = validate_result(res)
                agent_results[name] = res
                self._audit_agent(ts, res)
                stages.append(name)
                if not vok:
                    fail = ("malformed_result", [ReasonCode.E_FIELDS])

        summary = self._advisory_summary(request, agent_results, strategy_candidate,
                                         dq.ok, fail)
        self.audit.emit(ts, "orchestrate", summary["advisory_decision"],
                        reason_code=(summary["reason_codes"] or ["A_OK"])[0],
                        signal_id=request.get("request_id"))

        explanation = self.explainer.explain(request, agent_results, summary, dq.as_dict())
        stages.append("explainability")
        mem_ids = self._write_memory_advisory(request, agent_results, summary, ts)
        stages.append("memory_write")
        self.audit.emit(ts, "orchestrate", "DONE",
                        signal_id=request.get("request_id"),
                        detail={"stages": stages, "phase": "4B",
                                "inactive": ["risk", "critic", "decision_coordinator"]})
        return {"advisory_summary": summary, "agent_results": agent_results,
                "explanation": explanation, "data_quality": dq.as_dict(),
                "stages": stages, "memory_ids": mem_ids}

    def _advisory_summary(self, request, agent_results, strategy_candidate,
                          dq_ok, fail):
        """Deterministic advisory aggregation (NOT coordinator authority). Hard,
        non-overridable stops first; then agent BLOCK/CAUTION; else CLEAR."""
        reasons = []
        if fail is not None:
            worst = Assessment.BLOCK
            reasons = fail[1]
        elif strategy_candidate != StrategyCandidate.QUALIFIED:
            worst = Assessment.BLOCK
            reasons = [ReasonCode.COORD_NO_TRADE_STRATEGY]
        else:
            missing = [a for a in LIVE_AGENTS_4B if a not in agent_results]
            if missing:
                worst = Assessment.BLOCK
                reasons = [ReasonCode.E_FIELDS]
            else:
                news = agent_results["news_compliance"].get("assessment")
                if news == Assessment.BLOCK:                 # news block, not overridable
                    worst = Assessment.BLOCK
                    reasons = agent_results["news_compliance"].get("reason_codes", [])
                else:
                    worst = Assessment.worst(
                        [r.get("assessment") for r in agent_results.values()])
                    for r in agent_results.values():
                        if r.get("assessment") == worst:
                            reasons += r.get("reason_codes", [])
        advisory = {Assessment.BLOCK: Advisory.NO_TRADE,
                    Assessment.CAUTION: Advisory.CAUTION,
                    Assessment.CLEAR: Advisory.PROCEED}[worst]
        conf = self._aggregate_conf(agent_results) if worst != Assessment.BLOCK else 0.0
        return {
            "advisory_decision": advisory,           # advisory label only
            "final_assessment_scale": worst,
            "strategy_candidate": strategy_candidate,
            "confidence": conf, "confidence_band": confidence_band(conf),
            "reason_codes": _dedup(reasons) or [ReasonCode.OK],
            "any_block": worst == Assessment.BLOCK,
            "is_order": False,                       # explicit: never an order
            "coordinator_authority_used": False,
            "inactive_stages": ["risk", "critic", "decision_coordinator"],
        }

    def _aggregate_conf(self, agent_results):
        vals = [r.get("confidence", 0.0) for r in agent_results.values()
                if isinstance(r.get("confidence"), (int, float))]
        return round(min(vals), 3) if vals else 0.0

    def _write_memory_advisory(self, request, agent_results, summary, ts):
        """One immutable record per agent + the advisory decision. A memory
        failure is audited and NEVER alters the advisory result."""
        ids = []
        subject = request.get("symbol")
        corr = request.get("correlation_id")
        refs = {k: request.get(k) for k in
                ("market_data_reference", "news_data_reference", "memory_context_reference")}
        for name, res in agent_results.items():
            content = dict(res)
            content["input_references"] = refs
            content["evaluation_timestamp"] = request.get("evaluation_timestamp")
            try:
                ids.append(self.memory.write_raw(
                    "agent_assessment", subject, content,
                    source=f"{name}/{res.get('agent_version')}", timestamp=ts,
                    correlation_id=corr))
            except Exception as exc:
                self.audit.emit(ts, "memory_write", "ERROR",
                                reason_code="MEM_WRITE_FAILED", signal_id=corr,
                                detail={"agent": name, "error": type(exc).__name__})
        try:
            ids.append(self.memory.write_raw(
                "strategy_decision", subject,
                {"advisory_decision": summary["advisory_decision"],
                 "strategy_candidate": summary["strategy_candidate"],
                 "reason_codes": summary["reason_codes"], "is_order": False},
                source="orchestrator_advisory/4B", timestamp=ts, correlation_id=corr))
        except Exception as exc:
            self.audit.emit(ts, "memory_write", "ERROR",
                            reason_code="MEM_WRITE_FAILED", signal_id=corr,
                            detail={"record": "strategy_decision", "error": type(exc).__name__})
        return ids

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


def _dedup(seq):
    seen = set()
    return [x for x in seq if not (x in seen or seen.add(x))]
