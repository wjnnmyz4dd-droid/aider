"""Session Edge — Windows / MT5 DEMO execution_outcome validation harness.

VALIDATION TOOLING ONLY (Validation #15A). This is NOT production functionality
and is NOT wired into Manager / Producer / EA / compliance / strategy / PM /
bridge / runtime loops. Its sole purpose is to let a Windows DEMO operator gather
the READ-ONLY evidence that resolves the environment-dependent assumptions behind
the accepted execution_outcome edge (PR-1 f4e57e4 / PR-1A 19c98c5):

  * ticket <-> position_id / position.identifier mapping,
  * real ``MetaTrader5.history_deals_get(position=...)`` semantics + scoping,
  * actually-installed DEAL_ENTRY_* / DEAL_REASON_* enum values vs observed,
  * partial-close and net-flat deal behaviour,
  * deal-history visibility latency after close,
  * end-to-end parity between the real deal set and any stored outcome.

Hard guarantees:
  * READ-ONLY. It never places / modifies / closes a trade, writes a bridge
    instruction, mutates PM/compliance state, or writes to MemoryStore.
  * It refuses to run unless the connected account is confirmed DEMO.
  * It never prints credentials or account financials (login, password, balance,
    equity, margin, profit, commission, swap, account number).
  * It never creates a validation trade — the operator opens/closes positions
    separately through the existing Session Edge system or manually.

The MT5-touching entrypoint (:func:`main`) runs only on a Windows host with the
``MetaTrader5`` package and a running terminal. All analysis logic is pure and
unit-tested off-Windows via injected data. Read-only production helpers are
reused verbatim (``spec.initial_risk``, the OutcomeReconciler's audit parsing,
directional R formula, and MemoryStore reads) so the harness mirrors production
rather than re-deriving it.
"""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from ..live import mt5_client as mc
from ..manage import outcome as _outcome
from ..position import spec
from ..position.contract import _is_long, _is_short

VALIDATION_VERSION = "15A.1"

# MT5 deal-entry classification — the source-assumed values (from mt5_client).
IN = mc.DEAL_ENTRY_IN
OUT = mc.DEAL_ENTRY_OUT
INOUT = mc.DEAL_ENTRY_INOUT
OUT_BY = mc.DEAL_ENTRY_OUT_BY
EXITS = (OUT, OUT_BY)
VOL_TOL = 1e-6

# fields the harness is permitted to surface from a deal (NO profit/commission/swap)
SAFE_DEAL_FIELDS = ("ticket", "order", "position_id", "time", "time_msc",
                    "type", "entry", "reason", "volume", "price", "symbol",
                    "comment")

# any key whose (case-insensitive) name matches must never appear in output
SENSITIVE_KEYS = frozenset({
    "login", "password", "passwd", "account", "account_number", "balance",
    "equity", "margin", "margin_free", "margin_level", "credit", "profit",
    "commission", "swap", "api_key", "apikey", "token", "email", "name",
    "first_name", "last_name", "leverage",
})

# validation status vocabulary (the harness must not overclaim)
S_MT5_UNAVAILABLE = "MT5_UNAVAILABLE"
S_DEMO_NOT_CONFIRMED = "DEMO_ACCOUNT_NOT_CONFIRMED"
S_NO_EPISODE = "ENVIRONMENT_READY_NO_MATCHING_EPISODE"
S_OPEN = "OPEN_POSITION_OBSERVED"
S_PARTIAL = "PARTIAL_CLOSE_OBSERVED"
S_PENDING = "CLOSED_HISTORY_OBSERVED_OUTCOME_PENDING"
S_MATCH = "CLOSED_OUTCOME_MATCH"
S_MISMATCH = "CLOSED_OUTCOME_MISMATCH"
S_IDENTITY_AMBIGUOUS = "IDENTITY_AMBIGUOUS"

