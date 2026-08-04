"""Consumer-side bridge interface (spec §5-§10). TRANSPORT ONLY — NO EXECUTION.

Atomic claiming, one shared dedup resolver, structural validation, a single
crash-safe terminal-result writer, archival, quarantine, and hook-posture-aware
reconciliation. It never executes trades: the execution decision is an injected
hook whose Phase-2 default is validation-only (ACCEPTED, no trade).
"""

from __future__ import annotations

from . import serialize
from .atomic import atomic_claim, atomic_move, atomic_write_text
from .contract import (ResultState, ReasonCode, HookPosture, DENY_STATE,
                       build_result, terminal_family)
from .dedup import SeenResolver
from .paths import (BridgePaths, INSTRUCTION_NAME_RE, instruction_name,
                    result_name, is_safe_regular_file, safe_read_text)
from .validate import validate_record


def validation_only_hook(record, now):
    """Default Phase-2 decision: transport validation passed -> ACCEPTED, no
    execution. Downstream layers replace this with a real (non-bridge) hook."""
    return ResultState.ACCEPTED, ReasonCode.OK, {"mode": "validation_only"}


class Consumer:
    """Bridge consumer interface. Filesystem-only; never executes trades."""

    def __init__(self, paths, cfg, ledger, audit, hook=None,
                 hook_posture=HookPosture.VALIDATION_ONLY, resolver=None):
        self.paths = paths if isinstance(paths, BridgePaths) else BridgePaths(paths)
        self.cfg = cfg
        self.ledger = ledger
        self.audit = audit
        self.hook = hook or validation_only_hook
        self.hook_posture = hook_posture
        self.resolver = resolver or SeenResolver(self.paths, ledger, cfg)

    # -- claiming -----------------------------------------------------------
    def claim(self, signal_id, now):
        src = self.paths.pending / instruction_name(signal_id)
        dst = self.paths.claimed / instruction_name(signal_id)
        won = atomic_claim(src, dst)   # exclusive: never overwrites an existing claim
        self.audit.emit(serialize.iso_utc(now), "claim",
                        "CLAIMED" if won else "MISSED", signal_id=signal_id)
        return won

    def claim_next(self, now):
        """Single pass over pending (sorted); claim the first valid instruction.
        No polling, no waiting. Returns signal_id or None."""
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
        """Validate a claimed instruction and produce exactly one terminal result.
        Never executes. Returns the result/ack record (or None if quarantined)."""
        received_iso = received_iso or serialize.iso_utc(now)
        path = self.paths.claimed / instruction_name(signal_id)

        if not is_safe_regular_file(path, self.paths.root):
            return self._quarantine(path, signal_id, now, ReasonCode.E_UNSAFE_PATH)
        ok, text, reason = safe_read_text(path, self.paths.root, self.cfg.max_instruction_bytes)
        if not ok:
            rc = {"too_large": ReasonCode.E_TOO_LARGE, "unsafe": ReasonCode.E_UNSAFE_PATH}.get(
                reason, ReasonCode.E_SERDE)
            return self._quarantine(path, signal_id, now, rc)
        parsed, record = serialize.loads(text)
        if not parsed:
            return self._quarantine(path, signal_id, now, ReasonCode.E_SERDE)

        # ONE dedup resolver over all persistent evidence (F-D)
        seen = self.resolver.resolve(signal_id)
        if seen.conflict:
            return self._quarantine(path, signal_id, now, ReasonCode.E_CONFLICT,
                                    detail=seen.detail)
        if seen.terminal:
            # already terminal elsewhere: adopt it, DO NOT mint a second result (F-C)
            return self._adopt(signal_id, seen, now, action="process")

        valid, vreason, detail = validate_record(record, self.cfg, now,
                                                 expected_signal_id=signal_id)
        if not valid:
            state = DENY_STATE.get(vreason, ResultState.REJECTED)
            return self._finish(signal_id, now, received_iso, state, vreason, record, detail)

        # transport OK -> injected decision hook (no execution here)
        try:
            state, hreason, detail = self.hook(record, now)
        except Exception as exc:
            state, hreason, detail = ResultState.FAILED, ReasonCode.E_HOOK, {"error": type(exc).__name__}
        return self._finish(signal_id, now, received_iso, state, hreason, record, detail)

    # -- terminal transition (the ONE terminal-result writer) ---------------
    def _finish(self, signal_id, now, received_iso, state, reason, record, detail):
        processed_iso = serialize.iso_utc(now)
        rid = serialize.result_id(signal_id, state)     # deterministic on (sid, state)
        # An execution hook may return broker fill fields under detail["execution"];
        # the bridge stays broker-agnostic and simply forwards them to the writer.
        execution = detail.get("execution") if isinstance(detail, dict) else None
        result = build_result(signal_id, rid, state, reason, received_iso,
                              processed_iso, instruction=record, detail=detail,
                              execution=execution)
        self._write_result(result)                       # (1) terminal artifact
        self.ledger.record(signal_id, state, rid, processed_iso)   # (2) ledger
        self._archive(signal_id, terminal_family(state), now)      # (3) archive
        self.audit.emit(processed_iso, "process", state, reason_code=reason,
                        signal_id=signal_id, detail={"result_id": rid})
        return result

    def _adopt(self, signal_id, seen, now, action):
        """Adopt an existing terminal outcome (F-C/F-D): repair the ledger from
        on-disk evidence and archive the claimed file to the matching family.
        Never writes a second result and never calls the hook."""
        processed_iso = serialize.iso_utc(now)
        self.resolver.repair_ledger(signal_id, seen, processed_iso)
        self._archive(signal_id, seen.family or "REJECTED", now)
        self.audit.emit(processed_iso, action, ResultState.DUPLICATE,
                        reason_code=ReasonCode.E_DUP, signal_id=signal_id,
                        detail={"adopted": ReasonCode.ADOPTED, "state": seen.state,
                                "evidence": seen.detail})
        return {"signal_id": signal_id, "status": ResultState.DUPLICATE,
                "reason_code": ReasonCode.E_DUP, "adopted_state": seen.state}

    def mark_reconciliation_required(self, signal_id, now):
        """Non-idempotent posture, non-terminal claimed item (F-S): do NOT re-run
        the hook; require external broker/execution reconciliation. Fail-closed:
        no result, no archive, no retry — the claimed file stays for review."""
        self.audit.emit(serialize.iso_utc(now), "reconcile",
                        ReasonCode.RECONCILIATION_REQUIRED,
                        reason_code=ReasonCode.RECONCILIATION_REQUIRED, signal_id=signal_id,
                        detail={"posture": self.hook_posture})
        return {"signal_id": signal_id, "status": ReasonCode.RECONCILIATION_REQUIRED}

    # -- filesystem helpers -------------------------------------------------
    def _write_result(self, result):
        name = result_name(result["signal_id"], result["result_id"])
        atomic_write_text(self.paths.results / name, serialize.dumps(result))

    def _archive(self, signal_id, family, now):
        dest_dir = self.paths.archive_accepted if family == "ACCEPTED" else self.paths.archive_rejected
        return self._move_or_audit(self.paths.claimed / instruction_name(signal_id),
                                   dest_dir / instruction_name(signal_id), now,
                                   "archive", signal_id)

    def _move_or_audit(self, src, dst, now, action, signal_id):
        """Move a file; on failure emit an audit event and fail closed (F-2)."""
        moved = atomic_move(src, dst)
        if not moved:
            self.audit.emit(serialize.iso_utc(now), action, ResultState.ERROR,
                            reason_code=ReasonCode.E_MOVE, signal_id=signal_id,
                            detail={"src": str(src.name), "dst": str(dst.name)})
        return moved

    def _quarantine(self, path, signal_id, now, reason, detail=None):
        moved = self._move_or_audit(path, self.paths.quarantine / path.name, now,
                                    "quarantine", signal_id)
        self.audit.emit(serialize.iso_utc(now), "quarantine", ResultState.ERROR,
                        reason_code=reason, signal_id=signal_id,
                        detail={"path": path.name, "moved": moved, **(detail or {})})
        return None
