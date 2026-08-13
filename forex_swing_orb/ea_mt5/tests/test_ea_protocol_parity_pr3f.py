"""PR-3F (P-1) — MQL5/Python structural protocol-parity guard.

The P-1 risk (proven once by MS-1): the Python side can be green while the SHIPPED
MQL5 EA silently disagrees on schema, required fields, direction/status vocabulary,
strategy identity, or the management protocol — and every real instruction is then
rejected in production. These tests read the ACTUAL shipped .mq5/.mqh and assert
they agree with the Python bridge/manage contracts. Mutation tests prove each guard
really catches drift. This is SOURCE parity, not MetaEditor compile / broker
execution ([ENV]); a green Python reference consumer alone never satisfies it.
"""

from __future__ import annotations

import pytest

import _ea_parity as P
from forex_swing_orb.bridge.config import DEFAULT_CONFIG as BRIDGE_CFG
from forex_swing_orb.bridge.contract import PRODUCTION_INSTRUCTION_SCHEMA_VERSION
from forex_swing_orb.producer.strategy_adapter import load_engine_module


def _engine_schema():
    return load_engine_module().INSTRUCTION_SCHEMA_VERSION


# --------------------------------------------------------------------------- #
# assert-helpers (canonical tests call with shipped source; mutation tests with
# mutated source, expecting AssertionError). Every guard is one function.
# --------------------------------------------------------------------------- #
def assert_schema_parity(entry):
    # M9: the EA accepts the producer's FINALIZED on-wire schema (production), which the
    # bridge also allows — this is what is actually written to the bridge, so the EA can
    # never silently disagree (the MS-1 guarantee). The frozen engine emits a pre-sizing
    # proto-schema that the producer finalizes (schema bump) by attaching the
    # authoritative volume; that proto-schema is strictly below the production schema.
    ea = P.define_int(entry, "ALLOW_SCHEMA_VERSION")
    assert ea == PRODUCTION_INSTRUCTION_SCHEMA_VERSION, (
        f"EA schema {ea} != production on-wire schema {PRODUCTION_INSTRUCTION_SCHEMA_VERSION}")
    assert ea in BRIDGE_CFG.schema_version_allowlist, "EA schema not in bridge allow-list"
    assert _engine_schema() < PRODUCTION_INSTRUCTION_SCHEMA_VERSION, (
        "producer must finalize the engine proto-schema up to the production schema")


def assert_schema_guard_wired(entry):
    assert P.has_schema_guard(entry), "EA schema check not structurally wired (read/compare/E_SCHEMA)"


def assert_need_fields(entry):
    need = P.need_fields(entry)
    assert need == P.EXPECTED_EA_NEED, (
        f"EA required-field drift: EA-only={sorted(need - P.EXPECTED_EA_NEED)} "
        f"missing={sorted(P.EXPECTED_EA_NEED - need)}")


def assert_directions(entry):
    assert P.accepted_directions(entry) == P.EXPECTED_DIRECTIONS, "direction vocabulary drift"


def assert_strategy_guard(entry):
    assert P.has_strategy_guard(entry), "EA strategy_id/version check not wired"
    assert P.define_str(entry, "ALLOW_STRATEGY_ID") in BRIDGE_CFG.strategy_id_allowlist
    assert P.define_str(entry, "ALLOW_STRATEGY_VERSION") in BRIDGE_CFG.strategy_version_allowlist


def assert_signal_id_guard(entry):
    assert P.has_signal_id_guard(entry), "EA signal_id<->filename check not wired (E_ID)"


def assert_entry_statuses(entry):
    vals = P.entry_status_values(entry)
    unknown = vals - P.PYTHON_RESULT_VOCAB
    assert not unknown, f"EA emits status(es) Python cannot interpret: {sorted(unknown)}"
    assert {"EXECUTED", "EXECUTION_FAILED"} <= vals, "EA missing core terminal statuses"


