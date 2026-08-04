"""Authority & boundary tests: agents cannot execute trades or write bridge
instructions; no networking in the agent/execution path; the agent layer never
imports the execution/producer machinery. (Test reqs 13,14,23,24,25,26.)"""

from __future__ import annotations

from pathlib import Path

from forex_swing_orb.agents import Orchestrator, StrategyCandidate
from conftest import make_request, good_bundle, NOW

AGENTS_DIR = Path(__file__).resolve().parents[1]


def _sources():
    return [p for p in AGENTS_DIR.rglob("*.py") if "tests" not in p.parts]


# -- no networking anywhere in the agent/execution path ---------------------
NET_TOKENS = ("WebRequest(", "SocketCreate(", "socket.socket", "import socket",
              "import requests", "requests.get", "requests.post", "urllib",
              "http.client", "httpx", "aiohttp", "websocket", "://",
              "localhost", "127.0.0.1")


def test_no_networking_in_agent_layer():
    for src in _sources():
        text = src.read_text()
        for tok in NET_TOKENS:
            assert tok not in text, f"{src.name} contains net token '{tok}'"


# -- agents never import execution / producer machinery ---------------------
FORBIDDEN_IMPORTS = ("producer", "ea_mt5", "execution_consumer", "mock_mt5",
                     "atomic_claim", "write_instruction", "order_send", "OrderSend")


def _import_lines(text):
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("import ") or s.startswith("from "):
            yield s


def test_agent_layer_does_not_import_execution_or_producer():
    for src in _sources():
        for line in _import_lines(src.read_text()):
            for tok in FORBIDDEN_IMPORTS:
                assert tok not in line, f"{src.name} imports execution/producer '{tok}'"


# -- agents expose no trade-executing surface -------------------------------
def test_agents_expose_no_execution_methods(orchestrator):
    banned = {"place_order", "execute", "submit", "write_instruction",
              "order_send", "claim", "process"}
    for name in ("market", "liquidity", "news", "risk", "critic", "coordinator"):
        agent = getattr(orchestrator, name)
        for m in banned:
            assert not hasattr(agent, m), f"{name} exposes '{m}'"


def test_orchestrator_holds_no_bridge_or_broker(orchestrator):
    # the orchestrator wires only memory, audit, llm and the agents
    for attr in ("producer", "consumer", "bridge", "mt5", "broker", "paths"):
        assert not hasattr(orchestrator, attr), f"orchestrator holds '{attr}'"


# -- the coordinator decision is never a trade instruction ------------------
def test_decision_is_not_a_bridge_instruction(orchestrator):
    out = orchestrator.run(make_request(), good_bundle(),
                           StrategyCandidate.QUALIFIED, NOW)
    decision = out["decision"]
    assert decision["is_order"] is False
    for order_field in ("entry_price", "stop_loss", "take_profit", "volume",
                        "direction", "integrity_digest"):
        assert order_field not in decision, f"decision leaks order field '{order_field}'"


# -- the agent layer does not touch strategy / bridge / MT5 source ----------
def test_agent_layer_is_self_contained_reuses_only_serialize_audit():
    """The only bridge modules the agent layer imports are the single serializer,
    audit contract, and atomic write primitive (reuse, not modification)."""
    allowed = {"serialize", "audit", "atomic"}
    import re
    rx = re.compile(r"from \.\.bridge(?:\.(\w+))? import")
    for src in _sources():
        for m in rx.finditer(src.read_text()):
            mod = m.group(1)
            if mod is not None:
                assert mod in allowed, f"{src.name} imports bridge.{mod} (not allowed)"