# close-analysis classifications
C_NO_HISTORY = "NO_HISTORY"
C_ENTRY_ONLY = "ENTRY_ONLY"
C_OPEN_OR_PARTIAL = "OPEN_OR_PARTIAL"
C_NET_FLAT = "NET_FLAT"
C_UNSUPPORTED_INOUT = "UNSUPPORTED_INOUT"
C_AMBIGUOUS = "AMBIGUOUS"

# identity classifications
ID_EQ = "TICKET_EQ_POSITION_IDENTIFIER"
ID_NE = "TICKET_NE_POSITION_IDENTIFIER"
ID_UNRESOLVED = "IDENTITY_UNRESOLVED"

# scoping classifications
SCOPE_CONFIRMED = "POSITION_SCOPED_CONFIRMED"
SCOPE_MISMATCH = "POSITION_SCOPED_MISMATCH"
SCOPE_UNRESOLVED = "POSITION_SCOPING_UNRESOLVED"


# --------------------------------------------------------------------------- #
# Generic read-only accessors
# --------------------------------------------------------------------------- #
def _get(obj, key, default=None):
    """Attribute-or-item accessor tolerant of MT5 namedtuples, plain objects and
    dicts. Never raises."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    try:
        return getattr(obj, key)
    except AttributeError:
        pass
    try:
        return obj[key]
    except Exception:
        return default


# --------------------------------------------------------------------------- #
# Pure analysis (unit-tested off-Windows)
# --------------------------------------------------------------------------- #
def validate_signal_id(sid):
    """Strict production signal_id validation (reuses the accepted rule)."""
    return _outcome._valid_sid(sid)


def is_demo_account(account):
    """(is_demo_or_None, reason). Only ACCOUNT_TRADE_MODE_DEMO counts as demo;
    REAL/CONTEST/unknown are NOT treated as demo (fail closed)."""
    mode = _get(account, "trade_mode", None)
    if mode is None:
        return None, "trade_mode_unavailable"
    if mode == mc.ACCOUNT_TRADE_MODE_DEMO:
        return True, "trade_mode=DEMO"
    if mode == mc.ACCOUNT_TRADE_MODE_REAL:
        return False, "trade_mode=REAL"
    if mode == mc.ACCOUNT_TRADE_MODE_CONTEST:
        return False, "trade_mode=CONTEST"
    return False, f"trade_mode={mode}"


def classify_account_mode(account):
    """NETTING / HEDGING / EXCHANGE / UNKNOWN from margin_mode (best effort)."""
    m = _get(account, "margin_mode", None)
    return {0: "NETTING", 1: "EXCHANGE", 2: "HEDGING"}.get(m, "UNKNOWN")


def extract_deal_fields(deal):
    """Safe, sanitized view of one deal — profit/commission/swap are never read."""
    return {k: _get(deal, k) for k in SAFE_DEAL_FIELDS}


def classify_identity(position_ticket, position_identifier):
    """Whether the MT5 position ticket equals its identifier (the value
    ``history_deals_get(position=...)`` is documented to expect)."""
    if position_ticket is None or position_identifier is None:
        return ID_UNRESOLVED
    return ID_EQ if position_ticket == position_identifier else ID_NE


def analyze_close(deals, *, entry_in=IN, exits=EXITS, inout=INOUT, tol=VOL_TOL):
    """Classify an episode from its deal set (read-only). Mirrors the production
    OutcomeReconciler net-flat rule and adds the richer states the validation
    needs. Volume-weights the exit price across all exit legs."""
    if not deals:
        return {"classification": C_NO_HISTORY, "in_volume": 0.0, "out_volume": 0.0,
                "difference": 0.0, "exit_deal_ids": [], "weighted_close": None,
                "net_flat": False, "deal_count": 0}
    in_vol = out_vol = notional = 0.0
    exit_ids = []
    has_inout = False
    classifiable = 0
    for d in deals:
        e = _get(d, "entry")
        v = _outcome._num(_get(d, "volume"))
        p = _outcome._num(_get(d, "price"))
        if e == inout:
            has_inout = True
        if v is None:
            continue
        if e == entry_in:
            in_vol += v
            classifiable += 1
        elif e in exits and p is not None:
            out_vol += v
            notional += p * v
            exit_ids.append(_get(d, "ticket"))
            classifiable += 1
    weighted = (notional / out_vol) if out_vol > 0 else None
    net_flat = in_vol > 0 and out_vol > 0 and abs(in_vol - out_vol) <= tol
    if has_inout:
        cls = C_UNSUPPORTED_INOUT
    elif classifiable == 0:
        cls = C_AMBIGUOUS
    elif in_vol > 0 and out_vol <= 0:
        cls = C_ENTRY_ONLY
    elif out_vol > 0 and in_vol <= 0:
        cls = C_AMBIGUOUS
    elif net_flat:
        cls = C_NET_FLAT
    elif out_vol < in_vol - tol:
        cls = C_OPEN_OR_PARTIAL
    else:
        cls = C_AMBIGUOUS
    return {"classification": cls, "in_volume": in_vol, "out_volume": out_vol,
            "difference": in_vol - out_vol, "exit_deal_ids": exit_ids,
            "weighted_close": weighted, "net_flat": net_flat,
            "deal_count": len(deals)}


def check_scoping(deals, queried_position_id):
    """Whether every returned deal belongs to the queried position id."""
    if queried_position_id is None:
        return SCOPE_UNRESOLVED
    pids = {_get(d, "position_id") for d in deals if _get(d, "position_id") is not None}
    if not pids:
        return SCOPE_UNRESOLVED
    return SCOPE_CONFIRMED if pids == {queried_position_id} else SCOPE_MISMATCH


def find_duplicate_deal_tickets(deals):
    """Sorted list of deal tickets appearing more than once."""
    counts = {}
    for d in deals:
        t = _get(d, "ticket")
        if t is None:
            continue
        counts[t] = counts.get(t, 0) + 1
    return sorted(t for t, c in counts.items() if c > 1)


def realized_r_crosscheck(direction, entry, initial_stop, weighted_close):
    """Independent realized-R, reusing ``spec.initial_risk`` and the SAME
    directional formula as OutcomeReconciler. R is undefined when initial risk is
    invalid or the exit price is missing."""
    e = _outcome._num(entry)
    s = _outcome._num(initial_stop)
    c = _outcome._num(weighted_close)
    R = spec.initial_risk(direction, e, s) if (e is not None and s is not None) else None
    r = _outcome.OutcomeReconciler._realized_r(direction, e, c, R)
    if r is None:
        status, won = "R_UNDEFINED", None
    else:
        status, won = "CLOSED", bool(r > 0)
    return {"direction": direction, "entry": e, "initial_stop": s,
            "initial_risk": R, "weighted_close": c, "r_multiple": r,
            "won": won, "status": status}


def package_enum_report(mt5):
    """Source-assumed constants vs the installed package's constants. Observed
    values are reported separately by the caller — a package constant is never
    treated as an empirical observation."""
    entry_names = ("DEAL_ENTRY_IN", "DEAL_ENTRY_OUT", "DEAL_ENTRY_INOUT",
                   "DEAL_ENTRY_OUT_BY")
    reason_names = ("DEAL_REASON_CLIENT", "DEAL_REASON_MOBILE", "DEAL_REASON_WEB",
                    "DEAL_REASON_EXPERT", "DEAL_REASON_SL", "DEAL_REASON_TP",
                    "DEAL_REASON_SO")
    pkg = {}
    for n in entry_names + reason_names:
        v = getattr(mt5, n, None) if mt5 is not None else None
        pkg[n] = v if v is not None else "NOT_OBSERVED"
    return {
        "source_assumed": {"DEAL_ENTRY_IN": IN, "DEAL_ENTRY_OUT": OUT,
                           "DEAL_ENTRY_INOUT": INOUT, "DEAL_ENTRY_OUT_BY": OUT_BY},
        "package_constant": pkg,
    }


def known_facts(audit_path, sid):
    """Immutable entry facts for ``sid`` from the durable PM audit, using the
    accepted per-line-tolerant reader + validation (read-only). None if absent
    or not well-formed."""
    facts = {}
    for r in _outcome._read_audit_file(str(audit_path)):
        if r.get("signal_id") != sid:
            continue
        for k in _outcome._REQUIRED:
            if facts.get(k) is None and r.get(k) is not None:
                facts[k] = r.get(k)
    return facts if _outcome._facts_valid(facts) else None


def sanitized_outcome(record):
    """Sanitized view of a stored execution_outcome, or the OUTCOME_NOT_PRESENT
    sentinel. Only the documented outcome fields are surfaced."""
    if record is None:
        return "OUTCOME_NOT_PRESENT"
    c = record.get("content", {}) or {}
    fields = ("signal_id", "status", "taken", "won", "r_multiple", "direction",
              "symbol", "ticket", "entry", "initial_stop", "weighted_close",
              "closed_volume", "deal_count")
    out = {k: c.get(k, "NOT_OBSERVED") for k in fields}
    out["source"] = record.get("source")
    out["timestamp"] = record.get("timestamp")
    out["memory_id"] = record.get("id")
    out["correlation_id"] = record.get("correlation_id")
    return out


def _num_eq(a, b, tol=1e-6):
    try:
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return False


def compare_outcome(independent, stored):
    """Per-field comparison of the harness's independent computation vs a stored
    outcome. Overall OUTCOME_MATCH / OUTCOME_MISMATCH / OUTCOME_NOT_YET_RECORDED."""
    if stored in (None, "OUTCOME_NOT_PRESENT") or not isinstance(stored, dict):
        return {"overall": "OUTCOME_NOT_YET_RECORDED", "fields": {}}
    numeric = {"entry", "initial_stop", "weighted_close", "r_multiple",
               "closed_volume"}
    fields = ("signal_id", "ticket", "direction", "entry", "initial_stop",
              "weighted_close", "r_multiple", "deal_count", "closed_volume")
    per = {}
    for f in fields:
        a = independent.get(f)
        b = stored.get(f)
        if a is None or b in (None, "NOT_OBSERVED"):
            per[f] = "NOT_COMPARABLE"
        elif f in numeric:
            per[f] = "MATCH" if _num_eq(a, b) else "MISMATCH"
        else:
            per[f] = "MATCH" if a == b else "MISMATCH"
    has_mismatch = any(v == "MISMATCH" for v in per.values())
    has_match = any(v == "MATCH" for v in per.values())
    overall = ("OUTCOME_MISMATCH" if has_mismatch
               else "OUTCOME_MATCH" if has_match
               else "OUTCOME_NOT_YET_RECORDED")
    return {"overall": overall, "fields": per}


def find_sensitive(obj, path="$"):
    """List of JSON paths whose key is sensitive (recursive). Empty == clean."""
    hits = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            here = f"{path}.{k}"
            if isinstance(k, str) and k.lower() in SENSITIVE_KEYS:
                hits.append(here)
            hits.extend(find_sensitive(v, here))
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            hits.extend(find_sensitive(v, f"{path}[{i}]"))
    return hits


def decide_status(*, mt5_available, demo_confirmed, identity_class,
                  position_present, close_classification, outcome_present,
                  comparison_overall):
    """Deterministic overall validation status (pure)."""
    if not mt5_available:
        return S_MT5_UNAVAILABLE
    if not demo_confirmed:
        return S_DEMO_NOT_CONFIRMED
    if position_present:
        return (S_PARTIAL if close_classification == C_OPEN_OR_PARTIAL else S_OPEN)
    if outcome_present:
        return (S_MATCH if comparison_overall == "OUTCOME_MATCH" else S_MISMATCH)
    if close_classification == C_NET_FLAT:
        return S_PENDING
    if identity_class == ID_UNRESOLVED and close_classification == C_NO_HISTORY:
        return S_NO_EPISODE
    if identity_class == ID_UNRESOLVED:
        return S_IDENTITY_AMBIGUOUS
    return S_NO_EPISODE


def repo_state(cwd=None):
    """Best-effort {commit, dirty} from git (read-only). UNKNOWN on failure."""
    def _run(args):
        return subprocess.check_output(args, cwd=cwd, text=True,
                                       stderr=subprocess.DEVNULL).strip()
    try:
        commit = _run(["git", "rev-parse", "HEAD"])
        dirty = bool(_run(["git", "status", "--porcelain"]))
        return {"commit": commit, "dirty": dirty}
    except Exception:
        return {"commit": "UNKNOWN", "dirty": "UNKNOWN"}


def observed_enum_values(deal_dicts):
    """Distinct entry/reason values ACTUALLY present in the returned deals."""
    return {
        "entry": sorted({_get(d, "entry") for d in deal_dicts
                         if _get(d, "entry") is not None}),
        "reason": sorted({_get(d, "reason") for d in deal_dicts
                          if _get(d, "reason") is not None}),
    }


# --------------------------------------------------------------------------- #
# MT5-touching layer (Windows only) — not exercised off-Windows
# --------------------------------------------------------------------------- #
def _connect():  # pragma: no cover - requires a live Windows terminal
    """Lazily import MetaTrader5 and attach to a running terminal. Returns the
    module or None (never raises)."""
    try:
        import MetaTrader5 as _mt5  # noqa: N813
    except Exception:
        return None
    try:
        if not _mt5.initialize():
            return None
    except Exception:
        return None
    return _mt5


def _positions_by_comment(mt5, sid):
    """Matching OPEN positions for ``sid``, or ``None`` when the query is UNKNOWN.

    F3: a positions_get() that returns None / raises / is malformed is UNKNOWN
    (could-not-query) and returns ``None`` — NEVER an empty list. A diagnostic probe
    must distinguish "no open positions" ([]) from "could not query positions" (None)
    so it never reports a false flat/absent state after an API failure."""
    try:
        raw = mt5.positions_get()
    except Exception:
        return None
    if raw is None or not isinstance(raw, (list, tuple)):
        return None
    return [p for p in raw if _get(p, "comment") == sid]


def _probe_history(mt5, position_id):  # pragma: no cover - live terminal only
    """Read-only history_deals_get(position=position_id) -> (ok, [deal dicts])."""
    if position_id is None:
        return False, []
    try:
        raw = mt5.history_deals_get(position=position_id)
    except Exception:
        return False, []
    if raw is None:
        return False, []
    return True, [extract_deal_fields(d) for d in raw]


def _account_view(mt5):  # pragma: no cover - live terminal only
    try:
        return mt5.account_info()
    except Exception:
        return None


def _watch_history(mt5, position_id, max_seconds):  # pragma: no cover - live only
    """Poll (>=1s) for the transition to a visible net-flat history after the
    position becomes absent. Read-only; finite duration required."""
    start = time.time()
    first_absent_at = None
    first_netflat_at = None
    samples = []
    while time.time() - start < max_seconds:
        matches = (_positions_by_comment(mt5, position_id.get("sid"))
                   if isinstance(position_id, dict) else None)
        # F3: None = UNKNOWN (could not query) — NEVER a false "absent". Only a KNOWN
        # empty list proves the position is absent.
        positions_queryable = matches is not None
        present = bool(matches) if matches is not None else None
        ok, deals = _probe_history(mt5, position_id if not isinstance(position_id, dict)
                                   else position_id.get("pid"))
        analysis = analyze_close(deals) if ok else {"classification": "UNAVAILABLE",
                                                    "net_flat": False}
        t = round(time.time() - start, 2)
        samples.append({"t": t, "history_available": ok,
                        "positions_queryable": positions_queryable,
                        "position_present": present,
                        "deal_count": len(deals) if ok else 0,
                        "classification": analysis["classification"]})
        if first_netflat_at is None and analysis.get("net_flat"):
            first_netflat_at = t
            break
        time.sleep(1.0)
    return {"first_absent_at": first_absent_at, "first_netflat_at": first_netflat_at,
            "samples": samples}


# --------------------------------------------------------------------------- #
# Entrypoint
# --------------------------------------------------------------------------- #
def _build_report(*, mt5, args, commit):  # pragma: no cover - live terminal only
    """Assemble the full validation report against a live terminal (Windows)."""
    from ..agents.memory import MemoryStore
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    sid = args.signal_id

    # runtime paths (override or accepted config)
    if args.runtime_dir:
        runtime_dir = Path(args.runtime_dir)
    else:
        from ..runtime.config import load_config
        runtime_dir = Path(load_config().runtime_dir)
    pm_audit_path = runtime_dir / "pm_audit.jsonl"
    memory = MemoryStore(str(runtime_dir / "memory"))

    account = _account_view(mt5)
    demo, demo_reason = is_demo_account(account)
    env = {
        "timestamp_utc": now, "os": platform.platform(),
        "python": platform.python_version(),
        "mt5_package_version": getattr(mt5, "__version__", "UNKNOWN"),
        "terminal_connected": True,
        "account_trade_mode_is_demo": demo, "demo_reason": demo_reason,
        "account_mode": classify_account_mode(account),
        "server": _get(account, "server", "UNKNOWN"),
        "repo_commit": commit["commit"], "repo_dirty": commit["dirty"],
    }
    report = {"validation_version": VALIDATION_VERSION, "environment": env,
              "package_enums": package_enum_report(mt5)}

    if demo is not True:
        report["validation_status"] = S_DEMO_NOT_CONFIRMED
        return report

    facts = known_facts(pm_audit_path, sid)
    positions = _positions_by_comment(mt5, sid)
    # F3: None = UNKNOWN (could not query positions) — never a false "no position".
    positions_queryable = positions is not None
    pos = positions[0] if positions else None
    pm_ticket = facts.get("ticket") if facts else args.ticket
    pos_ticket = _get(pos, "ticket")
    pos_identifier = _get(pos, "identifier")
    identity_class = classify_identity(pos_ticket, pos_identifier)
    report["identity"] = {
        "signal_id": sid, "pm_ticket": pm_ticket, "position_ticket": pos_ticket,
        "position_identifier": pos_identifier, "symbol": _get(pos, "symbol"),
        "comment_match": bool(pos),
        "positions_queryable": positions_queryable,   # F3: False => UNKNOWN, not "absent"
        "pm_matches_position": (
            pm_ticket is not None and pos_ticket is not None and pm_ticket == pos_ticket),
        "classification": identity_class if positions_queryable else "POSITIONS_UNAVAILABLE",
    }

    # history probes: PM ticket, and identifier if different/available
    query_ids, seen = [], set()
    for qid in (pm_ticket, pos_ticket, pos_identifier):
        if qid is not None and qid not in seen:
            seen.add(qid)
            query_ids.append(qid)
    history_queries, all_deals, scoping = [], [], SCOPE_UNRESOLVED
    for qid in query_ids:
        ok, deals = _probe_history(mt5, qid)
        history_queries.append({
            "query_identifier": qid, "success": ok, "deal_count": len(deals),
            "unique_deal_tickets": sorted({d["ticket"] for d in deals
                                           if d["ticket"] is not None}),
            "unique_position_ids": sorted({d["position_id"] for d in deals
                                           if d["position_id"] is not None}),
            "symbols": sorted({d["symbol"] for d in deals if d["symbol"]}),
            "duplicate_deal_tickets": find_duplicate_deal_tickets(deals),
            "scoping": check_scoping(deals, qid),
        })
        if ok and not all_deals:
            all_deals = deals
            scoping = check_scoping(deals, qid)
    report["history_queries"] = history_queries
    report["observed_deals"] = all_deals
    report["observed_enum_values"] = observed_enum_values(all_deals)
    report["history_scoping"] = scoping

    close = analyze_close(all_deals)
    report["close_analysis"] = close

    # realized-R cross-check only when net-flat and facts are known
    independent = {"signal_id": sid, "ticket": pm_ticket}
    if facts and close["net_flat"]:
        rr = realized_r_crosscheck(facts["direction"], facts["entry_price"],
                                   facts["initial_stop"], close["weighted_close"])
        report["realized_r_crosscheck"] = rr
        independent.update({"direction": facts["direction"],
                            "entry": rr["entry"], "initial_stop": rr["initial_stop"],
                            "weighted_close": rr["weighted_close"],
                            "r_multiple": rr["r_multiple"],
                            "closed_volume": close["out_volume"],
                            "deal_count": close["deal_count"]})
    else:
        report["realized_r_crosscheck"] = "NOT_APPLICABLE"

    stored_row = _stored_outcome(memory, sid)
    stored = sanitized_outcome(stored_row)
    report["stored_outcome"] = stored
    report["comparison"] = compare_outcome(independent, stored)

    report["validation_status"] = decide_status(
        mt5_available=True, demo_confirmed=True, identity_class=identity_class,
        position_present=bool(pos), close_classification=close["classification"],
        outcome_present=isinstance(stored, dict),
        comparison_overall=report["comparison"]["overall"])
    return report


def _stored_outcome(memory, sid):
    """Read-only MemoryStore lookup of the execution_outcome for ``sid``."""
    try:
        rows = memory.query(kind=_outcome.OUTCOME_KIND, limit=1_000_000)
    except Exception:
        return None
    for row in rows:
        if (row.get("content") or {}).get("signal_id") == sid:
            return row
    return None


def main(argv=None):  # pragma: no cover - Windows/terminal orchestration
    p = argparse.ArgumentParser(
        description="Read-only Windows/MT5 DEMO execution_outcome validation harness")
    p.add_argument("--signal-id", required=True, help="16-hex production signal_id")
    p.add_argument("--ticket", type=int, default=None,
                   help="optional PM ticket if not discoverable from PM audit")
    p.add_argument("--runtime-dir", default=None,
                   help="override runtime dir (defaults to accepted config)")
    p.add_argument("--watch-history-seconds", type=int, default=0,
                   help="optional read-only latency watch (finite, >=1s cadence)")
    p.add_argument("--json-only", action="store_true")
    args = p.parse_args(argv)

    if not validate_signal_id(args.signal_id):
        _emit({"validation_version": VALIDATION_VERSION,
               "error": "INVALID_SIGNAL_ID",
               "validation_status": S_NO_EPISODE}, args)
        return 2

    commit = repo_state()
    mt5 = _connect()
    if mt5 is None:
        _emit({"validation_version": VALIDATION_VERSION,
               "environment": {"os": platform.platform(),
                               "python": platform.python_version(),
                               "terminal_connected": False,
                               "repo_commit": commit["commit"]},
               "validation_status": S_MT5_UNAVAILABLE}, args)
        return 3

    try:
        report = _build_report(mt5=mt5, args=args, commit=commit)
        if args.watch_history_seconds and args.watch_history_seconds > 0:
            report["history_latency"] = "WATCH_MODE_REQUIRES_OPERATOR_CLOSE"
    finally:
        try:
            mt5.shutdown()
        except Exception:
            pass

    leaks = find_sensitive(report)
    if leaks:                       # never emit a report that leaks sensitive keys
        _emit({"validation_version": VALIDATION_VERSION,
               "error": "SENSITIVE_FIELD_LEAK", "paths": leaks,
               "validation_status": "ABORTED"}, args)
        return 4
    _emit(report, args)
    return 0


def _emit(report, args):  # pragma: no cover - I/O
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    if not getattr(args, "json_only", False):
        print("\n--- SUMMARY ---", file=sys.stderr)
        print(f"status : {report.get('validation_status')}", file=sys.stderr)
        if "close_analysis" in report:
            print(f"close  : {report['close_analysis'].get('classification')}",
                  file=sys.stderr)
        if "comparison" in report:
            print(f"compare: {report['comparison'].get('overall')}", file=sys.stderr)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