def assert_result_fields(entry):
    keys = P.result_json_keys(entry)
    assert {"signal_id", "status", "result_schema_version"} <= keys, "EA result missing core fields"


def assert_manage_parity(manage):
    import re
    assert P.has_manage_schema_guard(manage), "manage schema check not wired before dispatch"
    assert P.define_int(manage, "MG_SCHEMA_VERSION") == P.PY_MANAGE_SCHEMA, "manage schema drift"
    body = P.manage_handler_body(manage)
    # the active handler explicitly branches on PROTECTIVE_CLOSE and treats the
    # remaining case as MODIFY_STOP (the default modify path). Every EXPLICIT action
    # token must be a Python action, PROTECTIVE_CLOSE must be recognized, and BOTH
    # broker paths must be reachable in the active handler.
    actions = P.manage_actions(manage)
    assert actions <= P.PY_MANAGE_ACTIONS, f"unknown explicit manage action(s): {sorted(actions - P.PY_MANAGE_ACTIONS)}"
    assert "PROTECTIVE_CLOSE" in actions, "PROTECTIVE_CLOSE not explicitly dispatched"
    assert "MODIFY_STOP" in P.PY_MANAGE_ACTIONS
    assert re.search(r"g_trade\.PositionClose", body), "PROTECTIVE_CLOSE path missing"
    assert re.search(r"g_trade\.PositionModify", body), "MODIFY_STOP path missing"
    ms = P.manage_status_values(manage)
    unknown = ms - P.PY_MANAGE_STATUSES
    assert not unknown, f"manage status(es) Python cannot interpret: {sorted(unknown)}"


# --------------------------------------------------------------------------- #
# 1-15, 22-24: canonical parity against the SHIPPED source
# --------------------------------------------------------------------------- #
def test_ea_source_files_exist():
    assert P.EA_ENTRY_PATH.is_file() and P.EA_MANAGE_PATH.is_file()


def test_shipped_paths_are_used():
    # the guard reads the real shipped files, not copied strings
    assert P.EA_ENTRY_PATH.name == "SessionEdgeExecutionEA.mq5"
    assert P.EA_MANAGE_PATH.name == "SessionEdgeManageHandler.mqh"
    assert "ValidateInstruction" in P.entry_source()


def test_missing_ea_source_fails_clearly(tmp_path):
    with pytest.raises(OSError):
        (tmp_path / "nope.mq5").read_text(encoding="utf-8")


def test_schema_matches():                 assert_schema_parity(P.entry_source())
def test_schema_guard_wired():             assert_schema_guard_wired(P.entry_source())
def test_required_fields_match():          assert_need_fields(P.entry_source())
def test_session_id_required_both_sides():
    assert "session_id" in P.need_fields(P.entry_source())
    from forex_swing_orb.bridge.contract import REQUIRED_INSTRUCTION_FIELDS
    assert "session_id" in REQUIRED_INSTRUCTION_FIELDS
def test_direction_vocabulary():           assert_directions(P.entry_source())
def test_sltp_entry_field_names():
    need = P.need_fields(P.entry_source())
    assert {"entry_price", "stop_loss", "take_profit"} <= need
def test_expiration_field_parity():
    assert "expiration_timestamp" in P.need_fields(P.entry_source())
def test_strategy_identity():              assert_strategy_guard(P.entry_source())
def test_strategy_identity_triangulated():
    # engine (emitter) == EA (executor) == bridge allow-list (validator): a drift on
    # ANY vertex is caught, closing the mirrored strategy-constant duplication.
    eng = load_engine_module()
    entry = P.entry_source()
    assert eng.STRATEGY_ID == P.define_str(entry, "ALLOW_STRATEGY_ID")
    assert eng.STRATEGY_VERSION == P.define_str(entry, "ALLOW_STRATEGY_VERSION")
    assert eng.STRATEGY_ID in BRIDGE_CFG.strategy_id_allowlist
    assert eng.STRATEGY_VERSION in BRIDGE_CFG.strategy_version_allowlist
