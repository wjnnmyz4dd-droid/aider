"""Read-only execution-outcome reconciliation (PR-1), sibling to the manage loop.

Observes signal_id-linked positions that have TRULY closed at the broker, reads
MT5 deal history through the read-only truth surface, computes a normalized
realized R deterministically from the IMMUTABLE entry / initial_stop, and writes
exactly ONE immutable ``execution_outcome`` memory record per signal_id.

NON-AUTHORITATIVE and NON-BLOCKING by construction:

  * it NEVER opens/closes/modifies a position, writes a bridge instruction, calls
    an EA/PM action, or otherwise touches trading — it only READS broker truth +
    the PM audit history and WRITES to the shared MemoryStore;
  * any failure is swallowed (fail-quiet) so trading is never delayed or changed;
  * it NEVER mistakes unavailable MT5 data for a close — an absent position is a
    candidate, but the close must be CONFIRMED by a netted-flat deal set;
  * it does not persist balance / equity / credentials — only the normalized R
    edge derived from immutable strategy facts and broker exit prices.

Restart-safe: candidate signal_ids come from the durable PM audit history (a
superset of the in-RAM PM cache), and signal_id-level idempotency is enforced
against already-stored outcomes, so a record is written at most once per signal.
"""

from __future__ import annotations

import math
import re

from ..bridge import serialize
from ..position import spec
from ..position.closure import confirm_full_close
from ..position.contract import _is_long, _is_short

# MT5 deal entry classification (READ-ONLY history semantics). Exit legs net the
# position toward flat; DEAL_ENTRY_INOUT (reversal) never occurs in this
# one-in-flight, no-reversal system and is deliberately not treated as an exit.
_ENTRY_IN = 0
_ENTRY_OUT = 1
_ENTRY_OUT_BY = 3
_EXITS = (_ENTRY_OUT, _ENTRY_OUT_BY)

_VOL_TOL = 1e-6          # lot reconciliation tolerance (min broker lot is 0.01)

OUTCOME_KIND = "execution_outcome"
OUTCOME_SOURCE = "outcome_reconciler"
OUTCOME_SCHEMA_VERSION = 1

# immutable facts required (from the PM audit history) to normalize an outcome
_REQUIRED = ("ticket", "symbol", "direction", "entry_price", "initial_stop")

# a production signal_id is sha256[:16]; anything else is not a real candidate
_SIGNAL_ID_RE = re.compile(r"^[0-9a-f]{16}$")


