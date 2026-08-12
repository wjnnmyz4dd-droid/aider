"""PR-3F — MQL5/Python structural protocol-parity support (TEST/BUILD-TIME ONLY).

Narrow, robust static extractors for the SHIPPED MQL5 source plus a declarative
parity manifest derived from the Python bridge/manage contracts. Used by the
parity tests to prove the Python reference/bridge side and the shipped EA cannot
silently drift in schema, required fields, direction/status vocabulary, strategy
identity, or the management protocol.

This is NOT runtime code and MUST NOT be imported by any production module — the
live pipeline never parses MQL5 source (see PR-3F §26). It is also NOT a full MQL5
parser: it matches specific declarations/patterns and is tolerant of whitespace,
comments, and formatting (PR-3F §20).
"""

from __future__ import annotations

import re
from pathlib import Path

# Python side — the single source of truth for the contract constants.
from forex_swing_orb.bridge.config import DEFAULT_CONFIG as BRIDGE_CFG
from forex_swing_orb.bridge.contract import (REQUIRED_INSTRUCTION_FIELDS, DIRECTIONS,
                                             ResultState)
from forex_swing_orb.manage import contract as MC

_EA_DIR = Path(__file__).resolve().parents[1]
EA_ENTRY_PATH = _EA_DIR / "SessionEdgeExecutionEA.mq5"
EA_MANAGE_PATH = _EA_DIR / "SessionEdgeManageHandler.mqh"


# --------------------------------------------------------------------------- #
# source access (default = shipped file; mutation tests pass a modified string)
# --------------------------------------------------------------------------- #
def entry_source():
    return EA_ENTRY_PATH.read_text(encoding="utf-8")


def manage_source():
    return EA_MANAGE_PATH.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# narrow extractors (operate on a source STRING)
# --------------------------------------------------------------------------- #
def define_int(src, name):
    m = re.search(r"#define\s+" + re.escape(name) + r"\s+(-?\d+)", src)
    if not m:
        raise AssertionError("EA #define int {} not found".format(name))
    return int(m.group(1))


def define_str(src, name):
    m = re.search(r'#define\s+' + re.escape(name) + r'\s+"([^"]*)"', src)
    if not m:
        raise AssertionError("EA #define str {} not found".format(name))
    return m.group(1)


def need_fields(src):
    """The required-field string[] literal inside ValidateInstruction."""
    m = re.search(r"string\s+need\[\]\s*=\s*\{(.*?)\}", src, re.S)
    if not m:
        raise AssertionError("EA need[] required-field array not found")
    return set(re.findall(r'"([^"]+)"', m.group(1)))


def status_defines(src):
    """Map of ST_* status #define name -> string value (entry EA)."""
    out = {}
    for name, val in re.findall(r'#define\s+(ST_[A-Z_]+)\s+"([^"]*)"', src):
        out[name] = val
    return out


def entry_status_values(src):
    return set(status_defines(src).values())


def accepted_directions(src):
    """Direction tokens the EA compares against (the `direction != "X"` guards)."""
    # the exact guard: direction != "LONG" && direction != "SHORT"
    m = re.search(r'direction\s*!=\s*"([A-Z]+)"\s*&&\s*direction\s*!=\s*"([A-Z]+)"', src)
    if not m:
        raise AssertionError("EA direction validity guard not found")
    return {m.group(1), m.group(2)}


def result_json_keys(src):
    """Field names in the entry-result JSON template written by WriteResult (the
    template is the one carrying result_schema_version / signal_id / status)."""
    literal = r'"(?:[^"\\]|\\.)*"'                       # a C string literal w/ escapes
    for m in re.finditer(r'StringFormat\(\s*((?:' + literal + r'\s*)+)', src):
        tmpl = m.group(1)
        keys = set(re.findall(r'\\"([a-z_]+)\\":', tmpl))
        if {"result_schema_version", "signal_id", "status"} <= keys:
            return keys
    raise AssertionError("EA WriteResult JSON template not found")