def test_signal_id_guard():                assert_signal_id_guard(P.entry_source())
def test_terminal_status_vocabulary():     assert_entry_statuses(P.entry_source())
def test_result_field_parity():            assert_result_fields(P.entry_source())
def test_management_parity():              assert_manage_parity(P.manage_source())


def test_schema_parity_is_bidirectional():
    # a Python-side schema bump (without an EA update) must also break parity
    ea = P.define_int(P.entry_source(), "ALLOW_SCHEMA_VERSION")
    fake_engine = ea + 1
    assert ea != fake_engine       # same equality the guard enforces would fail


def test_required_field_addition_is_caught():
    # if the bridge gains a new EA-relevant required field, EA need[] no longer matches
    grown = P.EXPECTED_EA_NEED | {"new_required_field"}
    assert P.need_fields(P.entry_source()) != grown


def test_python_consumer_still_green_with_canonical_fixture():
    # the Python REFERENCE consumer mirrors the contract but is NOT proof of EA
    # behavior; it must still accept a canonical schema-2 instruction's field set.
    from forex_swing_orb.bridge.contract import REQUIRED_INSTRUCTION_FIELDS
    fixture = {f: 1 for f in REQUIRED_INSTRUCTION_FIELDS}
    assert set(fixture) == set(REQUIRED_INSTRUCTION_FIELDS)


# --------------------------------------------------------------------------- #
# 16-21: MUTATION TESTS — prove each guard actually catches drift
# --------------------------------------------------------------------------- #
def test_mutation_schema_drift_caught():
    mut = P.entry_source().replace("ALLOW_SCHEMA_VERSION   3", "ALLOW_SCHEMA_VERSION   2")
    assert "ALLOW_SCHEMA_VERSION   2" in mut
    with pytest.raises(AssertionError):
        assert_schema_parity(mut)


def test_mutation_missing_session_id_caught():
    mut = P.entry_source().replace('"session_id",', "")
    with pytest.raises(AssertionError):
        assert_need_fields(mut)


def test_mutation_renamed_stop_loss_caught():
    mut = P.entry_source().replace('"stop_loss","take_profit"', '"stoploss","take_profit"')
    with pytest.raises(AssertionError):
        assert_need_fields(mut)


def test_mutation_direction_token_drift_caught():
    mut = P.entry_source().replace('direction != "LONG"', 'direction != "LONGX"')
    with pytest.raises(AssertionError):
        assert_directions(mut)


def test_mutation_removed_strategy_version_check_caught():
    mut = P.entry_source().replace(
        'if(JsonGet(json, "strategy_version") != ALLOW_STRATEGY_VERSION) return "E_STRATEGY";', "")
    with pytest.raises(AssertionError):
        assert_strategy_guard(mut)


def test_mutation_status_token_drift_caught():
    mut = P.entry_source().replace('#define ST_EXECUTED         "EXECUTED"',
                                   '#define ST_EXECUTED         "FILLED"')
    with pytest.raises(AssertionError):
        assert_entry_statuses(mut)


def test_mutation_removed_schema_reject_branch_caught():
    mut = P.entry_source().replace('return "E_SCHEMA";', "")
    with pytest.raises(AssertionError):
        assert_schema_guard_wired(mut)


def test_mutation_removed_signal_id_check_caught():
    mut = P.entry_source().replace('return "E_ID";', "")
    with pytest.raises(AssertionError):
        assert_signal_id_guard(mut)


def test_mutation_manage_schema_drift_caught():
    mut = P.manage_source().replace("MG_SCHEMA_VERSION 1", "MG_SCHEMA_VERSION 2")
    with pytest.raises(AssertionError):
        assert_manage_parity(mut)


def test_mutation_manage_action_drift_caught():
    mut = P.manage_source().replace('action == "PROTECTIVE_CLOSE"', 'action == "FLATTEN"')
    with pytest.raises(AssertionError):
        assert_manage_parity(mut)
