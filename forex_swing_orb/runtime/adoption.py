"""Manager position adoption + restart-recovery orchestration inputs (G4).

READ-ONLY discovery and evidence inspection for the manager. This module holds NO
phase logic and NO stop mathematics: :meth:`PositionManager.recover` is the single
phase-recovery implementation, and :meth:`PositionManager.register` the single
new-position path. Here we only (a) discover open broker positions carrying a
signal_id, (b) recover a genuinely-new position's approved ENTER immutable facts,
and (c) inspect a PM audit history for immutable-fact consistency so the service
can decide recover-vs-register-vs-fail-closed. Never guesses entry/stop/phase.
"""

from __future__ import annotations

import re

from ..bridge import serialize
from ..bridge.paths import BridgePaths

_SIGNAL_ID_RE = re.compile(r"^[0-9a-f]{16}$")

# immutable entry facts a PM audit history must carry consistently to be a
# trustworthy recovery basis (phase progression is NOT one of these — that is
# reconstructed by PositionManager.recover()).
_IMMUTABLE = ("direction", "symbol", "ticket", "entry_price", "initial_stop")


def discover_positions(truth):
    """Open broker positions carrying a valid 16-hex signal_id comment.

    Returns ``[{signal_id, ticket, symbol}]`` (broker symbol), deduped by
    signal_id (first occurrence wins). Read-only; closed positions never appear
    (the truth source returns only open positions)."""
    out, seen = [], set()
    for pos in truth.positions():
        sid = getattr(pos, "comment", None)
        ticket = getattr(pos, "ticket", None)
        if not isinstance(sid, str) or not _SIGNAL_ID_RE.match(sid):
            continue
        if ticket is None or sid in seen:
            continue
        seen.add(sid)
        out.append({"signal_id": sid, "ticket": ticket,
                    "symbol": getattr(pos, "symbol", None)})
    return out


def enter_reference(bridge_paths, signal_id, ticket, symbol=None):
    """Approved ENTER immutable facts for a GENUINELY NEW position (no PM history).

    Recovered from the archived/claimed/pending ENTER instruction. Returns a dict
    {signal_id, ticket, symbol, direction, entry, initial_stop, take_profit} or
    None if the approved reference is unavailable or malformed — fail closed:
    entry/stop are never guessed."""
    paths = bridge_paths if isinstance(bridge_paths, BridgePaths) else BridgePaths(bridge_paths)
    instr = _recover_instruction(paths, signal_id)
    if instr is None:
        return None
    try:
        return {
            "signal_id": signal_id,
            "ticket": ticket,
            "symbol": symbol or instr.get("symbol"),
            "direction": str(instr["direction"]),
            "entry": float(instr["entry_price"]),
            "initial_stop": float(instr["stop_loss"]),
            "take_profit": float(instr["take_profit"]),
        }
    except (KeyError, TypeError, ValueError):
        return None


def audit_immutable_conflict(records):
    """True iff a PM audit history is not a trustworthy recovery basis: an
    immutable entry fact is missing across every record, or two records disagree
    on one. Deterministic; phase progression is intentionally NOT checked here."""
    seen = {}
    for r in records:
        for k in _IMMUTABLE:
            v = r.get(k)
            if v is None:
                continue
            if k in seen and seen[k] != v:
                return True
            seen[k] = v
    return any(k not in seen for k in _IMMUTABLE)


def audit_ticket(records):
    """The single ticket referenced by a (conflict-free) audit history, else None."""
    tickets = {r.get("ticket") for r in records if r.get("ticket") is not None}
    return next(iter(tickets)) if len(tickets) == 1 else None


def market_from_truth(truth):
    """Current broker price per ticket (read-only), for the manager's evaluate."""
    m = {}
    for pos in truth.positions():
        ticket = getattr(pos, "ticket", None)
        price = getattr(pos, "price_current", None)
        if ticket is not None and isinstance(price, (int, float)):
            m[ticket] = float(price)
    return m


def open_times_from_truth(truth):
    """Broker position OPEN times per ticket (epoch seconds), read-only. The single
    source of verified position-open evidence for deterministic bars_open. A
    position missing an open time is simply absent (bars_open then fails closed)."""
    out = {}
    for pos in truth.positions():
        ticket = getattr(pos, "ticket", None)
        t = getattr(pos, "time", None)
        if ticket is not None and isinstance(t, (int, float)) and not isinstance(t, bool):
            out[ticket] = int(t)
    return out


def _recover_instruction(paths, signal_id):
    name = signal_id + ".json"
    for d in (paths.archive_accepted, paths.claimed, paths.pending):
        f = d / name
        if not f.exists():
            continue
        try:
            ok, rec = serialize.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if ok and isinstance(rec, dict) and rec.get("signal_id") == signal_id:
            return rec
    return None
