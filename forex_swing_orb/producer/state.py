"""Runner-local durable state + audit (Phase 7A).

Persists exactly what is needed to recover without duplicate signals: the last
processed closed-bar per symbol, the set of signal_ids already written, and the
latest input versions. Uses the accepted atomic write + canonical serializer —
no new serialization format. No in-memory-only correctness state.
"""

from __future__ import annotations

from ..bridge import serialize
from ..bridge.atomic import append_line_fsync, atomic_write_text


class RunnerState:
    def __init__(self, path):
        self.path = path
        self.last_processed = {}     # symbol -> bar open iso
        self.written_signals = []    # signal_ids written (audit/idempotency aid)
        self.load()

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                ok, obj = serialize.loads(f.read())
        except FileNotFoundError:
            return
        if ok:
            self.last_processed = dict(obj.get("last_processed", {}))
            self.written_signals = list(obj.get("written_signals", []))

    def save(self):
        atomic_write_text(self.path, serialize.canonical_json({
            "last_processed": self.last_processed,
            "written_signals": self.written_signals,
        }))

    def mark_processed(self, symbol, bar_iso):
        self.last_processed[symbol] = bar_iso
        self.save()

    def mark_written(self, signal_id):
        if signal_id not in self.written_signals:
            self.written_signals.append(signal_id)
            self.save()

    def get_last(self, symbol):
        return self.last_processed.get(symbol)


class RunnerAudit:
    """Append-only deterministic cycle audit (canonical JSONL). No secrets."""

    def __init__(self, path):
        self.path = path

    def emit(self, record):
        append_line_fsync(self.path, serialize.canonical_json(record))
        return record

    def read_all(self):
        out = []
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    ok, obj = serialize.loads(line)
                    if ok:
                        out.append(obj)
        except FileNotFoundError:
            return []
        return out
