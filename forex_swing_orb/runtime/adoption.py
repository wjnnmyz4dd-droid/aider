"""Manager position adoption (Phase 8D) — READ-ONLY discovery + initial-reference
recovery.

The autonomous manager must learn which open broker positions to manage. The
ENTER-channel EA stamps each position's comment with the originating ``signal_id``;
this module correlates open broker positions to their approved ENTER instruction
(recovering the immutable entry / initial-stop / take-profit that define the R
basis) so the PositionManager can register and manage them. It computes no
strategy, no risk, and no stop; it never places or closes anything. Fail closed:
a position whose approved reference cannot be recovered is skipped (never adopted
with a guessed stop).
"""

from __future__ import annotations

import re

from ..bridge import serialize
from ..bridge.paths import BridgePaths

_SIGNAL_ID_RE = re.compile(r"^[0-9a-f]{16}$")


def discover_registrations(truth, bridge_paths, tracked_signals):
    """Return a list of registration dicts for open broker positions that are not
    yet tracked and whose approved ENTER reference is recoverable.

    Each dict: {signal_id, ticket, symbol, direction, entry, initial_stop,
    take_profit}. ``symbol`` is the broker symbol reported by the terminal.
    """
    paths = bridge_paths if isinstance(bridge_paths, BridgePaths) else BridgePaths(bridge_paths)
    tracked = set(tracked_signals or ())
    out = []
    seen = set()
    for pos in truth.positions():
        sid = getattr(pos, "comment", None)
        ticket = getattr(pos, "ticket", None)
        if not isinstance(sid, str) or not _SIGNAL_ID_RE.match(sid):
            continue                                 # no correlatable signal_id
        if sid in tracked or sid in seen or ticket is None:
            continue
        instr = _recover_instruction(paths, sid)
        if instr is None:
            continue                                 # fail closed: unknown approved reference
        reg = _registration(pos, sid, ticket, instr)
        if reg is None:
            continue
        out.append(reg)
        seen.add(sid)
    return out


def market_from_truth(truth):
    """Current broker price per ticket (read-only), for the manager's evaluate."""
    m = {}
    for pos in truth.positions():
        ticket = getattr(pos, "ticket", None)
        price = getattr(pos, "price_current", None)
        if ticket is not None and isinstance(price, (int, float)):
            m[ticket] = float(price)
    return m


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


def _registration(pos, signal_id, ticket, instr):
    try:
        entry = float(instr["entry_price"])
        initial_stop = float(instr["stop_loss"])
        take_profit = float(instr["take_profit"])
        direction = str(instr["direction"])
    except (KeyError, TypeError, ValueError):
        return None
    return {
        "signal_id": signal_id,
        "ticket": ticket,
        "symbol": getattr(pos, "symbol", instr.get("symbol")),
        "direction": direction,
        "entry": entry,
        "initial_stop": initial_stop,
        "take_profit": take_profit,
    }
