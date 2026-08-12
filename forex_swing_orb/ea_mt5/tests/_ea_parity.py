"""PR-3F / PR-3F.1 — MQL5/Python structural protocol-parity support (TEST-ONLY).

Verifies the SHIPPED MQL5 entry/manage protocol agrees with the Python bridge/manage
contracts and — since PR-3F.1 — proves the enforcement lives in the ACTIVE execution
path, not merely as tokens somewhere in the file. Guarantees:

  * comments (// and /* */) are stripped before any assertion, with string literals
    preserved, so tokens surviving only inside comments never satisfy a guard;
  * execution-critical checks are scoped to the ACTIVE function body responsible for
    them (ValidateInstruction / Execute / MgProcessClaimed), so a dead helper cannot
    satisfy the guard;
  * ordering is established for critical checks (validation BEFORE broker dispatch).

NOT runtime code — never imported by any production module (the live pipeline never
parses MQL5 source). NOT a general MQL5 parser: it targets specific declarations and
active bodies and fails closed (raises AssertionError) when they cannot be extracted.
"""

from __future__ import annotations

import re
from pathlib import Path

from forex_swing_orb.bridge.config import DEFAULT_CONFIG as BRIDGE_CFG
from forex_swing_orb.bridge.contract import (REQUIRED_INSTRUCTION_FIELDS, DIRECTIONS,
                                             ResultState)
from forex_swing_orb.manage import contract as MC

_EA_DIR = Path(__file__).resolve().parents[1]
EA_ENTRY_PATH = _EA_DIR / "SessionEdgeExecutionEA.mq5"
EA_MANAGE_PATH = _EA_DIR / "SessionEdgeManageHandler.mqh"

# active function names (from source) and the broker-dispatch call markers.
ENTRY_VALIDATOR = "ValidateInstruction"
ENTRY_DISPATCH = "Execute"
MANAGE_HANDLER = "MgProcessClaimed"
_ORDER_CALLS = (r"g_trade\.Buy\b", r"g_trade\.Sell\b")
_MANAGE_ORDER_CALLS = (r"g_trade\.PositionModify\b", r"g_trade\.PositionClose\b")


# --------------------------------------------------------------------------- #
# source access
# --------------------------------------------------------------------------- #
def entry_source():
    return EA_ENTRY_PATH.read_text(encoding="utf-8")


def manage_source():
    return EA_MANAGE_PATH.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# comment-aware analysis primitives (PR-3F.1)
# --------------------------------------------------------------------------- #
def strip_comments(src):
    """Return ``src`` with // line and /* */ block comments removed, PRESERVING
    string and char literals (so `"a//b"` and `"/*x*/"` survive intact). A tiny
    char-scanner — robust where a regex would confuse strings and comments."""
    out = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c == '"' or c == "'":                     # string / char literal
            q = c
            out.append(c); i += 1
            while i < n:
                if src[i] == "\\" and i + 1 < n:     # escape: keep both chars
                    out.append(src[i]); out.append(src[i + 1]); i += 2; continue
                out.append(src[i])
                if src[i] == q:
                    i += 1; break
                i += 1
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "/":     # line comment
            while i < n and src[i] != "\n":
                i += 1
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "*":     # block comment
            i += 2
            while i + 1 < n and not (src[i] == "*" and src[i + 1] == "/"):
                i += 1
            i += 2
            out.append(" ")                          # keep token separation
            continue
        out.append(c); i += 1
    return "".join(out)


