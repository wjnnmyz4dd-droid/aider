"""Phase 4B — shared services & boundary guarantees (checks 39-56)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from forex_swing_orb.agents import (Orchestrator, MemoryStore, MockLLMProvider,
                                    StrategyCandidate, Advisory)
from forex_swing_orb.agents.llm import LLMProvider, LLMResponse
from forex_swing_orb.bridge.audit import AuditLog
import phase4b_helpers as H

AGENTS_DIR = Path(__file__).resolve().parents[1]


def _orch(llm="mock", tmp=None):
    tmp = tmp or tempfile.mkdtemp()
    mem = MemoryStore(Path(tmp) / "mem")
    audit = AuditLog(Path(tmp) / "audit.jsonl")
    provider = MockLLMProvider() if llm == "mock" else llm
    return Orchestrator(mem, audit, llm=provider), mem, audit


def _run(orch, strategy=StrategyCandidate.QUALIFIED, bundle=None):
    return orch.run_advisory(H.req(), bundle or H.full_bundle(), strategy, H.NOW)


# 39-41 memory ----------------------------------------------------------------
def test_one_shared_memory_store():
    orch, mem, _ = _orch()
    assert orch.memory is mem


def test_immutable_deterministic_memory_records():
    orch, mem, _ = _orch()
    out1 = _run(orch)
    first = {i: mem.get_raw(i) for i in out1["memory_ids"]}
    out2 = _run(orch)                                  # identical inputs
    assert set(out1["memory_ids"]) == set(out2["memory_ids"])   # deterministic ids
    for i, rec in first.items():
        assert mem.get_raw(i) == rec                  # raw records never mutated


# 42-45 LLM -------------------------------------------------------------------
def test_one_shared_llm_provider_instance():
    orch, _, _ = _orch()
    assert orch.market.llm is orch.liquidity.llm is orch.llm
    assert isinstance(orch.llm, LLMProvider)


def test_no_per_agent_model_clients():
    orch, _, _ = _orch()
    assert orch.news.llm is None                       # deterministic agent
    # only ONE provider object is shared by all LLM-eligible agents
    assert {id(orch.market.llm), id(orch.liquidity.llm)} == {id(orch.llm)}


class _BadLLM(LLMProvider):
    model_id = "bad"

    def complete(self, prompt, *, prompt_version, max_tokens=512, temperature=0.0):
        return LLMResponse(text="x", model_id="", prompt_version="")  # invalid


def test_malformed_llm_result_rejected():
    orch, _, _ = _orch(llm=_BadLLM())
    out = _run(orch)
    mi = out["agent_results"]["market_intelligence"]
    assert mi["evidence"]["llm_validation"] == "REJECTED"
    assert mi["model_id"] is None                      # provenance not falsely set
    # deterministic assessment still stands
    assert mi["assessment"] in ("CLEAR", "CAUTION", "BLOCK")


def test_agents_work_without_llm():
    orch, _, _ = _orch(llm=None)
    out = _run(orch)
    assert out["advisory_summary"]["advisory_decision"] == Advisory.PROCEED
    assert out["agent_results"]["market_intelligence"]["model_id"] is None


# 46-47 explainability + audit ------------------------------------------------
def test_explainability_contains_all_agent_outputs():
    orch, _, _ = _orch()
    out = _run(orch)
    assert set(out["explanation"]["agent_outputs"]) == {
        "market_intelligence", "liquidity", "news_compliance"}
    assert out["explanation"]["is_decision_maker"] is False
    assert "strategy_candidate" in out["explanation"]


def test_audit_full_correlation_chain():
    orch, _, audit = _orch()
    _run(orch)
    rows = audit.read_all()
    corr = H.req()["request_id"]
    assert any(r["action"] == "orchestrate" and r["outcome"] == "DATA_QUALITY" for r in rows)
    assert any(r["action"] == "orchestrate" and r["outcome"] == "DONE" for r in rows)
    assert sum(1 for r in rows if r["action"] == "agent") == 3
    assert any(r["signal_id"] == corr for r in rows)


# 48-50 non-override + no order ----------------------------------------------
def test_strategy_rejection_cannot_be_overridden():
    orch, _, _ = _orch()
    out = _run(orch, strategy=StrategyCandidate.NO_TRADE)
    assert out["advisory_summary"]["advisory_decision"] == Advisory.NO_TRADE
    assert "COORD_NO_TRADE_STRATEGY" in out["advisory_summary"]["reason_codes"]


def test_news_block_cannot_be_overridden():
    orch, _, _ = _orch()
    bundle = H.full_bundle(events=[H.event(currency="EUR", impact="HIGH",
                                           minutes_from_now=10)])
    out = _run(orch, bundle=bundle)
    assert out["advisory_summary"]["advisory_decision"] == Advisory.NO_TRADE
    assert out["advisory_summary"]["any_block"] is True


def test_agent_block_cannot_create_order():
    orch, _, _ = _orch()
    out = _run(orch, strategy=StrategyCandidate.NO_TRADE)
    assert out["advisory_summary"]["is_order"] is False
    # even a clean PROCEED is never an order
    clean = _run(orch)
    assert clean["advisory_summary"]["is_order"] is False


# 51-56 boundaries (static + structural) -------------------------------------
def _sources():
    return [p for p in AGENTS_DIR.rglob("*.py") if "tests" not in p.parts] + \
           list(AGENTS_DIR.glob("*.mqh"))


def test_no_bridge_writes_in_advisory():
    orch, mem, _ = _orch()
    out = _run(orch)
    # the memory root holds only memory tiers — never bridge outbox/inbox
    root = mem.root
    assert not (root / "outbox").exists()
    assert not (root / "inbox").exists()
    assert all("integrity_digest" not in (rid or "") for rid in out["memory_ids"])
    assert out["advisory_summary"]["is_order"] is False


def test_no_mt5_imports():
    for src in _sources():
        for line in src.read_text().splitlines():
            s = line.strip()
            if s.startswith(("import ", "from ")):
                assert "ea_mt5" not in s and "mock_mt5" not in s


def test_no_networking():
    net = ("import socket", "socket.socket", "WebRequest(", "urllib", "http.client",
           "requests.get", "requests.post", "httpx", "aiohttp", "websocket", "://")
    for src in _sources():
        text = src.read_text()
        for tok in net:
            assert tok not in text, f"{src.name}:{tok}"


def test_no_forex_factory_scraping():
    banned = ("forexfactory", "scrape", "beautifulsoup", "selenium", "webdriver")
    for src in _sources():
        low = src.read_text().lower()
        for tok in banned:
            assert tok not in low, f"{src.name}:{tok}"


def test_no_strategy_modification_imports():
    for src in _sources():
        for line in src.read_text().splitlines():
            s = line.strip()
            if s.startswith(("import ", "from ")):
                assert "signal_engine" not in s and "run_dir" not in s


def test_no_duplicate_responsibilities_and_no_pivot_recompute():
    # unique agent ids
    import re
    ids = []
    for p in (AGENTS_DIR / "agents").glob("*.py"):
        ids += re.findall(r'^\s+agent_id = "([^"]+)"', p.read_text(), re.MULTILINE)
    assert len(ids) == len(set(ids))
    # liquidity consumes strategy swings; it defines no pivot/trend computation
    calc = (AGENTS_DIR / "agents" / "liquidity_calc.py").read_text()
    for fn in ("def pivot", "def fractal", "def trend", "def compute_pivots"):
        assert fn not in calc
    liq = (AGENTS_DIR / "agents" / "liquidity.py").read_text()
    assert "strategy_swings" in liq            # consumes, not recomputes
