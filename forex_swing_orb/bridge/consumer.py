"""Consumer-side bridge interface (spec §5-§9). TRANSPORT ONLY — NO EXECUTION.

This provides atomic claiming, transport validation, result writing, archival,
and quarantine. It does NOT implement the MT5 consumer: the actual execution
decision is an injected hook. The Phase-2 default hook is validation-only and
returns ACCEPTED without any trade, so the full flow is testable with no broker.
"""

from __future__ import annotations

from . import serialize
from .atomic import atomic_claim, atomic_move, atomic_write_text
from .contract import ResultState, ReasonCode, DENY_STATE, build_result
from .paths import (BridgePaths, INSTRUCTION_NAME_RE, instruction_name,
                    result_name, signal_id_from_instruction_name, is_safe_regular_file)
from .validate import validate_record


def validation_only_hook(record, now):
    """Default Phase-2 decision: transport validation passed -> ACCEPTED, no
    execution. Downstream layers replace this with a real (non-bridge) hook."""
    return ResultState.ACCEPTED, ReasonCode.OK, {"mode": "validation_only"}


class Consumer:
    """Bridge consumer interface. Filesystem-only; never executes trades."""

    def __init__(self, paths, cfg, ledger, audit, hook=None):
        self.paths = paths if isinstance(paths, BridgePaths) else BridgePaths(paths)
        self.cfg = cfg
        self.ledger = ledger
        self.audit = audit
        self.hook = hook or validation_only_hook

    # -- claiming -----------------------------------------------------------
    def claim(self, signal_id, now):
        """Atomically claim one pending instruction (rename pending->claimed)."""
        src = self.paths.pending / instruction_name(signal_id)
        dst = self.paths.claimed / instruction_name(signal_id)
        won = atomic_claim(src, dst)
        self.audit.emit(serialize.iso_utc(now), "claim",
                        "CLAIMED" if won else "MISSED", signal_id=signal_id)
        return won

    def claim_next(self, now):
        """Scan pending once (sorted) and claim the first valid instruction.
        Single pass — no polling, no waiting. Returns signal_id or None."""
        try:
            names = sorted(p.name for p in self.paths.pending.iterdir())
        except FileNotFoundError:
            return None
        for name in names:
            if not INSTRUCTION_NAME_RE.match(name):
                continue
            sid = name[:-5]
            if self.claim(sid, now):
                return sid
        return None

    # -- processing ---------------------------------------------------------
    def process(self, signal_id, now, received_iso=None):
        """Validate a claimed instruction and write exactly one terminal result.
        Never executes. Returns the result record (or None if quarantined)."""
        received_iso = received_iso or serialize.iso_utc(now)
        path = self.paths.claimed / instruction_name(signal_id)

        if not is_safe_regular_file(path, self.paths.root):
            return self._quarantine(path, signal_id, now, ReasonCode.E_UNSAFE_PATH)
        if path.stat().st_size > self.cfg.max_instruction_bytes:
            return self._quarantine(path, signal_id, now, ReasonCode.E_TOO_LARGE)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return self._quarantine(path, signal_id, now, ReasonCode.E_INTERNAL)
        ok, record = serialize.loads(text)
        if not ok:
            return self._quarantine(path, signal_id, now, ReasonCode.E_SERDE)

        # idempotency: an already-terminal signal_id is a duplicate, not re-run
        if self.ledger.is_seen(signal_id):
            return self._finish(signal_id, now, received_iso, ResultState.DUPLICATE,
                                ReasonCode.E_DUP, record, {"signal_id": signal_id})

        valid, reason, detail = validate_record(record, self.cfg, now, self.ledger,
                                                expected_signal_id=signal_id)
        if not valid:
            state = DENY_STATE.get(reason, ResultState.REJECTED)
            return self._finish(signal_id, now, received_iso, state, reason, record, detail)

        # transport OK -> hand to the injected decision hook (no execution here)
        try:
            state, reason, detail = self.hook(record, now)
        except Exception as exc:   # a hook failure is FAILED, never a crash
            state, reason, detail = ResultState.FAILED, ReasonCode.E_HOOK, {"error": type(exc).__name__}
        return self._finish(signal_id, now, received_iso, state, reason, record, detail)

    def _finish(self, signal_id, now, received_iso, state, reason, record, detail):
        processed_iso = serialize.iso_utc(now)
        rid = serialize.result_id(signal_id, processed_iso, state)
        result = build_result(signal_id, rid, state, reason, received_iso,
                              processed_iso, instruction=record, detail=detail)
        self._write_result(result)
        self.ledger.record(signal_id, state, rid, processed_iso)
        dest_dir = self.paths.archive_accepted if state == ResultState.ACCEPTED \
            else self.paths.archive_rejected
        atomic_move(self.paths.claimed / instruction_name(signal_id),
                    dest_dir / instruction_name(signal_id))
        self.audit.emit(processed_iso, "process", state, reason_code=reason,
                        signal_id=signal_id, detail={"result_id": rid})
        return result

    def _write_result(self, result):
        name = result_name(result["signal_id"], result["result_id"])
        atomic_write_text(self.paths.results / name, serialize.dumps(result))

    def _quarantine(self, path, signal_id, now, reason):
        dest = self.paths.quarantine / path.name
        atomic_move(path, dest)
        self.audit.emit(serialize.iso_utc(now), "quarantine", ResultState.ERROR,
                        reason_code=reason, signal_id=signal_id, detail={"path": path.name})
        return None
