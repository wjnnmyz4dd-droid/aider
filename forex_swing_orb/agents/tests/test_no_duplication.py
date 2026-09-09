"""No-duplication / single-source-of-truth + offline-authority tests.
(Test reqs 16,17,18; offline components carry no live authority.)"""

from __future__ import annotations

import re
from pathlib import Path

from forex_swing_orb.agents.offline.research import ResearchAgent, LIVE_AUTHORITY as R_AUTH
from forex_swing_orb.agents.offline.performance_analytics import (
    PerformanceAnalyticsAgent, LIVE_AUTHORITY as P_AUTH)

AGENTS_DIR = Path(__file__).resolve().parents[1]
PKG = AGENTS_DIR.parent


def _py(root):
    return [p for p in root.rglob("*.py") if "tests" not in p.parts]


def _count(pattern, root):
    rx = re.compile(pattern, re.MULTILINE)
    return sum(len(rx.findall(p.read_text())) for p in _py(root))


def test_unique_agent_ids():
    ids = []
    rx = re.compile(r'^\s+agent_id = "([^"]+)"', re.MULTILINE)
    for p in _py(AGENTS_DIR):
        ids += rx.findall(p.read_text())
    assert len(ids) == len(set(ids)), f"duplicate agent_id: {ids}"


def test_single_decision_coordinator():
    assert _count(r"^class DecisionCoordinator\b", AGENTS_DIR) == 1


def test_single_explainability_service():
    assert _count(r"^class ExplainabilityService\b", AGENTS_DIR) == 1


def test_single_memory_store():
    assert _count(r"^class MemoryStore\b", AGENTS_DIR) == 1


def test_single_llm_provider_abstraction():
    # exactly one abstract provider; the mock subclasses it (not a parallel one)
    assert _count(r"^class LLMProvider\b", AGENTS_DIR) == 1


def test_no_duplicate_serializer_or_validator_in_agent_layer():
    # the agent layer reuses the bridge's single serializer; it defines none
    assert _count(r"^def canonical_json\b", AGENTS_DIR) == 0
    assert _count(r"^def compute_integrity_digest\b", AGENTS_DIR) == 0


def test_agents_do_not_each_define_a_memory_store():
    # only memory.py mentions the MemoryStore class definition; agents receive it
    for p in _py(AGENTS_DIR / "agents"):
        assert "class MemoryStore" not in p.read_text()


def test_offline_components_have_no_live_authority():
    assert R_AUTH is False and P_AUTH is False
    proposal = ResearchAgent().propose("try wider stop")
    assert proposal["applies_automatically"] is False
    assert proposal["requires_governed_approval"] is True


def test_offline_components_not_in_live_orchestrator():
    text = (AGENTS_DIR / "orchestrator.py").read_text()
    assert "research" not in text.lower()
    assert "performance_analytics" not in text.lower()