class OutcomeReconciler:
    """Read-only, non-blocking closed-trade outcome recorder. Injected alongside
    the ManagerService; owns no trading authority."""

    def __init__(self, truth, audit, memory, *, now_fn=None):
        self._truth = truth        # read-only broker truth (Mt5TruthSource)
        self._audit = audit        # PM audit history (read-only source of facts)
        self._memory = memory      # shared MemoryStore (the only write target)
        self._now = now_fn

    # -- one reconciliation pass -------------------------------------------
    def run(self, now=None):
        """One read-only pass. Returns the list of newly-written outcome dicts
        (possibly empty). Never raises for expected failures."""
        facts = self._known_signals()
        if not facts:
            return []
        if not self._connected():             # never infer a close when disconnected
            return []
        recorded = self._existing_outcomes()  # signal_id-level idempotency
        out = []
        for sid, f in facts.items():
            if sid in recorded:
                continue
            rec = self._reconcile_one(sid, f, now)
            if rec is not None:
                out.append(rec)
                recorded.add(sid)             # guard against duplicate facts in-pass
        return out

    # -- candidate discovery (durable, restart-safe) -----------------------
    def _known_signals(self):
        """Immutable facts per signal_id from the PM audit history — the durable
        superset that survives a manager restart.

        Read at the observational boundary with PER-RECORD fault isolation
        (OUT-1): a single malformed/torn audit line is skipped, and valid records
        before AND after it remain usable, so one corrupt line can never suppress
        reconciliation for otherwise-valid historical signals. Fields are only
        USED when well-formed — an invalid signal_id / ticket / price / direction
        is ignored, NEVER guessed from another record — so a corrupt record can
        never fabricate a candidate. Read-only."""
        facts = {}
        for r in self._audit_records():
            sid = r.get("signal_id")
            if not _valid_sid(sid):
                continue
            cur = facts.setdefault(sid, {})
            for k in _REQUIRED:                # immutable: first present value wins
                if cur.get(k) is None and r.get(k) is not None:
                    cur[k] = r.get(k)
        return {sid: f for sid, f in facts.items() if _facts_valid(f)}

    def _audit_records(self):
        """PM audit records with per-line tolerance. Prefers the durable file path
        exposed by the production ``PMAudit`` and parses each line independently
        (skipping malformed/torn/non-dict/non-finite lines); falls back to a test
        double's ``read_all()`` only when no path is exposed. Never raises."""
        path = getattr(self._audit, "path", None)
        if path is not None:
            return _read_audit_file(path)
        try:
            records = self._audit.read_all()
        except Exception:
            return []
        return [r for r in (records or []) if isinstance(r, dict)]

    def _existing_outcomes(self):
        try:
            rows = self._memory.query(kind=OUTCOME_KIND, limit=1_000_000)
        except Exception:
            return set()
        seen = set()
        for row in rows:
            sid = (row.get("content") or {}).get("signal_id")
            if sid:
                seen.add(sid)
        return seen

    # -- per-signal reconciliation -----------------------------------------
    def _reconcile_one(self, sid, f, now):
        ticket = f["ticket"]
        try:                                   # still open at the broker -> no outcome yet
            if self._truth.position_by_ticket(ticket) is not None:
                return None
        except Exception:
            return None
        deals = self._deals(ticket)
        if deals is None:                      # unavailable -> never infer a close
            return None
        close = self._closed_exit(deals)
        if close is None:                      # not a confirmed FULL close
            return None
        weighted_close, closed_volume, deal_count = close
        return self._write(sid, f, weighted_close, closed_volume, deal_count, now)

    def _deals(self, ticket):
        try:
            return self._truth.deals_for_position(ticket)
        except Exception:
            return None

    def _closed_exit(self, deals):
        """``(weighted_close, out_volume, deal_count)`` iff the deal set confirms a
        FULL netted-flat close, else None. Delegates to the single source of truth
        (``position.closure.confirm_full_close``) shared with the Position Manager."""
        return confirm_full_close(deals, entry_in=_ENTRY_IN, exits=_EXITS, tol=_VOL_TOL)

    # -- record construction + write ---------------------------------------
    def _write(self, sid, f, weighted_close, closed_volume, deal_count, now):
        direction = f["direction"]
        entry = _num(f["entry_price"])
        istop = _num(f["initial_stop"])
        symbol = f["symbol"]
        ticket = f["ticket"]
        R = spec.initial_risk(direction, entry, istop) \
            if (entry is not None and istop is not None) else None
        r_multiple = self._realized_r(direction, entry, weighted_close, R)
        if r_multiple is None:
            status, won = "R_UNDEFINED", None
        else:
            status, won = "CLOSED", bool(r_multiple > 0)
        content = {
            "schema_version": OUTCOME_SCHEMA_VERSION,
            "signal_id": sid,
            "status": status,
            "won": won,
            "taken": True,
            "r_multiple": r_multiple,
            "direction": direction,
            "symbol": symbol,
            "ticket": ticket,
            "broker_order_id": ticket,         # netting position id == position ticket
            "entry": entry,
            "initial_stop": istop,
            "weighted_close": weighted_close,
            "closed_volume": closed_volume,
            "deal_count": deal_count,
            "realized_r_source": "mt5_deal_history",
        }
        ts = self._timestamp(now)
        try:
            self._memory.write_raw(OUTCOME_KIND, symbol, content,
                                   source=OUTCOME_SOURCE, timestamp=ts,
                                   correlation_id=sid)
        except Exception:
            return None
        return content

    @staticmethod
    def _realized_r(direction, entry, weighted_close, R):
        """Normalized realized R from the IMMUTABLE entry/initial_stop and the
        broker exit. None (undefined) when R is invalid or a price is missing."""
        if R is None or entry is None or weighted_close is None:
            return None
        if _is_long(direction):
            return (weighted_close - entry) / R
        if _is_short(direction):
            return (entry - weighted_close) / R
        return None

    def _timestamp(self, now):
        if now is not None:
            return serialize.iso_utc(now)
        if self._now is not None:
            try:
                return serialize.iso_utc(self._now())
            except Exception:
                return ""
        return ""

    def _connected(self):
        try:
            return bool(self._truth.terminal_connected())
        except Exception:
            return False


def _num(v):
    """Coerce to a finite float, or None (rejects bool/NaN/Inf/non-numeric)."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if math.isfinite(v) else None
    return None


def _valid_sid(sid):
    """A well-formed production signal_id (sha256[:16]); anything else is ignored."""
    return isinstance(sid, str) and bool(_SIGNAL_ID_RE.match(sid))


def _facts_valid(f):
    """True iff every immutable fact is present AND well-typed — never fabricated.

    A finite-but-equal entry/initial_stop is intentionally allowed: that is the
    zero-risk R_UNDEFINED case, resolved deterministically downstream, not an
    invalid record. Malformed/implausible values (non-numeric price, unknown
    direction, non-int ticket, empty symbol) make the record ignorable so it can
    never fabricate an outcome."""
    ticket = f.get("ticket")
    symbol = f.get("symbol")
    direction = f.get("direction")
    return (isinstance(ticket, int) and not isinstance(ticket, bool)
            and isinstance(symbol, str) and bool(symbol)
            and (_is_long(direction) or _is_short(direction))
            and _num(f.get("entry_price")) is not None
            and _num(f.get("initial_stop")) is not None)


def _read_audit_file(path):
    """Read a JSONL audit log with PER-RECORD fault isolation: parse each line
    independently and skip malformed/torn/non-dict/non-finite lines, keeping every
    valid record on either side of the corruption. Missing file -> []. Never raises.
    Read-only — it never writes, truncates, or repairs the log."""
    out = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
    except FileNotFoundError:
        return out
    except Exception:
        return out
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        ok, rec = serialize.loads(raw)         # strict per-line; malformed -> skip
        if ok:
            out.append(rec)
    return out
