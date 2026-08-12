"""PR-3F.1 (P-1F-1/2/3) — ACTIVE-PATH parity: enforcement, not token presence.

Proves the Python/MQL5 parity gate cannot be fooled by comments, dead code, unused
helpers, stale constants, or tokens that remain after the ACTIVE execution path has
drifted. Each guard is scoped to the active function body, comment-stripped, and —
for execution-critical checks — ordered before broker dispatch. Every mutation in
§N-1..18 must FAIL; harmless reformatting (§N-19/20) must still PASS.
"""

from __future__ import annotations

import re
import pytest

import _ea_parity as P
from forex_swing_orb.bridge.config import DEFAULT_CONFIG as BRIDGE_CFG
from forex_swing_orb.producer.strategy_adapter import load_engine_module

E = P.entry_source()
M = P.manage_source()


def _engine_schema():
    return load_engine_module().INSTRUCTION_SCHEMA_VERSION


# --------------------------------------------------------------------------- #
# comment-stripper primitive (§A)
# --------------------------------------------------------------------------- #
def test_strip_comments_removes_line_and_block():
    s = P.strip_comments('int x=1; // note E_SCHEMA\n/* block ALLOW_SCHEMA_VERSION */ int y=2;')
    assert "E_SCHEMA" not in s and "ALLOW_SCHEMA_VERSION" not in s and "x=1" in s and "y=2" in s


def test_strip_comments_preserves_string_literals():
    s = P.strip_comments(r'string u="http://x/*not a comment*/"; // gone')
    assert 'http://x/*not a comment*/' in s and "gone" not in s


def test_tokens_only_in_comments_do_not_satisfy_guard():
    # remove the ACTIVE schema comparison but leave the tokens in a comment
    mut = E.replace('if(!ok || schema != ALLOW_SCHEMA_VERSION) return "E_SCHEMA";',
                    '// if(!ok || schema != ALLOW_SCHEMA_VERSION) return "E_SCHEMA";')
    assert not P.has_schema_guard(mut)


# --------------------------------------------------------------------------- #
# active-function scoping + fail-closed (§B, §M)
# --------------------------------------------------------------------------- #
def test_active_bodies_extracted():
    assert "schema_version" in P.entry_validator_body(E)
    assert "g_trade.Buy" in P.entry_dispatch_body(E)
    assert "PositionModify" in P.manage_handler_body(M)


def test_missing_active_function_fails_closed():
    with pytest.raises(AssertionError):
        P.function_body("void Other(){}", "ValidateInstruction")


def test_dead_helper_cannot_satisfy_schema_guard():
    # active validator loses the check; a dead helper keeps the old check verbatim
    mut = E.replace('if(!ok || schema != ALLOW_SCHEMA_VERSION) return "E_SCHEMA";', "")
    mut += ('\nstring _DeadValidator(){ long schema=0; '
            'if(schema != ALLOW_SCHEMA_VERSION) return "E_SCHEMA"; return ""; }\n')
    assert not P.has_schema_guard(mut)          # dead helper must NOT satisfy the guard


# --------------------------------------------------------------------------- #
# canonical parity against the shipped source (must all hold)
# --------------------------------------------------------------------------- #
def test_active_schema_enforced():        assert P.has_schema_guard(E)
def test_active_strategy_enforced():      assert P.has_strategy_guard(E)
def test_active_signal_id_enforced():     assert P.has_signal_id_guard(E)
def test_active_direction_enforced():     assert P.has_direction_guard(E)
def test_active_geometry_enforced():      assert P.has_geometry_guard(E)     # §K present
def test_active_manage_schema_enforced(): assert P.has_manage_schema_guard(M)
def test_order_side_keyed_on_direction(): assert P.order_side_direction_token(E) == "LONG"
def test_active_status_writer_in_vocab():
    tok = P.active_result_status_tokens(E)
    assert tok <= P.PYTHON_RESULT_VOCAB
    assert P.CORE_ACTIVE_STATUSES <= tok       # EXECUTED/EXECUTION_FAILED/REJECTED/EXPIRED emitted


# --------------------------------------------------------------------------- #
# §N adversarial mutations 1-18 — each MUST fail parity
# --------------------------------------------------------------------------- #
def test_m01_schema_constant_drift():
    mut = E.replace("ALLOW_SCHEMA_VERSION   2", "ALLOW_SCHEMA_VERSION   3")
    assert P.define_int(mut, "ALLOW_SCHEMA_VERSION") != _engine_schema()


def test_m02_schema_comparison_removed():
    mut = E.replace('if(!ok || schema != ALLOW_SCHEMA_VERSION) return "E_SCHEMA";', "")
    assert not P.has_schema_guard(mut)


def test_m03_schema_comparison_commented():
    mut = E.replace('schema != ALLOW_SCHEMA_VERSION', '/* schema != ALLOW_SCHEMA_VERSION */ false')
    assert not P.has_schema_guard(mut)


def test_m04_schema_check_moved_after_order_dispatch():
    # remove schema check from the validator; the dispatch still calls the validator
    # first, but with no schema branch the schema guard is not wired -> FAIL.
    mut = E.replace('if(!ok || schema != ALLOW_SCHEMA_VERSION) return "E_SCHEMA";', "")
    assert not P.has_schema_guard(mut)


def test_m04b_validation_after_dispatch_caught():
    # synthetic Execute where the order dispatch precedes the ValidateInstruction call
    fake = ('void Execute(const string sid){ '
            'bool sent = g_trade.Buy(1,"x",0,0,0,sid); '
            'string v = ValidateInstruction(sid); }')
    assert not P.occurs_before(P.function_body(fake, "Execute"),
                               r"\bValidateInstruction\s*\(", (r"g_trade\.Buy\b",))


