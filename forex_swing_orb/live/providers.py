"""Live MT5-backed providers (Phase 8A) — READ-ONLY adapters.

They normalize live MT5 data into the accepted repository contracts and contain
NO trading logic: they never place trades, modify stops, generate signals,
compute strategy, or make compliance decisions. They fail closed on missing /
malformed / disconnected data. Forex-only. No HTTP / socket / scraping — the only
external integration is the injected MT5 client (see ``mt5_client``).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..bridge import serialize
from ..compliance import mapping
from ..producer.providers import (AccountStateProvider, Bars, BrokerHealthProvider,
                                  MarketDataProvider, NewsDataProvider)
from . import mt5_client as mc


# --------------------------------------------------------------------------- #
# Canonical <-> broker symbol mapping (Forex-only)
# --------------------------------------------------------------------------- #
class SymbolMap:
    def __init__(self, suffix=""):
        self.suffix = suffix

    def to_broker(self, canonical):
        core = mapping.strip_fx(canonical)
        return (core + self.suffix) if core else ""

    def to_canonical(self, broker):
        core = broker[:-len(self.suffix)] if self.suffix and broker.endswith(self.suffix) else broker
        return core + ".FX"

    def is_supported(self, canonical):
        return mapping.is_forex_symbol(canonical)


# --------------------------------------------------------------------------- #
# Daily-anchor bookkeeping (capture-at-rollover; NOT a calculation/decision)
# --------------------------------------------------------------------------- #
class DailyAnchorTracker:
    """M2/M3/H2: persists the day-start BALANCE and day-start EQUITY captured at the
    first snapshot of each FTMO trading day (00:00 Europe/Prague, DST-aware).
    Balance excludes floating P/L; equity includes it. FTMO's daily-loss reference
    is the higher of the two. Idempotent per day; conflict-detected via integrity
    digest; survives restart.

    PR-3A.2 — a new day's anchor may be first-captured ONLY when this process
    provably observed the trading-day rollover: the immediately-preceding
    observation THIS run belonged to an earlier Prague trading day AND the elapsed
    UTC gap between the two observations is within one producer cadence (+ bounded
    scheduler jitter). Clock proximity to midnight is NOT proof — a fresh cold-start
    process, a stalled/slept/disconnected process, and a backwards/forward host-clock
    jump can never label current account state as historical day-start state; they
    FAIL CLOSED. First-writer-wins across concurrent producers via an atomic per-day
    hardlink claim (bridge.atomic.atomic_claim)."""

    # Distinct fail-closed diagnostics (operator-facing; no secrets).
    R_COLD_START = "no_valid_anchor_cold_start"          # fresh process, rollover not observed
    R_MISSED_ROLLOVER = "anchor_missed_rollover_stall"    # gap too large (stall/sleep/multi-day/fwd-jump)
    R_CLOCK_BACKWARDS = "anchor_clock_backwards"          # non-monotonic / backwards host clock
    R_CLOCK_INVALID = "anchor_clock_invalid"              # naive / non-tz-aware instant
    R_CONCURRENT = "anchor_concurrent_writer_conflict"    # lost the atomic claim, winner unreadable
    R_LEGACY = "anchor_legacy_incomplete"                # reused anchor lacks day_start_equity

    # Cold-start BROKER-HISTORY reconstruction diagnostics (observational detail; the
    # producer-level blocker stays R_ACCOUNT_ANCHOR_UNAVAILABLE). Each marks a case
    # where the mid-day anchor could NOT be proven from authoritative broker history.
    R_RECON_HISTORY_UNAVAILABLE = "recon_history_unavailable"     # range query returned None
    R_RECON_HISTORY_INCOMPLETE = "recon_history_incomplete"       # window does not cover midnight
    R_RECON_UNKNOWN_EVENT = "recon_unknown_balance_event"         # deal.type outside KNOWN set
    R_RECON_TIMEBASE = "recon_timebase_unverified"               # naive/future/malformed deal time
    R_RECON_OPEN_SPANS_MIDNIGHT = "recon_open_position_spans_midnight"  # equity != balance, unprovable
    R_RECON_NONFINITE = "recon_nonfinite_value"                  # NaN/inf balance or result
    R_RECON_IDENTITY = "recon_account_identity_mismatch"          # evidence account != expected
    R_RECON_NO_EVIDENCE = "recon_evidence_unavailable"           # cold start but no evidence source

    # Anchor provenance (observational metadata; compliance consumes the value the same
    # way regardless of source). NOT a second authority.
    SOURCE_LIVE_ROLLOVER = "LIVE_ROLLOVER"
    SOURCE_BROKER_HISTORY = "BROKER_HISTORY_RECONSTRUCTION"

    def __init__(self, path, reset_timezone="Europe/Prague", cadence_sec=900):
        self.path = path
        self.reset_timezone = reset_timezone
        # Single authoritative production cadence (RuntimeConfig.cadence_sec, default
        # 900s = one M15 bar). A healthy producer observes once per cadence, so the
        # FIRST observation of a new trading day must fall within ~one cadence of its
        # last prior-day observation. A bounded jitter allowance covers scheduler
        # slack + per-tick processing, but the total stays STRICTLY below 2x cadence
        # so a single MISSED observation (stall/disconnect/clock jump) is rejected
        # rather than allowed to anchor a materially late account state.
        self.cadence_sec = float(cadence_sec) if cadence_sec and cadence_sec > 0 else 900.0
        self.max_rollover_gap_sec = self.cadence_sec + min(self.cadence_sec * 0.5, 120.0)
        self._last_seen = None          # in-memory: last trading_day observed THIS run
        self._last_seen_ts = None       # in-memory: UTC instant of that observation
        self._records = {}          # trading_day -> anchor record
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                ok, obj = serialize.loads(f.read())
            if ok:
                self._records = dict(obj.get("records", {}))
        except FileNotFoundError:
            pass

    def _trading_day(self, now):
        from ..compliance.contract import prague_trading_day
        return prague_trading_day(now, self.reset_timezone)

    def _observed_rollover(self, prev_seen, prev_ts, tday, now):
        """Return (ok, reason). ``ok`` iff this process provably observed the
        trading-day rollover into ``tday`` within the permitted observation gap.
        Clock proximity to midnight is deliberately NOT considered."""
        # Cold start: no prior observation THIS run (or the prior one was the same
        # trading day and never produced a record) -> cannot prove a rollover.
        if prev_seen is None or prev_ts is None or prev_seen == tday:
            return False, self.R_COLD_START
        # Both instants must be tz-aware for a sound elapsed-UTC calculation.
        if now is None or now.tzinfo is None or prev_ts.tzinfo is None:
            return False, self.R_CLOCK_INVALID
        # Non-monotonic / backwards host clock: current instant not after the prior,
        # or the "previous" trading day is not earlier than the current one.
        if (now - prev_ts).total_seconds() <= 0 or prev_seen > tday:
            return False, self.R_CLOCK_BACKWARDS
        # Bounded observation gap: a stalled/slept/disconnected process, a large
        # forward clock jump, or a multi-day (e.g. weekend) gap all exceed one
        # cadence and must NOT anchor a late account state.
        if (now - prev_ts).total_seconds() > self.max_rollover_gap_sec:
            return False, self.R_MISSED_ROLLOVER
        return True, None

    def _claim_path(self, tday):
        p = Path(self.path)
        return p.parent / (p.name + "." + tday + ".claim")

    def _load_claim(self, tday):
        try:
            with open(self._claim_path(tday), "r", encoding="utf-8") as f:
                ok, obj = serialize.loads(f.read())
            return obj if ok and isinstance(obj, dict) else None
        except (FileNotFoundError, OSError):
            return None

    def record(self, now, balance, *, equity=None, initial_balance=None,
               daily_loss_pct=None, account_id=None, profile_id=None,
               source_snapshot_id=None, safety_buffer_fraction=0.20,
               cold_start_evidence_fn=None):
        """Return the anchor record for the current Prague trading day, capturing
        the day-start BALANCE and day-start EQUITY on first sight (H2: FTMO's daily
        reference is the higher of the two). Idempotent; flags conflict on tamper."""
        tday = self._trading_day(now)
        if tday is None:
            return None                                # naive/tz-unloadable -> caller fails closed
        prev_seen, prev_ts = self._last_seen, self._last_seen_ts
        self._last_seen, self._last_seen_ts = tday, now   # remember for the next call (this run)
        existing = self._records.get(tday)
        if existing is not None:
            # idempotent; verify integrity (tamper/conflict detection). Reused as-is
            # on a mid-day restart (never recaptured from current account state).
            if not _digest_ok(existing):
                existing = dict(existing); existing["daily_anchor_conflict"] = True
                return existing
            # PR-3A.1: a legacy/incomplete anchor (no day_start_equity) is preserved
            # verbatim on disk but flagged so the operator diagnostic is distinct; it
            # remains non-authorizable downstream (ftmo_levels fails closed).
            if existing.get("day_start_equity") is None:
                existing = dict(existing); existing["anchor_reason"] = self.R_LEGACY
            return existing
        # P3A1-1/P3A1-2: first-capture a NEW day anchor ONLY when this process
        # provably observed the rollover within one producer cadence. Otherwise FAIL
        # CLOSED: never invent day-start balance/equity from a cold-start snapshot or
        # a materially late (stalled) observation.
        ok, reason = self._observed_rollover(prev_seen, prev_ts, tday, now)
        if ok:
            return self._first_write_anchor(
                now, prev_ts, tday, balance, equity, initial_balance, daily_loss_pct,
                account_id, profile_id, source_snapshot_id, safety_buffer_fraction,
                source=self.SOURCE_LIVE_ROLLOVER)
        # PR-3A.3 cold-start recovery: the live rollover was NOT observed this run
        # (fresh install / reboot / outage / mid-day cold start). If the caller supplied
        # a READ-ONLY broker-history evidence source, attempt a conservative,
        # deterministic reconstruction of today's anchor. It NEVER uses current
        # balance/equity/initial/yesterday as the anchor: it recomputes the Prague-
        # midnight balance from complete deal history and accepts the anchor ONLY when
        # the book was PROVABLY flat at midnight (so equity == balance). Any gap in the
        # proof fails closed with a specific reason. It never overwrites an existing
        # anchor (handled above) and uses the same first-writer atomic claim.
        if cold_start_evidence_fn is None:
            return {"trading_day": tday, "anchor_unavailable": True,
                    "anchor_reason": reason}
        rec = self._reconstruct_cold_start(
            now, tday, cold_start_evidence_fn, initial_balance, daily_loss_pct,
            account_id, profile_id, source_snapshot_id, safety_buffer_fraction)
        return rec

    def _first_write_anchor(self, now, prev_ts, tday, balance, equity,
                            initial_balance, daily_loss_pct, account_id, profile_id,
                            source_snapshot_id, safety_buffer_fraction,
                            source=SOURCE_LIVE_ROLLOVER, provenance=None):
        """Build the schema-v2 anchor and persist it with FIRST-WRITER-WINS semantics
        (P3A1-3). The per-day hardlink claim is atomic and only ever fully-written, so
        the first producer to observe the rollover (or prove the cold-start
        reconstruction) establishes the authoritative anchor; a concurrent producer
        reads and reuses it (never overwrites it). ``source`` records provenance
        (observational metadata only); the value is consumed identically regardless."""
        from zoneinfo import ZoneInfo
        rec = {
            "anchor_schema_version": 2,        # complete format: balance + equity
            "profile_id": profile_id, "account_id": account_id,
            "trading_day": tday, "timezone": self.reset_timezone,
            "anchor_source": source,           # LIVE_ROLLOVER | BROKER_HISTORY_RECONSTRUCTION
            "anchor_timestamp_utc": serialize.iso_utc(now),
            "anchor_timestamp_prague": now.astimezone(ZoneInfo(self.reset_timezone)).strftime("%Y-%m-%dT%H:%M:%S"),
            # rollover-observation evidence (P3A1-2 audit trail): the prior-day
            # observation and the measured gap that authorized this capture.
            "prev_observation_utc": (serialize.iso_utc(prev_ts) if prev_ts is not None else None),
            "observation_gap_sec": ((now - prev_ts).total_seconds() if prev_ts is not None else None),
            "max_observation_gap_sec": self.max_rollover_gap_sec,
            "day_start_balance": float(balance),
            "day_start_equity": (float(equity) if equity is not None else None),
            "initial_balance": (float(initial_balance) if initial_balance is not None else None),
            "daily_loss_pct": daily_loss_pct,
            "official_loss_amount": (daily_loss_pct * initial_balance
                                     if (daily_loss_pct and initial_balance) else None),
            "internal_loss_amount": (daily_loss_pct * initial_balance * (1 - safety_buffer_fraction)
                                     if (daily_loss_pct and initial_balance) else None),
            "source_snapshot_id": source_snapshot_id,
            # cold-start reconstruction provenance (None for live capture): history
            # window, event count, algorithm version — observational audit only.
            "reconstruction": provenance,
        }
        rec["integrity_digest"] = serialize.compute_integrity_digest(rec)
        return self._finalize(tday, rec)

    def _finalize(self, tday, rec):
        """Atomically publish ``rec`` (first-writer-wins) and return the authoritative
        record. A losing writer reuses the winner; an unreadable claim fails closed."""
        won = self._claim_day(tday, rec)
        if won:
            self._records[tday] = rec
            self._sync_aggregate()
            return rec
        # Lost the atomic claim: another producer established this day's anchor first.
        winner = self._load_claim(tday)
        if winner is not None and _digest_ok(winner):
            self._records[tday] = winner
            self._sync_aggregate()
            return winner
        # Claim exists but is unreadable/invalid -> fail closed (never overwrite).
        return {"trading_day": tday, "anchor_unavailable": True,
                "anchor_reason": self.R_CONCURRENT}

    def _reconstruct_cold_start(self, now, tday, evidence_fn, initial_balance,
                                daily_loss_pct, account_id, profile_id,
                                source_snapshot_id, safety_buffer_fraction):
        """Cold-start reconstruction of today's anchor from authoritative broker
        history. Returns the authoritative record on success, or an ``anchor_
        unavailable`` dict with a specific reason on any failure (fail closed)."""
        try:
            evidence = evidence_fn()
        except Exception:                              # noqa: BLE001 - never raise upward
            evidence = None
        fields, reason = reconstruct_cold_start_anchor(
            tday=tday, now=now, evidence=evidence, expected_account_id=account_id)
        if fields is None:
            return {"trading_day": tday, "anchor_unavailable": True,
                    "anchor_reason": reason}
        return self._first_write_anchor(
            now, None, tday, fields["day_start_balance"],
            fields["day_start_equity"], initial_balance, daily_loss_pct, account_id,
            profile_id, source_snapshot_id, safety_buffer_fraction,
            source=self.SOURCE_BROKER_HISTORY, provenance=fields["provenance"])

    def _claim_day(self, tday, rec):
        """Atomically publish ``rec`` as the day's anchor iff no claim exists yet.
        Returns True iff this caller won (created) the claim. Uses the bridge's
        hardlink claim so the visible claim file is always complete (never partial)."""
        import os
        from ..bridge.atomic import atomic_claim
        claim = self._claim_path(tday)
        tmp = claim.parent / ("." + claim.name + ".tmp.%d" % os.getpid())
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(serialize.canonical_json(rec))
                f.flush()
                os.fsync(f.fileno())
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            return False
        won = atomic_claim(tmp, claim)     # hardlink+unlink; False if already claimed
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return won

    def _sync_aggregate(self):
        """Persist the in-memory records to the aggregate file for restart-reuse. The
        per-day claim files remain the authoritative concurrency guard; the aggregate
        is a convenience cache, re-merged on each write to avoid clobbering peers."""
        from ..bridge.atomic import atomic_write_text
        merged = {}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                ok, obj = serialize.loads(f.read())
            if ok and isinstance(obj.get("records"), dict):
                merged.update(obj["records"])
        except (FileNotFoundError, OSError):
            pass
        merged.update(self._records)
        atomic_write_text(self.path, serialize.canonical_json({"records": merged}))


def _digest_ok(rec):
    claimed = rec.get("integrity_digest")
    body = {k: v for k, v in rec.items() if k != "integrity_digest"}
    return isinstance(claimed, str) and claimed == serialize.compute_integrity_digest(body)


def _finite(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def reconstruct_cold_start_anchor(*, tday, now, evidence, expected_account_id=None):
    """PURE, deterministic cold-start anchor reconstruction from authoritative broker
    deal history. Returns ``(fields, None)`` on success or ``(None, reason)`` on any
    failure (fail closed). NEVER uses current balance/equity/initial/yesterday as the
    anchor: it recomputes the Prague-midnight BALANCE as

        day_start_balance = current_balance
                          - Σ_{deal.time >= midnight}(profit + commission + swap + fee)

    (balance is a step function changed only by deals; every balance-affecting deal
    encodes its delta in those four fields). It accepts the anchor ONLY when the book
    was PROVABLY FLAT at Prague midnight, in which case day_start_equity == day_start_
    balance (no floating P/L to reconstruct). Historical floating P/L at a past instant
    is NOT recoverable from broker history, so any position open across midnight (or any
    unprovable case) FAILS CLOSED — the daily-loss equity reference is never approximated.

    ``evidence`` (all read-only, gathered by the account provider):
      history_ok, current_balance, midnight_utc, history_from_utc, account_id,
      deals=[{time,type,entry,profit,commission,swap,fee,position_id}],
      open_positions=[{position_id,open_time}].
    """
    R = DailyAnchorTracker
    if not isinstance(evidence, dict):
        return None, R.R_RECON_NO_EVIDENCE
    if not evidence.get("history_ok"):
        return None, R.R_RECON_HISTORY_UNAVAILABLE
    midnight = evidence.get("midnight_utc")
    hist_from = evidence.get("history_from_utc")
    # every instant must be tz-aware UTC; now strictly after midnight (mid-day start)
    for inst in (now, midnight, hist_from):
        if inst is None or getattr(inst, "tzinfo", None) is None:
            return None, R.R_RECON_TIMEBASE
    if (now - midnight).total_seconds() <= 0:
        return None, R.R_RECON_TIMEBASE
    # the fetched window MUST start at/before midnight to prove coverage of the boundary
    if (midnight - hist_from).total_seconds() < 0:
        return None, R.R_RECON_HISTORY_INCOMPLETE
    ev_acct = evidence.get("account_id")
    if (expected_account_id is not None and ev_acct is not None
            and ev_acct != expected_account_id):
        return None, R.R_RECON_IDENTITY
    cur_bal = _finite(evidence.get("current_balance"))
    if cur_bal is None:
        return None, R.R_RECON_NONFINITE
    deals = evidence.get("deals")
    if deals is None:
        return None, R.R_RECON_HISTORY_UNAVAILABLE

    net = 0.0
    opened_today = set()        # position_ids with an IN trade leg at time >= midnight
    closed_after = []           # position_ids with an OUT trade leg at time >= midnight
    future_skew = 120.0
    for d in deals:
        t = d.get("time")
        if t is None or getattr(t, "tzinfo", None) is None:
            return None, R.R_RECON_TIMEBASE
        if (t - now).total_seconds() > future_skew:          # deal after 'now' -> bad clock/data
            return None, R.R_RECON_TIMEBASE
        dtype = d.get("type")
        if dtype not in mc.KNOWN_DEAL_TYPES:                  # unknown broker balance event
            return None, R.R_RECON_UNKNOWN_EVENT
        at_or_after = (t - midnight).total_seconds() >= 0
        if at_or_after:
            for f in ("profit", "commission", "swap", "fee"):
                fv = _finite(d.get(f, 0.0))
                if fv is None:
                    return None, R.R_RECON_NONFINITE
                net += fv
            if dtype in (mc.DEAL_TYPE_BUY, mc.DEAL_TYPE_SELL):   # trade legs carry position semantics
                entry = d.get("entry")
                pid = d.get("position_id")
                if entry == mc.DEAL_ENTRY_IN:
                    opened_today.add(pid)
                elif entry == mc.DEAL_ENTRY_OUT:
                    closed_after.append(pid)
                else:                                            # reversal / out_by -> unprovable
                    return None, R.R_RECON_OPEN_SPANS_MIDNIGHT
    day_start_balance = _finite(cur_bal - net)
    if day_start_balance is None or day_start_balance <= 0:
        return None, R.R_RECON_NONFINITE

    # Flat-book-at-midnight proof (equity == balance only if nothing was open then):
    #   * no currently-open position that opened before midnight, AND
    #   * every position that CLOSED after midnight also OPENED after midnight
    #     (its IN leg is in-window at time >= midnight). A close-after-midnight whose
    #     open is before/outside the window means it was open at midnight -> fail.
    for p in (evidence.get("open_positions") or []):
        ot = p.get("open_time")
        if ot is None or getattr(ot, "tzinfo", None) is None:
            return None, R.R_RECON_TIMEBASE
        if (ot - midnight).total_seconds() < 0:
            return None, R.R_RECON_OPEN_SPANS_MIDNIGHT
    for pid in closed_after:
        if pid not in opened_today:
            return None, R.R_RECON_OPEN_SPANS_MIDNIGHT

    provenance = {
        "algorithm_version": 1,
        "history_from_utc": serialize.iso_utc(hist_from),
        "history_to_utc": serialize.iso_utc(now),
        "prague_midnight_utc": serialize.iso_utc(midnight),
        "event_count": len(deals),
        "net_balance_change_since_midnight": net,
        "flat_book_at_midnight": True,
    }
    return ({"day_start_balance": day_start_balance,
             "day_start_equity": day_start_balance,     # provably flat -> equity == balance
             "provenance": provenance}, None)


# --------------------------------------------------------------------------- #
# Market data
# --------------------------------------------------------------------------- #
class Mt5MarketDataProvider(MarketDataProvider):
    def __init__(self, client, symbol_map=None, history=300):
        self.client = client
        self.map = symbol_map or SymbolMap()
        self.history = history

    def get_bars(self, symbol, timeframe, now):
        if not self.map.is_supported(symbol):        # Forex-only; reject unsupported
            return None
        broker = self.map.to_broker(symbol)
        raw = self.client.copy_rates_from_pos(broker, timeframe, 0, self.history + 1)
        if not raw:
            return None
        # drop the forming (current) bar -> closed bars only
        closed = list(raw)[:-1]
        rows = []
        for r in closed:
            t = r["time"] if not hasattr(r, "time") else r.time
            rows.append({
                "open_time": datetime.fromtimestamp(int(t), tz=timezone.utc),
                "open": float(r["open"]), "high": float(r["high"]),
                "low": float(r["low"]), "close": float(r["close"])})
        if not rows:
            return None
        return Bars(symbol, timeframe, rows)


# --------------------------------------------------------------------------- #
# Account state
# --------------------------------------------------------------------------- #
class Mt5AccountStateProvider(AccountStateProvider):
    _TRADE_MODE = {mc.ACCOUNT_TRADE_MODE_DEMO: "DEMO",
                   mc.ACCOUNT_TRADE_MODE_CONTEST: "CONTEST",
                   mc.ACCOUNT_TRADE_MODE_REAL: "REAL"}

    def __init__(self, client, *, initial_balance, anchor_tracker, symbol_map=None,
                 daily_loss_pct=0.05):
        self.client = client
        self.initial_balance = float(initial_balance)   # operator config (FTMO funded balance)
        self.anchor = anchor_tracker
        self.map = symbol_map or SymbolMap()
        self.daily_loss_pct = daily_loss_pct            # FTMO 2-Step: 5% of initial

    def snapshot(self, now):
        ai = self.client.account_info()
        if ai is None:
            return None                                 # fail closed
        ti = self.client.terminal_info()
        connected = getattr(ti, "connected", None) if ti is not None else None
        positions = self.client.positions_get() or ()
        balance = float(ai.balance)
        equity = float(ai.equity)
        # PR-3A.3: a READ-ONLY broker-history evidence source for cold-start anchor
        # reconstruction. Built lazily — the tracker invokes it ONLY on a mid-day cold
        # start (no existing anchor, rollover not observed), never on a normal cycle, so
        # there is no per-cycle history-fetch overhead. It fetches nothing but history;
        # it never trades. Correctness of the reconstruction depends on the system-wide
        # B2 UTC-timebase invariant (deal/position times in UTC), validated separately.
        def _cold_start_evidence():
            return self._cold_start_evidence(now, ai, balance, positions)
        # M3/H2: anchor day-start BALANCE and EQUITY at the Prague rollover; on a mid-day
        # cold start, reconstruct from authoritative broker history if provable.
        rec = self.anchor.record(now, balance, equity=equity,
                                 initial_balance=self.initial_balance,
                                 daily_loss_pct=self.daily_loss_pct,
                                 account_id=getattr(ai, "login", None),
                                 cold_start_evidence_fn=_cold_start_evidence)
        if rec is None:
            return None                                 # tz unloadable -> fail closed
        return {
            "balance": balance,
            "current_balance": balance,
            "equity": equity,
            "initial_balance": self.initial_balance,
            "day_start_balance": rec.get("day_start_balance"),   # M3: balance anchor
            "day_start_equity": rec.get("day_start_equity"),      # H2: equity anchor
            "trading_day": rec["trading_day"],
            # P3A-1: explicit flag when no valid rollover anchor exists (mid-day cold
            # start) -> the account validation fails closed with a clear reason.
            "daily_anchor_unavailable": bool(rec.get("anchor_unavailable")),
            "daily_anchor_reason": rec.get("anchor_reason"),
            "daily_anchor_conflict": bool(rec.get("daily_anchor_conflict")),
            # PR-3A.3 provenance (observational only): LIVE_ROLLOVER vs
            # BROKER_HISTORY_RECONSTRUCTION; compliance consumes the value identically.
            "daily_anchor_source": rec.get("anchor_source"),
            "anchor_snapshot_id": rec.get("integrity_digest"),
            "floating_pl": float(getattr(ai, "profit", 0.0)),
            "swaps": sum(float(getattr(p, "swap", 0.0) or 0.0) for p in positions),
            "commissions": sum(float(getattr(p, "commission", 0.0) or 0.0) for p in positions),
            "open_risk_at_stop": self._open_risk(positions),
            "open_position_count": len(positions),
            "open_symbols": tuple(sorted(self.map.to_canonical(p.symbol) for p in positions)),
            "terminal_connected": connected,
            "as_of": serialize.iso_utc(now),
            "is_demo": (getattr(ai, "trade_mode", None) == mc.ACCOUNT_TRADE_MODE_DEMO),
            "account_type": self._TRADE_MODE.get(getattr(ai, "trade_mode", None), "UNKNOWN"),
            "account_currency": getattr(ai, "currency", None),
            "leverage": getattr(ai, "leverage", None),
            "margin": float(getattr(ai, "margin", 0.0)),
            "margin_free": float(getattr(ai, "margin_free", 0.0)),
            "margin_level": float(getattr(ai, "margin_level", 0.0)),
        }

    # Generous history margin BEFORE Prague midnight so recent position-open (IN) legs
    # are visible for the flat-book proof. A larger margin is strictly safer (more
    # evidence); reconstruction fails closed whenever an IN leg is missing regardless.
    COLD_START_HISTORY_MARGIN_SEC = 7 * 24 * 3600

    def _cold_start_evidence(self, now, ai, balance, positions):
        """READ-ONLY evidence for cold-start anchor reconstruction. Returns the
        normalized evidence dict, or ``{"history_ok": False}`` when the range query is
        rejected (-> the tracker fails closed). Fetches history only; never trades."""
        from zoneinfo import ZoneInfo
        try:
            prague = ZoneInfo(self.anchor.reset_timezone)
            now_local = now.astimezone(prague)
            midnight_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
            midnight_utc = midnight_local.astimezone(timezone.utc)
        except Exception:                               # noqa: BLE001 - tz unloadable
            return {"history_ok": False}
        hist_from = midnight_utc - timedelta(seconds=self.COLD_START_HISTORY_MARGIN_SEC)
        raw = None
        try:
            raw = self.client.history_deals_range(hist_from, now)
        except Exception:                               # noqa: BLE001 - query error -> unknown
            raw = None
        if raw is None:
            return {"history_ok": False}
        deals = []
        for d in raw:
            ts = int(getattr(d, "time", 0) or 0)
            deals.append({
                "time": datetime.fromtimestamp(ts, tz=timezone.utc),
                "type": int(getattr(d, "type", -1)),
                "entry": int(getattr(d, "entry", -1)),
                "profit": getattr(d, "profit", 0.0),
                "commission": getattr(d, "commission", 0.0),
                "swap": getattr(d, "swap", 0.0),
                "fee": getattr(d, "fee", 0.0),
                "position_id": getattr(d, "position_id", 0),
            })
        open_positions = []
        for p in (positions or ()):
            pt = int(getattr(p, "time", 0) or 0)
            open_positions.append({
                "position_id": getattr(p, "ticket", getattr(p, "identifier", 0)),
                "open_time": datetime.fromtimestamp(pt, tz=timezone.utc),
            })
        return {"history_ok": True, "current_balance": balance,
                "midnight_utc": midnight_utc, "history_from_utc": hist_from,
                "account_id": getattr(ai, "login", None),
                "deals": deals, "open_positions": open_positions}

    def _open_risk(self, positions):
        """Worst-case equity drop if every open position hits its stop (money from
        CURRENT price to SL). Aggregation of broker fields; no strategy/decision."""
        total = 0.0
        for p in positions:
            sl = float(getattr(p, "sl", 0.0) or 0.0)
            if sl <= 0:
                continue
            cur = float(getattr(p, "price_current", 0.0) or 0.0)
            vol = float(getattr(p, "volume", 0.0) or 0.0)
            si = self.client.symbol_info(p.symbol)
            tick_size = float(getattr(si, "trade_tick_size", 0.0) or 0.0) if si else 0.0
            tick_value = float(getattr(si, "trade_tick_value", 0.0) or 0.0) if si else 0.0
            if p.type == mc.POSITION_TYPE_BUY:
                dist = max(0.0, cur - sl)
            else:
                dist = max(0.0, sl - cur)
            if tick_size > 0 and tick_value > 0:
                total += (dist / tick_size) * tick_value * vol
            else:
                total += dist * vol                     # degraded fallback
        return total


# --------------------------------------------------------------------------- #
# Broker health
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class BrokerHealthConfig:
    max_spread_points: float = 30.0
    max_slippage_points: float = 15.0
    max_quote_age_sec: float = 30.0


class Mt5BrokerHealthProvider(BrokerHealthProvider):
    def __init__(self, client, cfg=None, symbol_map=None, missing_ack_count=0,
                 slippage_source=None):
        self.client = client
        self.cfg = cfg or BrokerHealthConfig()
        self.map = symbol_map or SymbolMap()
        self._missing_ack_count = missing_ack_count
        # optional broker-derived recent-slippage observation (Phase 8D, item 8);
        # object exposing recent_points(symbol, now, point) -> float | None.
        self._slippage_source = slippage_source

    def snapshot(self, symbol, now):
        broker = self.map.to_broker(symbol)
        si = self.client.symbol_info(broker)
        if si is None:
            return None                                 # fail closed
        ti = self.client.terminal_info()
        connected = bool(getattr(ti, "connected", False)) if ti is not None else False
        point = float(getattr(si, "point", 0.0) or 0.0)
        qt = getattr(si, "time", 0) or 0
        quote_age = ((now - datetime.fromtimestamp(int(qt), tz=timezone.utc)).total_seconds()
                     if qt else self.cfg.max_quote_age_sec + 1)   # missing quote time -> stale
        stop_level_pts = float(getattr(si, "trade_stops_level", 0.0) or 0.0)
        slippage_points = self._recent_slippage(symbol, now, point)
        if slippage_points is None:
            return None                                 # configured source failed -> fail closed
        return {
            "terminal_connected": connected,
            "bridge_healthy": True,                     # bridge health is supplied by the runner side
            "spread_points": float(getattr(si, "spread", 0.0) or 0.0),
            "max_spread_points": self.cfg.max_spread_points,
            "recent_slippage_points": slippage_points,  # broker-derived (ENTER fills) or 0.0 if none
            "max_slippage_points": self.cfg.max_slippage_points,
            "missing_ack_count": self._missing_ack_count,
            "quote_age_sec": quote_age,
            "max_quote_age_sec": self.cfg.max_quote_age_sec,
            # market-gate fields
            "symbol_tradable": bool(getattr(si, "visible", True)) and self.map.is_supported(symbol),
            "market_open": connected and (getattr(si, "trade_mode", None) == mc.SYMBOL_TRADE_MODE_FULL),
            # broker constraints (normalized)
            "point": point,
            "digits": int(getattr(si, "digits", 0) or 0),
            "freeze_level": float(getattr(si, "trade_freeze_level", 0.0) or 0.0),
            "stop_level": stop_level_pts,
            "tick_size": float(getattr(si, "trade_tick_size", 0.0) or 0.0),
            "tick_value": float(getattr(si, "trade_tick_value", 0.0) or 0.0),
            "broker_min_stop_distance": stop_level_pts * point,
            # M9: per-symbol volume constraints for the upstream sizing authority.
            "volume_min": float(getattr(si, "volume_min", 0.0) or 0.0),
            "volume_max": float(getattr(si, "volume_max", 0.0) or 0.0),
            "volume_step": float(getattr(si, "volume_step", 0.0) or 0.0),
        }

    def _recent_slippage(self, symbol, now, point):
        """Broker-derived recent slippage in points. Without a configured source,
        report 0.0 (no observation). With a source, return its value or None (a
        source that cannot produce a trustworthy value fails the snapshot closed)."""
        if self._slippage_source is None:
            return 0.0
        try:
            return self._slippage_source.recent_points(symbol, now, point)
        except Exception:
            return None


# --------------------------------------------------------------------------- #
# News (file-backed normalized bundle; no HTTP/scraping)
# --------------------------------------------------------------------------- #
class FileNewsDataProvider(NewsDataProvider):
    """Reads an operator-/approved-adapter-maintained normalized calendar file and
    returns the frozen NewsBundle. Fail closed on missing/malformed. The file IS
    the lawful source boundary — this provider fetches nothing."""

    def __init__(self, path):
        self.path = path

    def bundle(self, now):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                ok, obj = serialize.loads(f.read())
        except (FileNotFoundError, OSError):
            return None
        if not ok or not isinstance(obj.get("events"), list):
            return None
        return obj