def has_schema_guard(src):
    """True iff the EA reads schema_version from JSON, compares it to
    ALLOW_SCHEMA_VERSION, and returns E_SCHEMA on mismatch (structurally wired,
    not just a #define). Tolerant of spacing/formatting."""
    reads = re.search(r'JsonGetLong\(\s*json\s*,\s*"schema_version"', src) is not None
    compares = re.search(r'schema\s*!=\s*ALLOW_SCHEMA_VERSION', src) is not None
    rejects = re.search(r'return\s+"E_SCHEMA"', src) is not None
    return reads and compares and rejects


def has_strategy_guard(src):
    """True iff both strategy_id and strategy_version are compared and rejected."""
    sid = re.search(r'strategy_id"\)\s*!=\s*ALLOW_STRATEGY_ID', src) is not None
    sver = re.search(r'strategy_version"\)\s*!=\s*ALLOW_STRATEGY_VERSION', src) is not None
    rej = re.search(r'return\s+"E_STRATEGY"', src) is not None
    return sid and sver and rej


def has_signal_id_guard(src):
    """True iff the EA verifies the JSON signal_id matches the filename sid -> E_ID."""
    return (re.search(r'signal_id"\)\s*!=\s*sid', src) is not None
            and re.search(r'return\s+"E_ID"', src) is not None)


def manage_actions(src):
    """Management action tokens the EA references (code literals, not comments)."""
    return set(re.findall(r'action\s*==\s*"([A-Z_]+)"', src)) | \
        set(re.findall(r'"action"\)\s*==\s*"([A-Z_]+)"', src))


def manage_status_values(src):
    """Management status string literals the EA emits: those passed to MgWriteResult
    plus status tokens assigned via a ternary (e.g. ``st=(...)?"NO_OP_CLOSED":"NO_POSITION"``).
    Restricted to tokens in the Python management-status vocabulary shape so action
    tokens and reason strings are not misread as statuses."""
    vals = set()
    for c in re.findall(r'MgWriteResult\((.*?)\)', src, re.S):
        vals |= set(re.findall(r'"([A-Z_]+)"', c))
    for c in re.findall(r'\bst\s*=\s*\([^;]*?;', src, re.S):        # ternary status assigns
        vals |= set(re.findall(r'"([A-Z_]+)"', c))
    # drop action tokens (MODIFY_STOP / PROTECTIVE_CLOSE) which are not statuses
    return {v for v in vals if v not in {a for a in MC.ManageAction.ALL}}


def has_manage_schema_guard(src):
    reads = re.search(r'JsonGetLong\(\s*json\s*,\s*"schema_version"', src) is not None
    compares = re.search(r'!=\s*MG_SCHEMA_VERSION', src) is not None
    return reads and compares


# --------------------------------------------------------------------------- #
# declarative parity manifest (expected contract, derived from Python)
# --------------------------------------------------------------------------- #
# Bridge-transport / upstream fields that the EA legitimately does NOT re-require
# for execution (documented platform-only exclusions, PR-3F §6). schema_version and
# integrity_digest ARE enforced by the EA, just via dedicated branches rather than
# the need[] array, so they are excluded from the need[] set comparison here.
_EA_SEPARATE_CHECK = frozenset({"schema_version", "integrity_digest"})
_BRIDGE_ONLY = frozenset({"evidence_summary", "news_eligibility"})

# The execution-critical required-field set the EA's need[] array must equal.
EXPECTED_EA_NEED = frozenset(REQUIRED_INSTRUCTION_FIELDS) - _EA_SEPARATE_CHECK - _BRIDGE_ONLY

# Direction vocabulary that must match exactly at the EA boundary.
EXPECTED_DIRECTIONS = frozenset(DIRECTIONS)

# Execution-layer terminal statuses the EA emits; every one must be interpretable by
# the Python result vocabulary.
PYTHON_RESULT_VOCAB = frozenset({
    ResultState.EXECUTED, ResultState.EXECUTION_FAILED, ResultState.REJECTED,
    ResultState.EXPIRED, ResultState.DUPLICATE, ResultState.ACCEPTED,
    ResultState.FAILED, ResultState.ERROR,
})

# Management vocabulary (Python side).
PY_MANAGE_ACTIONS = frozenset(MC.ManageAction.ALL)
PY_MANAGE_STATUSES = frozenset(MC.ManageStatus.ALL)
PY_MANAGE_SCHEMA = MC.SCHEMA_VERSION
