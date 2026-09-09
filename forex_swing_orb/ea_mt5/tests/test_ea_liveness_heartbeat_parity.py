"""EA liveness-heartbeat + directory-probe parity (TRUE READINESS hardening, §D/§L).

Structural, comment-aware proofs over the SHIPPED MQL5 source that:

  * the EA writes a recurring liveness beacon health\\ea_status.json whose artifact
    name / schema / filename EXACTLY match runtime.ea_liveness (the Python owner),
    and whose payload carries every field ea_liveness validates;
  * the beacon is emitted from BOTH OnInit and OnTimer (so it recurs on the poll
    cadence);
  * the beacon carries ZERO trade authority — no order dispatch, no integrity digest
    (a heartbeat authorizes nothing);
  * the OnInit bridge-presence warning no longer uses FileIsExist() on a directory
    path (build-dependent, warned spuriously) but the robust FileFindFirst-based
    BridgeDirHasEntries probe.

These run off-terminal (no MetaEditor); final confirmation that the compiled EA emits
the beacon requires a MetaEditor recompile + on-terminal run (Windows manual matrix).
"""

from __future__ import annotations

import re

from forex_swing_orb.runtime import ea_liveness as EL
from _ea_parity import entry_source, strip_comments, function_body


def _body(name):
    return function_body(strip_comments(entry_source()), name)


def _json_keys(body):
    # keys appear escaped inside the MQL5 StringFormat literal: \"key\":
    return set(re.findall(r'\\"([a-z_]+)\\":', body))


def test_heartbeat_writes_health_ea_status_file():
    b = _body("WriteEaStatus")
    assert 'BridgeWriteTextAtomic(Path(BR_HEALTH, "ea_status.json")' in b
    assert EL.EA_STATUS_FILE == "ea_status.json"


def test_heartbeat_payload_has_every_field_ea_liveness_validates():
    keys = _json_keys(_body("WriteEaStatus"))
    required = {"artifact", "schema_version", "ea_id", "timestamp", "bridge_root",
               "use_common_folder", "poll_seconds", "data_path", "account_login",
               "polling_active"}
    assert required <= keys, f"missing heartbeat fields: {required - keys}"


def test_heartbeat_artifact_and_schema_match_python_owner():
    b = _body("WriteEaStatus")
    assert f'"artifact\\":\\"{EL.EA_STATUS_ARTIFACT}\\"' in b
    assert f'"schema_version\\":{EL.EA_STATUS_SCHEMA}' in b
    assert '"polling_active\\":true' in b


def test_heartbeat_emitted_from_oninit_and_ontimer():
    assert "WriteEaStatus()" in _body("OnInit")
    assert "WriteEaStatus()" in _body("OnTimer")


def test_heartbeat_has_no_trade_authority():
    b = _body("WriteEaStatus")
    # authorizes nothing: no order dispatch, no claim/execute, no integrity digest
    for banned in ("g_trade.", "OrderSend", "integrity_digest", "BridgeClaim(",
                   "WriteResult(", "WriteAck("):
        assert banned not in b, f"heartbeat writer must not contain {banned!r}"


def test_oninit_directory_probe_is_robust_not_fileisexist_on_dir():
    b = _body("OnInit")
    # the robust FileFindFirst-based probe is used...
    assert "BridgeDirHasEntries(" in b
    # ...and the old build-dependent FileIsExist-on-a-directory probes are gone.
    assert 'BridgeExists(Path(BR_PENDING' not in b
    assert 'BridgeExists(BridgeRoot + "\\\\outbox"' not in b


def test_dir_probe_helper_uses_filefindfirst():
    # BridgeDirHasEntries lives in JsonBridge.mqh and must enumerate, not FileIsExist.
    from _ea_parity import EA_ENTRY_PATH
    mqh = (EA_ENTRY_PATH.parent / "JsonBridge.mqh").read_text(encoding="utf-8")
    body = function_body(strip_comments(mqh), "BridgeDirHasEntries")
    assert "FileFindFirst(" in body and "FileFindClose(" in body
    assert "FileIsExist" not in body
