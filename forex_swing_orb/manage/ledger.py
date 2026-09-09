"""Persistent manage-channel ledger (Phase 7B-B).

Durable, restart-surviving state: per-ticket monotonic sequence, one-in-flight
map, and terminal dedup by manage_id. Uses the accepted atomic writer + canonical
serializer. In-flight is cleared ONLY by a terminal result or verified
reconciliation — never by timeout.
"""

from __future__ import annotations

from ..bridge import serialize
from ..bridge.atomic import atomic_write_text


class ManageLedger:
    def __init__(self, path):
        self.path = path
        self.seq = {}          # ticket(str) -> last sequence (int)
        self.inflight = {}     # ticket(str) -> manage_id
        self.terminal = {}     # manage_id -> {"ticket","status","sequence"}
        self.load()

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                ok, obj = serialize.loads(f.read())
        except FileNotFoundError:
            return
        if ok:
            self.seq = {str(k): int(v) for k, v in obj.get("seq", {}).items()}
            self.inflight = dict(obj.get("inflight", {}))
            self.terminal = dict(obj.get("terminal", {}))

    def _save(self):
        atomic_write_text(self.path, serialize.canonical_json(
            {"seq": self.seq, "inflight": self.inflight, "terminal": self.terminal}))

    # -- sequence -----------------------------------------------------------
    def next_seq(self, ticket):
        t = str(ticket)
        self.seq[t] = self.seq.get(t, 0) + 1
        self._save()
        return self.seq[t]

    def last_terminal_seq(self, ticket):
        best = 0
        for rec in self.terminal.values():
            if str(rec.get("ticket")) == str(ticket):
                best = max(best, int(rec.get("sequence", 0)))
        return best

    # -- one-in-flight ------------------------------------------------------
    def get_inflight(self, ticket):
        return self.inflight.get(str(ticket))

    def set_inflight(self, ticket, manage_id):
        self.inflight[str(ticket)] = manage_id
        self._save()

    def clear_inflight(self, ticket):
        self.inflight.pop(str(ticket), None)
        self._save()

    # -- terminal dedup -----------------------------------------------------
    def is_terminal(self, manage_id):
        return manage_id in self.terminal

    def terminal_status(self, manage_id):
        rec = self.terminal.get(manage_id)
        return rec.get("status") if rec else None

    def record_terminal(self, manage_id, ticket, status, sequence):
        self.terminal[manage_id] = {"ticket": str(ticket), "status": status,
                                    "sequence": int(sequence)}
        # a terminal result clears in-flight for that ticket iff it was this id
        if self.inflight.get(str(ticket)) == manage_id:
            self.inflight.pop(str(ticket), None)
        self._save()
