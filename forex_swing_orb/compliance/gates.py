"""Deterministic compliance gates (Phase 5C).

Each gate is a pure function returning a :class:`GateVerdict`. No wall clock (the
UTC ``now`` is injected), no RNG, no networking. Every gate fails closed: any
missing / malformed / non-finite input yields a REJECT with an explicit reason
code (never a generic failure, never fail-open).
"""

from __future__ import annotations

from . import mapping
from .contract import (GateVerdict, ReasonCode, Stage, candidate_risk_amount,
                       finite, ftmo_limits)

_DIRECTIONS = ("LONG", "SHORT")
_MTF_KEYS = ("daily_bias", "h4_structure", "h1_setup", "m15_timing", "aligned")


def _ok(stage, evidence=None):
    return GateVerdict(stage, True, (), evidence or {})


def _no(stage, codes, evidence=None):
    return GateVerdict(stage, False, tuple(codes), evidence or {})


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


def gate_ftmo(candidate, account_state, cfg, session_cfg, now):
    if now is None:
        return _no(Stage.FTMO, [ReasonCode.UNKNOWN_STATE], {"missing": "now"})
    if not isinstance(account_state, dict):
        return _no(Stage.FTMO, [ReasonCode.UNKNOWN_STATE], {"missing": "account_state"})

    limits = ftmo_limits(account_state, cfg)
    if limits is None:
        return _no(Stage.FTMO, [ReasonCode.UNKNOWN_STATE], {"missing": "anchor/initial"})

    # weekend-flat for NEW entries (protective)
    if cfg.weekend_flat_required and _is_weekend(now, session_cfg):
        return _no(Stage.FTMO, [ReasonCode.WEEKEND_BLOCK],
                   {"isoweekday": now.isoweekday()})

    open_count = account_state.get("open_position_count")
    open_symbols = account_state.get("open_symbols") or ()
    if open_count is None:
        return _no(Stage.FTMO, [ReasonCode.UNKNOWN_STATE], {"missing": "open_position_count"})

    if cfg.one_position_per_symbol and candidate.get("symbol") in tuple(open_symbols):
        return _no(Stage.FTMO, [ReasonCode.ONE_PER_SYMBOL],
                   {"symbol": candidate.get("symbol")})
    if int(open_count) >= cfg.max_open_positions:
        return _no(Stage.FTMO, [ReasonCode.MAX_POSITIONS],
                   {"open": int(open_count), "max": cfg.max_open_positions})

    daily_loss = finite(account_state.get("current_daily_loss"))
    open_risk = finite(account_state.get("open_risk_at_stop"))
    equity = finite(account_state.get("equity"))
    initial = finite(account_state.get("initial_balance"))
    risk_amt = candidate_risk_amount(candidate, account_state)
    if None in (daily_loss, open_risk, equity, initial, risk_amt):
        return _no(Stage.FTMO, [ReasonCode.UNKNOWN_STATE], {"missing": "account numerics"})

    projected_daily = daily_loss + open_risk + risk_amt
    if projected_daily >= limits["internal_daily_limit"]:
        codes = [ReasonCode.DAILY_LOSS_LIMIT]
        if projected_daily < limits["ftmo_daily_limit"]:
            codes.append(ReasonCode.INTERNAL_BUFFER_TRIP)   # tripped internal, before FTMO
        return _no(Stage.FTMO, codes, {
            "projected_daily_loss": projected_daily,
            "internal_daily_limit": limits["internal_daily_limit"],
            "ftmo_daily_limit": limits["ftmo_daily_limit"]})

    projected_total = (initial - equity) + risk_amt
    if projected_total >= limits["internal_max_loss"]:
        codes = [ReasonCode.MAX_ACCOUNT_LOSS]
        if projected_total < limits["ftmo_max_loss"]:
            codes.append(ReasonCode.INTERNAL_BUFFER_TRIP)
        return _no(Stage.FTMO, codes, {
            "projected_total_loss": projected_total,
            "internal_max_loss": limits["internal_max_loss"],
            "ftmo_max_loss": limits["ftmo_max_loss"]})

    return _ok(Stage.FTMO, {"projected_daily_loss": projected_daily,
                            "projected_total_loss": projected_total,
                            "internal_daily_limit": limits["internal_daily_limit"],
                            "internal_max_loss": limits["internal_max_loss"]})


# -- Stage 4: Session compliance -------------------------------------------
def _minute_of_day(now):
    return now.hour * 60 + now.minute


def _session_active(open_min, close_min, m):
    if open_min == close_min:
        return False
    if open_min < close_min:
        return open_min <= m < close_min
    return m >= open_min or m < close_min          # wrap past midnight


def active_sessions(session_cfg, now):
    m = _minute_of_day(now)
    return tuple(name for (name, o, c) in session_cfg.sessions
                 if _session_active(o, c, m))


def gate_session(candidate, session_cfg, now):
    if now is None:
        return _no(Stage.SESSION, [ReasonCode.UNKNOWN_STATE], {"missing": "now"})
    m = _minute_of_day(now)
    wd = now.isoweekday()

    # explicit friday-close / sunday-open restrictions (deterministic)
    if session_cfg.friday_close_min is not None and wd == 5 and m >= session_cfg.friday_close_min:
        return _no(Stage.SESSION, [ReasonCode.SESSION_BLOCK],
                   {"restriction": "friday_close", "minute": m})
    if session_cfg.sunday_open_min is not None and wd == 7 and m < session_cfg.sunday_open_min:
        return _no(Stage.SESSION, [ReasonCode.SESSION_BLOCK],
                   {"restriction": "sunday_open", "minute": m})

    active = active_sessions(session_cfg, now)
    allowed_active = tuple(s for s in active if s in tuple(session_cfg.allowed_sessions))
    if not allowed_active:
        return _no(Stage.SESSION, [ReasonCode.OUTSIDE_SESSION],
                   {"active": list(active), "allowed": list(session_cfg.allowed_sessions)})
    return _ok(Stage.SESSION, {"active_session": allowed_active[0],
                               "active_sessions": list(allowed_active)})


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
def gate_risk(candidate, account_state, cfg, now):
    rf = finite(candidate.get("risk_fraction"))
    if rf is None or rf < 0:
        return _no(Stage.RISK, [ReasonCode.UNKNOWN_STATE], {"risk_fraction": candidate.get("risk_fraction")})
    if rf > cfg.max_risk_per_trade_pct:
        return _no(Stage.RISK, [ReasonCode.RISK_PER_TRADE_EXCEEDED],
                   {"risk_fraction": rf, "max": cfg.max_risk_per_trade_pct})

    limits = ftmo_limits(account_state, cfg)
    risk_amt = candidate_risk_amount(candidate, account_state)
    daily_loss = finite(account_state.get("current_daily_loss"))
    open_risk = finite(account_state.get("open_risk_at_stop"))
    if limits is None or risk_amt is None or daily_loss is None or open_risk is None:
        return _no(Stage.RISK, [ReasonCode.UNKNOWN_STATE], {"missing": "risk numerics"})

    projected_daily = daily_loss + open_risk + risk_amt
    if projected_daily >= limits["internal_daily_limit"]:
        return _no(Stage.RISK, [ReasonCode.RISK_PROJECTED_BREACH],
                   {"projected_daily_loss": projected_daily,
                    "internal_daily_limit": limits["internal_daily_limit"]})
    return _ok(Stage.RISK, {"risk_amount": risk_amt, "projected_daily_loss": projected_daily})
