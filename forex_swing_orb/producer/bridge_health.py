"""Read-only entry-bridge observation (PR-3C / H5).

ONE authoritative, read-only snapshot of the ENTRY execution bridge, feeding three
consumers with a single consistent inventory (never three divergent scans):

  * account-capacity reservation (PR-4A.1): outstanding non-terminal intents;
  * acknowledgement liveness: ``missing_ack_count`` — entry instructions the consumer
    failed to ACKNOWLEDGE within their own validity window;
  * bridge health: ``bridge_healthy`` — is the entry bridge operational enough to
    accept new risk.

Authoritative bridge contract (verified from source):
  * The producer writes an instruction to ``outbox/pending/`` (atomic temp+rename).
  * The consumer (MQL5 EA / reference consumer) ATOMICALLY claims it
    ``pending -> claimed`` (``FileMove`` without overwrite). That atomic claim is the
    earliest authoritative CONSUMER ACKNOWLEDGEMENT (it has taken responsibility).
  * A terminal result MOVES the file ``claimed -> archive/*`` atomically. So a signal
    is in EXACTLY ONE of pending / claimed / archive at any instant — a signal still
    in pending/claimed is, by that invariant, NON-TERMINAL (no archive scan needed).

Definitions:
  * ACKNOWLEDGED  = the instruction is CLAIMED (or terminal). PENDING = not yet acked.
  * ACK WINDOW    = the instruction's own signed ``expiration_timestamp`` (the existing
    authoritative execution-validity contract — no invented timeout). A PENDING (still
    unclaimed) instruction whose ``now >= expiration_timestamp`` has missed its ACK
    window: the consumer never took it within the window it was valid to execute in.
  * OUTSTANDING   = any non-terminal entry intent (pending OR claimed) — reserves
    account capacity until it becomes a broker position or terminal.

Fail closed: any I/O error, missing directory, unparseable/corrupt instruction, or
future/invalid timestamp yields ``healthy=False`` (never True/empty). Read-only: this
module never writes, deletes, claims, or repairs anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..bridge import serialize

# Instruction file names are the 16-hex signal_id + ".json".
_NAME_LEN = 21


@dataclass(frozen=True)
class BridgeObservation:
    healthy: bool
    reason: str                       # "" when healthy, else why it is unhealthy
    outstanding_count: int            # non-terminal entry intents (pending + claimed)
    outstanding_symbols: tuple        # symbols of those intents (readable ones)
    missing_ack_count: int            # pending intents past their ACK window (expiration)
    oldest_unacked_age_sec: float = None
    stale_signal_ids: tuple = ()      # signal_ids counted as missing-ack
    outstanding_signal_ids: tuple = ()

    def as_dict(self):
        return {
            "bridge_healthy": bool(self.healthy),
            "bridge_reason": self.reason,
            "outstanding_count": int(self.outstanding_count),
            "missing_ack_count": int(self.missing_ack_count),
            "oldest_unacked_age_sec": self.oldest_unacked_age_sec,
            "stale_signal_ids": list(self.stale_signal_ids),
        }


def _unhealthy(reason, *, outstanding_count=0, outstanding_symbols=(),
               outstanding_signal_ids=()):
    """An unhealthy observation still fails closed on ACK: unknown bridge state can
    never lower missing_ack_count to zero, so a positive stale count is reported and
    capacity is still reserved for any intents we could enumerate."""
    return BridgeObservation(
        healthy=False, reason=reason, outstanding_count=outstanding_count,
        outstanding_symbols=tuple(outstanding_symbols), missing_ack_count=1,
        oldest_unacked_age_sec=None, stale_signal_ids=(),
        outstanding_signal_ids=tuple(outstanding_signal_ids))


def _terminal_evidence(paths, sid):
    """True iff authoritative TERMINAL evidence exists for ``sid`` (the consumer
    moved it out of the outbox): archive/accepted, archive/rejected, or quarantine.
    Read-only ``.exists()`` checks — done ONLY when a file vanished mid-scan (never a
    routine archive scan), so the atomic-move design is preserved."""
    name = sid + ".json"
    for attr in ("archive_accepted", "archive_rejected", "quarantine"):
        d = getattr(paths, attr, None)
        try:
            if d is not None and (d / name).exists():
                return True
        except OSError:
            continue
    return False


def _read_json(path):
    """Read+parse one instruction file. Returns (kind, payload):
      ("OK", obj)         parsed dict
      ("VANISHED", None)  file no longer at this path (FileNotFoundError only)
      ("CORRUPT", reason) any OTHER I/O error, decode error, or unparseable JSON
    Only FileNotFoundError is non-fatal — every other failure stays fail-closed."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return "VANISHED", None
    except (OSError, UnicodeError) as exc:        # permission / isdir / decode / io
        return "CORRUPT", "io_error:{}".format(type(exc).__name__)
    ok, obj = serialize.loads(text)
    if not ok or not isinstance(obj, dict):
        return "CORRUPT", "unparseable"
    return "OK", obj


def _reconcile_vanished(paths, sid, orig_state):
    """A file disappeared from ``orig_state`` during the scan. Reconcile against
    CURRENT authoritative bridge state before classifying failure (F-H5-1):
      ("TERMINAL", None)  terminal evidence exists -> no longer outstanding;
      ("CLAIMED", obj)    a pending file was atomically claimed -> normal ACK;
      ("CORRUPT", reason) disappeared with NO authoritative evidence -> fail closed.
    Disappearance is never inferred as success on its own."""
    if _terminal_evidence(paths, sid):
        return "TERMINAL", None
    if orig_state == "PENDING":
        # the one proven normal transition: pending -> claimed (atomic FileMove)
        kind, payload = _read_json(paths.claimed / (sid + ".json"))
        if kind == "OK":
            return "CLAIMED", payload
        if kind == "VANISHED":
            # advanced again during the re-check; only terminal evidence rescues it
            if _terminal_evidence(paths, sid):
                return "TERMINAL", None
            return "CORRUPT", "pending_vanished_no_evidence:{}".format(sid)
        return "CORRUPT", payload                 # claimed unreadable -> fail closed
    # a CLAIMED file vanished but is in no terminal location -> unexplained
    return "CORRUPT", "claimed_vanished_no_terminal:{}".format(sid)


