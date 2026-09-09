"""Deterministic compliance gates (Phase 5C).

Each gate is a pure function returning a :class:`GateVerdict`. No wall clock (the
UTC ``now`` is injected), no RNG, no networking. Every gate fails closed: any
missing / malformed / non-finite input yields a REJECT with an explicit reason
code (never a generic failure, never fail-open).
"""

from __future__ import annotations

from . import mapping, sizing
from .contract import (GateVerdict, ReasonCode, Stage, candidate_risk_amount,
                       finite, ftmo_levels, prague_trading_day)

_DIRECTIONS = ("LONG", "SHORT")
_MTF_KEYS = ("daily_bias", "h4_structure", "h1_setup", "m15_timing", "aligned")


def _ok(stage, evidence=None):
    return GateVerdict(stage, True, (), evidence or {})


def _no(stage, codes, evidence=None):
    return GateVerdict(stage, False, tuple(codes), evidence or {})


def _committed_risk(account_state):
    """H-1: aggregate account risk already committed BEFORE the current candidate
    (open-position downside + outstanding + same-cycle authorized intents), supplied by
    the runner as an account-state field. Returns ``(amount, reason)``:
      * ``reason`` is None and ``amount>=0`` when the reservation is trustworthy;
      * ``reason`` is a non-None string (caller FAILS CLOSED) when a reservation is
        present but unverifiable / non-finite / negative — NEVER a silent zero;
      * an ABSENT field yields ``(0.0, None)`` — backward compatible: a legacy or
        single-candidate caller reserves nothing extra and behaves exactly as before.
    This adds NO second risk authority: it only reads a reserved amount the runner
    computed from the existing sizing/lifecycle facts; the gate still owns the decision.
    """
    if account_state.get("committed_risk_unverifiable"):
        return 0.0, "committed_risk_unverifiable"
    if "committed_risk_at_stop" not in account_state:
        return 0.0, None
    c = finite(account_state.get("committed_risk_at_stop"))
    if c is None or c < 0:
        return 0.0, "committed_risk_at_stop"
    return c, None


# -- Stage 1: Kill switch ---------------------------------------------------
def gate_kill_switch(kill_switch):
    if bool(kill_switch):
        return _no(Stage.KILL_SWITCH, [ReasonCode.KILL_SWITCH], {"active": True})
    return _ok(Stage.KILL_SWITCH, {"active": False})


# -- Stage 2: Market compliance (candidate + market tradability) ------------
def gate_market(candidate, market_state, now):
    if not isinstance(candidate, dict):
        return _no(Stage.MARKET, [ReasonCode.CANDIDATE_MALFORMED], {"candidate": None})
    for k in ("signal_id", "symbol", "direction", "entry", "stop_loss",
              "take_profit", "risk_fraction", "mtf"):
        if candidate.get(k) is None:
            return _no(Stage.MARKET, [ReasonCode.CANDIDATE_MALFORMED], {"missing": k})

    symbol = candidate["symbol"]
    if not mapping.is_forex_symbol(symbol):
        return _no(Stage.MARKET, [ReasonCode.SYMBOL_NOT_FOREX], {"symbol": symbol})

    if candidate["direction"] not in _DIRECTIONS:
        return _no(Stage.MARKET, [ReasonCode.CANDIDATE_MALFORMED],
                   {"direction": candidate["direction"]})

    entry = finite(candidate["entry"])
    sl = finite(candidate["stop_loss"])
    tp = finite(candidate["take_profit"])
    if entry is None or sl is None or tp is None or min(entry, sl, tp) <= 0:
        return _no(Stage.MARKET, [ReasonCode.CANDIDATE_MALFORMED], {"prices": "non_finite"})
    if candidate["direction"] == "LONG" and not (sl < entry < tp):
        return _no(Stage.MARKET, [ReasonCode.CANDIDATE_MALFORMED], {"geometry": "LONG"})
    if candidate["direction"] == "SHORT" and not (sl > entry > tp):
        return _no(Stage.MARKET, [ReasonCode.CANDIDATE_MALFORMED], {"geometry": "SHORT"})

    # MTF integrity ONLY (compliance never computes trend/bias)
    mtf = candidate["mtf"]
    if not isinstance(mtf, dict) or any(mtf.get(k) is None for k in _MTF_KEYS):
        return _no(Stage.MARKET, [ReasonCode.MTF_CONFLICT], {"mtf": "incomplete"})
    if mtf.get("aligned") is not True:
        return _no(Stage.MARKET, [ReasonCode.MTF_CONFLICT], {"aligned": mtf.get("aligned")})

    # market tradability snapshot (deterministic input)
    if not isinstance(market_state, dict):
        return _no(Stage.MARKET, [ReasonCode.UNKNOWN_STATE], {"market_state": None})
    if market_state.get("symbol_tradable") is not True:
        return _no(Stage.MARKET, [ReasonCode.SYMBOL_NOT_FOREX], {"symbol_tradable": False})
    if market_state.get("market_open") is not True:
        return _no(Stage.MARKET, [ReasonCode.MARKET_CLOSED], {"market_open": False})

    return _ok(Stage.MARKET, {"symbol": symbol})