def function_body(src, name):
    """Return the brace-balanced body (including braces) of function ``name`` in
    ``src``. ``src`` should already be comment-stripped. Fails closed."""
    m = re.search(r"\b" + re.escape(name) + r"\s*\([^;{]*\)\s*\{", src, re.S)
    if not m:
        raise AssertionError("active function {} not found in EA source".format(name))
    start = m.end() - 1
    depth = 0
    for j in range(start, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[start:j + 1]
    raise AssertionError("unterminated body for {}".format(name))


def _stripped_entry(src=None):
    return strip_comments(src if src is not None else entry_source())


def _stripped_manage(src=None):
    return strip_comments(src if src is not None else manage_source())


def entry_validator_body(src=None):
    return function_body(_stripped_entry(src), ENTRY_VALIDATOR)


def entry_dispatch_body(src=None):
    return function_body(_stripped_entry(src), ENTRY_DISPATCH)


def manage_handler_body(src=None):
    return function_body(_stripped_manage(src), MANAGE_HANDLER)


def _first(pattern, body):
    m = re.search(pattern, body)
    return m.start() if m else None


def occurs_before(body, before_pat, after_pats):
    """True iff ``before_pat`` occurs and every pattern in ``after_pats`` that occurs
    does so AFTER it (or is absent). Used to prove validation precedes dispatch."""
    b = _first(before_pat, body)
    if b is None:
        return False
    for ap in after_pats:
        a = _first(ap, body)
        if a is not None and a < b:
            return False
    return True


# --------------------------------------------------------------------------- #
# value/vocabulary extractors (comment-stripped)
# --------------------------------------------------------------------------- #
def define_int(src, name):
    m = re.search(r"#define\s+" + re.escape(name) + r"\s+(-?\d+)", strip_comments(src))
    if not m:
        raise AssertionError("EA #define int {} not found".format(name))
    return int(m.group(1))


def define_str(src, name):
    m = re.search(r'#define\s+' + re.escape(name) + r'\s+"([^"]*)"', strip_comments(src))
    if not m:
        raise AssertionError("EA #define str {} not found".format(name))
    return m.group(1)


def need_fields(src):
    """Required-field string[] literal INSIDE the active ValidateInstruction body."""
    body = entry_validator_body(src)
    m = re.search(r"string\s+need\[\]\s*=\s*\{(.*?)\}", body, re.S)
    if not m:
        raise AssertionError("need[] required-field array not found in active validator")
    return set(re.findall(r'"([^"]+)"', m.group(1)))


def status_defines(src):
    out = {}
    for name, val in re.findall(r'#define\s+(ST_[A-Z_]+)\s+"([^"]*)"', strip_comments(src)):
        out[name] = val
    return out


def entry_status_values(src):
    return set(status_defines(src).values())


def accepted_directions(src):
    """Direction tokens in the ACTIVE validator's direction guard."""
    body = entry_validator_body(src)
    m = re.search(r'direction\s*!=\s*"([A-Z]+)"\s*&&\s*direction\s*!=\s*"([A-Z]+)"', body)
    if not m:
        raise AssertionError("active direction validity guard not found in validator")
    return {m.group(1), m.group(2)}


def order_side_direction_token(src):
    """The direction token that selects the BUY side in the ACTIVE order dispatch
    (proves order side is keyed on the validated vocabulary, not BUY/SELL literals)."""
    body = entry_dispatch_body(src)
    m = re.search(r'\(\s*direction\s*==\s*"([A-Z]+)"\s*\)\s*\?\s*g_trade\.Buy', body, re.S)
    if not m:
        raise AssertionError("active order-side branch not keyed on direction==\"...\"")
    return m.group(1)


def active_result_status_tokens(src):
    """Terminal-status arguments actually passed to WriteResult(...) in the ACTIVE
    Execute body, resolved through the ST_* vocabulary. A raw literal (e.g. "FILLED")
    that is not an ST_* symbol is returned verbatim so parity can reject it."""
    body = entry_dispatch_body(src)
    defines = status_defines(src)                     # ST_* -> value
    tokens = set()
    for args in re.findall(r'WriteResult\(\s*[^,]+,\s*([^,]+),', body):
        a = args.strip()
        if a in defines:
            tokens.add(defines[a])                    # ST_* symbol -> its defined value
            continue
        m = re.match(r'"([^"]*)"', a)
        if m:
            tokens.add(m.group(1))                    # raw quoted literal (e.g. "FILLED")
            continue
        # an identifier (e.g. a ternary-assigned `st`): resolve the status OPERANDS
        # assigned to it within the active body. For `x = cond ? A : B` only A and B
        # are statuses (never the condition), so a drifted literal branch is caught
        # while a reason-code compared in the condition is ignored.
        resolved = False
        for assign in re.findall(re.escape(a) + r'\s*=\s*([^;]+);', body):
            operands = re.findall(r'\?\s*("[^"]*"|ST_[A-Z_]+)\s*:\s*("[^"]*"|ST_[A-Z_]+)', assign)
            flat = [o for pair in operands for o in pair]
            if not flat:                              # non-ternary: take ST_* / literals
                flat = re.findall(r'"[A-Z_]+"|ST_[A-Z_]+', assign)
            for op in flat:
                if op in defines:
                    tokens.add(defines[op]); resolved = True
                elif op.startswith('"'):
                    tokens.add(op.strip('"')); resolved = True
        if not resolved:
            tokens.add(a)                             # unresolved expression -> fail-closed
    return tokens


def result_json_keys(src):
    """Field names in the entry-result JSON template (the one with
    result_schema_version/signal_id/status) written in the active dispatch."""
    src = strip_comments(src)
    literal = r'"(?:[^"\\]|\\.)*"'
    for m in re.finditer(r'StringFormat\(\s*((?:' + literal + r'\s*)+)', src):
        keys = set(re.findall(r'\\"([a-z_]+)\\":', m.group(1)))
        if {"result_schema_version", "signal_id", "status"} <= keys:
            return keys
    raise AssertionError("EA WriteResult JSON template not found")


def manage_actions(src):
    """Action tokens the ACTIVE manage handler dispatches on."""
    body = manage_handler_body(src)
    return set(re.findall(r'action\s*==\s*"([A-Z_]+)"', body)) | \
        set(re.findall(r'"action"\)\s*==\s*"([A-Z_]+)"', body))


def manage_status_values(src):
    """Status literals emitted by the ACTIVE manage handler (MgWriteResult args +
    ternary status assignments)."""
    body = manage_handler_body(src)
    vals = set()
    for c in re.findall(r'MgWriteResult\((.*?)\)', body, re.S):
        vals |= set(re.findall(r'"([A-Z_]+)"', c))
    for c in re.findall(r'\bst\s*=\s*\([^;]*?;', body, re.S):
        vals |= set(re.findall(r'"([A-Z_]+)"', c))
    return {v for v in vals if v not in set(MC.ManageAction.ALL)}


# --------------------------------------------------------------------------- #
# ACTIVE-PATH structural guards (PR-3F.1) — scoped + comment-aware + ordered
# --------------------------------------------------------------------------- #
def has_schema_guard(src):
    """schema_version read, compared to ALLOW_SCHEMA_VERSION, and E_SCHEMA returned,
    all INSIDE the active validator; and the validator runs BEFORE broker dispatch."""
    v = entry_validator_body(src)
    wired = (re.search(r'JsonGetLong\(\s*json\s*,\s*"schema_version"', v) is not None
             and re.search(r'schema\s*!=\s*ALLOW_SCHEMA_VERSION', v) is not None
             and re.search(r'return\s+"E_SCHEMA"', v) is not None)
    return wired and _validation_precedes_dispatch(src)


def _validation_precedes_dispatch(src):
    """The ValidateInstruction CALL precedes any g_trade.Buy/Sell in Execute."""
    d = entry_dispatch_body(src)
    return occurs_before(d, r"\b" + re.escape(ENTRY_VALIDATOR) + r"\s*\(", _ORDER_CALLS)


def has_strategy_guard(src):
    v = entry_validator_body(src)
    return (re.search(r'strategy_id"\)\s*!=\s*ALLOW_STRATEGY_ID', v) is not None
            and re.search(r'strategy_version"\)\s*!=\s*ALLOW_STRATEGY_VERSION', v) is not None
            and re.search(r'return\s+"E_STRATEGY"', v) is not None
            and _validation_precedes_dispatch(src))


def has_signal_id_guard(src):
    v = entry_validator_body(src)
    return (re.search(r'signal_id"\)\s*!=\s*sid', v) is not None
            and re.search(r'return\s+"E_ID"', v) is not None
            and _validation_precedes_dispatch(src))


def has_direction_guard(src):
    v = entry_validator_body(src)
    return (re.search(r'direction\s*!=\s*"LONG"\s*&&\s*direction\s*!=\s*"SHORT"', v) is not None
            and re.search(r'return\s+"E_STRUCT"', v) is not None
            and _validation_precedes_dispatch(src))


def has_geometry_guard(src):
    """Directional SL/TP ordering enforced in the active validator (LONG sl<entry<tp,
    SHORT sl>entry>tp) -> E_STRUCT. Returns True iff present (K)."""
    v = entry_validator_body(src)
    long_ok = re.search(r'direction\s*==\s*"LONG"\s*&&\s*!\(\s*sl\s*<\s*entry\s*&&\s*entry\s*<\s*tp\s*\)', v)
    short_ok = re.search(r'direction\s*==\s*"SHORT"\s*&&\s*!\(\s*sl\s*>\s*entry\s*&&\s*entry\s*>\s*tp\s*\)', v)
    return long_ok is not None and short_ok is not None


def has_manage_schema_guard(src):
    """Manage schema read + compared to MG_SCHEMA_VERSION in the active handler,
    BEFORE any PositionModify/PositionClose dispatch."""
    b = manage_handler_body(src)
    wired = (re.search(r'JsonGetLong\(\s*json\s*,\s*"schema_version"', b) is not None
             and re.search(r'!=\s*MG_SCHEMA_VERSION', b) is not None)
    return wired and occurs_before(b, r'!=\s*MG_SCHEMA_VERSION', _MANAGE_ORDER_CALLS)


# --------------------------------------------------------------------------- #
# declarative manifest (derived from the Python runtime contracts)
# --------------------------------------------------------------------------- #
_EA_SEPARATE_CHECK = frozenset({"schema_version", "integrity_digest"})
_BRIDGE_ONLY = frozenset({"evidence_summary", "news_eligibility"})
EXPECTED_EA_NEED = frozenset(REQUIRED_INSTRUCTION_FIELDS) - _EA_SEPARATE_CHECK - _BRIDGE_ONLY
EXPECTED_DIRECTIONS = frozenset(DIRECTIONS)
PYTHON_RESULT_VOCAB = frozenset({
    ResultState.EXECUTED, ResultState.EXECUTION_FAILED, ResultState.REJECTED,
    ResultState.EXPIRED, ResultState.DUPLICATE, ResultState.ACCEPTED,
    ResultState.FAILED, ResultState.ERROR,
})
CORE_ACTIVE_STATUSES = frozenset({"EXECUTED", "EXECUTION_FAILED", "REJECTED", "EXPIRED"})
PY_MANAGE_ACTIONS = frozenset(MC.ManageAction.ALL)
PY_MANAGE_STATUSES = frozenset(MC.ManageStatus.ALL)
PY_MANAGE_SCHEMA = MC.SCHEMA_VERSION