def _list_instruction_files(directory):
    """List instruction files in a bridge dir. Returns list[Path]; raises OSError if
    the directory is missing/unreadable (caller fails closed). Ignores dot-temp files
    (atomic writes use a leading-dot temp name) and any non 16-hex-.json name."""
    if not directory.exists():
        raise OSError("missing bridge directory: {}".format(directory))
    out = []
    for p in directory.iterdir():                    # raises OSError on unreadable dir
        name = p.name
        if name.startswith("."):
            continue                                  # in-progress atomic temp
        if len(name) == _NAME_LEN and name.endswith(".json"):
            out.append(p)
    return out


def observe_entry_bridge(paths, now):
    """Return a :class:`BridgeObservation` for the entry bridge at ``now`` (tz-aware
    UTC). Read-only and deterministic. Fails closed (healthy=False) on any ambiguity."""
    if now is None or getattr(now, "tzinfo", None) is None:
        return _unhealthy("invalid_now")
    try:
        pending = _list_instruction_files(paths.pending)
        claimed = _list_instruction_files(paths.claimed)
        # results/archive dirs must be at least accessible (consumer output paths)
        for d in (paths.claimed, paths.pending):
            if not d.is_dir():
                return _unhealthy("bridge_path_not_dir")
    except OSError as exc:
        return _unhealthy("bridge_unreadable:{!r}".format(exc))

    outstanding_ids = {}          # signal_id -> {"state","symbol"}; claimed wins over pending
    outstanding_syms = set()
    missing = []
    oldest_age = None
    corrupt = None
    future = None

    # claimed first so claimed state wins if a signal_id appears in both (dedupe;
    # one signal contributes at most one outstanding/ack state).
    for state, files in (("CLAIMED", claimed), ("PENDING", pending)):
        for p in files:
            sid = p.name[:16]
            eff_state = state
            # A signal_id already counted as CLAIMED wins over any later PENDING
            # duplicate; skip the read entirely (dedupe before touching disk).
            rec = outstanding_ids.get(sid)
            if rec is not None and rec["state"] == "CLAIMED":
                continue

            kind, obj = _read_json(p)
            if kind == "VANISHED":
                # F-H5-1: the file left this state mid-scan. A normal consumer claim
                # (pending -> claimed, atomic FileMove) or a terminal archive move are
                # both authoritative and MUST NOT be misread as a bridge failure.
                rkind, robj = _reconcile_vanished(paths, sid, state)
                if rkind == "TERMINAL":
                    continue                          # no longer outstanding; not counted
                if rkind == "CLAIMED":
                    eff_state, obj = "CLAIMED", robj  # normal ACK — count as claimed
                else:                                 # CORRUPT: unexplained disappearance
                    corrupt = corrupt or robj
                    outstanding_ids.setdefault(sid, {"state": state, "symbol": None})
                    continue
            elif kind == "CORRUPT":
                corrupt = corrupt or "{}:{}".format(obj, sid)
                outstanding_ids.setdefault(sid, {"state": state, "symbol": None})
                continue

            # reconcile may have upgraded PENDING -> CLAIMED; re-check dedupe so a
            # signal already counted as CLAIMED is not double-counted.
            rec = outstanding_ids.get(sid)
            if rec is not None and rec["state"] == "CLAIMED":
                continue
            symbol = obj.get("symbol")
            outstanding_ids[sid] = {"state": eff_state, "symbol": symbol}
            if symbol:
                outstanding_syms.add(symbol)
            # ACK liveness only applies to still-unclaimed (PENDING) intents; a CLAIMED
            # intent is acknowledged by the atomic claim.
            if eff_state == "PENDING":
                gen = serialize.parse_iso(obj.get("generated_timestamp"))
                exp = serialize.parse_iso(obj.get("expiration_timestamp"))
                if gen is None or exp is None:
                    corrupt = corrupt or "bad_timestamp:{}".format(sid)
                    continue
                if (gen - now).total_seconds() > 0:
                    future = future or "future_instruction:{}".format(sid)   # clock jump / forged
                    continue
                if now >= exp:                        # missed its own validity/ACK window
                    missing.append(sid)
                    age = (now - gen).total_seconds()
                    oldest_age = age if oldest_age is None else max(oldest_age, age)

    outstanding_count = len(outstanding_ids)
    outstanding_all_ids = tuple(sorted(outstanding_ids))
    if corrupt is not None:
        return _unhealthy(corrupt, outstanding_count=outstanding_count,
                          outstanding_symbols=outstanding_syms,
                          outstanding_signal_ids=outstanding_all_ids)
    if future is not None:
        return _unhealthy(future, outstanding_count=outstanding_count,
                          outstanding_symbols=outstanding_syms,
                          outstanding_signal_ids=outstanding_all_ids)

    return BridgeObservation(
        healthy=True, reason="", outstanding_count=outstanding_count,
        outstanding_symbols=tuple(sorted(outstanding_syms)),
        missing_ack_count=len(missing), oldest_unacked_age_sec=oldest_age,
        stale_signal_ids=tuple(sorted(missing)),
        outstanding_signal_ids=outstanding_all_ids)
