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

from ..bridge import serialize
from ..position import spec
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
        superset that survives a manager restart. Read-only; malformed history or
        an unreadable log yields no candidates (fail closed)."""
        try:
            records = self._audit.read_all()
        except Exception:
            return {}
        facts = {}
        for r in records:
            sid = r.get("signal_id")
            if not isinstance(sid, str) or not sid:
                continue
            cur = facts.setdefault(sid, {})
            for k in _REQUIRED:                # immutable: first non-null wins
                if cur.get(k) is None and r.get(k) is not None:
                    cur[k] = r.get(k)
        return {sid: f for sid, f in facts.items()
                if all(f.get(k) is not None for k in _REQUIRED)}

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
        FULL close — an entry leg, one or more exit legs, netted flat — else None.
        The exit price is volume-weighted across any partial closes; requiring both
        an IN and matching OUT volume guards against a partial history snapshot
        being mistaken for a completed round trip."""
        in_vol = out_vol = notional = 0.0
        n = 0
        for d in deals:
            n += 1
            entry = getattr(d, "entry", None)
            vol = _num(getattr(d, "volume", None))
            price = _num(getattr(d, "price", None))
            if vol is None:
                continue
            if entry == _ENTRY_IN:
                in_vol += vol
            elif entry in _EXITS and price is not None:
                out_vol += vol
                notional += price * vol
        if in_vol <= 0 or out_vol <= 0:        # need both sides of a round trip
            return None
        if abs(in_vol - out_vol) > _VOL_TOL:   # not netted flat -> still partial, hold
            return None
        return notional / out_vol, out_vol, n

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