# -- Stage 3: FTMO compliance ----------------------------------------------
def _is_weekend(now, cfg):
    return now.isoweekday() in tuple(cfg.weekend_isoweekdays)


def gate_ftmo(candidate, account_state, profile, cfg, session_cfg, now):
    if now is None:
        return _no(Stage.FTMO, [ReasonCode.UNKNOWN_STATE], {"missing": "now"})
    if not isinstance(account_state, dict):
        return _no(Stage.FTMO, [ReasonCode.UNKNOWN_STATE], {"missing": "account_state"})

    # profile must be a verified FTMO_TWO_STEP / FTMO_SWING profile (defense in
    # depth; the producer preflight also enforces this before startup).
    perr = profile.verification_error()
    if perr is not None:
        return _no(Stage.FTMO, [perr], {"profile": profile.program,
                                        "account_type": profile.account_type})

    # M2: FTMO trading day is the Prague (00:00 CE(S)T) calendar date.
    tday = prague_trading_day(now, profile.reset_timezone)
    if tday is None:
        return _no(Stage.FTMO, [ReasonCode.PRAGUE_ROLLOVER_FAILED],
                   {"reset_timezone": profile.reset_timezone})
    if account_state.get("daily_anchor_conflict"):
        return _no(Stage.FTMO, [ReasonCode.FTMO_DAILY_ANCHOR_CONFLICT], {})
    anchor_day = account_state.get("trading_day")
    if anchor_day is not None and anchor_day != tday:
        return _no(Stage.FTMO, [ReasonCode.FTMO_DAILY_ANCHOR_STALE],
                   {"anchor_day": anchor_day, "trading_day": tday})

    # M1/M3: levels from INITIAL capital, anchored to DAY-START BALANCE.
    levels = ftmo_levels(account_state, profile, cfg)
    if levels is None:
        if finite(profile.initial_balance) is None or profile.initial_balance <= 0:
            return _no(Stage.FTMO, [ReasonCode.FTMO_INITIAL_BALANCE_INVALID], {})
        return _no(Stage.FTMO, [ReasonCode.FTMO_DAILY_ANCHOR_MISSING], {})

    # M5: weekend flattening is an INTERNAL overlay only (FTMO Swing allows holding).
    if cfg.internal_weekend_flat and _is_weekend(now, session_cfg):
        return _no(Stage.FTMO, [ReasonCode.INTERNAL_WEEKEND_POLICY],
                   {"isoweekday": now.isoweekday()})

    # internal position overlays (NOT FTMO Swing rules)
    open_count = account_state.get("open_position_count")
    open_symbols = account_state.get("open_symbols") or ()
    if open_count is None:
        return _no(Stage.FTMO, [ReasonCode.UNKNOWN_STATE], {"missing": "open_position_count"})
    if cfg.one_position_per_symbol and candidate.get("symbol") in tuple(open_symbols):
        return _no(Stage.FTMO, [ReasonCode.ONE_PER_SYMBOL], {"symbol": candidate.get("symbol")})
    if int(open_count) >= cfg.max_open_positions:
        return _no(Stage.FTMO, [ReasonCode.MAX_POSITIONS],
                   {"open": int(open_count), "max": cfg.max_open_positions})

    equity = finite(account_state.get("equity"))
    risk_amt = candidate_risk_amount(candidate, profile)
    if equity is None or risk_amt is None:
        return _no(Stage.FTMO, [ReasonCode.UNKNOWN_STATE], {"missing": "equity/risk"})
    # H-1: the AGGREGATE committed-risk projection (open + outstanding + same-cycle) is
    # enforced in gate_risk (which runs AFTER gate_broker_health, so a genuinely
    # unhealthy bridge is still reported with its specific reason). gate_ftmo keeps the
    # single-candidate projection AND the current-equity level checks below; because the
    # internal daily level gate_risk aggregates against is strictly tighter (safer) than
    # the official daily level, protecting the internal level protects the official one.
    projected = equity - risk_amt        # worst-case post-trade equity (breach iff < level)

    odl, idl = levels["official_daily_level"], levels["internal_daily_level"]
    oml, iml = levels["official_max_level"], levels["internal_max_level"]
    ev = {"equity": equity, "projected_post_trade_equity": projected, **levels}

    # -- daily loss (most severe first) --
    if equity < odl:
        return _no(Stage.FTMO, [ReasonCode.FTMO_DAILY_LOSS_BREACH], ev)
    if equity < idl:
        return _no(Stage.FTMO, [ReasonCode.INTERNAL_DAILY_BUFFER_TRIP], ev)
    if projected < odl:
        return _no(Stage.FTMO, [ReasonCode.PROJECTED_DAILY_LOSS_BREACH,
                                ReasonCode.FTMO_DAILY_LOSS_BREACH], ev)
    if projected < idl:
        return _no(Stage.FTMO, [ReasonCode.PROJECTED_DAILY_LOSS_BREACH,
                                ReasonCode.INTERNAL_DAILY_BUFFER_TRIP], ev)
    # -- static maximum loss --
    if equity < oml:
        return _no(Stage.FTMO, [ReasonCode.FTMO_MAXIMUM_LOSS_BREACH], ev)
    if equity < iml:
        return _no(Stage.FTMO, [ReasonCode.INTERNAL_MAXIMUM_LOSS_BUFFER_TRIP], ev)
    if projected < oml:
        return _no(Stage.FTMO, [ReasonCode.FTMO_MAXIMUM_LOSS_BREACH], ev)
    if projected < iml:
        return _no(Stage.FTMO, [ReasonCode.INTERNAL_MAXIMUM_LOSS_BUFFER_TRIP], ev)
    return _ok(Stage.FTMO, ev)