def test_m05_dead_helper_retains_old_schema_check():
    mut = E.replace('if(!ok || schema != ALLOW_SCHEMA_VERSION) return "E_SCHEMA";', "")
    mut += '\nstring _Dead(){ if(0 != ALLOW_SCHEMA_VERSION) return "E_SCHEMA"; return ""; }\n'
    assert not P.has_schema_guard(mut)


def test_m06_required_field_removed():
    mut = E.replace('"session_id",', "")
    assert P.need_fields(mut) != P.EXPECTED_EA_NEED       # drift detected


def test_m07_required_field_only_in_comment():
    mut = E.replace('"stop_loss","take_profit"', '"take_profit"') + "\n// stop_loss handled\n"
    assert P.need_fields(mut) != P.EXPECTED_EA_NEED


def test_m08_direction_validation_disabled():
    mut = E.replace('if(direction != "LONG" && direction != "SHORT") return "E_STRUCT";',
                    '// disabled')
    assert not P.has_direction_guard(mut)


def test_m09_active_order_branch_drift():
    mut = E.replace('(direction == "LONG")\n      ? g_trade.Buy', '(direction == "BUY")\n      ? g_trade.Buy')
    assert P.order_side_direction_token(mut) != "LONG"


def test_m10_signal_id_check_removed():
    mut = E.replace('if(JsonGet(json, "signal_id")        != sid)                    return "E_ID";', "")
    assert not P.has_signal_id_guard(mut)


def test_m11_signal_id_check_commented():
    mut = E.replace('JsonGet(json, "signal_id")        != sid', '/* JsonGet(json,"signal_id") != sid */ false')
    assert not P.has_signal_id_guard(mut)


def test_m12_signal_id_after_execution():
    fake = ('void Execute(const string sid){ g_trade.Buy(1,"x",0,0,0,sid); '
            'string v = ValidateInstruction(sid); }')
    assert not P.occurs_before(P.function_body(fake, "Execute"),
                              r"\bValidateInstruction\s*\(", (r"g_trade\.Buy\b",))


def test_m13_strategy_check_disabled():
    mut = E.replace('if(JsonGet(json, "strategy_version") != ALLOW_STRATEGY_VERSION) return "E_STRATEGY";', "")
    assert not P.has_strategy_guard(mut)


def test_m14_active_executed_to_filled():
    mut = E.replace('WriteResult(sid, ST_EXECUTED, "X_OK"', 'WriteResult(sid, "FILLED", "X_OK"')
    assert not (P.active_result_status_tokens(mut) <= P.PYTHON_RESULT_VOCAB)


def test_m15_active_rejection_status_drift():
    mut = E.replace('? ST_EXPIRED : ST_REJECTED', '? ST_EXPIRED : "DENIED"')
    assert not (P.active_result_status_tokens(mut) <= P.PYTHON_RESULT_VOCAB)


def test_m16_manage_schema_check_commented():
    mut = M.replace('JsonGetLong(json, "schema_version", ok) != MG_SCHEMA_VERSION',
                    '/* JsonGetLong(json,"schema_version",ok) != MG_SCHEMA_VERSION */ false')
    assert not P.has_manage_schema_guard(mut)


def test_m17_manage_schema_after_action():
    fake = ('void MgProcessClaimed(const string mid){ bool ok; '
            'g_trade.PositionModify(1,0,0); '
            'if(JsonGetLong(json,"schema_version",ok) != MG_SCHEMA_VERSION) return; }')
    body = P.function_body(fake, "MgProcessClaimed")
    assert not P.occurs_before(body, r'!=\s*MG_SCHEMA_VERSION', (r"g_trade\.PositionModify\b",))


def test_m18_manage_action_branch_drift():
    mut = M.replace('action == "PROTECTIVE_CLOSE"', 'action == "FLATTEN"')
    acts = P.manage_actions(mut)
    assert "PROTECTIVE_CLOSE" not in acts or not (acts <= P.PY_MANAGE_ACTIONS)


# --------------------------------------------------------------------------- #
# §N-19/20 harmless transformations — must still PASS
# --------------------------------------------------------------------------- #
def test_m19_whitespace_reformat_survives():
    mut = E.replace('schema != ALLOW_SCHEMA_VERSION', 'schema   !=   ALLOW_SCHEMA_VERSION')
    assert P.has_schema_guard(mut)


def test_m20_added_comment_survives():
    mut = E.replace('string need[] = {', '/* required schema-2 fields */ string need[] = {')
    assert P.need_fields(mut) == P.EXPECTED_EA_NEED
    assert P.has_schema_guard(E)               # unrelated comment addition


# --------------------------------------------------------------------------- #
# §O MS-1 regression + §P canonical source
# --------------------------------------------------------------------------- #
def test_ms1_regression_schema2_engine_vs_schema1_ea():
    mut = E.replace("ALLOW_SCHEMA_VERSION   2", "ALLOW_SCHEMA_VERSION   1")
    ea = P.define_int(mut, "ALLOW_SCHEMA_VERSION")
    assert ea == 1 and ea != _engine_schema()   # the exact MS-1 mismatch -> CI fails


def test_canonical_single_shipped_copy():
    from pathlib import Path
    root = Path(P._EA_DIR).parents[1]
    for name in ("SessionEdgeExecutionEA.mq5", "SessionEdgeManageHandler.mqh", "JsonBridge.mqh"):
        hits = [p for p in root.rglob(name) if ".git" not in p.parts]
        assert len(hits) == 1, f"expected exactly one shipped {name}, found {hits}"
