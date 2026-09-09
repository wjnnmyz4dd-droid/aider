"""MetaEditor compatibility / compile-robustness guards for the MQL5 execution
adapter (repair of the Windows "undeclared identifier 'BridgeDirHasEntries' /
'JsonEscape'" + cascade). Static, comment-aware proofs over the SHIPPED source so
the exact regression cannot silently return. Off-terminal (no MetaEditor); a real
0-error compile still requires MetaEditor on Windows.
"""

from __future__ import annotations

import re
from pathlib import Path

from _ea_parity import entry_source, manage_source, strip_comments, function_body, EA_ENTRY_PATH

_EA_DIR = EA_ENTRY_PATH.parent
JB = (_EA_DIR / "JsonBridge.mqh")
MH = (_EA_DIR / "SessionEdgeManageHandler.mqh")


# --- pure ASCII (no codepage-dependent tokenizer surprises in MetaEditor) ----
def test_all_mql5_sources_are_pure_ascii():
    for p in (EA_ENTRY_PATH, JB, MH):
        b = p.read_bytes()
        bad = [(i, byte) for i, byte in enumerate(b) if byte > 0x7F]
        assert not bad, f"{p.name}: non-ASCII byte(s) at {bad[:5]}"


# --- include guards on both headers (double-include safety) -------------------
def test_headers_have_include_guards():
    jb = JB.read_text(encoding="utf-8")
    assert "#ifndef SESSION_EDGE_JSONBRIDGE_MQH" in jb
    assert "#define SESSION_EDGE_JSONBRIDGE_MQH" in jb
    assert "#endif" in jb
    mh = MH.read_text(encoding="utf-8")
    assert "#ifndef SESSION_EDGE_MANAGE_HANDLER_MQH" in mh
    assert "#define SESSION_EDGE_MANAGE_HANDLER_MQH" in mh
    assert "#endif" in mh


# --- the EA links its helper header, so the identifiers resolve --------------
def test_ea_includes_jsonbridge_before_use():
    src = entry_source()
    inc = src.find('#include "JsonBridge.mqh"')
    assert inc > 0, "EA must #include JsonBridge.mqh"
    # every use of the helper identifiers comes AFTER the include
    for ident in ("JsonEscape", "BridgeDirHasEntries"):
        first_use = src.find(ident, inc + 1)
        assert first_use > inc, f"{ident} used before/without the JsonBridge include"


# --- BridgeDirHasEntries: defined (enumerate, not FileIsExist) + used --------
def test_bridge_dir_has_entries_defined_and_used():
    jb = strip_comments(JB.read_text(encoding="utf-8"))
    body = function_body(jb, "BridgeDirHasEntries")
    assert "FileFindFirst(" in body and "FileFindClose(" in body
    assert "FileIsExist" not in body               # must NOT probe a dir with FileIsExist
    # observational only: it returns bool, never trades / claims / writes results
    for banned in ("g_trade", "OrderSend", "BridgeClaim(", "WriteResult"):
        assert banned not in body
    # used by the OnInit bridge presence probe
    assert "BridgeDirHasEntries(" in function_body(strip_comments(entry_source()), "OnInit")


# --- JsonEscape: defined with the full escaping contract + used in heartbeat --
def test_json_escape_defined_with_full_contract():
    jb = strip_comments(JB.read_text(encoding="utf-8"))
    body = function_body(jb, "JsonEscape")
    assert body.count("StringReplace(") == 5, "JsonEscape must escape 5 char classes"
    bs = "\\"
    # backslash-first, then quote, CR, LF, TAB (each present as an escape output)
    assert (bs + bs) in body                        # backslash -> \\
    assert (bs + '"') in body                       # quote -> \"
    for ch in ("r", "n", "t"):
        assert (bs + ch) in body, f"JsonEscape missing \\{ch} handling"
    # backslash replacement occurs before quote replacement (order matters)
    assert body.index(bs + bs) < body.index(bs + '"')


def test_heartbeat_uses_json_escape():
    b = function_body(strip_comments(entry_source()), "WriteEaStatus")
    assert "JsonEscape(" in b                        # status strings are escaped
    assert "BridgeWriteTextAtomic(" in b


# --- M-4 management parity preserved in the handler --------------------------
def test_manage_result_identity_parity_preserved():
    mh = strip_comments(manage_source())
    assert "string MgEffectiveStatus(" in mh
    assert 'Sha256Hex16(mid + "|" + MgEffectiveStatus(status))' in mh
    # APPLIED/ALREADY_APPLIED collapse + REJECTED/CLOSED effective classes
    eff = function_body(mh, "MgEffectiveStatus")
    assert '"APPLIED"' in eff and '"REJECTED"' in eff and '"CLOSED"' in eff
    assert 'status=="ALREADY_APPLIED"' in eff


def test_ea_includes_manage_handler():
    assert '#include "SessionEdgeManageHandler.mqh"' in entry_source()


# --- EA remains EXECUTION-ONLY (no strategy/sizing/session authority) --------
def test_ea_inputs_are_execution_only():
    # collect declared `input` names; none may be a lot/volume/risk/session control
    inputs = re.findall(r'^\s*input\s+\w+\s+(\w+)', entry_source(), re.M)
    banned = re.compile(r'(?i)(volume|lot|risk|session|magic_?risk|score|quality)')
    offenders = [n for n in inputs if banned.search(n) and n.lower() != "magicnumber"]
    assert not offenders, f"EA exposes non-execution input(s): {offenders}"


def test_ea_has_no_strategy_or_indicator_authority():
    # Genuine strategy/price-series/indicator COMPUTATION tokens (these never appear
    # as mere JSON field names). NB: a transported field NAME like "risk_fraction" is
    # legitimate — the EA validates the field's presence and executes the authoritative
    # volume verbatim; it never sizes from risk (proven by the volume-parity suite).
    src = strip_comments(entry_source())
    for banned in ("iCustom(", "CopyRates(", "CopyBuffer(", "iMA(", "iRSI(",
                   "iStochastic(", "iClose(", "iOpen(", "iHigh(", "iLow(",
                   "OrderCalcProfit", "OrderCalcMargin", "IndicatorCreate("):
        assert banned not in src, f"EA must not contain strategy/indicator token {banned!r}"
