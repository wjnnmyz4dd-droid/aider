"""Single shared seen-signal resolver (F-D).

Deduplication must survive loss of ``dedup.jsonl``. This is the ONE resolver the
whole bridge uses (validate/consumer/reconcile) — no parallel dedup logic. It
answers "have we seen this signal_id?" from ALL persistent evidence:

  - the dedup ledger
  - inbox/results/<sid>.*.json      (terminal result artifact)
  - archive/accepted/<sid>.json     (terminal, accepted family)
  - archive/rejected/<sid>.json     (terminal, rejected family)
  - outbox/claimed/<sid>.json       (in-flight)

Terminal evidence from disk repairs/rebuilds the ledger. Conflicting evidence
(both accepted and rejected families for one signal_id) FAILS CLOSED.
"""

from __future__ import annotations

from . import serialize
from .contract import terminal_family, ResultState
from .paths import instruction_name, safe_read_text


class SeenResult:
    __slots__ = ("seen", "terminal", "family", "state", "conflict", "claimed",
                 "ledger_has", "results", "detail")

    def __init__(self, seen=False, terminal=False, family=None, state=None,
                 conflict=False, claimed=False, ledger_has=False, results=None,
                 detail=None):
        self.seen = seen
        self.terminal = terminal
        self.family = family
        self.state = state
        self.conflict = conflict
        self.claimed = claimed
        self.ledger_has = ledger_has
        self.results = results or []
        self.detail = detail or {}


class SeenResolver:
    def __init__(self, paths, ledger, cfg):
        self.paths = paths
        self.ledger = ledger
        self.cfg = cfg

    def _result_files(self, signal_id):
        prefix = signal_id + "."
        try:
            return sorted(p for p in self.paths.results.iterdir()
                          if p.name.startswith(prefix) and p.name.endswith(".json"))
        except FileNotFoundError:
            return []

    def resolve(self, signal_id):
        families = set()
        states = set()
        detail = {}

        led = self.ledger.get(signal_id)
        if led is not None:
            states.add(led.get("state"))
            families.add(terminal_family(led.get("state")))
            detail["ledger"] = led.get("state")

        result_files = self._result_files(signal_id)
        for rf in result_files:
            ok, text, reason = safe_read_text(rf, self.paths.root, self.cfg.max_result_bytes)
            if not ok:
                # unreadable/oversized result evidence -> cannot trust -> conflict
                return SeenResult(seen=True, terminal=True, conflict=True,
                                  results=[p.name for p in result_files],
                                  detail={"bad_result": rf.name, "reason": reason})
            parsed_ok, rec = serialize.loads(text)
            status = rec.get("status") if parsed_ok else None
            if status is None:
                return SeenResult(seen=True, terminal=True, conflict=True,
                                  results=[p.name for p in result_files],
                                  detail={"malformed_result": rf.name})
            states.add(status)
            families.add(terminal_family(status))
        if result_files:
            detail["results"] = [p.name for p in result_files]

        acc = (self.paths.archive_accepted / instruction_name(signal_id)).exists()
        rej = (self.paths.archive_rejected / instruction_name(signal_id)).exists()
        if acc:
            families.add("ACCEPTED"); detail["archive"] = "accepted"
        if rej:
            families.add("REJECTED"); detail["archive"] = (detail.get("archive"), "rejected")

        claimed = (self.paths.claimed / instruction_name(signal_id)).exists()

        terminal = len(families) >= 1
        conflict = len(families) > 1
        family = next(iter(families)) if (terminal and not conflict) else None
        # pick a representative concrete state where unambiguous
        state = None
        if not conflict and states:
            state = ResultState.ACCEPTED if family == "ACCEPTED" else \
                (next(iter(states)) if len(states) == 1 else ResultState.REJECTED)
        elif not conflict and family:
            state = ResultState.ACCEPTED if family == "ACCEPTED" else ResultState.REJECTED

        return SeenResult(
            seen=terminal or claimed, terminal=terminal, family=family, state=state,
            conflict=conflict, claimed=claimed, ledger_has=led is not None,
            results=[p.name for p in result_files], detail=detail,
        )

    def repair_ledger(self, signal_id, seen, processed_iso):
        """Rebuild the ledger entry from on-disk terminal evidence if missing."""
        if seen.terminal and not seen.ledger_has and not seen.conflict:
            rid = serialize.result_id(signal_id, seen.state)
            self.ledger.record(signal_id, seen.state, rid, processed_iso)
            return True
        return False
