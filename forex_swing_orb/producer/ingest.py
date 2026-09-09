"""Result / acknowledgement ingestion + reconciliation (Phase 7A).

READ-ONLY correlation of producer + bridge + EA evidence. It reuses the accepted
bridge dedup (:class:`SeenResolver`) and never modifies the bridge, never places
an order, and never moves a stop. Uncertain execution state (a claim/ack with no
terminal result) is reported as reconciliation-required — never assumed failed.
"""

from __future__ import annotations

from ..bridge import serialize
from ..bridge.config import DEFAULT_CONFIG
from ..bridge.dedup import SeenResolver
from ..bridge.ledger import DedupLedger


def _ack_present(paths, signal_id):
    if not paths.acks.exists():
        return False
    prefix = signal_id + "."
    return any(p.name.startswith(prefix) for p in paths.acks.iterdir())


def _in_flight(paths, signal_id):
    pend = paths.pending / (signal_id + ".json")
    claim = paths.claimed / (signal_id + ".json")
    return pend.exists() or claim.exists()


def signal_status(paths, signal_id, cfg=DEFAULT_CONFIG):
    """Return a correlation dict for one signal_id (read-only)."""
    resolver = SeenResolver(paths, DedupLedger(paths.dedup_ledger), cfg)
    seen = resolver.resolve(signal_id)
    ack = _ack_present(paths, signal_id)
    in_flight = _in_flight(paths, signal_id)
    # uncertain: evidence of an attempt (ack or claim) but no terminal result
    uncertain = (ack or in_flight) and not seen.terminal
    return {
        "signal_id": signal_id,
        "seen": bool(seen.seen),
        "terminal": bool(seen.terminal),
        "state": seen.state,
        "family": seen.family,
        "ack_present": ack,
        "in_flight": in_flight,
        "reconcile_required": bool(uncertain),
    }


def already_seen(paths, signal_id, cfg=DEFAULT_CONFIG):
    """True iff the bridge already holds this signal_id anywhere (dedup guard)."""
    resolver = SeenResolver(paths, DedupLedger(paths.dedup_ledger), cfg)
    return bool(resolver.resolve(signal_id).seen) or _in_flight(paths, signal_id)


def ingest(paths, signal_ids, cfg=DEFAULT_CONFIG):
    """Correlate a set of signal_ids -> {signal_id: status}. Read-only."""
    return {sid: signal_status(paths, sid, cfg) for sid in signal_ids}
