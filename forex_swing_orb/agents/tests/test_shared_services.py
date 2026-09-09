"""Shared-service tests: one memory, one LLM abstraction, one explainability,
complete audit trace, model/prompt capture. (Test reqs 15,16,17,19,22.)"""

from __future__ import annotations

from forex_swing_orb.agents import (Orchestrator, MockLLMProvider, MemoryStore,
                                    ExplainabilityService, StrategyCandidate)
from forex_swing_orb.agents.llm import LLMProvider
from conftest import make_request, good_bundle, NOW


def test_one_shared_llm_instance_across_agents(orchestrator):
    llm = orchestrator.llm
    # every LLM-eligible agent holds the SAME injected instance
    assert orchestrator.market.llm is llm
    assert orchestrator.liquidity.llm is llm
    assert orchestrator.critic.llm is llm
    # deterministic agents hold none
    assert orchestrator.news.llm is None
    assert orchestrator.risk.llm is None


def test_llm_is_single_abstraction():
    assert issubclass(MockLLMProvider, LLMProvider)


def test_one_shared_memory_store(orchestrator, memory):
    assert orchestrator.memory is memory


def test_one_explainability_service(orchestrator):
    assert isinstance(orchestrator.explainer, ExplainabilityService)


def test_model_and_prompt_version_captured(orchestrator):
    out = orchestrator.run(make_request(), good_bundle(),
                           StrategyCandidate.QUALIFIED, NOW)
    mi = out["agent_results"]["market_intelligence"]
    assert mi["model_id"] is not None and mi["prompt_version"] == "market_intelligence.v2"
    # deterministic agents never carry model provenance
    assert out["agent_results"]["risk"]["model_id"] is None
    assert out["agent_results"]["news_compliance"]["model_id"] is None


def test_complete_audit_trace(orchestrator, audit):
    orchestrator.run(make_request(), good_bundle(), StrategyCandidate.QUALIFIED, NOW)
    actions = [(a["action"], a["outcome"]) for a in audit.read_all()]
    assert ("orchestrate", "DATA_QUALITY") in actions
    assert ("orchestrate", "DONE") in actions
    agent_events = [a for a in audit.read_all() if a["action"] == "agent"]
    assert len(agent_events) == 5                # one per live agent


def test_llm_completion_is_deterministic():
    a, b = MockLLMProvider(), MockLLMProvider()
    ra = a.complete({"x": 1}, prompt_version="v1")
    rb = b.complete({"x": 1}, prompt_version="v1")
    assert ra.text == rb.text
    assert ra.model_id == rb.model_id == "mock-llm.v1"
