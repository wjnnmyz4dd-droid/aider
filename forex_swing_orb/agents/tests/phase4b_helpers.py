"""Builders for Phase 4B live-agent tests (uniquely named; not a conftest)."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from forex_swing_orb.agents import build_request   # noqa: E402

NOW = datetime(2024, 1, 25, 12, 0, 0, tzinfo=timezone.utc)   # a Thursday


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def req(symbol="EURUSD.FX", correlation_id="corr-4b"):
    return build_request(symbol, iso(NOW), "forex_swing_orb", "swing_orb.v1.4.0",
                         "md://ref", "news://ref", "mem://ref", correlation_id)


def bar(t, o, h, l, c):
    return {"t": t, "o": o, "h": h, "l": l, "c": c}


def flat_bars(n=30, high=1.1020, low=1.0980, close=1.1000, start_min=40):
    """n closed bars ending ~start_min ago, deterministic timestamps."""
    return [bar(iso(NOW - timedelta(minutes=start_min - i)), 1.10, high, low, close)
            for i in range(n)]


def market_facts(trend_d1="BULLISH", trend_h4="BULLISH", trend_health="STRONG",
                 session="LONDON", volatility="NORMAL", htf_structure="HH_HL",
                 trend_continuation="YES", age_sec=60, **extra):
    m = {"timestamp": iso(NOW - timedelta(minutes=1)), "provenance": "feed",
         "timezone": "UTC", "bars_monotonic": True, "trend_d1": trend_d1,
         "trend_h4": trend_h4, "trend_health": trend_health, "session": session,
         "volatility": volatility, "htf_structure": htf_structure,
         "trend_continuation": trend_continuation, "age_sec": age_sec}
    m.update(extra)
    return m


def news_bundle(events=None, verified=True, age_sec=60, **extra):
    n = {"timestamp": iso(NOW - timedelta(minutes=1)), "provenance": "calendar",
         "verified": verified, "events": events if events is not None else [],
         "age_sec": age_sec, "pre_lockout_min": 30, "post_lockout_min": 30}
    n.update(extra)
    return n


def event(currency="EUR", impact="HIGH", minutes_from_now=10, name="ECB Rate",
          verification_state="VERIFIED", timezone_field=None, event_id=None,
          event_timestamp=None):
    ts = event_timestamp or iso(NOW + timedelta(minutes=minutes_from_now))
    ev = {"event_id": event_id or f"evt-{currency}-{name}", "source": "calendar",
          "source_timestamp": iso(NOW - timedelta(minutes=5)),
          "event_timestamp": ts, "currency": currency, "impact": impact,
          "event_name": name, "previous": "1.0", "forecast": "1.1",
          "verification_state": verification_state,
          "ingestion_timestamp": iso(NOW - timedelta(minutes=2))}
    if timezone_field is not None:
        ev["timezone"] = timezone_field
    return ev


def liq_bundle(bars=None, candidate=None, prior_session_bars=None,
               strategy_swings=None, stale=None, tolerance_pips=2.0, **extra):
    b = {"timestamp": iso(NOW - timedelta(minutes=1)), "provenance": "feed",
         "pip_size": 0.0001, "tolerance_pips": tolerance_pips,
         "bars": bars if bars is not None else flat_bars(),
         "candidate": candidate or {"direction": "LONG", "entry": 1.1000,
                                    "stop": 1.0980, "target": 1.1040}}
    if prior_session_bars is not None:
        b["prior_session_bars"] = prior_session_bars
    if strategy_swings is not None:
        b["strategy_swings"] = strategy_swings
    if stale is not None:
        b["stale"] = stale
    b.update(extra)
    return b


def ctx(market=None, liquidity=None, news=None, direction="LONG"):
    return {"market": market, "liquidity": liquidity, "news": news,
            "strategy_candidate_direction": direction}


def full_bundle(events=None, market=None, liquidity=None):
    return {"market": market or market_facts(),
            "news": news_bundle(events=events),
            "liquidity": liquidity or liq_bundle(),
            "strategy_candidate_direction": "LONG"}