# -- Stage 4: Session compliance -------------------------------------------
def _minute_of_day(now):
    return now.hour * 60 + now.minute


def _session_active(open_min, close_min, m):
    if open_min == close_min:
        return False
    if open_min < close_min:
        return open_min <= m < close_min
    return m >= open_min or m < close_min          # wrap past midnight


def _canonical_model(session_cfg):
    """Return the canonical SessionModel for this SessionConfig — the injected one
    if present, else a legacy model derived from allowed_sessions / friday / sunday
    (overlap DISABLE). The gate NEVER computes its own time windows (Phase 9A: the
    canonical model is the single owner of session/overlap window logic)."""
    from ..session.model import (SessionModel, OverlapMode, SESSION_IDS)
    if getattr(session_cfg, "session_model", None) is not None:
        return session_cfg.session_model
    # normalize legacy "NEWYORK" -> canonical "NEW_YORK"; keep only known ids
    norm = {"NEWYORK": "NEW_YORK"}
    enabled = tuple(s for s in (norm.get(x, x) for x in session_cfg.allowed_sessions)
                    if s in SESSION_IDS)
    return SessionModel(enabled_sessions=enabled, enabled_overlaps=(),
                        overlap_mode=OverlapMode.DISABLE,
                        friday_close_policy=session_cfg.friday_close_min,
                        sunday_open_policy=session_cfg.sunday_open_min,
                        strategy_session_policy="REPORT_ONLY")   # strategy gate is producer-side


