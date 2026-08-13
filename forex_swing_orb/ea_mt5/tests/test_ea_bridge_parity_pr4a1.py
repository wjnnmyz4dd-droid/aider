"""PR-4A.1 MS-1 — EA <-> bridge schema parity guard.

The previous CI blind spot: the Python consumer accepted schema 2 while the shipped
MQL5 EA still hard-accepted schema 1, so every real instruction would be rejected
E_SCHEMA and NO test caught it. This static source-parity check reads the constants
straight out of SessionEdgeExecutionEA.mq5 and asserts they agree with the Python
bridge — so any future schema bump breaks CI unless BOTH sides are updated.

This is a SOURCE parity guard, not Windows/MT5 execution validation ([ENV]).
"""

from __future__ import annotations

import re
from pathlib import Path

from forex_swing_orb.bridge.config import DEFAULT_CONFIG as BRIDGE_CFG
from forex_swing_orb.bridge.contract import REQUIRED_INSTRUCTION_FIELDS

EA = (Path(__file__).resolve().parents[1] / "SessionEdgeExecutionEA.mq5").read_text()


def _define_int(name):
    m = re.search(r"#define\s+" + re.escape(name) + r"\s+(\d+)", EA)
    assert m, f"{name} not found in EA source"
    return int(m.group(1))


def _define_str(name):
    m = re.search(r'#define\s+' + re.escape(name) + r'\s+"([^"]*)"', EA)
    assert m, f"{name} not found in EA source"
    return m.group(1)


def _ea_need_fields():
    # the required-field array inside ValidateInstruction (a MQL5 string[] literal)
    m = re.search(r"string\s+need\[\]\s*=\s*\{(.*?)\}", EA, re.S)
    assert m, "need[] array not found in EA source"
    return set(re.findall(r'"([^"]+)"', m.group(1)))


# --------------------------------------------------------------------------- #
# schema parity (the exact defect MS-1)
# --------------------------------------------------------------------------- #
def test_ea_schema_equals_bridge_production_schema():
    ea_schema = _define_int("ALLOW_SCHEMA_VERSION")
    # the EA must accept exactly the bridge's current production schema
    assert ea_schema in BRIDGE_CFG.schema_version_allowlist, (
        f"EA ALLOW_SCHEMA_VERSION={ea_schema} not in bridge allow-list "
        f"{sorted(BRIDGE_CFG.schema_version_allowlist)} — EA would reject production "
        "instructions (MS-1).")


def test_ea_and_bridge_agree_on_current_instruction_schema():
    # M9: the EA accepts the producer's FINALIZED on-wire schema (what is actually
    # written to the bridge), not the frozen engine's pre-sizing proto-schema. The
    # producer finalizes the engine proto-instruction by attaching the authoritative
    # volume and bumping the schema; the EA must accept exactly that production schema.
    from forex_swing_orb.producer.strategy_adapter import load_engine_module
    from forex_swing_orb.bridge.contract import PRODUCTION_INSTRUCTION_SCHEMA_VERSION
    engine_schema = load_engine_module().INSTRUCTION_SCHEMA_VERSION
    ea_schema = _define_int("ALLOW_SCHEMA_VERSION")
    assert ea_schema == PRODUCTION_INSTRUCTION_SCHEMA_VERSION, (
        f"EA schema {ea_schema} != production schema {PRODUCTION_INSTRUCTION_SCHEMA_VERSION}")
    assert PRODUCTION_INSTRUCTION_SCHEMA_VERSION in BRIDGE_CFG.schema_version_allowlist
    assert engine_schema < PRODUCTION_INSTRUCTION_SCHEMA_VERSION, (
        "producer finalizes the engine proto-schema up to the production schema")


def test_schema_one_is_retired_everywhere():
    # legacy London-only schema 1 must not be silently re-accepted on any side
    assert 1 not in BRIDGE_CFG.schema_version_allowlist
    assert _define_int("ALLOW_SCHEMA_VERSION") != 1


# --------------------------------------------------------------------------- #
# session_id + strategy parity
# --------------------------------------------------------------------------- #
def test_ea_requires_session_id_like_the_bridge():
    assert "session_id" in _ea_need_fields()            # schema-2 integrity in the EA
    assert "session_id" in REQUIRED_INSTRUCTION_FIELDS   # and in the bridge


def test_ea_strategy_allowlists_match_bridge():
    assert _define_str("ALLOW_STRATEGY_ID") in BRIDGE_CFG.strategy_id_allowlist
    assert _define_str("ALLOW_STRATEGY_VERSION") in BRIDGE_CFG.strategy_version_allowlist


def test_ea_remains_session_neutral():
    # the EA must NOT gain session-eligibility authority: no session-time evaluation
    for banned in ("TimeGMT() >", "session_active", "SessionActive", "or_start_local",
                   "strategy_entry_end", "IsSessionOpen", "active_sessions"):
        assert banned not in EA, f"EA appears to evaluate session logic: {banned!r}"