def active_sessions(session_cfg, now):
    """Delegates to the canonical model (kept for backward-compatible callers)."""
    from ..session import model as sm
    return sm.active_sessions(_canonical_model(session_cfg), now)


def gate_session(candidate, session_cfg, now):
    if now is None:
        return _no(Stage.SESSION, [ReasonCode.UNKNOWN_STATE], {"missing": "now"})
    from ..session import model as sm
    model = _canonical_model(session_cfg)
    act = sm.active_sessions(model, now)
    act_o = sm.active_overlaps(model, now)
    elig = sm.eligibility(model, now, capability=None)   # strategy support gated in producer
    ev = {"active_session": (act[0] if act else None),
          "active_sessions": list(act), "active_overlaps": list(act_o),
          "overlap_mode": model.overlap_mode, "eligibility_reason": elig["reason"]}
    if elig["eligible"]:
        return _ok(Stage.SESSION, {**ev, "primary_session": elig["primary_session"]})
    # map canonical session reasons -> frozen compliance reason codes
    if elig["reason"] in (sm.SessionReason.FRIDAY_CLOSED, sm.SessionReason.SUNDAY_CLOSED):
        return _no(Stage.SESSION, [ReasonCode.SESSION_BLOCK], ev)
    return _no(Stage.SESSION, [ReasonCode.OUTSIDE_SESSION], ev)


# -- Stage 6: Broker health -------------------------------------------------
def gate_broker_health(broker_health, now):
    if not isinstance(broker_health, dict):
        return _no(Stage.BROKER_HEALTH, [ReasonCode.BROKER_UNHEALTHY, ReasonCode.UNKNOWN_STATE],
                   {"missing": "broker_health"})

    required = ("terminal_connected", "bridge_healthy", "spread_points",
                "max_spread_points", "recent_slippage_points", "max_slippage_points",
                "missing_ack_count", "quote_age_sec", "max_quote_age_sec")
    for k in required:
        if broker_health.get(k) is None:
            return _no(Stage.BROKER_HEALTH,
                       [ReasonCode.BROKER_UNHEALTHY, ReasonCode.UNKNOWN_STATE], {"missing": k})

    if broker_health.get("terminal_connected") is not True:
        return _no(Stage.BROKER_HEALTH,
                   [ReasonCode.TERMINAL_DISCONNECTED, ReasonCode.BROKER_UNHEALTHY], {})
    if broker_health.get("bridge_healthy") is not True:
        return _no(Stage.BROKER_HEALTH,
                   [ReasonCode.BRIDGE_UNHEALTHY, ReasonCode.BROKER_UNHEALTHY], {})

    quote_age = finite(broker_health["quote_age_sec"])
    max_quote_age = finite(broker_health["max_quote_age_sec"])
    if quote_age is None or max_quote_age is None:
        return _no(Stage.BROKER_HEALTH,
                   [ReasonCode.BROKER_UNHEALTHY, ReasonCode.UNKNOWN_STATE], {})
    if quote_age > max_quote_age:
        return _no(Stage.BROKER_HEALTH,
                   [ReasonCode.MARKET_DATA_STALE, ReasonCode.BROKER_UNHEALTHY],
                   {"quote_age_sec": quote_age, "max": max_quote_age})

    if int(broker_health["missing_ack_count"]) > 0:
        return _no(Stage.BROKER_HEALTH,
                   [ReasonCode.ACK_MISSING, ReasonCode.BROKER_UNHEALTHY],
                   {"missing_ack_count": int(broker_health["missing_ack_count"])})

    spread = finite(broker_health["spread_points"])
    max_spread = finite(broker_health["max_spread_points"])
    if spread is None or max_spread is None:
        return _no(Stage.BROKER_HEALTH,
                   [ReasonCode.BROKER_UNHEALTHY, ReasonCode.UNKNOWN_STATE], {})
    if spread > max_spread:
        return _no(Stage.BROKER_HEALTH,
                   [ReasonCode.SPREAD_TOO_HIGH, ReasonCode.BROKER_UNHEALTHY],
                   {"spread_points": spread, "max": max_spread})

    slip = finite(broker_health["recent_slippage_points"])
    max_slip = finite(broker_health["max_slippage_points"])
    if slip is None or max_slip is None:
        return _no(Stage.BROKER_HEALTH,
                   [ReasonCode.BROKER_UNHEALTHY, ReasonCode.UNKNOWN_STATE], {})
    if slip > max_slip:
        return _no(Stage.BROKER_HEALTH,
                   [ReasonCode.SLIPPAGE_TOO_HIGH, ReasonCode.BROKER_UNHEALTHY],
                   {"recent_slippage_points": slip, "max": max_slip})

    return _ok(Stage.BROKER_HEALTH, {"spread_points": spread, "quote_age_sec": quote_age})


# -- Stage 7: Risk compliance ----------------------------------------------
def gate_risk(candidate, account_state, profile, cfg, now, broker_health=None):
    """M9: declared ``risk_fraction`` is a POLICY input (a cap), never the sole proof.
    The gate independently RE-COMPUTES the actual monetary loss-at-stop for the
    approved ``volume`` from broker symbol metadata (tick size/value) and requires it
    within ``risk_fraction × initial_balance``. Missing volume / metadata fails closed
    (RISK_MONETARY_UNVERIFIABLE) — never a fall-back to the declared fraction alone."""
    rf = finite(candidate.get("risk_fraction"))
    if rf is None or rf < 0:
        return _no(Stage.RISK, [ReasonCode.UNKNOWN_STATE], {"risk_fraction": candidate.get("risk_fraction")})
    if rf > cfg.max_risk_per_trade_pct:
        return _no(Stage.RISK, [ReasonCode.RISK_PER_TRADE_EXCEEDED],
                   {"risk_fraction": rf, "max": cfg.max_risk_per_trade_pct})

    levels = ftmo_levels(account_state, profile, cfg)
    risk_amt = candidate_risk_amount(candidate, profile)   # permitted = rf × initial_balance
    equity = finite(account_state.get("equity"))
    if levels is None or risk_amt is None or equity is None:
        return _no(Stage.RISK, [ReasonCode.UNKNOWN_STATE], {"missing": "risk numerics"})

    # M9 authoritative loss-at-stop from the APPROVED VOLUME (the exact lot the EA
    # executes) + broker tick metadata. risk_fraction alone is never accepted.
    bh = broker_health if isinstance(broker_health, dict) else {}
    volume = candidate.get("volume")
    ok_risk, loss = sizing.risk_within_limit(
        candidate.get("entry"), candidate.get("stop_loss"), volume,
        bh.get("tick_size"), bh.get("tick_value"), risk_amt)
    if loss is None:
        return _no(Stage.RISK, [ReasonCode.RISK_MONETARY_UNVERIFIABLE],
                   {"volume": volume, "tick_size": bh.get("tick_size"),
                    "tick_value": bh.get("tick_value")})
    if not ok_risk:
        return _no(Stage.RISK, [ReasonCode.RISK_PER_TRADE_EXCEEDED],
                   {"loss_at_stop": loss, "permitted_risk_amount": risk_amt,
                    "volume": volume})

    # daily-buffer defense-in-depth uses the DECLARED amount (>= actual loss), so this
    # check is never weakened by the tighter authoritative loss figure. H-1: also
    # reserve already-committed account risk (open + outstanding + same-cycle) here,
    # consistent with gate_ftmo; fail closed if it cannot be verified.
    committed, c_reason = _committed_risk(account_state)
    if c_reason is not None:
        return _no(Stage.RISK, [ReasonCode.UNKNOWN_STATE], {"missing": c_reason})
    projected = equity - committed - risk_amt        # (FTMO gate catches first)
    if projected < levels["internal_daily_level"]:
        return _no(Stage.RISK, [ReasonCode.RISK_PROJECTED_BREACH],
                   {"projected_post_trade_equity": projected, "committed_risk_at_stop": committed,
                    "internal_daily_level": levels["internal_daily_level"]})
    return _ok(Stage.RISK, {"risk_amount": risk_amt, "loss_at_stop": loss,
                            "volume": volume, "projected_post_trade_equity": projected})
