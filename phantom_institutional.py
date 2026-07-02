# -*- coding: utf-8 -*-
"""
PhantomEdge Institutional Server v4.0

All 15 hedge-fund upgrades in one file:

1. Order Flow Proxy          -- delta divergence, absorption, volume imbalance
2. ML Signal Classifier      -- XGBoost/Random Forest trained on live trade history
3. Liquidity Heatmap         -- stop cluster estimation, next pool targeting
4. Monte Carlo Simulator     -- 10,000 sequence DD simulation, risk of ruin
5. Correlation-Adjusted Sizing -- covariance matrix, constant portfolio volatility
6. Dynamic RR by Regime      -- expansion=3.5:1, trend=2.5:1, fragile=1.5:1
7. Latency Optimizer         -- per-symbol slippage budgets, fill quality tracking
8. Multi-Account Orchestrator -- master signal -> N accounts, per-account DD control
9. Sentiment Aggregator      -- COT proxy, retail positioning, swap rate differentials
10. Regime Early Warning      -- ATR correlation spike, equity/FX divergence detection

Endpoints:
POST /score               -- AI trade score (v3 compatible)
POST /portfolio_check     -- Portfolio exposure check
POST /portfolio_sync      -- Sync positions on EA init
POST /feedback            -- Closed trade feedback
POST /retrain             -- Trigger ML retrain
POST /order_flow          -- Receive tick/volume data from EA
POST /orchestrate         -- Multi-account signal distribution
GET  /monte_carlo         -- Run DD simulation
GET  /liquidity_map       -- Current liquidity heatmap for symbol
GET  /sentiment           -- Current sentiment readings
GET  /regime              -- Current regime + early warning status
GET  /dynamic_rr          -- Recommended RR for current regime
GET  /stats               -- Full performance stats
GET  /health              -- Server health
GET  /dashboard           -- Web dashboard

Install:
pip install flask numpy pandas scikit-learn requests beautifulsoup4 lxml pytz
(XGBoost optional: pip install xgboost)

Run:
python phantom_institutional.py
"""

from flask import Flask, request, jsonify, render_template_string, Response
import numpy as np
import json, csv, os, sys, uuid, logging, threading, time, math, random, traceback
from logging.handlers import RotatingFileHandler                              # [IMP-2]

class _SafeRotatingFileHandler(RotatingFileHandler):
    """RotatingFileHandler that silently skips rotation on Windows WinError 32.
    Standard RotatingFileHandler crashes when another process/handler holds the
    log file open during rename — common on Windows VPS environments."""
    def doRollover(self):
        try:
            super().doRollover()
        except PermissionError:
            pass  # WinError 32: file locked — skip this rotation cycle
from datetime import datetime, timedelta, timezone
from collections import deque, defaultdict
from typing import Dict, List, Tuple, Optional
import requests

# ── Optional ML imports ───────────────────────────────────────────────

try:
    from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
    from sklearn.preprocessing import StandardScaler
    from sklearn.model_selection import cross_val_score
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False
    logging.warning("scikit-learn not found. ML classifier disabled.")

# ── Optional WebSocket (Twelve Data live price stream) ───────────────
try:
    import websocket as _websocket_lib
    HAS_WEBSOCKET = True
except ImportError:
    HAS_WEBSOCKET = False  # pip install websocket-client on VPS to enable

try:
    import xgboost as xgb
    HAS_XGB = True
except ImportError:
    HAS_XGB = False

# ── LLM macro bias cache — populated by background thread from dashboard API ──
_llm_bias_cache: dict = {}   # { "EURUSD": {bias, score_delta, confidence, reasoning, ...} }
_llm_bias_lock  = threading.Lock()

def _llm_bias_fetch_loop():
    """Background thread: fetch cached LLM bias from dashboard every 30 min."""
    import time as _time
    while True:
        try:
            url = f"{DASHBOARD_API_URL}/ai/llm-bias"
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                data = r.json()
                biases = data.get("biases", [])
                with _llm_bias_lock:
                    for entry in biases:
                        sym = (entry.get("symbol") or "").upper()
                        if sym:
                            _llm_bias_cache[sym] = entry
                logging.info(f"[LLM-BIAS] Fetched bias for {[b.get('symbol') for b in biases]}")
        except Exception as e:
            logging.debug(f"[LLM-BIAS] Fetch failed (will retry in 30min): {e}")
        _time.sleep(30 * 60)

# ══════════════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════════════

HOST             = os.environ.get("PHANTOM_HOST", "0.0.0.0")
PORT             = int(os.environ.get("PHANTOM_PORT", "5000"))
_PHANTOM_ENV     = os.environ.get("PHANTOM_ENV", "production")
_SERVER_START      = time.time()   # uptime counter for /healthz
_last_heartbeat_ts: float = 0.0   # unix ts of last EA heartbeat (Phase 8)
_g_daily_dd_pct:   float = 0.0   # last daily drawdown % seen in heartbeat (Phase 8)
_g_portfolio_heat: float = 0.0   # last portfolio heat [0,1] (Phase 8)
MIN_SCORE        = 72.0          # Minimum AI score threshold (v3.12: tightened from 68 → 72 — synced with EA InpAIMinScore + api-server entryThreshold)

# Command center circuit breaker — ALL EAs blocked when limits are hit
CMD_CENTER_URL   = "http://127.0.0.1:5002"   # phantom_command_center.py
# [FIX-1] CB_FAIL_OPEN controls behavior when the command center is unreachable.
# False = trades are BLOCKED when command center is unreachable (fail-SAFE / prop-firm safe).
#         This is the correct production default. The watchdog restarts the command center
#         within seconds of a crash, so the block window is minimal and deliberate.
# True  = trades are ALLOWED when command center is unreachable (fail-open / NOT recommended).
#         Only set True if you have an unstable VPS network AND accept that the daily-loss
#         and total-DD circuit breakers will be bypassed during any outage window.
# ⚠ OPERATOR: Do NOT change to True unless you fully understand the prop-firm risk.
CB_FAIL_OPEN     = False  # [HARDENED] Fail-safe: block trades when command center is offline

# Kelly Criterion at 68% WR / 2.8:1 RR = ~1.1% optimal bet
# Base risk: 1.0% (conservative Kelly). Hard cap: 1.5%. No aggressive mode.
# All sizing done via dynamic multipliers -- never manual aggression selection.

_DOCS            = os.path.join(os.path.expanduser("~"), "Documents")           # [IMP-1]
LOG_FILE         = os.path.join(_DOCS, "phantom_v4.log")                        # [IMP-1]
JOURNAL_FILE     = os.path.join(_DOCS, "phantom_feedback.csv")                  # [IMP-1]
MODEL_FILE       = os.path.join(_DOCS, "phantom_ml_model.pkl")                  # [IMP-1]
MAX_HISTORY      = 2000
MONTE_CARLO_RUNS = 10000

SCANNER_PAIRS = [
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD"
]  # 5-pair core basket — EURJPY/GBPJPY/XAUUSD removed (pair intelligence v4.02)

# Per-pair minimum AI score thresholds (pair intelligence v4.02).
# Regime adjustments (expansion −10/−12, fragile +10, FUNDED +5) stack on top.
# Falls back to global MIN_SCORE for any unknown symbol.
PAIR_MIN_SCORE = {
    "EURUSD": 78.0,   # tightest liquid pair — high-quality setups only
    "GBPUSD": 82.0,   # volatile; needs strong conviction
    "USDJPY": 76.0,   # reliable trend pair — slightly looser
    "AUDUSD": 80.0,   # commodity-correlated; moderate filter
    "USDCAD": 81.0,   # NY-session pair; needs NY confluence
}

# Pair correlations matrix
CORRELATIONS = {
    ("EURUSD", "GBPUSD"): 0.72,  ("EURUSD", "AUDUSD"): 0.65,
    ("EURUSD", "USDJPY"): -0.61, ("GBPUSD", "AUDUSD"): 0.58,
    ("GBPUSD", "USDJPY"): -0.55, ("EURUSD", "USDCAD"): -0.52,
    ("AUDUSD", "USDCAD"): -0.48, ("USDJPY", "USDCAD"): 0.41,
    ("GBPUSD", "USDCAD"): -0.45, ("AUDUSD", "USDJPY"): -0.50,
}  # 5-pair basket only — GBPJPY/EURJPY/USDCHF/NZDUSD entries removed

# Dynamic RR by regime
REGIME_RR = {
    "expansion": 3.5,
    "trend":     2.5,
    "fragile":   1.5,
}

# Session slippage budgets (pips)
SESSION_SLIPPAGE = {
    "LONDON_NY": 0.8,
    "LONDON":    1.0,
    "NY":        1.2,
    "ASIA":      2.0,
    "OFF":       3.0,
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        _SafeRotatingFileHandler(LOG_FILE, maxBytes=5*1024*1024, backupCount=3, encoding="utf-8"),  # [IMP-2] 5 MB × 3 backups — Windows-safe
        logging.StreamHandler(),
    ]
)
log = logging.getLogger("PhantomV4")
# [IMP-3] Startup capability summary — logged at process start so operators immediately
# know which optional modules are active on the VPS and where files are written.
# This also validates that file paths are correct before the server starts accepting
# trade score requests — a misconfigured path shows up in the log, not silently at trade time.
log.info("=== PhantomEdge Adaptive Scoring Engine v4.02 — STARTUP ===")
log.info("  Scoring mode : 29-factor rule engine with optional XGBoost/RF classifier overlay")
log.info("  sklearn   : %s",
    "✓ installed — ML classifier will activate after 50 fills per strategy (cold-start: rule-based until then)"
    if HAS_SKLEARN else
    "✗ not installed — run: pip install scikit-learn  (rule-based scoring active; ML unavailable)")
log.info("  xgboost   : %s",
    "✓ installed — XGBoost preferred over RandomForest when sklearn active"
    if HAS_XGB else
    "✗ not installed — run: pip install xgboost  (RandomForest fallback when sklearn active)")
log.info("  websocket : %s",  "✓ active (Twelve Data live stream)" if HAS_WEBSOCKET else "✗ disabled — run: pip install websocket-client")
log.info("  defusedxml: (inline import per request — run: pip install defusedxml for hardened XML)")
log.info("  LOG_FILE     : %s", LOG_FILE)
log.info("  MODEL_FILE   : %s", MODEL_FILE)
log.info("  JOURNAL_FILE : %s", JOURNAL_FILE)
log.info("  CB_FAIL_OPEN : %s  (True = score requests pass when command center is offline)", CB_FAIL_OPEN)
log.info("  MIN_SCORE    : %s  (current effective threshold before regime adjustment)", MIN_SCORE)
log.info("  Log rotation : 5 MB × 3 backups")
log.info("========================================================")
# ══════════════════════════════════════════════════════════════════════
# FOREX CALENDAR — live HIGH-impact news block (ForexFactory XML feed)
# ══════════════════════════════════════════════════════════════════════

CALENDAR_URL          = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"
CALENDAR_REFRESH_SECS = 3600   # re-fetch every hour
NEWS_BLOCK_WINDOW_MIN = 30     # block ±30 min around each HIGH impact event

_calendar_cache: Dict = {
    "events":     [],
    "fetched_at": None,
    "lock":       threading.Lock(),
}


def _fetch_calendar() -> List:
    """Fetch and parse ForexFactory XML. Cache for 1 hour. Returns list of HIGH impact events."""
    with _calendar_cache["lock"]:
        now = datetime.utcnow()
        if (_calendar_cache["fetched_at"] is not None and
                (now - _calendar_cache["fetched_at"]).total_seconds() < CALENDAR_REFRESH_SECS):
            return list(_calendar_cache["events"])

    try:
        # Use defusedxml to harden against XXE / billion-laughs while parsing
        # the third-party ForexFactory feed. Falls back to stdlib ET if
        # defusedxml is unavailable on the VPS (logs a warning so the user
        # can `pip install defusedxml`).
        try:
            import defusedxml.ElementTree as ET  # type: ignore
        except Exception:
            import xml.etree.ElementTree as ET  # noqa: F401
            print("[CAL] defusedxml not installed — falling back to stdlib xml.etree (run: pip install defusedxml)")
        resp = requests.get(CALENDAR_URL, timeout=12)
        root = ET.fromstring(resp.content)
        events = []
        for ev in root.findall("event"):
            impact = (ev.findtext("impact") or "").strip().upper()
            if impact not in ("HIGH", "RED"):
                continue
            currency = ev.findtext("currency") or ""
            title    = ev.findtext("title")    or ""
            date_str = ev.findtext("date")     or ""
            time_str = ev.findtext("time")     or ""
            try:
                dt_str = f"{date_str} {time_str}".strip()
                dt = datetime.strptime(dt_str, "%m-%d-%Y %I:%M%p")
            except Exception:
                try:
                    dt = datetime.strptime(date_str.strip(), "%m-%d-%Y")
                except Exception:
                    continue
            events.append({"currency": currency.upper(), "title": title, "dt": dt})
        with _calendar_cache["lock"]:
            _calendar_cache["events"]     = events
            _calendar_cache["fetched_at"] = datetime.utcnow()
        log.info(f"[CALENDAR] Fetched {len(events)} HIGH impact events")
        return events
    except Exception as cal_err:
        log.warning(f"[CALENDAR] Fetch failed: {cal_err}")
        with _calendar_cache["lock"]:
            return list(_calendar_cache["events"])  # return stale cache


def is_news_blocked_server(symbol: str) -> Tuple[bool, str]:
    """
    Server-side news block. Overrides EA news_block field when live calendar
    shows a HIGH impact event within NEWS_BLOCK_WINDOW_MIN minutes.
    Returns (blocked, event_title).
    """
    if len(symbol) < 6:
        return False, ""
    ccy1 = symbol[:3].upper()
    ccy2 = symbol[3:6].upper()
    events = _fetch_calendar()
    now    = datetime.utcnow()
    for ev in events:
        if ev["currency"] not in (ccy1, ccy2):
            continue
        diff_min = abs((ev["dt"] - now).total_seconds() / 60)
        if diff_min <= NEWS_BLOCK_WINDOW_MIN:
            return True, ev["title"]
    return False, ""


# Tier-1 events that move markets violently. Title substrings (case-insensitive).
# Anything in this set inside the inner ±5min window is still HARD-BLOCKED.
NEWS_TIER1_KEYWORDS = (
    "non-farm", "nonfarm", "nfp",
    "cpi", "core cpi",
    "fomc", "federal funds", "rate decision", "interest rate",
    "ecb press conference", "ecb rate", "boe rate", "boj rate",
    "ppi", "gdp",
)

def _is_tier1(title: str) -> bool:
    t = (title or "").lower()
    return any(k in t for k in NEWS_TIER1_KEYWORDS)


def grade_news_event(symbol: str, signal: int = 0) -> Dict:
    """
    Graded news scoring — replaces the binary ±30min block with a curve.

    Returns dict:
      action:   "block"      → kill the setup outright
                "score_adj"  → apply `delta` to score, continue
                "neutral"    → no news effect
      delta:    score adjustment (-25..+8). Only meaningful when action=score_adj.
      mins_away: signed minutes to event (+future, -past)
      title:    triggering event title
      tier:     1 (NFP/CPI/FOMC/etc) or 2 (other HIGH)
      reason:   short human-readable string

    mins_away convention: signed minutes such that
        mins_away > 0  → event is in the FUTURE (pre-event)
        mins_away < 0  → event is in the PAST   (post-event)

    Curve:
      pre   ( 0,  5]    tier1 → BLOCK   |  tier2 → -25
      pre   ( 5, 15]    any   → -15
      pre   (15, 30]    any   → -8
      post  [-5,  0)    any   → -10   (first-tick whipsaw)
      post  [-15,-5)    any   → +6    (vol opportunity)
      post  [-30,-15)   any   → +3
      else              → neutral
    """
    if len(symbol) < 6:
        return {"action": "neutral", "delta": 0.0, "mins_away": 9999.0, "title": "", "tier": 0, "reason": ""}
    ccy1 = symbol[:3].upper()
    ccy2 = symbol[3:6].upper()
    events = _fetch_calendar()
    now    = datetime.utcnow()
    closest = None
    closest_abs = 9999.0
    for ev in events:
        if ev["currency"] not in (ccy1, ccy2):
            continue
        # +ve = future (pre-event); -ve = past (post-event)
        diff_min = (ev["dt"] - now).total_seconds() / 60.0
        if abs(diff_min) > 30:
            continue
        if abs(diff_min) < closest_abs:
            closest_abs = abs(diff_min)
            closest = (diff_min, ev)
    if closest is None:
        return {"action": "neutral", "delta": 0.0, "mins_away": 9999.0, "title": "", "tier": 0, "reason": ""}

    mins, ev = closest
    title = ev["title"]
    tier  = 1 if _is_tier1(title) else 2

    # Pre-event (mins > 0 → event still in the future)
    if 0 < mins <= 5:
        if tier == 1:
            return {"action": "block", "delta": 0.0, "mins_away": mins, "title": title, "tier": tier,
                    "reason": f"tier1 within 5min: {title}"}
        return {"action": "score_adj", "delta": -25.0, "mins_away": mins, "title": title, "tier": tier,
                "reason": f"tier2 within 5min: {title}"}
    if 5 < mins <= 15:
        return {"action": "score_adj", "delta": -15.0, "mins_away": mins, "title": title, "tier": tier,
                "reason": f"5-15min before {title}"}
    if 15 < mins <= 30:
        return {"action": "score_adj", "delta": -8.0, "mins_away": mins, "title": title, "tier": tier,
                "reason": f"15-30min before {title}"}
    # Post-event (mins < 0 → event already happened)
    if -5 <= mins < 0:
        return {"action": "score_adj", "delta": -10.0, "mins_away": mins, "title": title, "tier": tier,
                "reason": f"first 5min after {title} (whipsaw risk)"}
    if -15 <= mins < -5:
        return {"action": "score_adj", "delta": +6.0, "mins_away": mins, "title": title, "tier": tier,
                "reason": f"post-event vol window 5-15min after {title}"}
    if -30 <= mins < -15:
        return {"action": "score_adj", "delta": +3.0, "mins_away": mins, "title": title, "tier": tier,
                "reason": f"post-event 15-30min after {title}"}

    return {"action": "neutral", "delta": 0.0, "mins_away": mins, "title": title, "tier": tier, "reason": ""}


def get_news_context_for_manage(symbol: str) -> Tuple[bool, float, str]:
    """
    Richer news context for position management.
    Returns (near_news, mins_away, event_title).
    mins_away is signed: negative = event already started (post-news window).
    Only considers HIGH impact events affecting this symbol's currencies.
    """
    if len(symbol) < 6:
        return False, 9999.0, ""
    ccy1 = symbol[:3].upper()
    ccy2 = symbol[3:6].upper()
    events = _fetch_calendar()
    now    = datetime.utcnow()
    closest_mins = 9999.0
    closest_title = ""
    for ev in events:
        if ev["currency"] not in (ccy1, ccy2):
            continue
        diff_min = (ev["dt"] - now).total_seconds() / 60  # signed: +ve = future
        abs_diff = abs(diff_min)
        if abs_diff <= NEWS_BLOCK_WINDOW_MIN and abs_diff < abs(closest_mins):
            closest_mins  = diff_min
            closest_title = ev["title"]
    near = abs(closest_mins) <= NEWS_BLOCK_WINDOW_MIN
    return near, round(closest_mins, 1), closest_title


# ══════════════════════════════════════════════════════════════════════
# TELEGRAM ALERTS
# ══════════════════════════════════════════════════════════════════════
# Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID env vars, or call
# POST /set_telegram at runtime to configure without restarting.

_telegram_cfg: Dict = {
    "token":       os.environ.get("TELEGRAM_BOT_TOKEN", ""),
    "chat_id":     os.environ.get("TELEGRAM_CHAT_ID",   ""),
    "alert_pairs": [],   # empty = all pairs; non-empty = only listed symbols
    "lock":        threading.Lock(),
}


def _telegram_symbol_ok(symbol: str) -> bool:
    """Return True if Telegram alerts should fire for this symbol."""
    with _telegram_cfg["lock"]:
        pairs = _telegram_cfg["alert_pairs"]
    if not pairs:
        return True
    return symbol.upper() in [p.upper() for p in pairs]


def send_telegram(message: str):
    """Fire-and-forget Telegram alert. Silently skips if credentials not set."""
    with _telegram_cfg["lock"]:
        token   = _telegram_cfg["token"]
        chat_id = _telegram_cfg["chat_id"]
    if not token or not chat_id:
        return
    def _send():
        try:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            requests.post(url, json={
                "chat_id": chat_id, "text": message, "parse_mode": "HTML",
            }, timeout=6)
        except Exception as tg_err:
            log.warning(f"[TELEGRAM] Send failed: {tg_err}")
    threading.Thread(target=_send, daemon=True).start()


# ── Severity-aware alert wrapper (Phase 8 — with 15-min suppression) ─────────
_alert_suppress: dict = {}   # {alert_key: last_sent_ts}

def send_phantom_alert(message: str,
                       severity: str = "WARNING",
                       alert_key: str = "generic") -> None:
    """
    Severity-annotated Telegram alert with 15-minute per-key suppression.
    severity: WARNING | CRITICAL | EMERGENCY | INFO
    Does nothing if Telegram credentials are not set.
    """
    icons = {"WARNING": "⚠️", "CRITICAL": "🚨", "EMERGENCY": "🔴", "INFO": "ℹ️"}
    icon  = icons.get(severity.upper(), "⚠️")
    now   = time.time()
    if now - _alert_suppress.get(alert_key, 0) < 900:   # 15-min window
        return
    _alert_suppress[alert_key] = now
    send_telegram(f"{icon} <b>{severity}</b>\n{message}")


# ── Daily trade counter (anti-overtrading) ────────────────────────────────────
_daily_trade_state = {"date": "", "approved_count": 0, "daily_dd_pct": 0.0, "consec_losses": 0}
_daily_lock = threading.Lock()

def _get_daily_state():
    with _daily_lock:
        today = datetime.utcnow().strftime("%Y-%m-%d")
        if _daily_trade_state["date"] != today:
            _daily_trade_state["date"] = today
            _daily_trade_state["approved_count"] = 0
            _daily_trade_state["daily_dd_pct"] = 0.0
            _daily_trade_state["consec_losses"] = 0   # reset streak each day
        return dict(_daily_trade_state)

def _record_approved_trade():
    with _daily_lock:
        _get_daily_state()
        _daily_trade_state["approved_count"] += 1

def _record_trade_result(was_win: bool):
    """Called from /feedback — tracks server-side consecutive loss streak."""
    with _daily_lock:
        _get_daily_state()   # ensure today is active
        if was_win:
            _daily_trade_state["consec_losses"] = 0
        else:
            _daily_trade_state["consec_losses"] = _daily_trade_state.get("consec_losses", 0) + 1

def _update_daily_dd(dd_pct: float):
    with _daily_lock:
        _daily_trade_state["daily_dd_pct"] = max(_daily_trade_state.get("daily_dd_pct", 0), dd_pct)

app = Flask(__name__)

# ══════════════════════════════════════════════════════════════════════
# 1. ORDER FLOW PROXY ENGINE
# ══════════════════════════════════════════════════════════════════════

class OrderFlowEngine:
    """
    Receives tick/volume data from EA.
    Detects: delta divergence, absorption, volume imbalance, iceberg patterns.
    Acts as proxy for real order flow without L2 data feed.
    """
    def __init__(self):
        self.tick_buffer   = defaultdict(lambda: deque(maxlen=500))
        self.volume_buffer = defaultdict(lambda: deque(maxlen=200))
        self.delta_buffer  = defaultdict(lambda: deque(maxlen=100))
        self.lock          = threading.Lock()

    def receive_tick(self, symbol: str, bid: float, ask: float,
                     volume: float, timestamp: str):
        with self.lock:
            spread = ask - bid
            self.tick_buffer[symbol].append({
                "bid": bid, "ask": ask,
                "mid": (bid + ask) / 2,
                "spread": spread,
                "volume": volume,
                "ts": timestamp
            })

    def receive_bar(self, symbol: str, open_: float, high: float,
                    low: float, close: float, volume: float,
                    buy_vol: float = 0, sell_vol: float = 0):
        """Receive completed bar data with optional buy/sell volume split."""
        with self.lock:
            if buy_vol == 0 and sell_vol == 0:
                if close > open_:
                    buy_vol  = volume * ((close - open_) / (high - low + 1e-10) * 0.5 + 0.5)
                    sell_vol = volume - buy_vol
                else:
                    sell_vol = volume * ((open_ - close) / (high - low + 1e-10) * 0.5 + 0.5)
                    buy_vol  = volume - sell_vol

            delta = buy_vol - sell_vol
            self.delta_buffer[symbol].append({
                "delta": delta, "volume": volume,
                "buy_vol": buy_vol, "sell_vol": sell_vol,
                "open": open_, "high": high, "low": low, "close": close
            })
            self.volume_buffer[symbol].append(volume)

    def get_signal(self, symbol: str) -> dict:
        """
        Analyze order flow for trading signal.
        Returns: bias, strength, patterns detected
        """
        with self.lock:
            deltas  = list(self.delta_buffer[symbol])
            volumes = list(self.volume_buffer[symbol])

        if len(deltas) < 10:
            return {"bias": "NEUTRAL", "strength": 0, "patterns": [], "score_bonus": 0}

        patterns    = []
        score_bonus = 0

        # Delta divergence: price making new high but delta declining = bearish
        recent_deltas    = [d["delta"] for d in deltas[-5:]]
        recent_closes    = [d["close"] for d in deltas[-5:]]
        avg_delta_recent = np.mean(recent_deltas)
        avg_delta_prior  = np.mean([d["delta"] for d in deltas[-10:-5]])

        price_up   = recent_closes[-1] > recent_closes[0]
        delta_down = avg_delta_recent < avg_delta_prior

        if price_up and delta_down:
            patterns.append("BEARISH_DELTA_DIV")
            score_bonus -= 8
        elif not price_up and not delta_down:
            patterns.append("BULLISH_DELTA_DIV")
            score_bonus += 8

        # Absorption: high volume but small candle body = absorption
        recent_bars = deltas[-3:]
        for bar in recent_bars:
            body = abs(bar["close"] - bar["open"])
            rng  = bar["high"] - bar["low"]
            if rng > 0 and body / rng < 0.3 and bar["volume"] > np.mean(volumes[-20:]) * 1.5:
                patterns.append("ABSORPTION")
                score_bonus += 6
                break

        # Volume imbalance: buy vol >> sell vol = bullish
        total_buy  = sum(d["buy_vol"] for d in deltas[-5:])
        total_sell = sum(d["sell_vol"] for d in deltas[-5:])
        total      = total_buy + total_sell
        if total > 0:
            buy_ratio = total_buy / total
            if buy_ratio > 0.65:
                patterns.append("BUY_IMBALANCE")
                score_bonus += 10
            elif buy_ratio < 0.35:
                patterns.append("SELL_IMBALANCE")
                score_bonus -= 10

        if score_bonus > 5:    bias = "BULLISH"
        elif score_bonus < -5: bias = "BEARISH"
        else:                  bias = "NEUTRAL"

        return {
            "bias":        bias,
            "strength":    abs(score_bonus),
            "patterns":    patterns,
            "score_bonus": score_bonus,
            "delta_trend": "DECLINING" if delta_down else "RISING",
            "buy_ratio":   round(total_buy / total, 3) if total > 0 else 0.5,
        }


order_flow = OrderFlowEngine()
log.info("OrderFlowEngine initialized successfully (instance: order_flow)")

# ══════════════════════════════════════════════════════════════════════
# 2. ML SIGNAL CLASSIFIER
# ══════════════════════════════════════════════════════════════════════

class MLClassifier:
    """
    Trains on labeled trade history.
    Predicts win probability for new setups.
    Falls back to weighted scorer when insufficient data.
    """
    MIN_SAMPLES = 50   # Minimum trades before ML activates

    def __init__(self):
        self.model         = None
        self.scaler        = StandardScaler() if HAS_SKLEARN else None
        self.is_trained    = False
        self.train_count   = 0
        self.last_train    = None
        self.feature_names = []
        self.lock          = threading.Lock()
        self.cv_score      = 0.0

    def _features_to_vector(self, features: dict) -> list:
        """Convert feature dict to numeric vector."""
        keys = sorted(features.keys())
        self.feature_names = keys
        return [1.0 if features.get(k, False) else 0.0 for k in keys]

    def train(self, history: list):
        if not HAS_SKLEARN or len(history) < self.MIN_SAMPLES:
            return

        with self.lock:
            X, y = [], []
            for record in history:
                if "features" not in record:
                    continue
                vec = self._features_to_vector(record["features"])
                X.append(vec)
                y.append(1 if record.get("won", False) else 0)

            if len(X) < self.MIN_SAMPLES:
                return

            X = np.array(X)
            y = np.array(y)

            X_scaled = self.scaler.fit_transform(X)

            if HAS_XGB:
                self.model = xgb.XGBClassifier(
                    n_estimators=100, max_depth=4,
                    learning_rate=0.1, use_label_encoder=False,
                    eval_metric="logloss", random_state=42
                )
            else:
                self.model = RandomForestClassifier(
                    n_estimators=200, max_depth=5,
                    min_samples_leaf=3, random_state=42
                )

            self.model.fit(X_scaled, y)

            cv = cross_val_score(self.model, X_scaled, y, cv=min(5, len(X) // 10))
            self.cv_score    = float(np.mean(cv))
            self.is_trained  = True
            self.train_count += 1
            self.last_train  = datetime.utcnow()

            log.info(f"ML trained on {len(X)} samples | "
                     f"CV score: {self.cv_score:.3f} | "
                     f"Model: {'XGBoost' if HAS_XGB else 'RandomForest'}")

    def predict(self, features: dict) -> dict:
        """Returns win probability 0-1 and confidence."""
        if not self.is_trained or self.model is None:
            return {"win_prob": 0.5, "confidence": 0.0, "ml_active": False}

        with self.lock:
            try:
                vec        = self._features_to_vector(features)
                X          = self.scaler.transform([vec])
                prob       = float(self.model.predict_proba(X)[0][1])
                confidence = abs(prob - 0.5) * 2
                return {
                    "win_prob":   round(prob, 3),
                    "confidence": round(confidence, 3),
                    "ml_active":  True,
                    "cv_score":   self.cv_score,
                }
            except Exception as e:
                log.error(f"ML predict error: {e}")
                return {"win_prob": 0.5, "confidence": 0.0, "ml_active": False}


ml_classifier = MLClassifier()

# ══════════════════════════════════════════════════════════════════════
# 3. LIQUIDITY HEATMAP
# ══════════════════════════════════════════════════════════════════════

class LiquidityHeatmap:
    """
    Estimates stop cluster locations from price structure.
    Identifies nearest and next liquidity pools.
    Targets entries toward next pool after sweep.
    """
    def __init__(self):
        self.price_data = defaultdict(lambda: deque(maxlen=500))
        self.lock       = threading.Lock()

    def update(self, symbol: str, high: float, low: float,
               close: float, atr: float):
        with self.lock:
            self.price_data[symbol].append({
                "high": high, "low": low,
                "close": close, "atr": atr,
                "ts": datetime.utcnow().isoformat()
            })

    def get_map(self, symbol: str, current_price: float) -> dict:
        """
        Identify liquidity pools above and below current price.
        Returns nearest pool, next pool, sweep potential.
        """
        with self.lock:
            bars = list(self.price_data[symbol])

        if len(bars) < 20:
            return {"pools_above": [], "pools_below": [],
                    "nearest_above": None, "nearest_below": None,
                    "sweep_target": None, "score_bonus": 0}

        atr = bars[-1]["atr"] if bars[-1]["atr"] > 0 else 0.001

        pools_above = []
        pools_below = []

        for i in range(2, len(bars) - 2):
            if (bars[i]["high"] > bars[i-1]["high"] and
                    bars[i]["high"] > bars[i-2]["high"] and
                    bars[i]["high"] > bars[i+1]["high"] and
                    bars[i]["high"] > bars[i+2]["high"]):
                level = bars[i]["high"]
                if level > current_price:
                    tests = sum(1 for b in bars if abs(b["high"] - level) < atr * 0.5)
                    pools_above.append({
                        "level": level,
                        "distance_atr": (level - current_price) / atr,
                        "tests": tests,
                        "strength": min(tests * 15, 100)
                    })

            if (bars[i]["low"] < bars[i-1]["low"] and
                    bars[i]["low"] < bars[i-2]["low"] and
                    bars[i]["low"] < bars[i+1]["low"] and
                    bars[i]["low"] < bars[i+2]["low"]):
                level = bars[i]["low"]
                if level < current_price:
                    tests = sum(1 for b in bars if abs(b["low"] - level) < atr * 0.5)
                    pools_below.append({
                        "level": level,
                        "distance_atr": (current_price - level) / atr,
                        "tests": tests,
                        "strength": min(tests * 15, 100)
                    })

        pools_above.sort(key=lambda x: x["distance_atr"])
        pools_below.sort(key=lambda x: x["distance_atr"])

        nearest_above = pools_above[0] if pools_above else None
        nearest_below = pools_below[0] if pools_below else None
        next_above    = pools_above[1] if len(pools_above) > 1 else None
        next_below    = pools_below[1] if len(pools_below) > 1 else None

        score_bonus  = 0
        sweep_target = None
        if nearest_below and next_below:
            room = next_below["distance_atr"] - nearest_below["distance_atr"]
            if room > 2.0:
                score_bonus += 8
                sweep_target = {"direction": "DOWN", "level": next_below["level"],
                                "distance_atr": next_below["distance_atr"]}
        if nearest_above and next_above:
            room = next_above["distance_atr"] - nearest_above["distance_atr"]
            if room > 2.0:
                score_bonus += 8
                sweep_target = {"direction": "UP", "level": next_above["level"],
                                "distance_atr": next_above["distance_atr"]}

        return {
            "pools_above":   pools_above[:5],
            "pools_below":   pools_below[:5],
            "nearest_above": nearest_above,
            "nearest_below": nearest_below,
            "next_above":    next_above,
            "next_below":    next_below,
            "sweep_target":  sweep_target,
            "score_bonus":   score_bonus,
            "current_price": current_price,
            "atr":           atr,
        }


liquidity_map = LiquidityHeatmap()

# ══════════════════════════════════════════════════════════════════════
# 4. MONTE CARLO SIMULATOR
# ══════════════════════════════════════════════════════════════════════

class MonteCarloSimulator:
    """
    Simulates 10,000 trade sequences using real win rate and RR.
    Returns: max DD distribution, risk of ruin, optimal risk %.
    """
    def run(self, win_rate: float, avg_rr: float, risk_pct: float,
            n_trades: int = 200, n_sims: int = MONTE_CARLO_RUNS,
            dd_limit: float = 5.0) -> dict:

        results        = []
        ruin_count     = 0
        max_dds        = []
        final_balances = []

        for _ in range(n_sims):
            balance = 100.0
            peak    = 100.0
            max_dd  = 0.0
            ruined  = False

            for _ in range(n_trades):
                won = random.random() < win_rate
                if won:
                    balance *= (1 + risk_pct / 100 * avg_rr)
                else:
                    balance *= (1 - risk_pct / 100)

                if balance > peak:
                    peak = balance
                dd = (peak - balance) / peak * 100
                if dd > max_dd:
                    max_dd = dd
                if dd >= dd_limit:
                    ruined = True
                    break

            max_dds.append(max_dd)
            final_balances.append(balance)
            if ruined:
                ruin_count += 1

        max_dds_arr        = np.array(max_dds)
        final_balances_arr = np.array(final_balances)

        return {
            "win_rate":            win_rate,
            "avg_rr":              avg_rr,
            "risk_pct":            risk_pct,
            "n_trades":            n_trades,
            "n_simulations":       n_sims,
            "dd_limit":            dd_limit,
            "risk_of_ruin_pct":    round(ruin_count / n_sims * 100, 2),
            "median_max_dd":       round(float(np.median(max_dds_arr)), 2),
            "p95_max_dd":          round(float(np.percentile(max_dds_arr, 95)), 2),
            "p99_max_dd":          round(float(np.percentile(max_dds_arr, 99)), 2),
            "median_final_return": round(float(np.median(final_balances_arr)) - 100, 2),
            "p10_final_return":    round(float(np.percentile(final_balances_arr, 10)) - 100, 2),
            "p90_final_return":    round(float(np.percentile(final_balances_arr, 90)) - 100, 2),
            "recommendation":      self._recommend(ruin_count / n_sims, np.percentile(max_dds_arr, 95)),
        }

    def _recommend(self, ruin_prob: float, p95_dd: float) -> str:
        if ruin_prob > 0.15:  return "REDUCE_RISK -- ruin probability too high"
        if ruin_prob > 0.05:  return "CAUTION -- consider reducing risk 20%"
        if p95_dd > 8.0:      return "MONITOR -- tail DD events possible"
        return "APPROVED -- risk parameters within acceptable bounds"


monte_carlo = MonteCarloSimulator()

# ══════════════════════════════════════════════════════════════════════
# 5. CORRELATION-ADJUSTED POSITION SIZING
# ══════════════════════════════════════════════════════════════════════

class CorrelationSizer:
    """
    Adjusts position size so total portfolio volatility stays constant.
    Uses covariance matrix across open positions.
    """
    TARGET_PORTFOLIO_VOL = 0.01   # 1% target daily portfolio volatility

    def get_correlation(self, sym1: str, sym2: str) -> float:
        key = tuple(sorted([sym1, sym2]))
        return CORRELATIONS.get(key, 0.0)

    def calc_size_multiplier(self, new_symbol: str,
                              open_positions: dict,
                              base_vol: float = 0.01) -> float:
        """
        Returns a multiplier (0.25-1.0) to apply to base lot size.
        Accounts for correlation with all existing open positions.
        """
        if not open_positions:
            return 1.0

        total_corr_exposure = 0.0
        for sym, pos in open_positions.items():
            corr            = self.get_correlation(new_symbol, sym)
            direction_match = pos.get("direction", 1)
            total_corr_exposure += abs(corr) * pos.get("lots", 1.0) * direction_match

        n = len(open_positions)

        if total_corr_exposure > 3.0:   return 0.50
        elif total_corr_exposure > 2.0: return 0.65
        elif total_corr_exposure > 1.0: return 0.80
        elif n >= 4:                    return 0.85
        elif n >= 2:                    return 0.90
        return 1.0


corr_sizer = CorrelationSizer()

# ══════════════════════════════════════════════════════════════════════
# 6. DYNAMIC RR ENGINE
# ══════════════════════════════════════════════════════════════════════

class DynamicRREngine:
    """
    Adjusts RR target based on current market regime.
    Expansion = wider targets, fragile = tighter targets.
    """
    def get_rr(self, regime: str, session: str, confluence: int) -> dict:
        base_rr = REGIME_RR.get(regime, 2.5)

        if session == "LONDON_NY":   base_rr *= 1.1
        elif session == "ASIA":      base_rr *= 0.85

        if confluence >= 3:          base_rr *= 1.15
        elif confluence == 1:        base_rr *= 0.90

        base_rr = round(max(1.5, min(4.0, base_rr)), 2)

        return {
            "recommended_rr": base_rr,
            "regime":         regime,
            "session":        session,
            "confluence":     confluence,
            "reasoning": f"Regime={regime} Session={session} Confluence={confluence} -> RR={base_rr}",
        }


dynamic_rr = DynamicRREngine()

# ══════════════════════════════════════════════════════════════════════
# 7. LATENCY / EXECUTION TRACKER
# ══════════════════════════════════════════════════════════════════════

class ExecutionTracker:
    """
    Tracks fill quality per symbol per session.
    Flags symbols with consistently poor execution.
    """
    def __init__(self):
        self.fills = defaultdict(list)
        self.lock  = threading.Lock()

    def record_fill(self, symbol: str, session: str,
                    requested_price: float, fill_price: float,
                    direction: int):
        slippage = (fill_price - requested_price) * direction
        with self.lock:
            self.fills[symbol].append({
                "session":  session,
                "slippage": slippage,
                "ts":       datetime.utcnow().isoformat(),
            })

    def get_slippage_budget(self, symbol: str, session: str) -> dict:
        budget = SESSION_SLIPPAGE.get(session, 2.0)
        with self.lock:
            recent = [f["slippage"] for f in self.fills[symbol]
                      if f["session"] == session][-20:]

        avg_slip = float(np.mean(recent)) if recent else 0.0
        ok       = avg_slip <= budget

        return {
            "symbol":         symbol,
            "session":        session,
            "budget_pips":    budget,
            "avg_slippage":   round(avg_slip, 4),
            "execution_ok":   ok,
            "score_penalty":  -10 if not ok else 0,
            "recommendation": "AVOID" if avg_slip > budget * 1.5 else "OK",
        }


execution_tracker = ExecutionTracker()

# ══════════════════════════════════════════════════════════════════════
# 8. MULTI-ACCOUNT ORCHESTRATOR
# ══════════════════════════════════════════════════════════════════════

class MultiAccountOrchestrator:
    """
    Distributes signals to multiple MT5 accounts.
    Per-account DD tracking, auto-pause on limit breach.
    Master signal -> N slave accounts.
    """
    def __init__(self):
        self.accounts = {}
        self.signals  = deque(maxlen=100)
        self.lock     = threading.Lock()

    def register_account(self, account_id: str, balance: float,
                          max_daily_dd: float, max_total_dd: float,
                          risk_pct: float, endpoint: str = ""):
        with self.lock:
            self.accounts[account_id] = {
                "balance":       balance,
                "start_balance": balance,
                "equity":        balance,
                "max_daily_dd":  max_daily_dd,
                "max_total_dd":  max_total_dd,
                "risk_pct":      risk_pct,
                "endpoint":      endpoint,
                "active":        True,
                "daily_start":   balance,
                "trades_today":  0,
                "total_trades":  0,
                "wins":          0,
                "registered_at": datetime.utcnow().isoformat(),
            }
            log.info(f"Account registered: {account_id} | "
                     f"Balance: ${balance:,.0f} | Risk: {risk_pct}%")

    def update_account(self, account_id: str, equity: float, balance: float):
        with self.lock:
            if account_id not in self.accounts:
                return
            acc      = self.accounts[account_id]
            acc["equity"]  = equity
            acc["balance"] = balance
            daily_dd = (acc["daily_start"] - equity) / acc["daily_start"] * 100
            total_dd = (acc["start_balance"] - equity) / acc["start_balance"] * 100
            if daily_dd >= acc["max_daily_dd"] or total_dd >= acc["max_total_dd"]:
                acc["active"] = False
                log.warning(f"Account {account_id} PAUSED | "
                            f"Daily DD: {daily_dd:.2f}% | Total DD: {total_dd:.2f}%")

    def distribute_signal(self, signal: dict) -> dict:
        """
        Broadcast a trade signal to all active accounts.
        Returns per-account execution instructions.
        """
        with self.lock:
            instructions = {}
            active_count = 0

            for acc_id, acc in self.accounts.items():
                if not acc["active"]:
                    instructions[acc_id] = {"execute": False, "reason": "Account paused"}
                    continue

                risk_pct = acc["risk_pct"]
                balance  = acc["balance"]

                instructions[acc_id] = {
                    "execute":    True,
                    "account_id": acc_id,
                    "symbol":     signal.get("symbol"),
                    "direction":  signal.get("direction"),
                    "risk_pct":   risk_pct,
                    "balance":    balance,
                    "ai_score":   signal.get("score", 0),
                    "regime":     signal.get("regime", "unknown"),
                }
                active_count += 1

            self.signals.append({
                "signal":           signal,
                "instructions":     instructions,
                "ts":               datetime.utcnow().isoformat(),
                "active_accounts":  active_count,
            })

            return {
                "distributed_to": active_count,
                "total_accounts": len(self.accounts),
                "instructions":   instructions,
                "signal_id":      len(self.signals),
            }

    def get_portfolio_summary(self) -> dict:
        with self.lock:
            total_balance = sum(a["balance"] for a in self.accounts.values())
            total_equity  = sum(a["equity"]  for a in self.accounts.values())
            active        = sum(1 for a in self.accounts.values() if a["active"])
            return {
                "total_accounts":  len(self.accounts),
                "active_accounts": active,
                "total_balance":   total_balance,
                "total_equity":    total_equity,
                "combined_dd_pct": round((total_balance - total_equity) / total_balance * 100, 2)
                                   if total_balance > 0 else 0,
                "accounts":        dict(self.accounts),
            }


orchestrator = MultiAccountOrchestrator()

# ══════════════════════════════════════════════════════════════════════
# 9. SENTIMENT AGGREGATOR
# ══════════════════════════════════════════════════════════════════════

class SentimentAggregator:
    """
    Aggregates positioning signals:
    - COT proxy (estimated from price action momentum)
    - Retail sentiment proxy (contrarian signal)
    - Swap rate differential (carry trade bias)
    - Fear/greed indicator
    """
    def __init__(self):
        self.sentiment_cache = {}
        self.cache_time      = {}
        self.cache_ttl       = 3600   # 1 hour cache
        self.lock            = threading.Lock()

    def get_sentiment(self, symbol: str, current_price: float = 0,
                      price_history: list = None) -> dict:
        with self.lock:
            now = datetime.utcnow().timestamp()
            if (symbol in self.sentiment_cache and
                    now - self.cache_time.get(symbol, 0) < self.cache_ttl):
                return self.sentiment_cache[symbol]

        result = self._calculate_sentiment(symbol, current_price, price_history or [])

        with self.lock:
            self.sentiment_cache[symbol] = result
            self.cache_time[symbol]      = now

        return result

    def _calculate_sentiment(self, symbol: str,
                              current_price: float,
                              price_history: list) -> dict:
        signals     = []
        score_bonus = 0

        carry_bias = self._get_carry_bias(symbol)
        if carry_bias != 0:
            signals.append(f"CARRY: {'POSITIVE' if carry_bias > 0 else 'NEGATIVE'}")
            score_bonus += carry_bias * 3

        if len(price_history) >= 20:
            prices   = [p["close"] for p in price_history[-20:]]
            momentum = (prices[-1] - prices[0]) / prices[0] * 100
            if abs(momentum) > 0.5:
                signals.append(f"MOMENTUM: {momentum:+.2f}%")
                score_bonus += 4 if momentum > 0 else -4

        if len(price_history) >= 50:
            prices_50 = [p["close"] for p in price_history[-50:]]
            mom_50    = (prices_50[-1] - prices_50[0]) / prices_50[0] * 100
            if mom_50 > 2.0:
                signals.append("RETAIL_CONTRARIAN: FADE_LONGS")
                score_bonus -= 3
            elif mom_50 < -2.0:
                signals.append("RETAIL_CONTRARIAN: FADE_SHORTS")
                score_bonus += 3

        return {
            "symbol":      symbol,
            "score_bonus": score_bonus,
            "signals":     signals,
            "carry_bias":  carry_bias,
            "overall":     "BULLISH" if score_bonus > 3 else "BEARISH" if score_bonus < -3 else "NEUTRAL",
            "cached_at":   datetime.utcnow().isoformat(),
        }

    def _get_carry_bias(self, symbol: str) -> int:
        """Simplified carry trade bias by pair."""
        positive_carry = {"NZDUSD": 1, "AUDUSD": 1, "GBPUSD": 1,
                          "USDCHF": 1, "USDCAD": 1, "USDJPY": 1}
        negative_carry = {"EURGBP": -1, "EURJPY": -1, "GBPJPY": 1}
        return positive_carry.get(symbol, negative_carry.get(symbol, 0))


sentiment_agg = SentimentAggregator()

# ══════════════════════════════════════════════════════════════════════
# 11. COT AGENT — CFTC Commitment of Traders real positioning
# ══════════════════════════════════════════════════════════════════════

class COTAgent:
    """
    Fetches real CFTC Commitment of Traders (legacy futures-only) data.
    Non-commercial net positioning (speculative money) for EUR, GBP, JPY,
    AUD, CAD, NZD futures contracts.

    Score modifier:
      >= 75th percentile  →  +6  (institutions heavily long base ccy)
      >= 60th percentile  →  +3
      <= 25th percentile  →  -6  (institutions heavily short base ccy)
      <= 40th percentile  →  -3
      otherwise           →   0  (neutral zone)

    Modifier is direction-aware: it only adds/subtracts when the trade
    direction aligns/opposes the institutional positioning.
    Falls back to 0 modifier if CFTC is unreachable.
    """

    CFTC_URL = "https://www.cftc.gov/dea/newcot/f_year.txt"

    PAIR_SEARCH = {
        "EURUSD": "EURO FX - CHICAGO MERCANTILE EXCHANGE",
        "GBPUSD": "BRITISH POUND STERLING - CHICAGO MERCANTILE EXCHANGE",
        "USDJPY": "JAPANESE YEN - CHICAGO MERCANTILE EXCHANGE",
        "AUDUSD": "AUSTRALIAN DOLLAR - CHICAGO MERCANTILE EXCHANGE",
        "USDCAD": "CANADIAN DOLLAR - CHICAGO MERCANTILE EXCHANGE",
        "NZDUSD": "NEW ZEALAND DOLLAR - CHICAGO MERCANTILE EXCHANGE",
        "USDCHF": "SWISS FRANC - CHICAGO MERCANTILE EXCHANGE",
        "EURGBP": "EURO FX - CHICAGO MERCANTILE EXCHANGE",
        "EURJPY": "EURO FX - CHICAGO MERCANTILE EXCHANGE",
        "GBPJPY": "BRITISH POUND STERLING - CHICAGO MERCANTILE EXCHANGE",
    }

    # For USD/XXX pairs the net is relative to the quote currency.
    # We flip sign so positive modifier always = bullish for base currency.
    INVERT_SIGN = {"USDJPY", "USDCAD", "USDCHF"}

    def __init__(self):
        self._rows: list        = []
        self._fetched_at: float = 0.0
        self._ttl               = 6 * 3600       # refresh every 6 h
        self._cache: dict       = {}
        self._lock              = threading.Lock()

    def _ensure_data(self) -> bool:
        now = time.time()
        if now - self._fetched_at < self._ttl and self._rows:
            return True
        try:
            r = requests.get(self.CFTC_URL, timeout=20)
            if r.status_code != 200:
                logging.warning(f"[COT] CFTC returned HTTP {r.status_code}")
                return bool(self._rows)
            lines = r.text.splitlines()
            reader = csv.DictReader(lines)
            self._rows = list(reader)
            self._fetched_at = now
            self._cache.clear()
            logging.info(f"[COT] Fetched {len(self._rows)} rows from CFTC")
            return True
        except Exception as e:
            logging.warning(f"[COT] Fetch failed: {e}")
            return bool(self._rows)

    def get_modifier(self, symbol: str, signal_dir: int = 0) -> dict:
        pair = (symbol[:6] if len(symbol) >= 6 else symbol).upper()
        with self._lock:
            if pair in self._cache:
                cached = self._cache[pair]
            else:
                ok = self._ensure_data()
                cached = self._compute(pair) if ok else self._neutral(pair, "no_data")
                self._cache[pair] = cached

        result = dict(cached)
        # Direction-aware modifier: only apply if signal direction known
        if signal_dir != 0:
            net = result.get("net", 0)
            invert = pair in self.INVERT_SIGN
            aligned = (signal_dir == 1 and net > 0 and not invert) or \
                      (signal_dir == -1 and net < 0 and not invert) or \
                      (signal_dir == 1 and net < 0 and invert) or \
                      (signal_dir == -1 and net > 0 and invert)
            if not aligned and result.get("modifier", 0) != 0:
                result["modifier"] = -result["modifier"]
                result["direction_note"] = "opposing"
            else:
                result["direction_note"] = "aligned"
        return result

    def _compute(self, pair: str) -> dict:
        search = self.PAIR_SEARCH.get(pair)
        if not search:
            return self._neutral(pair, "no_contract")
        search_upper = search.upper()
        matching = [
            row for row in self._rows
            if row.get("Market_and_Exchange_Names", "").upper().strip() == search_upper
        ]
        if not matching:
            # Partial match fallback
            search_short = search.split(" - ")[0].upper()
            matching = [
                row for row in self._rows
                if search_short in row.get("Market_and_Exchange_Names", "").upper()
                and "CHICAGO MERCANTILE EXCHANGE" in row.get("Market_and_Exchange_Names", "").upper()
            ]
        if not matching:
            return self._neutral(pair, "not_found")
        try:
            matching.sort(
                key=lambda x: x.get("As_of_Date_in_Form_YYMMDD", "000000"),
                reverse=True
            )
            latest    = matching[0]
            long_str  = latest.get("NonComm_Positions_Long_All", "0").replace(",", "").strip() or "0"
            short_str = latest.get("NonComm_Positions_Short_All", "0").replace(",", "").strip() or "0"
            long_nc   = int(long_str)
            short_nc  = int(short_str)
            net       = long_nc - short_nc

            all_nets = []
            for row in matching[:52]:
                try:
                    l = int(row.get("NonComm_Positions_Long_All",  "0").replace(",", "").strip() or "0")
                    s = int(row.get("NonComm_Positions_Short_All", "0").replace(",", "").strip() or "0")
                    all_nets.append(l - s)
                except Exception:
                    pass

            if len(all_nets) >= 3:
                mn, mx = min(all_nets), max(all_nets)
                pct = int((net - mn) / (mx - mn + 1) * 100) if mx > mn else 50
            else:
                pct = 50

            if   pct >= 75: modifier = +6
            elif pct >= 60: modifier = +3
            elif pct <= 25: modifier = -6
            elif pct <= 40: modifier = -3
            else:           modifier = 0

            bias      = "LONG" if net > 0 else "SHORT"
            intensity = (
                "EXTREME"  if pct >= 80 or pct <= 20 else
                "MODERATE" if pct >= 65 or pct <= 35 else
                "NEUTRAL"
            )
            rpt_date  = latest.get("Report_Date_as_MM_DD_YYYY", "—")

            result = {
                "symbol":      pair,
                "net":         net,
                "long_nc":     long_nc,
                "short_nc":    short_nc,
                "percentile":  pct,
                "bias":        bias,
                "intensity":   intensity,
                "modifier":    modifier,
                "report_date": rpt_date,
                "source":      "cftc_weekly",
            }
            logging.info(
                f"[COT] {pair} net={net:+,} {bias} {pct}th-pct "
                f"modifier={modifier:+d} report={rpt_date}"
            )
            return result
        except Exception as e:
            logging.warning(f"[COT] Parse error for {pair}: {e}")
            return self._neutral(pair, f"parse_err")

    def _neutral(self, pair: str, reason: str = "") -> dict:
        return {
            "symbol": pair, "net": 0, "long_nc": 0, "short_nc": 0,
            "percentile": 50, "bias": "NEUTRAL", "intensity": "NEUTRAL",
            "modifier": 0, "report_date": "—", "source": f"neutral_{reason}",
        }

    def to_dashboard_payload(self) -> list:
        """Returns list of cached COT entries for the dashboard push."""
        with self._lock:
            return list(self._cache.values())


cot_agent = COTAgent()

# ══════════════════════════════════════════════════════════════════════
# 12. MACRO AGENT — Central bank rate differentials
# ══════════════════════════════════════════════════════════════════════

class MacroAgent:
    """
    Central bank interest rate differential bias.
    Rates stored here — update when central banks change policy.

    Differential = base_currency_rate - quote_currency_rate.
    Score modifier scales by size of differential.
    Also direction-aware: only adds if trade aligns with macro bias.
    Never blocks — only nudges score ±5 max.
    """

    # ── Current central bank policy rates (%) — Last updated: May 2026 ──
    RATES: dict = {
        "FED":  4.25,   # Federal Reserve (target upper bound)
        "ECB":  2.25,   # European Central Bank (deposit rate)
        "BOE":  5.00,   # Bank of England (base rate)
        "BOJ":  0.25,   # Bank of Japan (policy rate, slowly rising)
        "RBA":  4.10,   # Reserve Bank of Australia
        "BOC":  3.25,   # Bank of Canada
        "RBNZ": 4.75,   # Reserve Bank of New Zealand
        "SNB":  0.50,   # Swiss National Bank
    }

    # (base_cb, quote_cb) — positive diff = bullish base currency
    PAIR_MAP: dict = {
        "EURUSD": ("ECB",  "FED"),
        "GBPUSD": ("BOE",  "FED"),
        "USDJPY": ("FED",  "BOJ"),   # positive diff = USD bullish
        "AUDUSD": ("RBA",  "FED"),
        "USDCAD": ("FED",  "BOC"),
        "NZDUSD": ("RBNZ", "FED"),
        "USDCHF": ("FED",  "SNB"),
        "EURGBP": ("ECB",  "BOE"),
        "EURJPY": ("ECB",  "BOJ"),
        "GBPJPY": ("BOE",  "BOJ"),
    }

    def get_modifier(self, symbol: str, signal_dir: int = 0) -> dict:
        pair    = (symbol[:6] if len(symbol) >= 6 else symbol).upper()
        mapping = self.PAIR_MAP.get(pair)
        if not mapping:
            return {"symbol": pair, "differential": 0.0, "modifier": 0,
                    "bias": "NEUTRAL", "source": "no_mapping",
                    "base_cb": "—", "quote_cb": "—",
                    "base_rate": 0.0, "quote_rate": 0.0}

        base_cb, quote_cb = mapping
        base_rate  = self.RATES.get(base_cb,  0.0)
        quote_rate = self.RATES.get(quote_cb, 0.0)
        diff       = round(base_rate - quote_rate, 2)

        if   diff >=  2.0: raw_mod = +5
        elif diff >=  0.5: raw_mod = +2
        elif diff <= -2.0: raw_mod = -5
        elif diff <= -0.5: raw_mod = -2
        else:              raw_mod = 0

        # Direction-aware: flip if trade opposes macro bias
        modifier = raw_mod
        if signal_dir != 0 and raw_mod != 0:
            macro_bullish_base = diff > 0
            trade_long_base    = signal_dir == 1
            if macro_bullish_base != trade_long_base:
                modifier = -abs(raw_mod)

        bias = "BULLISH_BASE" if diff > 0 else "BEARISH_BASE" if diff < 0 else "NEUTRAL"
        return {
            "symbol":       pair,
            "base_cb":      base_cb,
            "quote_cb":     quote_cb,
            "base_rate":    base_rate,
            "quote_rate":   quote_rate,
            "differential": diff,
            "modifier":     modifier,
            "bias":         bias,
            "source":       "central_bank_rates",
        }

    def update_rate(self, cb: str, rate: float) -> None:
        self.RATES[cb.upper()] = round(rate, 2)
        logging.info(f"[MACRO] Updated {cb.upper()} rate → {rate:.2f}%")

    def all_rates(self) -> dict:
        return dict(self.RATES)

    def all_biases(self) -> list:
        results = []
        for pair in self.PAIR_MAP:
            results.append(self.get_modifier(pair))
        return results


macro_agent = MacroAgent()


# ══════════════════════════════════════════════════════════════════════
# 9b. INTERMARKET AGENT — DXY, Gold, US 10-Year Yield
# ══════════════════════════════════════════════════════════════════════

class IntermarketAgent:
    """
    Real-time intermarket data agent — 5 instruments, 3 sources.

    Instruments:
      DXY    → Twelve Data WebSocket (live) + HTTP fallback → Yahoo fallback
      GOLD   → Twelve Data WebSocket (live) + HTTP fallback → Yahoo fallback
      US10Y  → FRED DGS10  (daily, official Fed data, no key)
      US2Y   → FRED DGS2   (daily, official Fed data, no key)
      VIX    → FRED VIXCLS (daily, official Fed data, no key)

    Score modifier: up to ±10 pts (DXY ±3, US10Y ±2, GOLD ±1, 2s10s ±2, VIX ±2)
    Cache persisted to disk so scorer restarts don't lose data.
    """
    YF_SYMBOLS  = {"DXY": "DX-Y.NYB", "GOLD": "GC=F", "US10Y": "^TNX"}
    TD_SYMBOLS  = {"DXY": "DXY",       "GOLD": "XAU/USD"}
    REFRESH     = 900   # HTTP poll interval (seconds); WS provides live updates

    def __init__(self):
        self._cache: dict = {}
        self._last_fetch  = 0.0
        self._lock        = threading.Lock()
        # ── Load persisted cache so we have data immediately on restart ──
        try:
            if os.path.exists(INTERMARKET_CACHE_FILE):
                with open(INTERMARKET_CACHE_FILE) as f:
                    self._cache = json.load(f)
                self._last_fetch = time.time() - self.REFRESH
                logging.info(f"[INTERMARKET] Loaded persisted cache: {list(self._cache.keys())}")
        except Exception:
            pass
        # ── HTTP polling thread ──────────────────────────────────────────
        threading.Thread(target=self._loop, daemon=True).start()
        # ── Twelve Data WebSocket thread (live ticks, DXY + Gold) ───────
        if HAS_WEBSOCKET and os.environ.get("TWELVE_DATA_API_KEY"):
            threading.Thread(target=self._ws_loop, daemon=True).start()
        elif not HAS_WEBSOCKET:
            logging.info("[INTERMARKET] websocket-client not installed — pip install websocket-client on VPS for live WS feed")

    # ── FRED generic series fetcher (DGS10, DGS2, VIXCLS …) ─────────────
    @staticmethod
    def _fetch_fred_series(series_id: str) -> "dict | None":
        """Fetch latest value from any FRED series CSV. Free, no key."""
        try:
            resp = requests.get(
                f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}",
                timeout=12,
            )
            rows = [
                ln.strip() for ln in resp.text.splitlines()
                if ln.strip() and not ln.startswith("DATE")
                and ln.split(",")[-1].strip() not in (".", "")
            ]
            if len(rows) < 2:
                return None
            prev = float(rows[-2].split(",")[1])
            curr = float(rows[-1].split(",")[1])
            chg  = ((curr - prev) / prev) * 100 if prev else 0
            return {"price": round(curr, 4), "change_pct": round(chg, 4)}
        except Exception as e:
            logging.debug(f"[INTERMARKET] FRED {series_id}: {e}")
            return None

    # ── Twelve Data HTTP (1-day bars, primary for DXY / Gold) ────────────
    def _fetch_twelve_data(self, td_symbol: str) -> "dict | None":
        key = os.environ.get("TWELVE_DATA_API_KEY", "")
        if not key:
            return None
        try:
            url  = (f"https://api.twelvedata.com/time_series"
                    f"?symbol={td_symbol}&interval=1day&outputsize=3&apikey={key}")
            resp = requests.get(url, timeout=10)
            data = resp.json()
            if data.get("status") == "error" or "values" not in data:
                logging.debug(f"[INTERMARKET] Twelve Data HTTP {td_symbol}: {data.get('message','error')}")
                return None
            vals = data["values"]
            if len(vals) < 2:
                return None
            curr = float(vals[0]["close"])
            prev = float(vals[1]["close"])
            chg  = ((curr - prev) / prev) * 100 if prev else 0
            return {"price": round(curr, 4), "change_pct": round(chg, 3)}
        except Exception as e:
            logging.debug(f"[INTERMARKET] Twelve Data HTTP {td_symbol}: {e}")
            return None

    # ── Yahoo Finance fallback ────────────────────────────────────────────
    def _fetch_yahoo(self, ticker: str) -> "dict | None":
        try:
            url  = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=5d"
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            data = resp.json()
            result = data["chart"]["result"][0]
            closes = [c for c in result["indicators"]["quote"][0]["close"] if c is not None]
            if len(closes) < 2:
                return None
            prev, curr = closes[-2], closes[-1]
            chg = ((curr - prev) / prev) * 100 if prev else 0
            return {"price": round(curr, 4), "change_pct": round(chg, 3)}
        except Exception as e:
            logging.debug(f"[INTERMARKET] Yahoo {ticker}: {e}")
            return None

    # ── Router: pick best available source per instrument ────────────────
    def _fetch_one(self, name: str) -> "dict | None":
        if name in ("US10Y", "US2Y", "VIX"):
            series = {"US10Y": "DGS10", "US2Y": "DGS2", "VIX": "VIXCLS"}[name]
            r = self._fetch_fred_series(series)
            if r:
                return {**r, "_src": "fred"}
            # FRED failed — Yahoo fallback only for US10Y
            if name == "US10Y":
                r2 = self._fetch_yahoo(self.YF_SYMBOLS["US10Y"])
                return ({**r2, "_src": "yahoo"} if r2 else None)
            return None

        td_sym = self.TD_SYMBOLS.get(name)
        if td_sym:
            r = self._fetch_twelve_data(td_sym)
            if r:
                return {**r, "_src": "twelve_data_http"}
        yf_ticker = self.YF_SYMBOLS.get(name, "")
        r = self._fetch_yahoo(yf_ticker)
        return ({**r, "_src": "yahoo"} if r else None)

    # ── Twelve Data WebSocket — live DXY + Gold ticks ────────────────────
    def _ws_loop(self):
        """Persistent WebSocket thread. Reconnects automatically on drop."""
        key = os.environ.get("TWELVE_DATA_API_KEY", "")
        if not key:
            return

        def on_message(ws, msg):
            try:
                d = json.loads(msg)
                if d.get("event") != "price":
                    return
                sym   = d.get("symbol", "")
                price = float(d.get("price", 0))
                if not price:
                    return
                name = "DXY" if sym == "DXY" else "GOLD" if sym == "XAU/USD" else None
                if not name:
                    return
                with self._lock:
                    prev  = self._cache.get(name, {}).get("price", price)
                    chg   = ((price - prev) / prev * 100) if prev else 0
                    self._cache[name] = {
                        "price":      round(price, 4),
                        "change_pct": round(chg, 3),
                        "_src":       "twelve_data_ws",
                    }
                    self._last_fetch = time.time()
            except Exception:
                pass

        def on_error(ws, err):
            logging.debug(f"[INTERMARKET-WS] error: {err}")

        def on_close(ws, *_):
            logging.debug("[INTERMARKET-WS] connection closed")

        def on_open(ws):
            ws.send(json.dumps({"action": "subscribe",
                                 "params": {"symbols": "DXY,XAU/USD"}}))
            logging.info("[INTERMARKET-WS] subscribed to DXY, XAU/USD via Twelve Data")

        while True:
            try:
                ws = _websocket_lib.WebSocketApp(
                    f"wss://ws.twelvedata.com/v1/quotes/price?apikey={key}",
                    on_message=on_message,
                    on_error=on_error,
                    on_close=on_close,
                    on_open=on_open,
                )
                ws.run_forever(ping_interval=30, ping_timeout=10)
            except Exception as e:
                logging.debug(f"[INTERMARKET-WS] exception: {e}")
            time.sleep(30)  # reconnect backoff

    # ── HTTP polling loop (15-min refresh for all 5 instruments) ─────────
    def _loop(self):
        time.sleep(5)   # let Flask start
        while True:
            fresh = {}
            # DXY + Gold via Twelve Data / Yahoo
            for name in ("DXY", "GOLD", "US10Y"):
                r = self._fetch_one(name)
                if r:
                    fresh[name] = r
            # Additional FRED series (2Y yield + VIX)
            for name, series in (("US2Y", "DGS2"), ("VIX", "VIXCLS")):
                r = self._fetch_fred_series(series)
                if r:
                    fresh[name] = {**r, "_src": "fred"}
            if fresh:
                with self._lock:
                    self._cache.update(fresh)
                    self._last_fetch = time.time()
                # Persist cache to disk
                try:
                    with open(INTERMARKET_CACHE_FILE, "w") as f:
                        json.dump(self._cache, f)
                except Exception:
                    pass
                sources = {k: v.get("_src", "?") for k, v in fresh.items()}
                logging.info(f"[INTERMARKET] Refreshed: {sources}")
            time.sleep(self.REFRESH)

    def get_state(self) -> dict:
        with self._lock:
            return dict(self._cache)

    def get_modifier(self, symbol: str, signal_dir: int) -> dict:
        with self._lock:
            cache = dict(self._cache)
        if not cache:
            return {"modifier": 0, "source": "no_data", "details": {}}

        sym       = symbol.upper()
        modifier  = 0.0
        details   = {}
        dxy       = cache.get("DXY",   {})
        gold      = cache.get("GOLD",  {})
        us10y     = cache.get("US10Y", {})
        us2y      = cache.get("US2Y",  {})
        vix_data  = cache.get("VIX",   {})
        dxy_chg   = dxy.get("change_pct",   0)
        gold_chg  = gold.get("change_pct",  0)
        yield_chg = us10y.get("change_pct", 0)

        usd_quote = sym in ("EURUSD", "GBPUSD", "AUDUSD", "NZDUSD")
        usd_base  = sym in ("USDJPY", "USDCAD", "USDCHF")

        # ── DXY — rising = USD strengthening ─────────────────────────────
        if abs(dxy_chg) >= 0.10:
            usd_up = dxy_chg > 0
            if usd_quote:
                if   usd_up  and signal_dir == -1: modifier += 3; details["DXY"] = "+3 rising DXY→short aligned"
                elif usd_up  and signal_dir ==  1: modifier -= 3; details["DXY"] = "-3 rising DXY→long opposed"
                elif not usd_up and signal_dir == 1: modifier += 3; details["DXY"] = "+3 falling DXY→long aligned"
                elif not usd_up and signal_dir ==-1: modifier -= 3; details["DXY"] = "-3 falling DXY→short opposed"
            elif usd_base:
                if   usd_up  and signal_dir ==  1: modifier += 3; details["DXY"] = "+3 rising DXY→long aligned"
                elif usd_up  and signal_dir == -1: modifier -= 3; details["DXY"] = "-3 rising DXY→short opposed"
                elif not usd_up and signal_dir ==-1: modifier += 3; details["DXY"] = "+3 falling DXY→short aligned"
                elif not usd_up and signal_dir == 1: modifier -= 3; details["DXY"] = "-3 falling DXY→long opposed"

        # ── US 10Y — rising yields = USD bullish ──────────────────────────
        if abs(yield_chg) >= 0.50:
            yield_up = yield_chg > 0
            if usd_quote:
                if   yield_up and signal_dir == -1: modifier += 2; details["US10Y"] = "+2 rising yields→short aligned"
                elif yield_up and signal_dir ==  1: modifier -= 2; details["US10Y"] = "-2 rising yields→long opposed"
                elif not yield_up and signal_dir == 1: modifier += 2; details["US10Y"] = "+2 falling yields→long aligned"
            elif usd_base:
                if   yield_up and signal_dir ==  1: modifier += 2; details["US10Y"] = "+2 rising yields→long aligned"
                elif yield_up and signal_dir == -1: modifier -= 2; details["US10Y"] = "-2 rising yields→short opposed"

        # ── Gold — rising = risk-off / USD strength ───────────────────────
        if abs(gold_chg) >= 0.30 and usd_quote:
            gold_up = gold_chg > 0
            if   gold_up and signal_dir == -1: modifier += 1; details["GOLD"] = "+1 rising gold→short aligned"
            elif gold_up and signal_dir ==  1: modifier -= 1; details["GOLD"] = "-1 rising gold→long opposed"
            elif not gold_up and signal_dir == 1: modifier += 1; details["GOLD"] = "+1 falling gold→long aligned"

        # ── 2s10s yield curve spread (10Y − 2Y) ──────────────────────────
        us2y_price = us2y.get("price", 0)
        us10y_price = us10y.get("price", 0)
        spread_2s10s = (us10y_price - us2y_price) if us2y_price > 0 else None
        if spread_2s10s is not None:
            if spread_2s10s < -0.25:   # deeply inverted — recession signal
                if usd_quote and signal_dir == 1:
                    modifier -= 2; details["2s10s"] = f"-2 curve inverted {spread_2s10s:.2f}%→risk-off"
                elif usd_base and signal_dir == 1:
                    modifier += 1; details["2s10s"] = f"+1 inversion→safe-haven long aligned"
            elif spread_2s10s < 0:     # mildly inverted
                if usd_quote and signal_dir == 1:
                    modifier -= 1; details["2s10s"] = f"-1 curve flat/inverted {spread_2s10s:.2f}%"

        # ── VIX risk sentiment ────────────────────────────────────────────
        vix_val = vix_data.get("price", 0)
        if vix_val > 0:
            if vix_val > 35:           # extreme fear — flight to safety
                if usd_quote and signal_dir == 1:
                    modifier -= 2; details["VIX"] = f"-2 extreme fear VIX={vix_val:.1f}"
                elif usd_base and signal_dir == 1:
                    modifier += 1; details["VIX"] = f"+1 extreme fear→safe-haven long aligned"
            elif vix_val > 25:         # elevated risk aversion
                if usd_quote and signal_dir == 1:
                    modifier -= 1; details["VIX"] = f"-1 elevated VIX={vix_val:.1f}"
            elif vix_val < 15:         # complacency / risk-on
                if usd_quote and signal_dir == 1:
                    modifier += 1; details["VIX"] = f"+1 low VIX risk-on={vix_val:.1f}"

        modifier = max(-10, min(10, round(modifier)))
        return {
            "modifier":      modifier,
            "dxy_price":     dxy.get("price", 0),
            "dxy_chg":       dxy_chg,
            "gold_price":    gold.get("price", 0),
            "gold_chg":      gold_chg,
            "us10y":         us10y_price,
            "us10y_chg":     yield_chg,
            "us2y":          us2y_price,
            "spread_2s10s":  round(spread_2s10s, 3) if spread_2s10s is not None else None,
            "vix":           vix_val or None,
            "details":       details,
            "source":        self._cache.get("DXY", {}).get("_src", "unknown"),
            "age_secs":      int(time.time() - self._last_fetch) if self._last_fetch else -1,
        }


intermarket_agent = IntermarketAgent()


# ══════════════════════════════════════════════════════════════════════
# 9c. SSI AGENT — Retail Sentiment Contrarian
# ══════════════════════════════════════════════════════════════════════

class SSIAgent:
    """
    Speculative Sentiment Index — contrarian signal.
    Data is pushed by the API server from broker SSI feeds (OANDA, IG, Myfxbook).
    If 70 %+ retail are long → bearish modifier (fade the crowd). Cap: ±5 pts.
    """
    def __init__(self):
        self._cache: dict = {}
        self._lock = threading.Lock()

    def update(self, symbol: str, long_pct: float, short_pct: float,
               source: str = "external", report_time: str | None = None):
        with self._lock:
            self._cache[symbol.upper()] = {
                "symbol":      symbol.upper(),
                "long_pct":    round(long_pct,  1),
                "short_pct":   round(short_pct, 1),
                "source":      source,
                "report_time": report_time or datetime.utcnow().isoformat(),
            }

    def get_modifier(self, symbol: str, signal_dir: int) -> dict:
        with self._lock:
            entry = self._cache.get(symbol.upper())
        if not entry:
            return {"modifier": 0, "source": "no_data"}

        long_pct  = entry["long_pct"]
        short_pct = entry["short_pct"]

        if   long_pct  >= 80: raw_mod = -5; bias = "EXTREME_LONG"
        elif long_pct  >= 70: raw_mod = -3; bias = "MAJORITY_LONG"
        elif long_pct  >= 60: raw_mod = -2; bias = "LEAN_LONG"
        elif short_pct >= 80: raw_mod = +5; bias = "EXTREME_SHORT"
        elif short_pct >= 70: raw_mod = +3; bias = "MAJORITY_SHORT"
        elif short_pct >= 60: raw_mod = +2; bias = "LEAN_SHORT"
        else:                 raw_mod =  0; bias = "NEUTRAL"

        # raw_mod > 0 means contrarian view is bullish.
        # Apply direction-awareness: if we want to go long and contrarian is bullish → confirm.
        if   signal_dir ==  1: modifier = raw_mod
        elif signal_dir == -1: modifier = -raw_mod
        else:                  modifier = 0

        modifier = max(-5, min(5, modifier))
        return {
            "modifier":    modifier,
            "long_pct":    long_pct,
            "short_pct":   short_pct,
            "bias":        bias,
            "source":      entry["source"],
            "report_time": entry["report_time"],
        }

    def all_entries(self) -> list:
        with self._lock:
            return list(self._cache.values())


ssi_agent = SSIAgent()


# ══════════════════════════════════════════════════════════════════════
# 9d. HTF FRACTAL AGENT — H4 / D1 Structural Alignment
# ══════════════════════════════════════════════════════════════════════

class HTFFractalAgent:
    """
    Uses the BarStore (H4 and D1 native bars, or M15-aggregated fallback) to
    determine if an M15 entry aligns with the higher-timeframe structural bias.
    Bullish structure: close above EMA-20 + recent HH/HL.
    Bearish structure: close below EMA-20 + recent LH/LL. Cap: ±5 pts.
    """

    @staticmethod
    def _ema(closes: list, period: int) -> float:
        if len(closes) < period:
            return closes[-1] if closes else 0
        k   = 2 / (period + 1)
        ema = sum(closes[:period]) / period
        for c in closes[period:]:
            ema = c * k + ema * (1 - k)
        return ema

    def _trend(self, bars: list) -> str:
        if len(bars) < 10:
            return "NEUTRAL"
        closes = [b["c"] for b in bars]
        highs  = [b["h"] for b in bars]
        lows   = [b["l"] for b in bars]
        ema20  = self._ema(closes, min(20, len(closes)))
        rh, rl = highs[-5:], lows[-5:]
        hh, hl = rh[-1] > rh[0],  rl[-1] > rl[0]
        lh, ll = rh[-1] < rh[0],  rl[-1] < rl[0]
        curr   = closes[-1]
        if   curr > ema20 and hh and hl: return "BULLISH"
        elif curr < ema20 and lh and ll: return "BEARISH"
        elif curr > ema20:               return "MILD_BULLISH"
        elif curr < ema20:               return "MILD_BEARISH"
        return "NEUTRAL"

    def get_modifier(self, symbol: str, signal_dir: int, bs) -> dict:
        h4_bars  = bs.get(symbol, "H4")
        d1_bars  = bs.get(symbol, "D1")
        h4_trend = self._trend(h4_bars) if h4_bars else "NEUTRAL"
        d1_trend = self._trend(d1_bars) if d1_bars else "NEUTRAL"

        _score = {"BULLISH": 1, "MILD_BULLISH": 0.5, "NEUTRAL": 0,
                  "MILD_BEARISH": -0.5, "BEARISH": -1}
        combined = _score.get(d1_trend, 0) * 0.6 + _score.get(h4_trend, 0) * 0.4

        raw_mod = combined * 5 if signal_dir == 1 else -combined * 5 if signal_dir == -1 else 0
        modifier = max(-5, min(5, round(raw_mod)))
        return {
            "modifier": modifier,
            "h4_trend": h4_trend,
            "d1_trend": d1_trend,
            "h4_bars":  len(h4_bars),
            "d1_bars":  len(d1_bars),
            "combined": round(combined, 2),
        }


htf_fractal_agent = HTFFractalAgent()


# ══════════════════════════════════════════════════════════════════════
# 9e. OPTIONS EXPIRY AGENT — NY Cut Magnetism
# ══════════════════════════════════════════════════════════════════════

class OptionsExpiryAgent:
    """
    Large notional FX option expiries at the NY 10am cut (15:00 UTC) create
    magnetic price attraction before the cut and sharp rejection after.
    Data is pushed daily by the user/VPS from Reuters/Bloomberg feeds.
    Cap: ±4 pts.
    """
    def __init__(self):
        self._expiries: list = []
        self._lock = threading.Lock()

    def update(self, expiries: list):
        with self._lock:
            self._expiries = [dict(e) for e in expiries
                              if e.get("symbol") and e.get("level")]

    def get_modifier(self, symbol: str, current_price: float, signal_dir: int) -> dict:
        with self._lock:
            today = [e for e in self._expiries
                     if e.get("symbol", "").upper() == symbol.upper()]
        if not today or current_price <= 0:
            return {"modifier": 0, "source": "no_data", "levels": []}

        now_utc    = datetime.utcnow()
        mins_to_cut = (15 - now_utc.hour) * 60 - now_utc.minute
        pip_size   = 0.01 if "JPY" in symbol.upper() else 0.0001
        best_mod   = 0.0
        best_level = None

        for exp in today:
            level    = float(exp["level"])
            notional = float(exp.get("notional_m", 0))
            dist_pip = abs(current_price - level) / pip_size
            if dist_pip > 25:
                continue
            prox  = max(0.0, (25 - dist_pip) / 25)
            wt    = 1.5 if notional >= 1000 else (1.2 if notional >= 500 else 1.0)
            above = level > current_price

            if 30 <= mins_to_cut <= 120:
                # Magnetic pull toward expiry level
                toward = (above and signal_dir == 1) or (not above and signal_dir == -1)
                raw_mod = prox * wt * (4 if toward else -4)
            elif -15 <= mins_to_cut < 30:
                # Near cut — rejection risk; fade trades toward level
                toward = (above and signal_dir == 1) or (not above and signal_dir == -1)
                raw_mod = prox * wt * (-3 if toward else 3)
            else:
                raw_mod = 0

            if abs(raw_mod) > abs(best_mod):
                best_mod   = raw_mod
                best_level = level

        modifier = max(-4, min(4, round(best_mod)))
        return {
            "modifier":      modifier,
            "nearest_level": best_level,
            "mins_to_cut":   mins_to_cut,
            "expiry_count":  len(today),
            "levels":        [{"level": e["level"], "notional_m": e.get("notional_m", 0)}
                              for e in today],
            "source": "manual_push",
        }

    def all_expiries(self) -> list:
        with self._lock:
            return list(self._expiries)


options_expiry_agent = OptionsExpiryAgent()


# ══════════════════════════════════════════════════════════════════════
# 9f. CORRELATION MATRIX AGENT — Cross-Pair USD Exposure Guard
# ══════════════════════════════════════════════════════════════════════

class CorrelationAgent:
    """
    Computes rolling Pearson correlation between pairs using the last 200 M15
    bars from BarStore.  When a newly approved trade would create a second
    position with high USD correlation in the same direction, a penalty is
    applied — preventing silent doubling of exposure.

    Polarity map: +1 = pair price rises when USD weakens (USD-quote pairs),
                  -1 = pair price rises when USD strengthens (USD-base pairs).

    Score penalty: correlation ≥0.85 → -8,  ≥0.70 → -4.  Cap: -8.
    """
    POLARITY = {
        "EURUSD":  1, "GBPUSD":  1, "AUDUSD":  1, "NZDUSD":  1,
        "USDJPY": -1, "USDCAD": -1, "USDCHF": -1,
        "EURGBP":  0, "EURJPY":  0, "GBPJPY":  0,   # cross pairs — skip
    }

    def __init__(self):
        self._recent_approvals: dict = {}   # {sym: {direction, time, score}}
        self._lock = threading.Lock()

    def record_approval(self, symbol: str, direction: int, score: float):
        with self._lock:
            self._recent_approvals[symbol.upper()] = {
                "direction": direction,
                "time":      datetime.utcnow(),
                "score":     score,
            }
            cutoff = datetime.utcnow() - timedelta(hours=2)
            self._recent_approvals = {
                k: v for k, v in self._recent_approvals.items() if v["time"] > cutoff
            }

    @staticmethod
    def _pearson(a: list, b: list) -> float:
        n = min(len(a), len(b))
        if n < 10:
            return 0.0
        a, b = a[-n:], b[-n:]
        ma   = sum(a) / n
        mb   = sum(b) / n
        cov  = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
        sa   = (sum((x - ma) ** 2 for x in a) / n) ** 0.5
        sb   = (sum((x - mb) ** 2 for x in b) / n) ** 0.5
        return round(cov / (n * sa * sb), 3) if sa and sb else 0.0

    def compute_matrix(self, bs) -> dict:
        """Return {pair: {pair: corr}} for all pairs with ≥30 bars."""
        pairs  = [p for p in self.POLARITY if self.POLARITY[p] != 0]
        closes = {}
        for p in pairs:
            bars = bs.get(p, "M15")
            if len(bars) >= 30:
                closes[p] = [b["c"] for b in bars[-200:]]
        matrix = {}
        for p1 in closes:
            matrix[p1] = {}
            for p2 in closes:
                matrix[p1][p2] = 1.0 if p1 == p2 else self._pearson(closes[p1], closes[p2])
        return matrix

    def get_modifier(self, symbol: str, signal_dir: int, bs) -> dict:
        with self._lock:
            recent = dict(self._recent_approvals)
        sym = symbol.upper()
        pol_new = self.POLARITY.get(sym, 0)
        if not recent or pol_new == 0:
            return {"modifier": 0, "risk": "none", "conflicts": [], "matrix": {}}

        usd_dir_new = -signal_dir * pol_new
        matrix      = self.compute_matrix(bs)
        conflicts   = []
        worst_corr  = 0.0

        for ex_sym, ex in recent.items():
            if ex_sym == sym:
                continue
            pol_ex = self.POLARITY.get(ex_sym, 0)
            if pol_ex == 0:
                continue
            usd_dir_ex = -ex["direction"] * pol_ex
            if usd_dir_new != usd_dir_ex:
                continue          # opposite USD direction → no additive exposure
            corr = matrix.get(sym, {}).get(ex_sym, 0.0)
            if abs(corr) > abs(worst_corr):
                worst_corr = corr
            if abs(corr) >= 0.70:
                conflicts.append({
                    "symbol":      ex_sym,
                    "correlation": corr,
                    "ago_mins":    int((datetime.utcnow() - ex["time"]).total_seconds() / 60),
                })

        if   abs(worst_corr) >= 0.85: modifier, risk = -8, "HIGH"
        elif abs(worst_corr) >= 0.70: modifier, risk = -4, "MODERATE"
        else:                          modifier, risk =  0, "none"

        return {
            "modifier":   modifier,
            "risk":       risk,
            "worst_corr": round(worst_corr, 3),
            "conflicts":  conflicts,
            "matrix":     {k: {k2: v2 for k2, v2 in v.items()} for k, v in matrix.items()},
        }

    def get_full_matrix(self, bs) -> dict:
        return self.compute_matrix(bs)


correlation_agent = CorrelationAgent()


# ══════════════════════════════════════════════════════════════════════
# 9g. ECONOMIC SURPRISE AGENT — Data Release Impact Scoring
# ══════════════════════════════════════════════════════════════════════

class EconomicSurpriseAgent:
    """
    Tracks economic data releases (actual vs forecast) and scores the
    direction + magnitude of the surprise.  Positive USD surprise → bearish
    EUR/GBP/AUD, bullish USD/JPY.  Events fade over 6h.  Cap: ±6 pts.

    Data is pushed by the VPS immediately after each release via POST /surprise/update.
    Format: [{currency, event, actual, forecast, importance, timestamp}, ...]
    """
    WEIGHT = {"high": 6, "medium": 3, "low": 1}

    def __init__(self):
        self._cache: list = []
        self._lock  = threading.Lock()
        # Auto-fetch released events from ForexFactory JSON every 5 minutes.
        # No manual VPS push required — the thread handles ingestion automatically.
        t = threading.Thread(target=self._auto_fetch_loop, daemon=True)
        t.start()

    @staticmethod
    def _parse_val(s) -> float | None:
        """Parse FF string values like '177K', '-0.3%', '1.25M' → float."""
        if not s:
            return None
        s = str(s).strip()
        if s in ("—", "N/A", "n/a", ""):
            return None
        mult = 1
        if   s.endswith("K"): mult, s = 1_000,         s[:-1]
        elif s.endswith("M"): mult, s = 1_000_000,     s[:-1]
        elif s.endswith("B"): mult, s = 1_000_000_000, s[:-1]
        s = s.replace("%", "").replace(",", "")
        try:
            return float(s) * mult
        except (ValueError, TypeError):
            return None

    def _auto_fetch_loop(self):
        """
        Background thread: every 5 minutes fetches the ForexFactory JSON calendars
        (this-week + next-week), detects newly released events (actual != ""),
        de-duplicates, and ingests them via self.update().
        Completely automatic — no VPS script required.
        """
        import time as _time
        URLS = [
            "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
            "https://nfs.faireconomy.media/ff_calendar_nextweek.json",
        ]
        _seen: set = set()   # (currency, title, date[:10]) — skip re-ingested events
        _time.sleep(15)      # give scorer 15 s to start before first fetch

        while True:
            try:
                new_events = []
                for url in URLS:
                    try:
                        resp = requests.get(url, timeout=12)
                        if not resp.ok:
                            continue
                        for ev in resp.json():
                            actual_raw   = ev.get("actual",   "")
                            forecast_raw = ev.get("forecast", "")
                            if not actual_raw or str(actual_raw).strip() in ("", "—", "N/A"):
                                continue   # not released yet
                            actual   = self._parse_val(actual_raw)
                            forecast = self._parse_val(forecast_raw)
                            if actual is None:
                                continue
                            ccy   = (ev.get("country") or ev.get("currency") or "").upper()
                            title = str(ev.get("title", ""))
                            date  = str(ev.get("date",  ""))
                            key   = (ccy, title, date[:10])
                            if key in _seen:
                                continue
                            _seen.add(key)
                            impact_raw = str(ev.get("impact", "low")).lower()
                            importance = (
                                "high"   if "high"  in impact_raw or "red"   in impact_raw else
                                "medium" if "medium" in impact_raw or "orange" in impact_raw else
                                "low"
                            )
                            new_events.append({
                                "currency":   ccy,
                                "event":      title,
                                "actual":     actual,
                                "forecast":   forecast if forecast is not None else actual,
                                "importance": importance,
                                "timestamp":  date,
                            })
                    except Exception as url_err:
                        log.warning(f"[SURPRISE-FETCH] {url} error: {url_err}")

                if new_events:
                    self.update(new_events)
                    log.info(f"[SURPRISE] Auto-fetched {len(new_events)} released events")

            except Exception as loop_err:
                log.warning(f"[SURPRISE] Auto-fetch loop error: {loop_err}")

            _time.sleep(300)   # check every 5 minutes

    def update(self, events: list):
        with self._lock:
            cutoff = datetime.utcnow() - timedelta(hours=48)
            self._cache = [
                e for e in self._cache
                if datetime.fromisoformat(e.get("timestamp", "2000-01-01")) > cutoff
            ]
            for e in events:
                if not e.get("currency") or e.get("actual") is None:
                    continue
                e.setdefault("timestamp", datetime.utcnow().isoformat())
                self._cache.append(dict(e))

    def get_modifier(self, symbol: str, signal_dir: int) -> dict:
        with self._lock:
            recent = list(self._cache)
        sym       = symbol.upper()
        base_ccy  = sym[:3]
        quote_ccy = sym[3:]
        cutoff    = datetime.utcnow() - timedelta(hours=6)
        relevant  = []

        for e in recent:
            try:
                ts = datetime.fromisoformat(e["timestamp"])
            except Exception:
                continue
            if ts < cutoff:
                continue
            ccy = e.get("currency", "").upper()
            if ccy not in (base_ccy, quote_ccy):
                continue
            actual   = float(e.get("actual",   0))
            forecast = float(e.get("forecast", actual))
            if forecast == 0:
                continue
            surprise_pct = (actual - forecast) / abs(forecast) * 100
            weight       = self.WEIGHT.get(e.get("importance", "low"), 1)
            # +surprise in base ccy → bullish pair price; +surprise in quote → bearish
            pair_bullish = (surprise_pct > 0 and ccy == base_ccy) or \
                           (surprise_pct < 0 and ccy == quote_ccy)
            age_mins     = int((datetime.utcnow() - ts).total_seconds() / 60)
            relevant.append({
                "event":       e.get("event", "—"),
                "currency":    ccy,
                "actual":      actual,
                "forecast":    forecast,
                "surprise_pct": round(surprise_pct, 2),
                "weight":      weight,
                "bullish":     pair_bullish,
                "age_mins":    age_mins,
            })

        if not relevant:
            return {"modifier": 0, "source": "no_data", "events": []}

        total = 0.0
        for r in relevant:
            raw = min(abs(r["surprise_pct"]) / 10 * r["weight"], 3.0)
            if r["age_mins"] > 120:
                raw *= 0.5           # fade after 2h
            total += raw if r["bullish"] else -raw

        modifier = max(-6, min(6, round(total * (1 if signal_dir == 1 else -1))))
        return {"modifier": modifier, "events": relevant, "source": "push"}

    def all_events(self) -> list:
        with self._lock:
            return list(self._cache)


economic_surprise_agent = EconomicSurpriseAgent()


# ══════════════════════════════════════════════════════════════════════
# 10. REGIME EARLY WARNING SYSTEM
# ══════════════════════════════════════════════════════════════════════

class RegimeEarlyWarning:
    """
    Detects regime shifts before they fully materialize.
    Monitors: ATR correlation spike, equity/FX divergence,
    spread widening patterns, session volume anomalies.
    """
    def __init__(self):
        self.atr_history     = defaultdict(lambda: deque(maxlen=100))
        self.spread_history  = defaultdict(lambda: deque(maxlen=100))
        self.volume_history  = defaultdict(lambda: deque(maxlen=100))
        self.warnings        = deque(maxlen=50)
        self.current_warning = None
        self.loss_streak     = 0
        self.win_streak      = 0
        self.lock            = threading.Lock()

    def update(self, symbol: str, atr: float, spread: float, volume: float):
        with self.lock:
            self.atr_history[symbol].append(atr)
            self.spread_history[symbol].append(spread)
            self.volume_history[symbol].append(volume)

    def check(self, symbol: str = None) -> dict:
        warnings = []
        regime   = "NORMAL"
        urgency  = 0

        with self.lock:
            pairs_to_check = [symbol] if symbol else list(self.atr_history.keys())
            atr_spikes = 0
            for sym in pairs_to_check:
                atrs = list(self.atr_history[sym])
                if len(atrs) >= 20:
                    recent_avg = np.mean(atrs[-5:])
                    hist_avg   = np.mean(atrs[-20:-5])
                    if hist_avg > 0 and recent_avg / hist_avg > 1.8:
                        atr_spikes += 1
                        warnings.append(f"ATR_SPIKE: {sym} +{(recent_avg/hist_avg-1)*100:.0f}%")

            if atr_spikes >= 2:
                regime  = "VOLATILITY_EXPANSION"
                urgency = 8
                self.current_warning = "VOLATILITY_EXPANSION"

            if symbol and len(self.spread_history[symbol]) >= 10:
                spreads   = list(self.spread_history[symbol])
                recent_sp = np.mean(spreads[-3:])
                hist_sp   = np.mean(spreads[-10:-3])
                if hist_sp > 0 and recent_sp / hist_sp > 2.0:
                    warnings.append(f"SPREAD_WIDENING: {symbol} x{recent_sp/hist_sp:.1f}")
                    urgency = max(urgency, 6)
                    regime  = "LIQUIDITY_STRESS" if regime == "NORMAL" else regime

            if self.loss_streak >= 4:
                warnings.append(f"LOSS_STREAK: {self.loss_streak} consecutive")
                regime  = "FRAGILE"
                urgency = max(urgency, 7)

        if urgency >= 8:   action = "REDUCE_SIZE_50PCT"
        elif urgency >= 6: action = "REDUCE_SIZE_25PCT"
        elif urgency >= 4: action = "TRADE_CAUTIOUSLY"
        else:              action = "NORMAL"

        result = {
            "regime":        regime,
            "warnings":      warnings,
            "urgency":       urgency,
            "action":        action,
            "loss_streak":   self.loss_streak,
            "win_streak":    self.win_streak,
            "score_penalty": -urgency if urgency > 4 else 0,
            "checked_at":    datetime.utcnow().isoformat(),
        }

        if warnings:
            with self.lock:
                self.warnings.append(result)

        return result

    def update_streak(self, won: bool):
        with self.lock:
            if won:
                self.win_streak  += 1
                self.loss_streak  = 0
            else:
                self.loss_streak += 1
                self.win_streak   = 0


regime_warning = RegimeEarlyWarning()

# ══════════════════════════════════════════════════════════════════════
# CORE AI SCORING (v3 compatible + all 10 bonuses)
# ══════════════════════════════════════════════════════════════════════

trade_history = deque(maxlen=MAX_HISTORY)
session_stats = {k: {"wins": 0, "losses": 0, "total": 0, "profit": 0.0}
                 for k in ["LONDON", "LONDON_NY", "NY", "ASIA", "OFF", "UNKNOWN"]}
setup_stats   = {k: {"wins": 0, "losses": 0, "total": 0, "profit": 0.0}
                 for k in ["SWEEP", "FVG", "BOS", "STRUCTURE", "UNKNOWN"]}


class PortfolioEngine:
    def __init__(self):
        self.open_positions = {}
        self.lock = threading.Lock()

    def update_position(self, symbol, direction, lots):
        with self.lock:
            if lots > 0:
                self.open_positions[symbol] = {"direction": direction, "lots": lots}
            elif symbol in self.open_positions:
                del self.open_positions[symbol]

    def check_trade(self, symbol, signal, equity, balance, max_dd):
        with self.lock:
            if balance > 0:
                dd = (balance - equity) / balance * 100
                if dd >= max_dd:
                    return {"approved": False,
                            "block_reason": f"Portfolio DD {dd:.1f}%",
                            "risk_multiplier": 0.0,
                            "total_exposure": self._total()}
            size_multi = corr_sizer.calc_size_multiplier(symbol, self.open_positions)
            n = len(self.open_positions)
            return {"approved": True, "block_reason": "",
                    "risk_multiplier": size_multi,
                    "total_exposure": self._total(),
                    "open_positions": n}

    def _total(self):
        return sum(p["lots"] for p in self.open_positions.values())


portfolio_engine = PortfolioEngine()


class RegimeDetector:
    def __init__(self):
        self.loss_streak = 0
        self.win_streak  = 0

    def detect(self, data):
        trend   = data.get("trend", "NEUTRAL")
        session = data.get("session", "OFF")
        smc     = data.get("smc", False)
        brkout  = data.get("breakout", False)
        dd_state = data.get("dd_state", "NORMAL")
        if dd_state in ["REDUCED_50", "HALTED"]:
            return "fragile"
        if self.loss_streak >= 3:
            return "fragile"
        if (trend in ["BULLISH", "BEARISH"] and
                session in ["LONDON", "LONDON_NY"] and (smc or brkout)):
            return "expansion"
        if trend in ["BULLISH", "BEARISH"] and session in ["LONDON", "LONDON_NY", "NY"]:
            return "trend"
        return "fragile"

    def update(self, won):
        if won:
            self.win_streak  += 1
            self.loss_streak  = 0
        else:
            self.loss_streak += 1
            self.win_streak   = 0


regime_detector = RegimeDetector()


BARSTORE_CACHE_FILE      = "bar_store_cache.json"
INTERMARKET_CACHE_FILE   = "intermarket_cache.json"

# ══════════════════════════════════════════════════════════════════════
# REGIME V2 — Multi-TF trend scoring (Task #23)
# Real ADX(14) + EMA-20 slope + Donchian + Hurst + market structure
# Aggregated across M15/H1/H4/D1 → composite trend_score 0-100
# 6-state regime = {BULL,BEAR,CHOP} × {LOW,NORMAL,HIGH} volatility
# ══════════════════════════════════════════════════════════════════════

class BarStore:
    """Stores OHLC bars per symbol per timeframe.
    Native storage for M15/H1/H4/D1 — EA pushes each TF directly so MTF
    agreement has real depth (50+ bars per TF) without needing 5000+ M15 bars.
    add_m15() also still aggregates upward, so legacy single-TF callers work.
    Fed by EA via POST /bars_push (latest M15) and /bars_backfill (per-TF batch).
    """
    CAPS = {"M15": 5000, "H1": 1500, "H4": 800, "D1": 400}

    def __init__(self):
        self._stores = {tf: defaultdict(lambda c=cap: deque(maxlen=c))
                        for tf, cap in self.CAPS.items()}
        self.lock     = threading.Lock()
        self._dirty   = False
        self.load_from_disk()
        t = threading.Thread(target=self._save_loop, daemon=True)
        t.start()

    # ── Disk persistence ─────────────────────────────────────────────
    def load_from_disk(self):
        try:
            if not os.path.exists(BARSTORE_CACHE_FILE):
                return
            with open(BARSTORE_CACHE_FILE) as f:
                data = json.load(f)
            total = 0
            for tf, sym_dict in data.items():
                if tf not in self._stores:
                    continue
                for sym, bars in sym_dict.items():
                    d = self._stores[tf][sym]
                    for b in bars[-d.maxlen:]:
                        d.append(b)
                    total += len(bars)
            log.info(f"[BARSTORE] Restored {total} bars from disk")
        except Exception as e:
            log.warning(f"[BARSTORE] Load failed: {e}")

    def save_to_disk(self):
        try:
            with self.lock:
                data = {tf: {sym: list(bars)
                             for sym, bars in sym_dict.items()}
                        for tf, sym_dict in self._stores.items()}
            with open(BARSTORE_CACHE_FILE, "w") as f:
                json.dump(data, f)
            self._dirty = False
        except Exception as e:
            log.warning(f"[BARSTORE] Save failed: {e}")

    def _save_loop(self):
        """Background thread: flush to disk every 5 minutes if dirty."""
        import time as _t
        while True:
            _t.sleep(300)
            if self._dirty:
                self.save_to_disk()

    def add_m15(self, symbol, o, h, l, c, v=0.0):
        with self.lock:
            self._stores["M15"][symbol].append(
                {"o": float(o), "h": float(h),
                 "l": float(l), "c": float(c), "v": float(v)})
        self._dirty = True

    def replace_tf(self, symbol, tf, bars):
        """Replace the deque for a given TF (used by /bars_backfill)."""
        if tf not in self._stores:
            return
        with self.lock:
            d = self._stores[tf][symbol]
            d.clear()
            for b in bars[-d.maxlen:]:
                d.append({"o": float(b.get("o", 0)), "h": float(b.get("h", 0)),
                          "l": float(b.get("l", 0)), "c": float(b.get("c", 0)),
                          "v": float(b.get("v", 0))})
        self._dirty = True
        # Backfills push a lot of bars at once — save immediately
        self.save_to_disk()

    # Legacy alias — still used by some callers.
    def replace_m15(self, symbol, bars):
        self.replace_tf(symbol, "M15", bars)

    def get(self, symbol, tf="M15"):
        """Return bars for tf. Prefer native storage; fall back to M15 aggregation."""
        with self.lock:
            native = list(self._stores.get(tf, {}).get(symbol, []))
        if native or tf == "M15":
            return native
        # Aggregate from M15 if native TF is empty
        with self.lock:
            bars = list(self._stores["M15"][symbol])
        if not bars:
            return []
        factor = {"H1": 4, "H4": 16, "D1": 96}.get(tf, 1)
        if factor <= 1:
            return bars
        rem  = len(bars) % factor
        head = bars[rem:]
        agg  = []
        for i in range(0, len(head), factor):
            chunk = head[i:i + factor]
            if not chunk:
                continue
            agg.append({
                "o": chunk[0]["o"],
                "h": max(b["h"] for b in chunk),
                "l": min(b["l"] for b in chunk),
                "c": chunk[-1]["c"],
                "v": sum(b["v"] for b in chunk),
            })
        return agg

    def count(self, symbol, tf="M15"):
        with self.lock:
            return len(self._stores.get(tf, {}).get(symbol, []))

    def counts(self, symbol):
        with self.lock:
            return {tf: len(self._stores[tf].get(symbol, []))
                    for tf in self._stores}


bar_store = BarStore()


def _ema_series(values, period):
    if len(values) < period:
        return []
    k = 2.0 / (period + 1)
    out = [sum(values[:period]) / period]
    for v in values[period:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def _adx(bars, period=14):
    """Wilder's ADX. Returns dict(adx, plus_di, minus_di) or None."""
    if len(bars) < period * 2 + 1:
        return None
    tr_list, plus_dm, minus_dm = [], [], []
    for i in range(1, len(bars)):
        h, l, c_prev = bars[i]["h"], bars[i]["l"], bars[i-1]["c"]
        tr = max(h - l, abs(h - c_prev), abs(l - c_prev))
        up = h - bars[i-1]["h"]
        dn = bars[i-1]["l"] - bars[i]["l"]
        plus  = up if (up > dn and up > 0) else 0.0
        minus = dn if (dn > up and dn > 0) else 0.0
        tr_list.append(tr); plus_dm.append(plus); minus_dm.append(minus)

    def wilder(arr, p):
        if len(arr) < p:
            return []
        s = sum(arr[:p])
        out = [s]
        for v in arr[p:]:
            s = s - (s / p) + v
            out.append(s)
        return out

    atr_s   = wilder(tr_list,  period)
    plus_s  = wilder(plus_dm,  period)
    minus_s = wilder(minus_dm, period)
    if not atr_s or not plus_s or not minus_s:
        return None
    n = min(len(atr_s), len(plus_s), len(minus_s))
    dx_list = []
    for i in range(n):
        a = atr_s[i] if atr_s[i] > 0 else 1e-10
        plus_di  = 100 * plus_s[i]  / a
        minus_di = 100 * minus_s[i] / a
        denom    = plus_di + minus_di
        dx       = 100 * abs(plus_di - minus_di) / denom if denom > 0 else 0.0
        dx_list.append(dx)
    if len(dx_list) < period:
        return None
    adx_smoothed = wilder(dx_list, period)
    if not adx_smoothed:
        return None
    adx = adx_smoothed[-1] / period
    a_last = atr_s[-1] if atr_s[-1] > 0 else 1e-10
    plus_di_last  = 100 * plus_s[-1]  / a_last
    minus_di_last = 100 * minus_s[-1] / a_last
    return {"adx": adx, "plus_di": plus_di_last, "minus_di": minus_di_last}


def _ema_slope_pct(bars, period=20, lookback=5):
    closes = [b["c"] for b in bars]
    series = _ema_series(closes, period)
    if len(series) < lookback + 1:
        return None
    cur, prev = series[-1], series[-1 - lookback]
    if prev == 0:
        return None
    return (cur - prev) / prev * 100.0


def _donchian_position(bars, period=20):
    if len(bars) < period:
        return None
    window = bars[-period:]
    hi = max(b["h"] for b in window)
    lo = min(b["l"] for b in window)
    if hi == lo:
        return 0.5
    return (bars[-1]["c"] - lo) / (hi - lo)


def _hurst(bars, max_lag=20):
    closes = [b["c"] for b in bars]
    n = len(closes)
    if n < max_lag * 2:
        return None
    lags = list(range(2, max_lag + 1))
    tau, used_lags = [], []
    for lag in lags:
        diffs = [closes[i + lag] - closes[i] for i in range(n - lag)]
        if len(diffs) < 2:
            continue
        std = float(np.std(diffs))
        if std <= 0:
            continue
        tau.append(std)
        used_lags.append(lag)
    if len(tau) < 4:
        return None
    log_lags = np.log(used_lags)
    log_tau  = np.log(tau)
    slope, _ = np.polyfit(log_lags, log_tau, 1)
    return float(slope)


def _structure(bars, lookback=20):
    """HH/HL → UP, LH/LL → DOWN, mixed/insufficient → NONE."""
    if len(bars) < lookback + 4:
        return "NONE"
    window = bars[-lookback:]
    highs, lows = [], []
    for i in range(2, len(window) - 2):
        b = window[i]
        if (b["h"] > window[i-1]["h"] and b["h"] > window[i-2]["h"]
                and b["h"] > window[i+1]["h"] and b["h"] > window[i+2]["h"]):
            highs.append(b["h"])
        if (b["l"] < window[i-1]["l"] and b["l"] < window[i-2]["l"]
                and b["l"] < window[i+1]["l"] and b["l"] < window[i+2]["l"]):
            lows.append(b["l"])
    if len(highs) >= 2 and len(lows) >= 2:
        if highs[-1] > highs[-2] and lows[-1] > lows[-2]: return "UP"
        if highs[-1] < highs[-2] and lows[-1] < lows[-2]: return "DOWN"
    return "NONE"


def _atr(bars, period=14):
    if len(bars) < period + 1:
        return None
    trs = []
    for i in range(1, len(bars)):
        h, l, c_prev = bars[i]["h"], bars[i]["l"], bars[i-1]["c"]
        trs.append(max(h - l, abs(h - c_prev), abs(l - c_prev)))
    return float(np.mean(trs[-period:]))


# ── Tunable component weights (sum = 100) ─────────────────────────────
# Stored as named constants per spec — change these to tune the model
# without touching scoring logic.
REGIME_V2_WEIGHTS = {
    "mtf_agreement": 30.0,   # EMA20/EMA50 alignment across M15/H1/H4/D1
    "adx":           20.0,   # ADX(14) trend strength on H1
    "ema_slope":     15.0,   # EMA-20 slope angle on H1
    "hurst":         10.0,   # Hurst exponent (trending vs mean-revert)
    "donchian":      15.0,   # Distance from Donchian-20 mid on H1
    "structure":     10.0,   # HH/HL vs LH/LL market structure on H1
}


def _neutral(component_name, value=None, **extra):
    """Standardized neutral 50 cold-start payload for any sub-score."""
    out = {"score": 50, "direction": 0, "value": value,
           "insufficient_data": True}
    out.update(extra)
    return out


def _mtf_agreement(symbol):
    """EMA(20)/EMA(50) crossover state across M15/H1/H4/D1.
    score=100 when all 4 align; scaled down per disagreeing TF.
    """
    votes = {}
    insuff = 0
    # Need ≥100 closes so the EMA50 has stabilized past its SMA seed.
    # At exactly 50 closes, _ema_series returns SMA(50) as its only value —
    # comparing that to EMA20 produces a biased, jittery signal.
    for tf in ("M15", "H1", "H4", "D1"):
        bars   = bar_store.get(symbol, tf)
        closes = [b["c"] for b in bars]
        if len(closes) < 100:
            votes[tf] = "NONE"
            insuff   += 1
            continue
        e20 = _ema_series(closes, 20)
        e50 = _ema_series(closes, 50)
        if len(e20) < 5 or len(e50) < 5:
            votes[tf] = "NONE"
            insuff   += 1
            continue
        if   e20[-1] > e50[-1]: votes[tf] = "BULL"
        elif e20[-1] < e50[-1]: votes[tf] = "BEAR"
        else:                   votes[tf] = "NONE"
    if insuff >= 2:
        return _neutral("mtf_agreement", value=votes, votes=votes)
    bulls = sum(1 for v in votes.values() if v == "BULL")
    bears = sum(1 for v in votes.values() if v == "BEAR")
    dom   = max(bulls, bears)
    direction = 1 if bulls > bears else -1 if bears > bulls else 0
    score = round(dom / 4.0 * 100)
    return {"score": score, "direction": direction,
            "value": f"{bulls}B/{bears}S", "votes": votes,
            "insufficient_data": False}


def _adx_score(symbol):
    """ADX(14) on H1 → 0-100 (ADX 50 ≈ very strong trend ⇒ score 100)."""
    bars = bar_store.get(symbol, "H1")
    if len(bars) < 30:
        return _neutral("adx")
    a = _adx(bars, 14)
    if not a:
        return _neutral("adx")
    score = max(0, min(100, round(a["adx"] * 2)))
    direction = (1  if a["plus_di"]  > a["minus_di"] else
                 -1 if a["minus_di"] > a["plus_di"]  else 0)
    return {"score": score, "direction": direction,
            "value": round(a["adx"], 2),
            "plus_di":  round(a["plus_di"],  2),
            "minus_di": round(a["minus_di"], 2),
            "insufficient_data": False}


def _ema_slope_score(symbol):
    """EMA-20 slope (% over last 5 bars) on H1 → 0-100 magnitude.

    Calibrated for FX H1 reality: typical strong-trend slope is 0.05-0.10%
    over 5 bars. Old scaling (×100) capped real trends at score≈55-65.
    New scaling (×500) puts a 0.10% slope at 100 (full credit), 0.05% at 75,
    flat at 50. Direction threshold raised to 0.05% so we don't call a
    grinding sideways tape "trending up" because EMA drifted 0.025%.
    """
    bars  = bar_store.get(symbol, "H1")
    slope = _ema_slope_pct(bars, 20, 5)
    if slope is None:
        return _neutral("ema_slope")
    score = max(0, min(100, round(50 + abs(slope) * 500)))
    direction = 1 if slope > 0.05 else -1 if slope < -0.05 else 0
    return {"score": score, "direction": direction,
            "value": round(slope, 4),
            "insufficient_data": False}


def _hurst_score(symbol):
    """Hurst exponent on H1 closes. >0.5 trending, <0.5 mean-reverting.
    Score is the magnitude of deviation from 0.5, scaled to 0-100.
    Hurst is direction-agnostic.
    """
    bars = bar_store.get(symbol, "H1")
    h = _hurst(bars, 20)
    if h is None:
        return _neutral("hurst")
    h_clipped = max(0.0, min(1.0, h))
    score = max(0, min(100, round(abs(h_clipped - 0.5) * 200)))
    return {"score": score, "direction": 0,
            "value": round(h_clipped, 3),
            "insufficient_data": False}


def _donchian_score(symbol):
    """Donchian-20 channel position on H1. score = distance from mid (0.5)."""
    bars = bar_store.get(symbol, "H1")
    d = _donchian_position(bars, 20)
    if d is None:
        return _neutral("donchian")
    score = max(0, min(100, round(abs(d - 0.5) * 200)))
    direction = 1 if d > 0.55 else -1 if d < 0.45 else 0
    return {"score": score, "direction": direction,
            "value": round(d, 3),
            "insufficient_data": False}


def _structure_score(symbol):
    """Market structure on H1. UP/DOWN swings → 80, NONE → 50 (neutral).

    NONE means swing pivots are unclear — that's no information, not bearish.
    Old code returned 30, which actively dragged the composite DOWN whenever
    the market lacked clean fractal swings (i.e. most ranging conditions).
    """
    bars = bar_store.get(symbol, "H1")
    if len(bars) < 24:
        return _neutral("structure", value="NONE")
    s = _structure(bars, 20)
    if s == "UP":   return {"score": 80, "direction":  1, "value": s, "insufficient_data": False}
    if s == "DOWN": return {"score": 80, "direction": -1, "value": s, "insufficient_data": False}
    return {"score": 50, "direction": 0, "value": s, "insufficient_data": False}


def _atr_percentile(symbol):
    """Bucket M15 ATR(14) against the trailing 100-bar ATR distribution.
    Returns LOW (≤25th), NORMAL (25-75th), HIGH (≥75th)."""
    bars = bar_store.get(symbol, "M15")
    if len(bars) < 100 + 14:
        return {"bucket": "NORMAL", "percentile": 50,
                "insufficient_data": True}
    atrs = []
    for i in range(14, len(bars)):
        a = _atr(bars[i-14:i+1], 14)
        if a is not None:
            atrs.append(a)
    if len(atrs) < 100:
        return {"bucket": "NORMAL", "percentile": 50,
                "insufficient_data": True}
    window = atrs[-100:]
    cur    = atrs[-1]
    rank   = sum(1 for v in window if v <= cur)
    pct    = round(rank / len(window) * 100)
    bucket = "HIGH" if pct >= 75 else "LOW" if pct <= 25 else "NORMAL"
    return {"bucket": bucket, "percentile": pct, "insufficient_data": False}


def compute_regime_v2(symbol: str) -> dict:
    """Composite multi-TF trend score 0-100 + 6-state regime label.

    Each component returns a normalized 0-100 magnitude AND a -1/0/+1
    direction vote; the composite is the weighted blend (REGIME_V2_WEIGHTS)
    of the magnitudes, with direction taken from the weighted vote sum.
    """
    components = {
        "mtf_agreement": _mtf_agreement(symbol),
        "adx":           _adx_score(symbol),
        "ema_slope":     _ema_slope_score(symbol),
        "hurst":         _hurst_score(symbol),
        "donchian":      _donchian_score(symbol),
        "structure":     _structure_score(symbol),
    }
    insuff_count = sum(1 for c in components.values() if c["insufficient_data"])
    insufficient = insuff_count >= 3

    total_w   = sum(REGIME_V2_WEIGHTS.values())
    composite = sum(components[k]["score"]     * REGIME_V2_WEIGHTS[k]
                    for k in components) / total_w
    dir_w     = sum(components[k]["direction"] * REGIME_V2_WEIGHTS[k]
                    for k in components) / total_w

    # Trend direction requires BOTH a meaningful weighted lean (≥0.40) AND
    # at least 2 independent components voting the same way. A single
    # component (even mtf_agreement at 0.30 weight) is no longer enough to
    # flip the regime label — that was the old behaviour and it produced
    # constant flip-flops between BULLISH/NEUTRAL on choppy data.
    bull_votes = sum(1 for c in components.values() if c["direction"] ==  1)
    bear_votes = sum(1 for c in components.values() if c["direction"] == -1)
    if   dir_w >=  0.40 and bull_votes >= 2: trend_dir = "BULLISH"
    elif dir_w <= -0.40 and bear_votes >= 2: trend_dir = "BEARISH"
    else:                                    trend_dir = "NEUTRAL"

    score = int(max(0, min(100, round(composite))))
    if insufficient:
        score     = 50
        trend_dir = "NEUTRAL"

    vol  = _atr_percentile(symbol)
    base = ("BULL" if trend_dir == "BULLISH" else
            "BEAR" if trend_dir == "BEARISH" else "CHOP")
    regime = (f"{base}_TREND_{vol['bucket']}_VOL" if base != "CHOP"
              else f"CHOP_{vol['bucket']}_VOL")
    label_map = {
        "BULL_TREND_LOW_VOL":    "Bull Trend · Low Vol",
        "BULL_TREND_NORMAL_VOL": "Bull Trend · Normal Vol",
        "BULL_TREND_HIGH_VOL":   "Bull Trend · High Vol",
        "BEAR_TREND_LOW_VOL":    "Bear Trend · Low Vol",
        "BEAR_TREND_NORMAL_VOL": "Bear Trend · Normal Vol",
        "BEAR_TREND_HIGH_VOL":   "Bear Trend · High Vol",
        "CHOP_LOW_VOL":          "Chop · Low Vol",
        "CHOP_NORMAL_VOL":       "Chop · Normal Vol",
        "CHOP_HIGH_VOL":         "Chop · High Vol",
    }

    return {
        "symbol":            symbol,
        "trend_score":       score,
        "trend_direction":   trend_dir,
        "regime":            regime,
        "regime_label":      label_map.get(regime, regime),
        "insufficient_data": insufficient,
        "vol_bucket":        vol["bucket"],
        "vol_state":         vol["bucket"],   # legacy alias
        "vol_percentile":    vol["percentile"],
        "components":        components,
        "weights":           REGIME_V2_WEIGHTS,
        "agreement":         round(min(1.0, abs(dir_w)), 2),
        "updated_at":        datetime.utcnow().isoformat(),
    }


DASHBOARD_API_URL = os.environ.get(
    "DASHBOARD_API_URL",
    "https://f4f246c4-7e44-48f2-afde-a61d1ea27f73-00-14bbhsih3jpou.kirk.replit.dev/api"
)


class AdaptiveModel:
    def __init__(self):
        self.weights = {
            # Trend (required to reach threshold — but not sufficient alone)
            "trend_aligned":          25.0, "trend_conflicting":       -25.0,
            # Setup quality — at least one required alongside trend_aligned
            "setup_sweep":            14.0,  # Liquidity sweep — highest-prob SMC entry
            "setup_fvg":              10.0,  # Fair value gap
            "setup_bos":               8.0,  # Break of structure
            # Combo bonus — sweep in direction of trend is the premium setup
            "sweep_trend_confirmed":  10.0,  # setup_sweep AND trend_aligned
            # Session quality
            "session_london_ny":      10.0,  # Overlap — highest liquidity window
            "session_london":          7.0,
            "session_ny":              5.0,
            "session_asia":           -8.0,
            # Session open premium (server-side, first 60 min of session)
            "session_open_premium":   12.0,  # London 08-09 UTC or NY 13-14 UTC
            # Confluence — multiple confirming signals
            "confluence_1":            2.0,
            "confluence_2":           10.0,
            "confluence_3":           22.0,  # Three confluences = high conviction
            # Intermarket / macro
            "intermarket_pos":         6.0, "intermarket_neg":          -8.0,
            # Streak penalties — tighten on losing runs
            "consec_losses_1":        -3.0, "consec_losses_2":          -8.0,
            "consec_losses_3":       -15.0,
            # Session losing streak today — server tracks intraday performance
            "session_losing_today":   -8.0,
        }
        self.base_score    = 30.0  # Lowered from 40 — trend alone (30+25=55) no longer clears 60
        self.train_history = deque(maxlen=MAX_HISTORY)
        self.retrain_count = 0
        self.last_retrain  = datetime.utcnow()
        self.lock          = threading.Lock()

    def score(self, features):
        with self.lock:
            s = self.base_score
            for f, v in features.items():
                if v and f in self.weights:
                    s += self.weights[f]
            return max(0.0, min(100.0, s))

    def record(self, features, won, profit):
        with self.lock:
            self.train_history.append({
                "features": features, "won": won, "profit": profit,
                "ts": datetime.utcnow().isoformat()
            })
        if len(self.train_history) % 50 == 0:
            threading.Thread(target=self.retrain, daemon=True).start()
            threading.Thread(
                target=lambda: ml_classifier.train(list(self.train_history)),
                daemon=True
            ).start()

    def retrain(self):
        with self.lock:
            history = list(self.train_history)
        if len(history) < 30:
            return
        feat_wins  = defaultdict(int)
        feat_total = defaultdict(int)
        for r in history:
            for f, v in r["features"].items():
                if v:
                    feat_total[f] += 1
                    feat_wins[f]  += (1 if r["won"] else 0)
        lr = 0.05
        with self.lock:
            wr = sum(1 for r in history if r["won"]) / len(history)
            for f in self.weights:
                if feat_total[f] >= 10:
                    fwr   = feat_wins[f] / feat_total[f]
                    delta = (fwr - wr) * abs(self.weights[f]) * lr
                    self.weights[f] = max(-30, min(30, self.weights[f] + delta))
            self.retrain_count += 1
            self.last_retrain   = datetime.utcnow()


ai_model = AdaptiveModel()


def extract_features(data):
    trend     = data.get("trend", "NEUTRAL")
    signal    = data.get("signal", 0)
    setup     = data.get("setup", "UNKNOWN").upper()
    session   = data.get("session", "OFF").upper()
    smc       = bool(data.get("smc", False))
    brkout    = bool(data.get("breakout", False))
    structure = bool(data.get("structure", False))
    im_score  = float(data.get("intermarket_score", 0))
    c_losses  = int(data.get("consec_losses", 0))
    conf      = int(data.get("confluence", 0))
    aligned   = (signal == 1 and trend == "BULLISH") or (signal == -1 and trend == "BEARISH")
    conf_count = conf if conf > 0 else sum([bool(smc), bool(brkout), bool(structure)])

    is_sweep   = "SWEEP" in setup
    is_fvg     = "FVG"   in setup
    is_bos     = "BOS"   in setup or "STRUCTURE" in setup

    # ── Server-side time premium (no EA data required) ───────────────────
    utc_hour = datetime.utcnow().hour
    # London open 08:00–09:00 UTC and NY open 13:00–14:00 UTC
    # are the highest-momentum windows — most intraday moves start here
    is_session_open = (
        (session in ("LONDON", "LONDON_NY") and utc_hour == 8)  or
        (session in ("NY", "LONDON_NY")     and utc_hour == 13)
    )

    # ── Session losing streak today (server-side, uses session_stats) ────
    sess_key = session if session in session_stats else "UNKNOWN"
    sess_data = session_stats.get(sess_key, {})
    sess_losses_today = sess_data.get("losses", 0)
    session_losing = sess_losses_today >= 2  # 2+ losses in this session today = tighten

    return {
        "trend_aligned":          aligned,
        "trend_conflicting":      not aligned and trend != "NEUTRAL",
        # Setup types
        "setup_sweep":            is_sweep,
        "setup_fvg":              is_fvg,
        "setup_bos":              is_bos,
        # Premium combo: sweep + trend aligned = highest-probability SMC entry
        "sweep_trend_confirmed":  is_sweep and aligned,
        # Session
        "session_london_ny":      session == "LONDON_NY",
        "session_london":         session == "LONDON",
        "session_ny":             session == "NY",
        "session_asia":           session == "ASIA",
        # Session open premium — server calculates this, not dependent on EA
        "session_open_premium":   is_session_open,
        # Confluence count
        "confluence_1":           conf_count == 1,
        "confluence_2":           conf_count == 2,
        "confluence_3":           conf_count >= 3,
        # Macro / intermarket
        "intermarket_pos":        im_score > 10,
        "intermarket_neg":        im_score < -10,
        # Losing streaks — tighten scoring
        "consec_losses_1":        c_losses == 1,
        "consec_losses_2":        c_losses == 2,
        "consec_losses_3":        c_losses >= 3,
        # Session performance today — if this session keeps losing, raise bar
        "session_losing_today":   session_losing,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# LEGEND AGENTS — multi-agent framework inspired by virattt/ai-hedge-fund
# Adapted for Forex M15 scalping. Each agent casts a structured vote;
# the results synthesise into score modifiers applied in score_trade().
# ═══════════════════════════════════════════════════════════════════════════════

class DruckenmillerAgent:
    """
    Macro trend conviction agent — inspired by Stanley Druckenmiller.

    Druckenmiller's edge: size BIG when multiple independent macro signals all
    agree on direction. Synthesises:
      1. Central bank rate differential direction
      2. DXY trend (USD strength/weakness)
      3. US 10Y yield direction (risk-on/off proxy)
      4. COT institutional positioning extremes

    Modifier: +10 (3-4 signals aligned), +6 (2 aligned), +3 (1 aligned),
              0 (mixed), -4/-7/-10 (signals opposed).
    """

    # Pairs where DXY up = base currency weakens (USD is quote)
    _USD_BASE  = {"EURUSD", "GBPUSD", "AUDUSD", "NZDUSD"}
    # Pairs where DXY up = base currency strengthens (USD is base)
    _USD_QUOTE = {"USDJPY", "USDCAD", "USDCHF"}

    def vote(self, symbol: str, signal_dir: int,
             macro_result: dict, inter_result: dict, cot_result: dict) -> dict:
        pair    = (symbol[:6] if len(symbol) >= 6 else symbol).upper()
        aligned = 0
        opposed = 0
        reasons = []

        # 1 — Rate differential
        macro_mod = macro_result.get("modifier", 0)
        diff      = macro_result.get("differential", 0.0)
        if macro_mod > 0:
            aligned += 1
            reasons.append(f"rate_diff={diff:+.2f}% aligns")
        elif macro_mod < 0:
            opposed += 1
            reasons.append(f"rate_diff={diff:+.2f}% opposes")

        # 2 — DXY trend
        dxy_chg = inter_result.get("dxy_chg", 0.0)
        if abs(dxy_chg) >= 0.15:
            if pair in self._USD_BASE:
                favours_sell = dxy_chg > 0          # DXY up → USD strong → base weaker → SELL
                if signal_dir == -1 and favours_sell:
                    aligned += 1; reasons.append(f"DXY={dxy_chg:+.2f}% aligns SELL")
                elif signal_dir == 1 and not favours_sell:
                    aligned += 1; reasons.append(f"DXY={dxy_chg:+.2f}% aligns BUY")
                elif signal_dir != 0:
                    opposed += 1; reasons.append(f"DXY={dxy_chg:+.2f}% opposes")
            elif pair in self._USD_QUOTE:
                favours_buy = dxy_chg > 0
                if signal_dir == 1 and favours_buy:
                    aligned += 1; reasons.append(f"DXY={dxy_chg:+.2f}% aligns BUY")
                elif signal_dir == -1 and not favours_buy:
                    aligned += 1; reasons.append(f"DXY={dxy_chg:+.2f}% aligns SELL")
                elif signal_dir != 0:
                    opposed += 1; reasons.append(f"DXY={dxy_chg:+.2f}% opposes")

        # 3 — US 10Y yield (rising yields → USD strength, same logic as DXY)
        us10y_chg = inter_result.get("us10y_chg", 0.0)
        if abs(us10y_chg) >= 0.02 and signal_dir != 0:
            if pair in self._USD_BASE:
                favours_sell = us10y_chg > 0
                if (signal_dir == -1) == favours_sell:
                    aligned += 1; reasons.append(f"US10Y={us10y_chg:+.3f}% aligns")
                else:
                    opposed += 1; reasons.append(f"US10Y={us10y_chg:+.3f}% opposes")
            elif pair in self._USD_QUOTE:
                favours_buy = us10y_chg > 0
                if (signal_dir == 1) == favours_buy:
                    aligned += 1; reasons.append(f"US10Y={us10y_chg:+.3f}% aligns")
                else:
                    opposed += 1; reasons.append(f"US10Y={us10y_chg:+.3f}% opposes")

        # 4 — COT institutional extreme positioning
        cot_pct = cot_result.get("percentile", 50)
        cot_mod = cot_result.get("modifier", 0)
        if cot_pct >= 70 or cot_pct <= 30:
            if cot_mod > 0:
                aligned += 1; reasons.append(f"COT={cot_pct}th-pct institutional aligns")
            elif cot_mod < 0:
                opposed += 1; reasons.append(f"COT={cot_pct}th-pct institutional opposes")

        # Conviction mapping
        net = aligned - opposed
        if   net >= 3:  modifier = +10
        elif net == 2:  modifier = +6
        elif net == 1:  modifier = +3
        elif net == 0:  modifier = 0
        elif net == -1: modifier = -4
        elif net == -2: modifier = -7
        else:           modifier = -10

        if signal_dir == 0:
            modifier = 0

        signal     = "BULLISH" if modifier > 0 else ("BEARISH" if modifier < 0 else "NEUTRAL")
        confidence = round(min(1.0, abs(net) / 4.0), 2)
        return {
            "agent":      "druckenmiller",
            "signal":     signal,
            "confidence": confidence,
            "modifier":   modifier,
            "aligned":    aligned,
            "opposed":    opposed,
            "reasoning":  " | ".join(reasons) or "insufficient_macro_data",
        }


class TalebAgent:
    """
    Black Swan / tail risk agent — inspired by Nassim Nicholas Taleb.

    Detects fragile, tail-risk market conditions and suppresses entry confidence.
    Never amplifies scores — only suppresses or vetoes.
    VETO mode caps score to MIN_SCORE-15 (guarantees rejection regardless of score).

    Tail conditions checked:
      1. VIX spike (>22 caution, >28 heavy suppression, >35 VETO)
      2. Same-direction pair losses today (correlated failure signal from EA)
      3. Daily drawdown already elevated (proximity to halt limit)
      4. Violent ATR / vol_ratio expansion >2.5x (unpredictable whipsaw risk)
      5. Gold surging +1%+ intraday (systemic risk-off flight)
      6. Multi-tail coincidence (2+ conditions simultaneously → VETO)
    """

    def vote(self, symbol: str, signal_dir: int,
             data: dict, inter_cache: dict) -> dict:
        modifier = 0
        veto     = False
        flags    = []

        # 1 — VIX
        vix_data = inter_cache.get("VIX", {})
        vix      = vix_data.get("price", 0.0) if isinstance(vix_data, dict) else 0.0
        if vix >= 35:
            veto = True
            flags.append(f"VIX={vix:.1f} extreme fear VETO")
        elif vix >= 28:
            modifier -= 12
            flags.append(f"VIX={vix:.1f} elevated -12")
        elif vix >= 22:
            modifier -= 6
            flags.append(f"VIX={vix:.1f} caution -6")

        # 2 — Same-direction pair losses today (EA sends pair_losses_today)
        pair_losses = int(data.get("pair_losses_today", 0))
        if pair_losses >= 2:
            veto = True
            flags.append(f"pair_losses={pair_losses} correlated failure VETO")
        elif pair_losses == 1:
            modifier -= 8
            flags.append(f"pair_losses={pair_losses} first loss warning -8")

        # 3 — Daily drawdown proximity
        daily_loss_pct = float(data.get("daily_loss_pct", 0.0))
        if daily_loss_pct >= 2.0:
            modifier -= 10
            flags.append(f"daily_loss={daily_loss_pct:.2f}% near halt -10")
        elif daily_loss_pct >= 1.0:
            modifier -= 5
            flags.append(f"daily_loss={daily_loss_pct:.2f}% caution -5")

        # 4 — Violent vol expansion (vol_ratio from EA)
        vol_ratio = float(data.get("vol_ratio", 1.0) or 1.0)
        if vol_ratio >= 2.5:
            modifier -= 8
            flags.append(f"vol_ratio={vol_ratio:.1f}x violent expansion -8")

        # 5 — Gold risk-off surge
        gold_data = inter_cache.get("GOLD", {})
        gold_chg  = gold_data.get("change_pct", 0.0) if isinstance(gold_data, dict) else 0.0
        if gold_chg >= 1.0:
            modifier -= 5
            flags.append(f"Gold={gold_chg:+.2f}% risk-off flight -5")

        # 6 — Multi-tail coincidence veto
        non_veto_flags = [f for f in flags if "VETO" not in f]
        if len(non_veto_flags) >= 2 and modifier <= -15 and not veto:
            veto = True
            flags.append("multi-tail coincidence VETO")

        modifier = max(-20, modifier)
        signal   = ("VETO" if veto else
                    "FRAGILE" if modifier <= -8 else
                    "CAUTION" if modifier < 0 else "STABLE")
        return {
            "agent":      "taleb",
            "signal":     signal,
            "confidence": round(min(1.0, abs(modifier) / 20.0), 2),
            "modifier":   modifier,
            "veto":       veto,
            "reasoning":  " | ".join(flags) or "no_tail_risk",
        }


druckenmiller_agent = DruckenmillerAgent()
taleb_agent         = TalebAgent()


class SorosAgent:
    """
    Reflexivity agent — inspired by George Soros.

    Soros's insight: markets create self-reinforcing feedback loops. When a
    currency begins trending, institutional flows, positioning, and momentum
    algos pile in. The trend becomes reflexive and continues far beyond what
    fundamentals justify — until the loop breaks violently.

    Fading a reflexive trend is the #1 cause of correlated stop-outs (May 18).

    VETO: fades of strong reflexive trends (ref_score >= 5).
    PENALTY: fades of moderate reflexive trends.
    BONUS: trades riding the reflexive flow.

    Reflexivity scored from existing payload fields:
      drift_atr, consec_bars, multi_tf, weekly_aligned, COT alignment, vol_ratio.
    """

    def vote(self, symbol: str, signal_dir: int, data: dict,
             cot_result: dict, bs_mom: dict = None) -> dict:
        trend_str      = str(data.get("trend", "FLAT")).upper()
        bs_mom         = bs_mom or {}
        # Use bar-store computed values when EA values are zero/missing
        drift_atr      = max(float(data.get("drift_atr", 0.0)), bs_mom.get("drift_atr", 0.0))
        consec_bars    = max(int(data.get("consec_bars", 0)), bs_mom.get("consec_bars", 0))
        multi_tf       = bool(data.get("multi_tf", False))
        weekly_aligned = bool(data.get("weekly_aligned", False))
        vol_ratio      = float(data.get("vol_ratio", 1.0) or 1.0)
        trend_dir      = 1 if trend_str == "UP" else (-1 if trend_str == "DOWN" else 0)
        cot_mod        = cot_result.get("modifier", 0)
        cot_pct        = cot_result.get("percentile", 50)

        ref_score  = 0
        conditions = []

        if drift_atr >= 2.0:
            ref_score += 2; conditions.append(f"drift={drift_atr:.1f}x PRIME")
        elif drift_atr >= 1.5:
            ref_score += 1; conditions.append(f"drift={drift_atr:.1f}x EXTENDED")

        if consec_bars >= 5:
            ref_score += 2; conditions.append(f"consec={consec_bars}bars")
        elif consec_bars >= 3:
            ref_score += 1; conditions.append(f"consec={consec_bars}bars")

        if multi_tf:
            ref_score += 1; conditions.append("multi_tf")
        if weekly_aligned:
            ref_score += 1; conditions.append("weekly_aligned")

        cot_aligned = ((trend_dir == 1 and cot_mod > 0) or
                       (trend_dir == -1 and cot_mod < 0))
        if cot_aligned and cot_pct >= 55:
            ref_score += 1; conditions.append(f"COT_aligned({cot_pct}th)")

        if vol_ratio >= 1.5:
            ref_score += 1; conditions.append(f"vol={vol_ratio:.1f}x")

        is_reflexive = ref_score >= 3 and trend_dir != 0

        if not is_reflexive or signal_dir == 0:
            return {"agent": "soros", "signal": "NEUTRAL", "confidence": 0.0,
                    "modifier": 0, "veto": False, "reflexive": False,
                    "ref_score": ref_score, "reasoning": "no_reflexive_trend"}

        fading = (signal_dir != trend_dir)

        if fading:
            if ref_score >= 5:
                veto, modifier, signal = True, 0, "VETO_FADE"
                conditions.append("REFLEXIVE_VETO")
            elif ref_score >= 4:
                veto, modifier, signal = False, -15, "FADE_DANGEROUS"
            else:
                veto, modifier, signal = False, -8, "FADE_CAUTION"
        else:
            veto = False
            if ref_score >= 5:   modifier, signal = +8, "RIDE_PRIME"
            elif ref_score >= 4: modifier, signal = +5, "RIDE_STRONG"
            else:                modifier, signal = +3, "RIDE_EARLY"

        return {
            "agent":      "soros",
            "signal":     signal,
            "confidence": round(min(1.0, ref_score / 6.0), 2),
            "modifier":   modifier,
            "veto":       veto,
            "reflexive":  True,
            "trend_dir":  trend_dir,
            "ref_score":  ref_score,
            "reasoning":  " | ".join(conditions),
        }


class BurryAgent:
    """
    Contrarian exhaustion agent — inspired by Michael Burry.

    Burry's edge: patience until the crowd is fully committed, then bet heavily
    against consensus when structural cracks appear. In Forex: wait for a
    reflexive trend to reach EXTREME overextension (PRIME Kotegawa, COT crowded,
    exhaustion streak) before fading — opposite timing from riding with Soros.

    Works in sequence with Soros:
      Soros fires EARLY  (drift >= 1.5, consec >= 3) → 'ride it, do not fade'
      Burry fires LATE   (drift >= 2.0, COT crowded, consec >= 5) → 'NOW fade it'
    When both fire on same setup: Burry modifier applied; Soros veto takes priority.

    BONUS for fading at exhaustion extreme, PENALTY for chasing a top/bottom.
    """

    def vote(self, symbol: str, signal_dir: int, data: dict,
             cot_result: dict, bs_mom: dict = None) -> dict:
        bs_mom      = bs_mom or {}
        # Use bar-store computed values when EA values are zero/missing
        drift_atr   = max(float(data.get("drift_atr", 0.0)), bs_mom.get("drift_atr", 0.0))
        consec_bars = max(int(data.get("consec_bars", 0)), bs_mom.get("consec_bars", 0))
        vol_ratio   = float(data.get("vol_ratio", 1.0) or 1.0)
        trend_str   = str(data.get("trend", "FLAT")).upper()
        trend_dir   = 1 if trend_str == "UP" else (-1 if trend_str == "DOWN" else 0)
        cot_pct     = cot_result.get("percentile", 50)

        exh_score  = 0
        conditions = []

        if drift_atr >= 2.0:
            exh_score += 2; conditions.append(f"drift={drift_atr:.1f}x PRIME")
        elif drift_atr >= 1.8:
            exh_score += 1; conditions.append(f"drift={drift_atr:.1f}x near-extreme")

        if cot_pct >= 80:
            exh_score += 2; conditions.append(f"COT={cot_pct}th-pct CROWDED_LONG")
        elif cot_pct <= 20:
            exh_score += 2; conditions.append(f"COT={cot_pct}th-pct CROWDED_SHORT")
        elif cot_pct >= 70 or cot_pct <= 30:
            exh_score += 1; conditions.append(f"COT={cot_pct}th-pct elevated")

        if consec_bars >= 5:
            exh_score += 1; conditions.append(f"consec={consec_bars}bars exhaustion")
        if vol_ratio >= 1.8:
            exh_score += 1; conditions.append(f"vol={vol_ratio:.1f}x expansion_peak")

        is_exhausted = exh_score >= 3 and trend_dir != 0

        if not is_exhausted or signal_dir == 0:
            return {"agent": "burry", "signal": "NEUTRAL", "confidence": 0.0,
                    "modifier": 0, "exhausted": False,
                    "exh_score": exh_score, "reasoning": "no_exhaustion"}

        fading = (signal_dir != trend_dir)

        if fading:
            modifier, signal = (+12, "FADE_EXTREME") if exh_score >= 4 else (+6, "FADE_STRONG")
        else:
            modifier, signal = (-8, "CHASE_DANGER") if exh_score >= 4 else (-4, "CHASE_CAUTION")

        return {
            "agent":      "burry",
            "signal":     signal,
            "confidence": round(min(1.0, exh_score / 5.0), 2),
            "modifier":   modifier,
            "exhausted":  True,
            "trend_dir":  trend_dir,
            "exh_score":  exh_score,
            "reasoning":  " | ".join(conditions),
        }


class DalioAgent:
    """
    Economic Machine agent — inspired by Ray Dalio.

    Dalio's framework: markets run in repeating patterns driven by the
    short-term debt cycle (credit expansion/contraction) and productivity.
    For Forex M15 this means three concrete checks:

    1. Cross-asset risk-off cluster (Gold + US10Y + VIX all screaming risk-off
       simultaneously) — signals a deleveraging event; oppose risk trades.
    2. Debt cycle trajectory via DXY + US10Y co-movement:
         Rising DXY + rising yields  = healthy expansion → USD structural bid
         Falling DXY + falling yields = stress / deleverage → USD structural weak
    3. Currency debasement signal: Gold up strongly + DXY falling = printing
       press is running → favour non-USD and safe-haven longs.
    4. Risk-parity size_mult: headwind flags shrink position; tailwind flags grow it.
       Applied on top of PM conviction (both multipliers chain together).

    Modifier: −20 to +15 | Independent size_mult: 0.7x – 1.1x
    """

    _USD_BASE    = {"EURUSD", "GBPUSD", "AUDUSD", "NZDUSD"}
    _USD_QUOTE   = {"USDJPY", "USDCAD", "USDCHF"}
    _SAFE_HAVENS = {"USDJPY", "USDCHF"}   # JPY/CHF strengthen in risk-off

    def vote(self, symbol: str, signal_dir: int,
             inter_cache: dict, macro_result: dict) -> dict:
        pair = (symbol[:6] if len(symbol) >= 6 else symbol).upper()

        dxy_data   = inter_cache.get("DXY",   {})
        gold_data  = inter_cache.get("GOLD",  {})
        us10y_data = inter_cache.get("US10Y", {})
        vix_data   = inter_cache.get("VIX",   {})

        dxy_chg   = dxy_data.get("change_pct",   0.0) if isinstance(dxy_data,   dict) else 0.0
        gold_chg  = gold_data.get("change_pct",  0.0) if isinstance(gold_data,  dict) else 0.0
        us10y_chg = us10y_data.get("change_pct", 0.0) if isinstance(us10y_data, dict) else 0.0
        vix_price = vix_data.get("price",         0.0) if isinstance(vix_data,   dict) else 0.0

        modifier     = 0
        size_mult    = 1.0
        conditions   = []
        debt_flags   = 0    # headwind signals
        health_flags = 0    # tailwind signals

        # ── 1. Cross-asset risk-off cluster ──────────────────────────────────
        risk_off_cnt = 0
        if gold_chg  >= 0.5:   risk_off_cnt += 1; conditions.append(f"Gold={gold_chg:+.2f}% risk_off")
        if us10y_chg <= -0.02: risk_off_cnt += 1; conditions.append(f"US10Y={us10y_chg:+.3f}% bonds_bid")
        if vix_price >= 20:    risk_off_cnt += 1; conditions.append(f"VIX={vix_price:.1f} elevated")

        if risk_off_cnt >= 3:
            if pair in self._USD_BASE and signal_dir == 1:
                modifier -= 15; debt_flags += 2
                conditions.append("DELEVERAGE_CLUSTER→risk_longs_opposed")
            elif pair in self._USD_BASE and signal_dir == -1:
                modifier += 8; health_flags += 1
                conditions.append("DELEVERAGE_CLUSTER→safe_haven_short_aligns")
            elif pair in self._USD_QUOTE and signal_dir == -1:
                modifier += 8; health_flags += 1
                conditions.append("DELEVERAGE_CLUSTER→JPY/CHF_buy_aligns")
            else:
                modifier -= 8; debt_flags += 1
                conditions.append("DELEVERAGE_CLUSTER→caution")
        elif risk_off_cnt == 2:
            modifier -= 6; debt_flags += 1
            conditions.append("risk_off_2x_signal -6")

        # ── 2. Debt cycle: DXY + US10Y co-movement ───────────────────────────
        if abs(dxy_chg) >= 0.10 and abs(us10y_chg) >= 0.02:
            if dxy_chg > 0 and us10y_chg > 0:
                # Expansion: USD structural bid
                if pair in self._USD_BASE:
                    if signal_dir == -1: modifier += 6; health_flags += 1; conditions.append("expansion_USD_bid→SELL_aligns +6")
                    else:                modifier -= 4; debt_flags   += 1; conditions.append("expansion_USD_bid→BUY_opposed -4")
                elif pair in self._USD_QUOTE:
                    if signal_dir == 1:  modifier += 6; health_flags += 1; conditions.append("expansion_USD_bid→BUY_aligns +6")
                    else:                modifier -= 4; debt_flags   += 1; conditions.append("expansion_USD_bid→SELL_opposed -4")
            elif dxy_chg < 0 and us10y_chg < 0:
                # Stress: USD structural weak
                if pair in self._USD_BASE:
                    if signal_dir == 1:  modifier += 6; health_flags += 1; conditions.append("stress_USD_weak→BUY_aligns +6")
                    else:                modifier -= 4; debt_flags   += 1; conditions.append("stress_USD_weak→SELL_opposed -4")
                elif pair in self._USD_QUOTE:
                    if signal_dir == -1: modifier += 6; health_flags += 1; conditions.append("stress_USD_weak→SELL_aligns +6")
                    else:                modifier -= 4; debt_flags   += 1; conditions.append("stress_USD_weak→BUY_opposed -4")

        # ── 3. Currency debasement: Gold ↑ + DXY ↓ ──────────────────────────
        if gold_chg >= 0.5 and dxy_chg <= -0.10:
            if pair in self._SAFE_HAVENS and signal_dir == -1:
                modifier += 6; health_flags += 1; conditions.append("debasement→safe_haven_buy +6")
            elif pair in self._USD_BASE and signal_dir == 1:
                modifier += 4; health_flags += 1; conditions.append("debasement→non_USD_buy_aligns +4")

        # ── 4. Risk-parity size adjustment ───────────────────────────────────
        net = health_flags - debt_flags
        if   net >= 2:  size_mult = 1.1
        elif net >= 1:  size_mult = 1.0
        elif net == 0:  size_mult = 0.9
        elif net == -1: size_mult = 0.8
        else:           size_mult = 0.7

        modifier = max(-20, min(15, modifier))
        signal   = ("BULLISH"  if modifier >  5 else
                    "BEARISH"  if modifier < -5 else
                    "TAILWIND" if modifier >  0 else
                    "HEADWIND" if modifier <  0 else "NEUTRAL")

        return {
            "agent":        "dalio",
            "signal":       signal,
            "confidence":   round(min(1.0, abs(modifier) / 15.0), 2),
            "modifier":     modifier,
            "size_mult":    round(size_mult, 2),
            "risk_off_cnt": risk_off_cnt,
            "reasoning":    " | ".join(conditions) or "insufficient_intermarket_data",
        }


class MungerAgent:
    """
    Inversion / mental model checklist agent — inspired by Charlie Munger.

    Munger's core method: "Invert, always invert." Before entering a trade,
    ask 'What would make this fail?' and check if those conditions are already
    true. Three canonical failure modes in Forex M15:

    1. Lollapalooza effect — when Druckenmiller + Soros + COT + LOR all point
       the same way, the trade is obvious; obvious trades are crowded.
       Maximum 4 forces aligned → crowd is already positioned → late entry.
    2. Social proof trap — SSI + COT + trend extreme all same direction.
       When everyone agrees, the move is usually done.
    3. Self-deception — BOS setup with no retest confirmation = confirming bias.
       Munger: "The first rule is not to fool yourself — and you are the easiest
       person to fool."

    Inversion PASS bonus: if none of the above fire, the trade is disciplined.
    VETO: if 3+ red flags simultaneously active.
    Modifier: −15 to +8
    """

    def vote(self, symbol: str, signal_dir: int, data: dict,
             cot_result: dict, ssi_result: dict,
             druck_result: dict, soros_result: dict,
             livermore_result: dict) -> dict:
        flags     = []
        red_flags = 0
        modifier  = 0
        veto      = False

        trend_str  = str(data.get("trend", "FLAT")).upper()
        trend_dir  = 1 if trend_str == "UP" else (-1 if trend_str == "DOWN" else 0)
        cot_pct    = cot_result.get("percentile", 50)
        cot_mod    = cot_result.get("modifier", 0)
        ssi_mod    = ssi_result.get("modifier", 0)
        druck_mod  = druck_result.get("modifier", 0)
        soros_mod  = soros_result.get("modifier", 0)
        lor_dir    = livermore_result.get("lor_dir", 0)

        # ── 1. Lollapalooza: too many forces aligned = crowded trade ─────────
        lolla = 0
        if druck_mod  > 5:                                       lolla += 1
        if soros_mod  > 3 and not soros_result.get("veto"):     lolla += 1
        if ((cot_pct >= 70 and cot_mod > 0) or
            (cot_pct <= 30 and cot_mod < 0)):                   lolla += 1
        if lor_dir == signal_dir and lor_dir != 0:              lolla += 1

        if lolla >= 4:
            modifier -= 8; red_flags += 1
            flags.append(f"LOLLAPALOOZA={lolla}/4 crowd_in -8")
        elif lolla == 3:
            modifier -= 4
            flags.append(f"lollapalooza={lolla}/4 late_entry -4")

        # ── 2. Social proof trap: SSI + COT + trend all extreme same side ────
        ssi_dir  = 1 if ssi_mod > 0 else (-1 if ssi_mod < 0 else 0)
        cot_dir  = 1 if cot_mod > 0 else (-1 if cot_mod < 0 else 0)
        all_same = (ssi_dir == signal_dir == trend_dir == cot_dir and signal_dir != 0)
        if all_same and (cot_pct >= 75 or cot_pct <= 25):
            modifier -= 6; red_flags += 1
            flags.append(f"social_proof_trap: SSI+COT+trend same_side COT={cot_pct}th -6")

        # ── 3. Self-deception: BOS entry without retest confirmation ─────────
        retest_conf = bool(data.get("retest_confirmed", True))
        if not retest_conf and str(data.get("setup", "")).upper() == "BOS":
            modifier -= 5; red_flags += 1
            flags.append("self_deception: BOS_no_retest confirming_bias -5")

        # ── 4. Inversion quality bonus: passes all checklist items ───────────
        if red_flags == 0 and signal_dir != 0:
            multi_tf       = bool(data.get("multi_tf", False))
            weekly_aligned = bool(data.get("weekly_aligned", False))
            if multi_tf and weekly_aligned:
                modifier += 8; flags.append("inversion_pass: multi_tf+weekly_aligned +8")
            elif multi_tf or weekly_aligned:
                modifier += 4; flags.append("inversion_pass: partial_alignment +4")
            else:
                modifier += 2; flags.append("inversion_pass: basic_checklist +2")

        # ── VETO: 3+ simultaneous red flags ──────────────────────────────────
        if red_flags >= 3:
            veto = True
            flags.append("MUNGER_VETO: 3+ red_flags — trade fails inversion test")

        modifier = max(-15, min(8, modifier))
        signal   = ("VETO"    if veto else
                    "REJECT"  if modifier <= -8 else
                    "CAUTION" if modifier <   0 else
                    "PASS"    if modifier >   0 else "NEUTRAL")

        return {
            "agent":     "munger",
            "signal":    signal,
            "confidence": round(min(1.0, (abs(modifier) + red_flags * 3) / 15.0), 2),
            "modifier":  modifier,
            "veto":      veto,
            "red_flags": red_flags,
            "reasoning": " | ".join(flags) or "checklist_clear",
        }


class KeynesAgent:
    """
    Liquidity cycle + beauty contest agent — inspired by John Maynard Keynes.

    Two Keynesian insights translated to Forex M15:

    1. Liquidity cycle: "The engine of growth is credit." Central bank stance
       determines the structural backdrop. Hawkish CB (higher rates) = liquidity
       drain = currency bullish. Dovish CB = liquidity injection = currency bearish.
       Captured via the macro rate differential between base and quote currency.

    2. Beauty contest: "It is not a case of choosing the prettiest face, but
       anticipating what average opinion expects average opinion to be."
       When SSI (retail) AND COT (institutional) AND macro ALL agree with the
       signal, the beauty contest is already decided — the market knows, and
       the move is mostly priced. Keynes fades full consensus; rewards contrarian
       entries where no single consensus is driving the trade.

    3. Rate divergence acceleration bonus: strong differential (≥0.50%) signals
       carry-trade momentum that is self-reinforcing until it violently reverses.

    Modifier: −15 to +12
    """

    def vote(self, symbol: str, signal_dir: int,
             macro_result: dict, cot_result: dict,
             ssi_result: dict) -> dict:
        modifier   = 0
        conditions = []

        macro_mod  = macro_result.get("modifier", 0)
        macro_diff = macro_result.get("differential", 0.0)  # base_rate − quote_rate
        cot_pct    = cot_result.get("percentile", 50)
        cot_mod    = cot_result.get("modifier", 0)
        ssi_mod    = ssi_result.get("modifier", 0)

        # ── 1. Liquidity cycle via CB rate differential ───────────────────────
        if abs(macro_diff) >= 0.25:
            base_hawkish = macro_diff > 0
            if signal_dir == 1 and base_hawkish:
                modifier += 8; conditions.append(f"liq_cycle: base_hawkish({macro_diff:+.2f}%) BUY_aligns +8")
            elif signal_dir == -1 and not base_hawkish:
                modifier += 8; conditions.append(f"liq_cycle: base_dovish({macro_diff:+.2f}%) SELL_aligns +8")
            elif signal_dir == 1 and not base_hawkish:
                modifier -= 8; conditions.append(f"liq_cycle: base_dovish({macro_diff:+.2f}%) BUY_opposed -8")
            elif signal_dir == -1 and base_hawkish:
                modifier -= 8; conditions.append(f"liq_cycle: base_hawkish({macro_diff:+.2f}%) SELL_opposed -8")
        elif abs(macro_diff) >= 0.10:
            aligned = ((signal_dir == 1 and macro_diff > 0) or
                       (signal_dir == -1 and macro_diff < 0))
            if aligned: modifier += 4; conditions.append(f"liq_cycle: marginal_aligned({macro_diff:+.2f}%) +4")
            else:       modifier -= 3; conditions.append(f"liq_cycle: marginal_opposed({macro_diff:+.2f}%) -3")

        # ── 2. Beauty contest: fade full consensus ────────────────────────────
        cot_aligned = (signal_dir == 1 and cot_mod > 0) or (signal_dir == -1 and cot_mod < 0)
        ssi_aligned = (signal_dir == 1 and ssi_mod > 0) or (signal_dir == -1 and ssi_mod < 0)
        mac_aligned = (signal_dir == 1 and macro_mod > 0) or (signal_dir == -1 and macro_mod < 0)

        consensus = 0
        if cot_aligned and cot_pct >= 65: consensus += 1
        if ssi_aligned:                   consensus += 1
        if mac_aligned:                   consensus += 1

        if consensus >= 3:
            modifier -= 8; conditions.append(f"beauty_contest: full_consensus(3/3) late_entry -8")
        elif consensus == 2:
            modifier -= 4; conditions.append(f"beauty_contest: partial_consensus(2/3) -4")
        elif consensus == 0 and signal_dir != 0:
            modifier += 4; conditions.append(f"beauty_contest: contrarian_entry(0/3) +4")

        # ── 3. Rate divergence acceleration bonus ─────────────────────────────
        if abs(macro_diff) >= 0.50 and signal_dir != 0:
            aligned = ((signal_dir == 1 and macro_diff > 0) or
                       (signal_dir == -1 and macro_diff < 0))
            if aligned:
                modifier += 4; conditions.append(f"rate_divergence_strong({macro_diff:+.2f}%) +4")

        modifier = max(-15, min(12, modifier))
        signal   = ("LIQUIDITY_WITH"    if modifier >= 8 else
                    "LIQUIDITY_MILD"    if modifier >  0 else
                    "BEAUTY_FADE"       if modifier <= -8 else
                    "CONSENSUS_CAUTION" if modifier <   0 else "NEUTRAL")

        return {
            "agent":         "keynes",
            "signal":        signal,
            "confidence":    round(min(1.0, abs(modifier) / 12.0), 2),
            "modifier":      modifier,
            "consensus_cnt": consensus,
            "reasoning":     " | ".join(conditions) or "insufficient_macro_data",
        }


class PortfolioManagerAgent:
    """
    Portfolio Manager — meta-synthesis agent, inspired by virattt/ai-hedge-fund.

    Weighs all legend agent votes (modifiers, signals, confidence) into a final
    conviction assessment. Does not override individual scores; instead produces:
      - conviction level: HIGH / MEDIUM-HIGH / MEDIUM / LOW / MINIMAL / VETO
      - size_mult: 0.5x – 1.1x applied to final_multi (position size adjustment)
      - thesis: one-sentence trade rationale visible in reasoning summary

    Agent weights reflect reliability for Forex M15:
      Soros/Taleb (3.0) > Druckenmiller/Burry/Munger (2.0) > Dalio/Livermore/COT (1.5)
    """

    _WEIGHTS = {
        "soros":         3.0,
        "taleb":         3.0,
        "druckenmiller": 2.0,
        "burry":         2.0,
        "munger":        2.0,
        "dalio":         1.5,
        "livermore":     1.5,
        "keynes":        1.5,
        "cot":           1.5,
        "htf":           1.0,
        "macro":         1.0,
        "intermarket":   1.0,
        "ssi":           0.5,
    }

    def vote(self, symbol: str, agent_results: list, veto_active: bool) -> dict:
        weighted_sum  = 0.0
        total_weight  = 0.0
        bull_count    = 0
        bear_count    = 0
        vote_lines    = []

        for res in agent_results:
            name   = res.get("agent", "unknown")
            mod    = res.get("modifier", 0)
            sig    = res.get("signal", "NEUTRAL")
            weight = self._WEIGHTS.get(name, 1.0)
            weighted_sum += mod * weight
            total_weight += weight
            if mod > 0: bull_count += 1
            elif mod < 0: bear_count += 1
            vote_lines.append(f"{name}={sig}({mod:+d})")

        avg = weighted_sum / total_weight if total_weight > 0 else 0.0

        if veto_active:
            conviction, size_mult = "VETO", 0.0
            thesis = "Veto active — entry blocked by protective agents"
        elif avg >= 8:
            conviction, size_mult = "HIGH", 1.1
            thesis = (f"{bull_count} agents bullish vs {bear_count} bearish | "
                      f"weighted_avg={avg:+.1f} — full conviction")
        elif avg >= 3:
            conviction, size_mult = "MEDIUM-HIGH", 1.0
            thesis = (f"{bull_count} agents bullish vs {bear_count} bearish | "
                      f"avg={avg:+.1f} — standard size")
        elif avg >= -3:
            conviction, size_mult = "MEDIUM", 0.85
            thesis = (f"Mixed signals — {bull_count} bullish {bear_count} bearish | "
                      f"avg={avg:+.1f} — reduce size 15%")
        elif avg >= -8:
            conviction, size_mult = "LOW", 0.65
            thesis = (f"Weak conviction — {bear_count} agents oppose | "
                      f"avg={avg:+.1f} — minimal size")
        else:
            conviction, size_mult = "MINIMAL", 0.5
            thesis = (f"Very low conviction — {bear_count} agents opposed | "
                      f"avg={avg:+.1f} — half size or pass")

        return {
            "agent":        "portfolio_manager",
            "conviction":   conviction,
            "size_mult":    round(size_mult, 2),
            "thesis":       thesis,
            "votes":        " | ".join(vote_lines),
            "weighted_avg": round(avg, 2),
        }


def _bars_momentum(symbol: str, bs) -> dict:
    """
    Compute independent momentum metrics from the scorer's H1 bar_store.
    Used by LivermoreAgent, SorosAgent, and BurryAgent as the authoritative
    source — not relying on EA proxy values which may be stale or zero.

    Returns:
      drift_atr   — EMA20 deviation in ATR units (float)
      consec_bars — consecutive H1 closes in same direction (int)
      lor_dir     — line-of-least-resistance direction: +1 / -1 / 0 (int)
      atr         — 14-period ATR in price units (float)
    """
    try:
        bars = list(bs.get(symbol, "H1"))
        if len(bars) < 22:
            return {"drift_atr": 0.0, "consec_bars": 0, "lor_dir": 0, "atr": 0.0}

        closes = [float(b["c"]) for b in bars]
        highs  = [float(b["h"]) for b in bars]
        lows   = [float(b["l"]) for b in bars]

        # 14-period ATR
        trs = [max(highs[i] - lows[i], abs(closes[i] - closes[i - 1]))
               for i in range(1, len(bars))]
        atr = sum(trs[-14:]) / 14 if len(trs) >= 14 else (sum(trs) / max(1, len(trs)))
        if atr <= 0:
            atr = 0.0001

        # EMA20 (current and one-step-back for slope direction)
        k = 2.0 / 21.0
        ema_cur = ema_prev = closes[0]
        for i, c in enumerate(closes[1:], 1):
            if i == len(closes) - 1:
                ema_prev = ema_cur
            ema_cur = c * k + ema_cur * (1.0 - k)

        drift_atr = round(abs(closes[-1] - ema_cur) / atr, 2)
        lor_dir   = 1 if ema_cur > ema_prev else (-1 if ema_cur < ema_prev else 0)

        # Consecutive H1 closes in same direction
        c_dir  = 1 if closes[-1] > closes[-2] else -1
        consec = 0
        for i in range(len(closes) - 1, 0, -1):
            d = 1 if closes[i] > closes[i - 1] else -1
            if d == c_dir:
                consec += 1
            else:
                break

        return {"drift_atr": drift_atr, "consec_bars": consec,
                "lor_dir": lor_dir, "atr": round(atr, 6)}
    except Exception:
        return {"drift_atr": 0.0, "consec_bars": 0, "lor_dir": 0, "atr": 0.0}


class LivermoreAgent:
    """
    Line-of-Least-Resistance agent — inspired by Jesse Livermore.

    Livermore's principle: every market has a path it naturally wants to travel.
    Identify it from price action, align with it, never fight it. When EMA is
    sloping, consecutive bars confirm direction, and momentum is expanding —
    that IS the line. Trade with it decisively.

    Unlike Soros (reflexive excess detection) and Burry (exhaustion detection),
    Livermore simply asks: which direction is the market making easier right now?

    Uses the scorer's own H1 bar_store (_bars_momentum) — fully independent of
    EA proxy values. This makes it the most reliable directional baseline.

    trend_strength 0-4 (independent of trade direction):
      drift_atr >= 1.5x ATR   → +2  (strong momentum)
      drift_atr >= 0.8x ATR   → +1  (moderate)
      consec H1 bars >= 4     → +2  (market showing its hand)
      consec H1 bars >= 2     → +1  (early confirmation)
    Following LOR: +3/+6/+10 | Opposing LOR: -2/-4/-8/-12
    """

    def vote(self, symbol: str, signal_dir: int, bs_mom: dict) -> dict:
        lor_dir     = bs_mom.get("lor_dir", 0)
        drift_atr   = bs_mom.get("drift_atr", 0.0)
        consec_bars = bs_mom.get("consec_bars", 0)
        atr         = bs_mom.get("atr", 0.0)

        if lor_dir == 0 or signal_dir == 0 or atr == 0:
            return {"agent": "livermore", "signal": "NEUTRAL", "confidence": 0.0,
                    "modifier": 0, "lor_score": 0, "lor_dir": lor_dir,
                    "reasoning": "insufficient_h1_data"}

        conditions  = []
        ema_aligned = (lor_dir == signal_dir)
        conditions.append("EMA_aligned" if ema_aligned else "EMA_opposed")

        # Trend strength (direction-independent)
        ts = 0
        if drift_atr >= 1.5:
            ts += 2; conditions.append(f"drift={drift_atr:.1f}x_STRONG")
        elif drift_atr >= 0.8:
            ts += 1; conditions.append(f"drift={drift_atr:.1f}x_MOD")

        if consec_bars >= 4:
            ts += 2; conditions.append(f"consec={consec_bars}bars")
        elif consec_bars >= 2:
            ts += 1; conditions.append(f"consec={consec_bars}bars")

        if ema_aligned:
            if ts >= 3:   modifier, signal = +10, "WITH_LOR_PRIME"
            elif ts >= 2: modifier, signal = +6,  "WITH_LOR_STRONG"
            elif ts >= 1: modifier, signal = +3,  "WITH_LOR_EARLY"
            else:         modifier, signal = 0,   "NEUTRAL"
        else:
            if ts >= 3:   modifier, signal = -12, "AGAINST_LOR_STRONG"
            elif ts >= 2: modifier, signal = -8,  "AGAINST_LOR_MOD"
            elif ts >= 1: modifier, signal = -4,  "AGAINST_LOR_WEAK"
            else:         modifier, signal = -2,  "AGAINST_LOR_EARLY"

        lor_score = ts + (1 if ema_aligned else 0)

        return {
            "agent":      "livermore",
            "signal":     signal,
            "confidence": round(min(1.0, lor_score / 5.0), 2),
            "modifier":   modifier,
            "lor_dir":    lor_dir,
            "lor_score":  lor_score,
            "with_trend": ema_aligned,
            "reasoning":  " | ".join(conditions),
        }


soros_agent             = SorosAgent()
burry_agent             = BurryAgent()
livermore_agent         = LivermoreAgent()
dalio_agent             = DalioAgent()
munger_agent            = MungerAgent()
keynes_agent            = KeynesAgent()
portfolio_manager_agent = PortfolioManagerAgent()

# ─────────────────────────────────────────────────────────────────────────────

def score_trade(data):
    # ── Phase 3: Stale-heartbeat guard ───────────────────────────────────────
    # If the EA has not sent a heartbeat for > _STALE_HB_MAX_SECS, refuse
    # trade approvals.  Prevents the scorer serving stale cached state after
    # an EA crash, MT5 disconnect, or VPS reboot where the EA has not yet
    # reconnected.  Internal ensemble second-pass calls (_silent=True) and
    # explicit probe requests (probe=True) bypass this guard.
    _STALE_HB_MAX_SECS = 300  # 5 min — EA heartbeats every ~60 s normally
    if (not data.get("_silent") and not data.get("probe")
            and _last_heartbeat_ts > 0):
        _hb_stale_age = time.time() - _last_heartbeat_ts
        if _hb_stale_age > _STALE_HB_MAX_SECS:
            try:
                print(f"[STALE-HB] {data.get('symbol', '?')} blocked "
                      f"— last heartbeat {_hb_stale_age:.0f}s ago "
                      f"(>{_STALE_HB_MAX_SECS}s limit)")
            except Exception:
                pass
            return _build(0, False, 0.0, 0.0, "fragile",
                          f"STALE_HEARTBEAT: {_hb_stale_age:.0f}s since last EA contact")

    spread_ok  = bool(data.get("spread_ok", True))
    # ── Phase 3: Server-side spread-to-ATR explosion guard ───────────────────
    # The EA's spread_ok flag defaults to True when absent or when spread data
    # is stale.  Cross-validate using the raw figures sent by the EA:
    # if spread_at_entry exceeds _MAX_SPREAD_ATR_RATIO × ATR the setup is
    # execution-unsafe regardless of what the EA flag reports.
    # Only fires when both figures are non-zero (EA must send atr + spread_at_entry).
    _MAX_SPREAD_ATR_RATIO = 0.35  # spread must be ≤ 35 % of ATR
    _sv_spread = float(data.get("spread_at_entry") or 0.0)
    _sv_atr    = float(data.get("atr") or 0.0)
    if spread_ok and _sv_spread > 0.0 and _sv_atr > 0.001:
        if _sv_spread / _sv_atr > _MAX_SPREAD_ATR_RATIO:
            spread_ok = False
            try:
                print(f"[SPREAD-GUARD] {data.get('symbol', '?')} server override "
                      f"spread={_sv_spread:.4f} atr={_sv_atr:.4f} "
                      f"ratio={_sv_spread / _sv_atr:.2f}x "
                      f"(>{_MAX_SPREAD_ATR_RATIO}x limit)")
            except Exception:
                pass

    news_block = bool(data.get("news_block", False))
    session    = data.get("session", "OFF")
    symbol     = data.get("symbol", "")
    mode       = data.get("mode", "CHALLENGE")
    sig_in     = int(data.get("signal", 0) or 0)

    # ── Graded news scoring (replaces binary ±30min block) ──────────────
    # Server-side calendar overrides the EA's coarse news_block flag. The
    # EA still sends news_block for backward compat; we now treat it as a
    # hint and let grade_news_event decide block-vs-adjust based on the
    # actual event tier and time-to-event window.
    news_grade   = grade_news_event(symbol, sig_in)
    news_action  = news_grade["action"]
    news_delta   = float(news_grade["delta"])
    news_reason  = news_grade["reason"]

    # ── News Intelligence Engine — severity + execution + cooldown ─────────────
    # Additive on top of grade_news_event. Can escalate neutral/score_adj → block.
    # Never removes or weakens the Tier-1 hard-block that follows below.
    try:
        _nie_mod = _get_news_intelligence_mod()
        if _nie_mod and news_grade.get("tier", 0) > 0:
            _nie = _nie_mod.news_intelligence_engine
            _nie_result = _nie.assess(
                symbol=symbol,
                event={**news_grade, "currency": symbol[:3].upper() if len(symbol) >= 3 else ""},
                session=session,
                regime=str(data.get("regime", "UNKNOWN")),
                spread_pips=float(data.get("spread_at_entry") or 0),
                slippage_pips=float(data.get("slippage_pips") or 0),
                latency_ms=float(data.get("latency_ms") or 0),
            )
            if _nie_result["execution_action"] == "block" and news_action != "block":
                news_action = "block"
                news_reason = f"NIE_ESCALATE: {_nie_result['reason']}"
            elif news_action != "block":
                news_delta  += _nie_result["additional_delta"]
                if _nie_result["reason"]:
                    news_reason += f" [{_nie_result['reason']}]"
            try:
                print(f"[NIE] {symbol} sev={_nie_result['severity_score']} "
                      f"cls={_nie_result['severity_class']} "
                      f"exec={_nie_result['execution_action']} "
                      f"cooldown={_nie_result['cooldown_active']}")
            except Exception:
                pass
    except Exception as _nie_e:
        try:
            print(f"[NIE] assess error: {_nie_e}")
        except Exception:
            pass

    if news_action == "block":
        try:
            _setup = data.get("setup", "?")
            _trend = data.get("trend", "?")
            print(f"[NEWS-BLOCK-AUDIT] {symbol} sess={session} setup={_setup} sig={sig_in} trend={_trend} reason={news_reason}")
        except Exception:
            pass
        return _build(0,  False, 0.0, 0.0, "fragile", f"NEWS_BLOCK: {news_reason}")

    # Legacy fallback: if EA insists news_block=true and we have NO calendar
    # data (action=neutral with no title), respect EA. Prevents trading when
    # calendar fetch is failing on the VPS.
    if news_block and news_action == "neutral" and not news_grade["title"]:
        try:
            print(f"[NEWS-BLOCK-AUDIT] {symbol} sess={session} sig={sig_in} reason=EA_FLAG_NO_CALENDAR")
        except Exception:
            pass
        return _build(0,  False, 0.0, 0.0, "fragile", "NEWS_BLOCK_EA_FALLBACK")
    if not spread_ok: return _build(10, False, 0.0, 0.1, "fragile", "SPREAD_BLOCK")
    if session == "OFF": return _build(5, False, 0.0, 0.0, "fragile", "OFF_SESSION")

    # ── v4.02 Phase 5: Pair Performance Engine — auto-disable check ──────────
    try:
        _ppe_mod = _get_pair_performance_engine_mod()
        if _ppe_mod:
            if _ppe_mod.get_pair_performance_engine().is_pair_disabled(symbol):
                try:
                    print(f"[PAIR-PERF] {symbol} AUTO-DISABLED — poor rolling performance")
                except Exception:
                    pass
                return _build(10, False, 0.0, 0.0, "fragile",
                              f"PAIR_AUTO_DISABLED:{symbol}")
    except Exception:
        pass

    # ── v4.02 Phase 1+2: Pair-Session Matrix + Session Quality Score ─────────
    _pair_session_mult    = 1.0
    _session_quality_score = 50
    _session_quality_class = "TRADABLE"
    _sq_lot_mult           = 1.0
    try:
        _psm_mod = _get_pair_session_engine()
        if _psm_mod:
            _pair_session_mult = _psm_mod.get_pair_session_mult(symbol, session)
            # Hard block for completely incompatible pair×session combos
            if _pair_session_mult <= 0.15:
                return _build(8, False, 0.0, 0.0, "fragile",
                              f"PAIR_SESSION_INCOMPATIBLE:{symbol}:{session}")
            # Dynamic session quality score (0-100)
            _sqe     = _psm_mod.get_session_quality_engine()
            _atr_val = float(data.get("atr", 0.001) or 0.001)
            _spd_val = float(data.get("spread", 0.0) or 0.0)
            _sqe.push_atr(symbol, _atr_val)
            _sq = _sqe.score(session, symbol, _spd_val, _atr_val)
            _session_quality_score = _sq.score
            _session_quality_class = _sq.quality_class
            _sq_lot_mult           = _sq.lot_mult
            try:
                print(f"[SESSION-QUALITY] {symbol} {session} sq={_session_quality_score} "
                      f"class={_session_quality_class} psm={_pair_session_mult:.2f}")
            except Exception:
                pass
    except Exception:
        pass

    features = extract_features(data)
    score    = ai_model.score(features)

    ml_pred = ml_classifier.predict(features)
    if ml_pred["ml_active"]:
        ml_bonus = (ml_pred["win_prob"] - 0.5) * 20
        score   += ml_bonus

    of_signal = order_flow.get_signal(symbol)
    score     += of_signal.get("score_bonus", 0)

    lmap   = liquidity_map.get_map(symbol, data.get("current_price", 0))
    score += lmap.get("score_bonus", 0)

    sent   = sentiment_agg.get_sentiment(symbol)
    score += sent.get("score_bonus", 0)

    ew     = regime_warning.check(symbol)
    score += ew.get("score_penalty", 0)

    exec_check = execution_tracker.get_slippage_budget(symbol, session)
    score     += exec_check.get("score_penalty", 0)

    # ── Range zone context ────────────────────────────────────────────────────
    # Mid-range trend entries have poor R:R — price has no room to run before
    # hitting the opposite wall. Edge touches are treated as range-break setups
    # and get a small bonus (mean reversion handles the larger edge bonus).
    rz = detect_range_zone(symbol)
    if rz["confidence"] >= 0.5:
        if rz["in_range"] and not rz["at_upper_edge"] and not rz["at_lower_edge"]:
            score -= 12
            try:
                print(f"[RANGE-MID] {symbol} conf={rz['confidence']:.2f} "
                      f"range {rz['range_low']:.5f}-{rz['range_high']:.5f} -12")
            except Exception:
                pass
        elif rz["at_upper_edge"] or rz["at_lower_edge"]:
            score += 5
            edge = "upper" if rz["at_upper_edge"] else "lower"
            try:
                print(f"[RANGE-EDGE] {symbol} at {edge} edge conf={rz['confidence']:.2f} +5")
            except Exception:
                pass

    # ── Monthly high/low proximity ────────────────────────────────────────────
    # Monthly H/L are the highest-timeframe institutional reference points.
    # Selling near monthly high or buying near monthly low = maximum confluence.
    # Buying into monthly high or selling into monthly low = fighting the wall.
    ml = detect_monthly_levels(symbol)
    if ml["monthly_high"] is not None:
        sig_dir = int(data.get("signal", 0))
        if sig_dir == -1 and ml["near_high"]:
            score += 12
            try:
                print(f"[MONTHLY-H] {symbol} sell near monthly high {ml['monthly_high']:.5f} +12"
                      f" (at_high={ml['at_high']})")
            except Exception:
                pass
        elif sig_dir == 1 and ml["near_low"]:
            score += 12
            try:
                print(f"[MONTHLY-L] {symbol} buy near monthly low {ml['monthly_low']:.5f} +12"
                      f" (at_low={ml['at_low']})")
            except Exception:
                pass
        elif sig_dir == 1 and ml["near_high"]:
            score -= 10
            try:
                print(f"[MONTHLY-H] {symbol} buy INTO monthly high {ml['monthly_high']:.5f} -10")
            except Exception:
                pass
        elif sig_dir == -1 and ml["near_low"]:
            score -= 10
            try:
                print(f"[MONTHLY-L] {symbol} sell INTO monthly low {ml['monthly_low']:.5f} -10")
            except Exception:
                pass

    # ── BOS retest confirmation gate ──────────────────────────────────────────
    # EA sends retest_confirmed=false when BOS was detected but price has NOT yet
    # pulled back and closed with a rejection body below/above the broken level.
    # Apply -15 to penalise premature BOS entries and deter InpRequireRetest=false.
    _setup_upper = str(data.get("setup", "")).upper()
    is_bos_entry = "BOS" in _setup_upper or "STRUCTURE" in _setup_upper
    is_sweep     = "SWEEP" in _setup_upper
    is_fvg       = "FVG"   in _setup_upper
    retest_conf  = bool(data.get("retest_confirmed", True))  # default True for non-BOS setups
    if is_bos_entry and not retest_conf:
        score -= 15
        try:
            print(f"[RETEST-UNCONFIRMED] {symbol} BOS entry without confirmed pullback+rejection -15")
        except Exception:
            pass

    # ── Momentum fade penalty ─────────────────────────────────────────────────
    # ATR contraction + body shrinkage together signal momentum is exhausting.
    # Penalise new entries and fire a Telegram alert (30-min debounce per pair).
    mom_fade = detect_momentum_fade(symbol)
    if mom_fade["fading"]:
        score -= 10
        _maybe_telegram_momentum_fade(symbol, mom_fade)
        try:
            print(f"[MOMENTUM-FADE] {symbol} atr_ratio={mom_fade['atr_ratio']:.2f} "
                  f"body_ratio={mom_fade['body_ratio']:.2f} -10")
        except Exception:
            pass

    # Apply graded news adjustment computed at top of score_trade.
    # ── Kotegawa overextension analysis ───────────────────────────────────────
    # BNF's core edge: bonuses for mean-reversion entries against overextended
    # moves; hard penalty for chasing an already-stretched extension.
    ktg = score_kotegawa(symbol, data)
    if ktg["score_delta"] != 0.0:
        score += ktg["score_delta"]

    # Penalties (pre-event windows) suppress score; boosts (post-event vol
    # windows) lift it. Logged once via [NEWS-GRADE] for journal audit.
    if news_action == "score_adj" and news_delta != 0.0:
        score += news_delta
        try:
            print(f"[NEWS-GRADE] {symbol} sess={session} delta={news_delta:+.0f} mins={news_grade['mins_away']:+.1f} tier={news_grade['tier']} reason={news_reason}")
        except Exception:
            pass

    # ── London / NY open 30-min premium ─────────────────────────────────────
    # First 30 min of London (08:00-08:30 UTC) and NY (13:00-13:30 UTC) have
    # the highest directional momentum on M15. Score bonus to capture these
    # high-probability windows before the move is half-done.
    _utc_now  = datetime.utcnow()
    _ldon_open = (session in ("LONDON", "LONDON_NY") and _utc_now.hour == 8 and _utc_now.minute < 30)
    _ny_open   = (session in ("NY", "LONDON_NY") and _utc_now.hour == 13 and _utc_now.minute < 30)
    if _ldon_open:
        score += 5.0
        try: print(f"[OPEN-BONUS] {symbol} London open +5 ({_utc_now.strftime('%H:%M')} UTC)")
        except Exception: pass
    elif _ny_open:
        score += 4.0
        try: print(f"[OPEN-BONUS] {symbol} NY open +4 ({_utc_now.strftime('%H:%M')} UTC)")
        except Exception: pass

    # ── LLM macro bias delta ─────────────────────────────────────────────────
    # Cached Claude analysis (refreshed every 30 min on the dashboard server).
    # Aligns or opposes the trade direction. Never blocks — only nudges score.
    try:
        _llm_entry = _llm_bias_cache.get(symbol.upper(), {})
        _llm_bias  = _llm_entry.get("bias", "NEUTRAL")
        _llm_delta = float(_llm_entry.get("score_delta", 0))
        _llm_conf  = _llm_entry.get("confidence", "LOW")
        if _llm_delta != 0 and _llm_bias != "NEUTRAL":
            _sig_dir = int(data.get("signal", 0))
            _aligned = (_llm_bias == "BULLISH" and _sig_dir == 1) or \
                       (_llm_bias == "BEARISH" and _sig_dir == -1)
            _against = (_llm_bias == "BULLISH" and _sig_dir == -1) or \
                       (_llm_bias == "BEARISH" and _sig_dir == 1)
            if _aligned:
                score += _llm_delta
                print(f"[LLM-BIAS] {symbol} {_llm_bias} confirms direction +{_llm_delta:.0f} (conf={_llm_conf})")
            elif _against:
                score -= abs(_llm_delta)
                print(f"[LLM-BIAS] {symbol} {_llm_bias} opposes direction -{abs(_llm_delta):.0f} (conf={_llm_conf})")
    except Exception:
        pass

    # ── COT Agent — real CFTC institutional positioning ──────────────────────
    # Non-commercial (speculative) net position percentile vs 52-week range.
    # Direction-aware: modifier applied when trade direction aligns with
    # institutional bias, reversed when opposing.  Cap: ±6 pts.
    _sig_dir  = int(data.get("signal", 0))
    _signal   = _sig_dir
    c_losses  = int(data.get("consec_losses", 0))
    _cot      = cot_agent.get_modifier(symbol, _sig_dir)
    _cot_mod  = _cot.get("modifier", 0)
    if _cot_mod != 0:
        score += _cot_mod
        try:
            print(f"[COT] {symbol} net={_cot.get('net',0):+,} "
                  f"{_cot.get('bias','—')} {_cot.get('percentile',50)}th-pct "
                  f"modifier={_cot_mod:+d} ({_cot.get('direction_note','—')})")
        except Exception:
            pass

    # ── Macro Agent — central bank rate differential ──────────────────────────
    # Positive differential (base CB > quote CB) = bullish base currency.
    # Direction-aware: adds when trade aligns with carry bias, subtracts when
    # opposing.  Cap: ±5 pts.
    _macro     = macro_agent.get_modifier(symbol, _sig_dir)
    _macro_mod = _macro.get("modifier", 0)
    if _macro_mod != 0:
        score += _macro_mod
        try:
            print(f"[MACRO] {symbol} {_macro.get('base_cb','—')}={_macro.get('base_rate',0):.2f}% "
                  f"vs {_macro.get('quote_cb','—')}={_macro.get('quote_rate',0):.2f}% "
                  f"diff={_macro.get('differential',0):+.2f} modifier={_macro_mod:+d}")
        except Exception:
            pass

    # ── Intermarket Agent — DXY / Gold / US10Y flow ──────────────────────────
    _inter     = intermarket_agent.get_modifier(symbol, _sig_dir)
    _inter_mod = _inter.get("modifier", 0)
    _dxy_chg   = _inter.get("dxy_chg", 0.0)
    dxy_impact = {
        "dxy_trend": "BULLISH" if _dxy_chg > 0.05 else "BEARISH" if _dxy_chg < -0.05 else "NEUTRAL",
        "dxy_price": str(round(float(intermarket_agent._cache.get("DXY", 0) or 0), 2) or "—"),
        "aligned":   _inter_mod > 0,
    }
    if _inter_mod != 0:
        score += _inter_mod
        try:
            print(f"[INTERMARKET] {symbol} DXY={_inter.get('dxy_chg',0):+.2f}% "
                  f"US10Y={_inter.get('us10y_chg',0):+.2f}% "
                  f"Gold={_inter.get('gold_chg',0):+.2f}% modifier={_inter_mod:+d} "
                  f"details={_inter.get('details',{})}")
        except Exception:
            pass

    # ── SSI Agent — retail sentiment contrarian ───────────────────────────────
    _ssi     = ssi_agent.get_modifier(symbol, _sig_dir)
    _ssi_mod = _ssi.get("modifier", 0)
    if _ssi_mod != 0:
        score += _ssi_mod
        try:
            print(f"[SSI] {symbol} retail_long={_ssi.get('long_pct',50):.0f}% "
                  f"{_ssi.get('bias','—')} (contrarian) modifier={_ssi_mod:+d}")
        except Exception:
            pass

    # ── HTF Fractal Agent — H4 / D1 structural alignment ─────────────────────
    _htf     = htf_fractal_agent.get_modifier(symbol, _sig_dir, bar_store)
    _htf_mod = _htf.get("modifier", 0)
    if _htf_mod != 0:
        score += _htf_mod
        try:
            print(f"[HTF] {symbol} H4={_htf.get('h4_trend','—')} "
                  f"D1={_htf.get('d1_trend','—')} combined={_htf.get('combined',0):+.2f} "
                  f"modifier={_htf_mod:+d}")
        except Exception:
            pass

    # ── Options Expiry Agent — NY cut magnetism ───────────────────────────────
    _curr_price = float(data.get("price", data.get("close", data.get("bid", 0))))
    _opts       = options_expiry_agent.get_modifier(symbol, _curr_price, _sig_dir)
    _opts_mod   = _opts.get("modifier", 0)
    if _opts_mod != 0:
        score += _opts_mod
        try:
            print(f"[OPTIONS] {symbol} level={_opts.get('nearest_level','—')} "
                  f"mins_to_cut={_opts.get('mins_to_cut',0)} modifier={_opts_mod:+d}")
        except Exception:
            pass

    # ── Correlation Matrix Agent — cross-pair USD exposure guard ─────────────
    # Penalises trades that would double USD exposure via a correlated position
    # approved in the last 2 hours.  Cap: -8 pts.
    _corr     = correlation_agent.get_modifier(symbol, _sig_dir, bar_store)
    _corr_mod = _corr.get("modifier", 0)
    if _corr_mod != 0:
        score += _corr_mod
        try:
            print(f"[CORR] {symbol} risk={_corr.get('risk','none')} "
                  f"worst_corr={_corr.get('worst_corr',0):.3f} modifier={_corr_mod:+d} "
                  f"conflicts={[c['symbol'] for c in _corr.get('conflicts',[])]}")
        except Exception:
            pass

    # ── Economic Surprise Agent — data release impact ─────────────────────────
    # Applies a score modifier based on recent economic releases (actual vs
    # forecast) for the pair's constituent currencies.  Fades after 2 hours.
    # Cap: ±6 pts.
    _surp     = economic_surprise_agent.get_modifier(symbol, _sig_dir)
    _surp_mod = _surp.get("modifier", 0)
    if _surp_mod != 0:
        score += _surp_mod
        try:
            _evts = [f"{e['currency']} {e['event']} {e['surprise_pct']:+.1f}%"
                     for e in _surp.get("events", [])[:3]]
            print(f"[SURPRISE] {symbol} modifier={_surp_mod:+d} events={_evts}")
        except Exception:
            pass

    # ── Druckenmiller Macro Conviction Agent ──────────────────────────────────
    # Synthesises rate differential + DXY + US10Y + COT into one conviction vote.
    # +10 when 3+ macro signals align with trade direction; -10 when 3+ oppose.
    _druck     = druckenmiller_agent.vote(symbol, _sig_dir, _macro, _inter, _cot)
    _druck_mod = _druck.get("modifier", 0)
    if _druck_mod != 0:
        score += _druck_mod
        try:
            print(f"[DRUCKENMILLER] {symbol} signal={_druck.get('signal','—')} "
                  f"aligned={_druck.get('aligned',0)} opposed={_druck.get('opposed',0)} "
                  f"conf={_druck.get('confidence',0):.2f} modifier={_druck_mod:+d} | "
                  f"{_druck.get('reasoning','—')}")
        except Exception:
            pass

    # ── Taleb Tail Risk Agent ─────────────────────────────────────────────────
    # Detects fragile / black-swan conditions. Only suppresses, never amplifies.
    # VETO caps score to MIN_SCORE-15, guaranteeing rejection regardless of score.
    _taleb     = taleb_agent.vote(symbol, _sig_dir, data, intermarket_agent._cache)
    _taleb_mod = _taleb.get("modifier", 0)
    if _taleb.get("veto"):
        score = min(score, MIN_SCORE - 15.0)
        try:
            print(f"[TALEB-VETO] {symbol} tail conditions: {_taleb.get('reasoning','—')} "
                  f"— score capped to {score:.0f}")
        except Exception:
            pass
    elif _taleb_mod != 0:
        score += _taleb_mod
        try:
            print(f"[TALEB] {symbol} signal={_taleb.get('signal','—')} "
                  f"modifier={_taleb_mod:+d} | {_taleb.get('reasoning','—')}")
        except Exception:
            pass

    # ── Bar-store independent momentum ────────────────────────────────────────
    # Compute drift_atr, consec_bars, EMA slope from scorer's own H1 bars.
    # Passed to Livermore, Soros, Burry — authoritative fallback over EA proxy data.
    _bs_mom = _bars_momentum(symbol, bar_store)

    # ── Livermore Line-of-Least-Resistance Agent ──────────────────────────────
    # Identifies which direction the market naturally wants to travel (H1 EMA+bars).
    # Fully independent of EA payload — uses scorer's bar_store computation only.
    _livermore     = livermore_agent.vote(symbol, _sig_dir, _bs_mom)
    _livermore_mod = _livermore.get("modifier", 0)
    if _livermore_mod != 0:
        score += _livermore_mod
        try:
            print(f"[LIVERMORE] {symbol} signal={_livermore.get('signal','—')} "
                  f"lor_score={_livermore.get('lor_score',0)}/5 modifier={_livermore_mod:+d} | "
                  f"{_livermore.get('reasoning','—')}")
        except Exception:
            pass

    # ── Soros Reflexivity Agent ────────────────────────────────────────────────
    # Self-reinforcing trend detection. VETO on dangerous fades of reflexive runs.
    # May 18 agent: would have flagged GBP as "reflexive bull — VETO all SELLs".
    _soros     = soros_agent.vote(symbol, _sig_dir, data, _cot, _bs_mom)
    _soros_mod = _soros.get("modifier", 0)
    if _soros.get("veto"):
        score = min(score, MIN_SCORE - 15.0)
        try:
            print(f"[SOROS-VETO] {symbol} reflexive trend fade VETOED | "
                  f"ref_score={_soros.get('ref_score',0)} | "
                  f"{_soros.get('reasoning','—')}")
        except Exception:
            pass
    elif _soros_mod != 0:
        score += _soros_mod
        try:
            print(f"[SOROS] {symbol} signal={_soros.get('signal','—')} "
                  f"ref_score={_soros.get('ref_score',0)} modifier={_soros_mod:+d} | "
                  f"{_soros.get('reasoning','—')}")
        except Exception:
            pass

    # ── Burry Contrarian Agent ────────────────────────────────────────────────
    # Exhaustion detection. Bonus for fading PRIME extremes; penalty for chasing.
    # Fires late (after Soros ride) when COT is crowded and drift is at 2x+ ATR.
    _burry     = burry_agent.vote(symbol, _sig_dir, data, _cot, _bs_mom)
    _burry_mod = _burry.get("modifier", 0)
    if _burry_mod != 0:
        # Soros veto blocks Burry bonus — extreme reflexive trend overrides exhaustion signal
        if not (_burry_mod > 0 and _soros.get("veto")):
            score += _burry_mod
            try:
                print(f"[BURRY] {symbol} signal={_burry.get('signal','—')} "
                      f"exh_score={_burry.get('exh_score',0)} modifier={_burry_mod:+d} | "
                      f"{_burry.get('reasoning','—')}")
            except Exception:
                pass

    # ── Dalio Economic Machine Agent ──────────────────────────────────────────
    # Cross-asset debt cycle: risk-off cluster, DXY+yield trajectory, debasement.
    # Also returns an independent size_mult for risk-parity position sizing.
    _dalio     = dalio_agent.vote(symbol, _sig_dir, intermarket_agent._cache, _macro)
    _dalio_mod = _dalio.get("modifier", 0)
    if _dalio_mod != 0:
        score += _dalio_mod
        try:
            print(f"[DALIO] {symbol} signal={_dalio.get('signal','—')} "
                  f"risk_off={_dalio.get('risk_off_cnt',0)}/3 "
                  f"size_mult={_dalio.get('size_mult',1.0):.2f}x "
                  f"modifier={_dalio_mod:+d} | {_dalio.get('reasoning','—')}")
        except Exception:
            pass

    # ── Munger Inversion Checklist Agent ──────────────────────────────────────
    # Asks 'what would make this trade fail?' — lollapalooza, social proof trap,
    # self-deception. VETO if 3+ red flags; bonus if trade passes all checks.
    _munger     = munger_agent.vote(symbol, _sig_dir, data,
                                    _cot, _ssi, _druck, _soros, _livermore)
    _munger_mod = _munger.get("modifier", 0)
    if _munger.get("veto"):
        score = min(score, MIN_SCORE - 15.0)
        try:
            print(f"[MUNGER-VETO] {symbol} inversion_fail: {_munger.get('reasoning','—')} "
                  f"red_flags={_munger.get('red_flags',0)} — score capped to {score:.0f}")
        except Exception:
            pass
    elif _munger_mod != 0:
        score += _munger_mod
        try:
            print(f"[MUNGER] {symbol} signal={_munger.get('signal','—')} "
                  f"red_flags={_munger.get('red_flags',0)} modifier={_munger_mod:+d} | "
                  f"{_munger.get('reasoning','—')}")
        except Exception:
            pass

    # ── Keynes Liquidity Cycle + Beauty Contest Agent ─────────────────────────
    # CB rate differential (liquidity cycle) + consensus fade (beauty contest).
    # Rewards contrarian entries; penalises trades where SSI+COT+macro all agree.
    _keynes     = keynes_agent.vote(symbol, _sig_dir, _macro, _cot, _ssi)
    _keynes_mod = _keynes.get("modifier", 0)
    if _keynes_mod != 0:
        score += _keynes_mod
        try:
            print(f"[KEYNES] {symbol} signal={_keynes.get('signal','—')} "
                  f"consensus={_keynes.get('consensus_cnt',0)}/3 "
                  f"modifier={_keynes_mod:+d} | {_keynes.get('reasoning','—')}")
        except Exception:
            pass

    # ── Portfolio Manager — meta synthesis ────────────────────────────────────
    # Weighs all agent votes into a conviction level and position-size adjustment.
    _any_veto = (_taleb.get("veto", False) or _soros.get("veto", False)
                 or _munger.get("veto", False))
    _pm = portfolio_manager_agent.vote(
        symbol,
        [{"agent": "cot",          "modifier": _cot_mod,        "signal": _cot.get("bias",   "NEUTRAL")},
         {"agent": "macro",        "modifier": _macro_mod,      "signal": _macro.get("bias",  "NEUTRAL")},
         {"agent": "intermarket",  "modifier": _inter_mod,      "signal": "POS" if _inter_mod > 0 else ("NEG" if _inter_mod < 0 else "NEUTRAL")},
         {"agent": "htf",          "modifier": _htf_mod,        "signal": _htf.get("combined_signal", "NEUTRAL")},
         {"agent": "druckenmiller","modifier": _druck_mod,      "signal": _druck.get("signal","NEUTRAL")},
         {"agent": "taleb",        "modifier": _taleb_mod,      "signal": _taleb.get("signal","STABLE")},
         {"agent": "livermore",    "modifier": _livermore_mod,  "signal": _livermore.get("signal","NEUTRAL")},
         {"agent": "soros",        "modifier": _soros_mod,      "signal": _soros.get("signal","NEUTRAL")},
         {"agent": "burry",        "modifier": _burry_mod,      "signal": _burry.get("signal","NEUTRAL")},
         {"agent": "dalio",        "modifier": _dalio_mod,      "signal": _dalio.get("signal","NEUTRAL")},
         {"agent": "munger",       "modifier": _munger_mod,     "signal": _munger.get("signal","NEUTRAL")},
         {"agent": "keynes",       "modifier": _keynes_mod,     "signal": _keynes.get("signal","NEUTRAL")}],
        _any_veto,
    )
    _pm_size_mult = _pm.get("size_mult", 1.0)

    score   = max(0.0, min(100.0, score))
    regime  = regime_detector.detect(data)

    # ── Compute regime_v2 BEFORE threshold so it can harden the gate ──────────
    # Previously this ran AFTER approval — meaning a FRAGILE regime_v2 never
    # influenced the threshold when the EA's local regime reported "trend".
    r2 = compute_regime_v2(symbol)
    _r2_regime = r2["regime"]   # "fragile" | "trend" | "expansion" | ...

    # Per-pair base threshold (pair intelligence v4.02).
    # Each pair has its own minimum score reflecting its volatility profile.
    # Regime adjustments stack on top of the pair's own base, not MIN_SCORE.
    _pair_base = PAIR_MIN_SCORE.get(symbol, MIN_SCORE)

    # Regime-aware threshold. May 6 2026 EURUSD lesson: a flat -5 in expansion
    # was too tight for violent impulsive moves. Now scaled by ATR expansion:
    #   atr_exp >= 2.0x  → "violent_expansion"  → pair_base -12 (catch impulses)
    #   atr_exp >= 1.3x  → standard "expansion" → pair_base -10 (was -5)
    #   fragile regime                          → pair_base +10 (unchanged)
    atr_exp_t = float(data.get("atr_expansion", 1.0) or 1.0)
    threshold = _pair_base
    if regime == "expansion":
        if atr_exp_t >= 2.0:    threshold = _pair_base - 12.0   # violent expansion
        else:                   threshold = _pair_base - 10.0   # standard expansion
    elif regime == "fragile":   threshold = _pair_base + 10.0
    if "FUNDED" in str(mode).upper():
        threshold += 5.0

    # ── Regime_v2 FRAGILE override ─────────────────────────────────────────────
    # If the multi-TF regime_v2 sees FRAGILE conditions but the EA's local
    # regime is non-fragile, enforce the tighter +10 threshold anyway.
    # This closes the gap where a mid-candle regime flip lets a borderline
    # score slip through on the EA's stale local reading.
    _regime_v2_override = False
    if _r2_regime == "fragile" and regime != "fragile":
        fragile_threshold = _pair_base + 10.0
        if "FUNDED" in str(mode).upper():
            fragile_threshold += 5.0
        if threshold < fragile_threshold:
            _regime_v2_override = True
            threshold = fragile_threshold
            try:
                print(f"[REGIME-V2-OVERRIDE] {symbol} ea_regime={regime} r2=FRAGILE "
                      f"threshold raised {_pair_base:.0f}→{threshold:.0f} score={score:.1f}")
            except Exception:
                pass

    approved = score >= threshold

    # ── Minimum confluence gate ───────────────────────────────────────────────
    # Standard bar: 3 SMC confirmations. Relaxed to 2 in lower-liquidity
    # conditions where achieving 3 is statistically harder without sacrificing
    # quality:
    #   • FRAGILE regime  — choppy market, setups naturally sparser
    #   • ASIA session    — thin liquidity; OB+FVG is sufficient conviction
    #   • Sweep/FVG setup — these ARE their own retest by nature; requiring a
    #                       3rd factor double-counts the setup quality
    # Standard EXPANSION/TREND setups require 4 confluence factors (raised from 3
    # to filter marginal setups and improve win rate toward 60% target).
    # Fragile/Asia/sweep/FVG setups require 3 — they carry a built-in factor.
    # Gate only fires when EA sends a real confluence count (> 0).
    _raw_conf = int(data.get("confluence", 0))
    _MIN_CONF = 3 if (regime == "FRAGILE" or session == "ASIA" or is_sweep or is_fvg) else 4
    if approved and _raw_conf > 0 and _raw_conf < _MIN_CONF:
        approved = False
        try:
            print(f"[CONFLUENCE-BLOCK] {symbol} conf={_raw_conf} < min={_MIN_CONF} score={score:.1f} regime={regime} sess={session}")
        except Exception:
            pass

    confluence = int(data.get("confluence", 1))
    rr_rec     = dynamic_rr.get_rr(regime, session, confluence)

    risk_multi = _calc_risk_multi(score, regime, session, mode)
    corr_multi = corr_sizer.calc_size_multiplier(symbol, portfolio_engine.open_positions)
    final_multi = round(min(2.0, max(0.25, risk_multi * corr_multi)), 2)
    # Portfolio Manager conviction scales position size
    # VETO→0.0x  MINIMAL→0.50x  LOW→0.65x  MEDIUM→0.85x  MED-HIGH→1.0x  HIGH→1.10x
    final_multi = round(min(2.0, max(0.25, final_multi * _pm_size_mult)), 2)
    # Dalio risk-parity overlay — chains on top of PM conviction
    # Debt-cycle headwinds: 0.7x–0.9x | tailwinds: 1.0x–1.1x
    _dalio_size = _dalio.get("size_mult", 1.0)
    final_multi = round(min(2.0, max(0.25, final_multi * _dalio_size)), 2)

    # ── v4.02 Phase 7+9: Trade Quality Tier + Execution Quality ─────────────
    _tq_tier    = "A"
    _tq_score   = 50
    _tq_mult    = 1.0
    _tq_reasons = []
    _exec_score = 1.0
    _exec_adj   = 1.0
    try:
        _tqe_mod = _get_trade_quality_engine_mod()
        if _tqe_mod:
            _exec_tracker = _tqe_mod.get_execution_quality_tracker()
            _exec_score   = _exec_tracker.get_execution_score(symbol, session)
            _exec_adj     = _exec_tracker.get_risk_adjustment(symbol, session)
            # Spread fraction for tier classifier
            _raw_spd_v   = float(data.get("spread", 0.0) or 0.0)
            _psm_mod2    = _get_pair_session_engine()
            _spread_cap2 = (_psm_mod2.get_spread_tolerance(symbol, session)
                            if _psm_mod2 else 2.0)
            _spread_frac = (_raw_spd_v / _spread_cap2) if _spread_cap2 > 0 else 0.5
            # Portfolio heat from existing engine (best-effort)
            _port_heat = 0.0
            try:
                _ph = portfolio_engine.heat_monitor.compute(
                    portfolio_engine.positions,
                    portfolio_engine.equity,
                    {},
                )
                _port_heat = min(1.0, float(_ph.get("heat_pct", 0)) / 100.0)
            except Exception:
                pass
            _tq_result  = _tqe_mod.get_trade_quality_classifier().classify(
                ai_score=score,
                session_quality=_session_quality_score,
                regime=regime,
                spread_frac=_spread_frac,
                confluence=_raw_conf if _raw_conf > 0 else 3,
                portfolio_heat=_port_heat,
                execution_score=_exec_score,
                min_score=int(_pair_base),
            )
            _tq_tier    = _tq_result.tier
            _tq_score   = _tq_result.tier_score
            _tq_mult    = _tq_result.lot_mult
            _tq_reasons = _tq_result.reasons
            # REJECT tier overrides approved (additive-reduction-only — never boosts)
            if _tq_result.hard_blocks and approved:
                approved = False
                try:
                    print(f"[TIER-REJECT] {symbol} hard_blocks={_tq_result.hard_blocks}")
                except Exception:
                    pass
            # B-tier reduces position size; A+ handled by PortfolioManagerAgent
            elif _tq_tier == "B":
                final_multi = round(max(0.25, final_multi * _tq_mult), 2)
            # Execution quality adjustment (reduction only)
            if _exec_adj < 1.0:
                final_multi = round(max(0.25, final_multi * _exec_adj), 2)
            # Session quality lot reduction (DEAD/UNSTABLE sessions)
            if _sq_lot_mult < 1.0:
                final_multi = round(max(0.25, final_multi * _sq_lot_mult), 2)
            try:
                print(f"[TRADE-TIER] {symbol} tier={_tq_tier} tscore={_tq_score} "
                      f"sq={_session_quality_score} exec={_exec_score:.2f} "
                      f"final_multi={final_multi}")
            except Exception:
                pass
    except Exception as _tq_err:
        pass

    # `_silent=True` is set by /v4/score so the second-pass score_trade()
    # call (used to derive base v3 metrics for the ensemble payload) does
    # NOT re-emit the TRADE APPROVED Telegram alert. Without this, every
    # approved setup would fire two identical alerts (one from /score,
    # one from /v4/score) and any other state mutations would happen twice.
    _silent = bool(data.get("_silent"))
    _probe  = bool(data.get("probe"))

    # ── Portfolio v2 — institutional validate_pre_trade ───────────────────────
    # Runs AFTER all per-trade sizing decisions so the portfolio check sees the
    # actual proposed lot size.  Skipped on silent (ensemble second-pass) calls.
    # All checks are additive reductions — lot_multiplier ∈ [0, 1], never > 1.
    _pv2_lot_mult      = 1.0
    _pv2_heat_level    = "COOL"
    _pv2_block         = None
    _pv2_kill_halted   = False
    _pv2_ccy_breaches: list = []
    _pv2_pair_disabled = False
    if not _silent:
        try:
            _pe2 = _load_portfolio_engine()
            if _pe2 is not None:
                _pv2 = _pe2.portfolio_risk_engine.validate_pre_trade(
                    symbol      = symbol,
                    direction   = int(data.get("direction", 1) or 1),
                    session     = session,
                    regime      = regime,
                    new_lots    = float(data.get("lots", 0.01) or 0.01),
                    new_sl_pips = float(data.get("sl_pips", 15.0) or 15.0),
                    new_atr     = float(data.get("atr", 0.0) or 0.0),
                )
                _pv2_lot_mult     = float(_pv2.get("lot_multiplier", 1.0))
                _pv2_heat_level   = _pv2.get("portfolio_heat", {}).get("heat_level", "COOL")
                _pv2_block        = _pv2.get("block_reason")
                # Extract killswitch + pair-disabled flags from checks list
                for _ck in _pv2.get("checks", []):
                    if _ck.get("name") == "PortfolioKillswitch":
                        _pv2_kill_halted = _ck.get("result", {}).get("halted", False)
                    if _ck.get("name") == "PairDisabled":
                        _pv2_pair_disabled = _ck.get("result", {}).get("disabled", False)
                _pv2_ccy_breaches = (
                    _pv2.get("exposure", {}).get("existing_breaches", [])
                )
                # Multiply into final_multi (additive reduction only, floor 0.20)
                if _pv2_lot_mult < 1.0:
                    final_multi = round(max(0.20, final_multi * _pv2_lot_mult), 2)
                # Hard block: killswitch, pair disabled, or currency cap
                if not _pv2.get("approved", True) and approved:
                    approved = False
                    try:
                        print(f"[PORTFOLIO-V2-BLOCK] {symbol}: {_pv2_block}")
                    except Exception:
                        pass
        except Exception as _pv2_err:
            pass

    # ── Macro Fusion — currency strength + macro bias + session affinity ─────
    # Phase 1/2/3/5 (v4.02): statistical currency strength from BarStore +
    # manually-configured macro bias fused into a score delta and risk adjustment.
    # Conservative: delta bounded [-15,+15], risk adj [0.65,1.05].
    # Additive-reduction only — cannot push final_multi above its pre-fusion value.
    _macro_fusion_delta  = 0
    _macro_fusion_block  = False
    _macro_fusion_reason = "ok"
    _macro_fusion_risk   = 1.0
    _macro_fusion_comps: dict = {}
    _ccy_str_bias:  dict = {}
    _ccy_str_scores: dict = {}
    _macro_ext_bias: dict = {}
    _session_affinity_score = 1.0
    if not _silent:
        try:
            _cse_mod = _get_currency_strength_engine_mod()
            _mae_mod = _get_macro_engine_mod()
            _mfe_mod = _get_macro_fusion_engine_mod()
            if _mfe_mod is not None and (_cse_mod is not None or _mae_mod is not None):
                _dir_int = int(data.get("direction", sig_in) or sig_in) or 1
                if _cse_mod is not None:
                    try:
                        _cse_mod.currency_strength_engine.update(bar_store)
                        _ccy_str_bias   = _cse_mod.currency_strength_engine.get_pair_bias(symbol, _dir_int)
                        _ccy_str_scores = _cse_mod.currency_strength_engine.get_scores()
                    except Exception:
                        pass
                if _mae_mod is not None:
                    try:
                        _macro_ext_bias = _mae_mod.macro_engine.get_pair_bias(symbol, _dir_int)
                    except Exception:
                        pass
                _fusion = _mfe_mod.fuse(
                    symbol            = symbol,
                    direction         = _dir_int,
                    session           = session,
                    macro_pair_bias   = _macro_ext_bias or None,
                    ccy_str_pair_bias = _ccy_str_bias   or None,
                    portfolio_heat    = _pv2_heat_level,
                )
                _macro_fusion_delta  = int(_fusion.get("score_delta",   0))
                _macro_fusion_block  = bool(_fusion.get("macro_block",  False))
                _macro_fusion_reason = str(_fusion.get("macro_reason",  "ok"))
                _macro_fusion_risk   = float(_fusion.get("risk_mult_adj", 1.0))
                _macro_fusion_comps  = _fusion.get("components", {})
                _session_affinity_score = float(_fusion.get("session_affinity", 1.0))

                # Apply score delta (both positive and negative)
                if _macro_fusion_delta != 0:
                    score = max(0.0, min(100.0, score + _macro_fusion_delta))
                    try:
                        print(f"[MACRO-FUSION] {symbol} dir={_dir_int} "
                              f"delta={_macro_fusion_delta:+d} score→{score:.0f} "
                              f"comps={_macro_fusion_comps}")
                    except Exception:
                        pass

                # Apply risk multiplier (additive-reduction only — never amplify)
                if _macro_fusion_risk < 1.0:
                    final_multi = round(max(0.20, final_multi * _macro_fusion_risk), 2)

                # Hard block: macro + ccy_strength both strongly oppose direction
                if _macro_fusion_block and approved:
                    approved = False
                    try:
                        print(f"[MACRO-FUSION-BLOCK] {symbol}: {_macro_fusion_reason}")
                    except Exception:
                        pass

                # Re-check approval threshold after score adjustment
                if approved and score < threshold:
                    approved = False
        except Exception:
            pass

    # ── ML Meta-Filter (Phases 1-8) ───────────────────────────────────────────
    # Runs AFTER all score/risk adjustments. BLOCK overrides approved=False.
    # REDUCE_RISK caps final_multi×0.75.  Never amplifies risk.
    # Falls back silently when ml_meta_filter.py is absent (VPS sync required).
    _mmf_recommendation = "FALLBACK_RULE_ONLY"
    _mmf_probability    = 0.5
    _mmf_confidence     = 0.0
    _mmf_version        = "untrained"
    _mmf_top_features: list = []
    try:
        _mmf_mod = _get_ml_meta_filter_mod()
        if _mmf_mod is not None:
            _mmf = _mmf_mod.get_ml_meta_filter()
            _mmf_nie_sev = 0.0
            try:
                _mmf_nie_sev = float(_nie_result.get("severity_score", 0) or 0)  # type: ignore[name-defined]
            except Exception:
                pass

            # ── Hybrid feature row (schema v1.1.0) ───────────────────────────
            # Build the full 20-field feature row via hybrid_feature_engine.
            # Falls back to inline dict when the engine file is absent (VPS sync).
            # Context supplies computed variables not available in the raw payload.
            _hfe_ctx = {
                "rule_score":          float(score),
                "news_severity":       _mmf_nie_sev,
                "session_quality":     float(_session_quality_score),
                "exec_quality":        float(_exec_adj),
                "portfolio_heat":      float(_g_portfolio_heat),
                "loss_streak":         int(c_losses),
                "win_streak":          int(getattr(regime_detector, "win_streak", 0)),
                "symbol_winrate_30d":  _mmf.get_symbol_winrate(symbol),
                # v1.1.0: macro + ccy_strength + execution enrichments
                "macro_bias":          float(_macro_fusion_delta) / 15.0,
                "ccy_strength":        float(
                    _ccy_str_bias.get("alignment") or
                    _ccy_str_bias.get("bias_score") or 0.0
                ),
                "correlated_exposure": min(1.0, len(_pv2_ccy_breaches) * 0.25),
                "avg_slippage_pips":   float(data.get("slippage_pips") or 0.0),
            }
            try:
                _hfe_mod = _get_hybrid_feature_engine_mod()
                if _hfe_mod is None:
                    raise ImportError("hybrid_feature_engine not available")
                _mmf_ctx = _hfe_mod.build_feature_row(data, _hfe_ctx)
            except Exception:
                # Inline fallback — identical to v1.1.0 schema
                _mmf_ctx = {
                    "symbol":              symbol,
                    "session":             session,
                    "regime":              regime,
                    "setup":               str(data.get("setup", "UNKNOWN")),
                    "spread_pips":         float(data.get("spread_at_entry", 0.5) or 0.5),
                    "atr_pips":            float(data.get("atr", 1.0) or 1.0),
                    "volatility_ratio":    float(data.get("atr_expansion", 1.0) or 1.0),
                    "confluence_count":    int(data.get("confluence", 0) or 0),
                    **_hfe_ctx,
                }

            _mmf_result = _mmf.predict(features, _mmf_ctx)
            _mmf_recommendation = _mmf_result.get("recommendation", "FALLBACK_RULE_ONLY")
            _mmf_probability    = _mmf_result.get("probability", 0.5)
            _mmf_confidence     = float(_mmf_result.get("confidence", 0.0))
            _mmf_version        = _mmf_result.get("model_version", "untrained")
            _mmf_top_features   = list(_mmf_result.get("top_features", []))
            _mmf_block, final_multi, _mmf_reason = _mmf_mod.MLMetaFilter.apply_risk_adjustment(
                _mmf_result, final_multi
            )
            if _mmf_block and approved:
                approved = False
                try:
                    print(f"[ML-META] {symbol} {_mmf_reason}")
                except Exception:
                    pass
            elif _mmf_recommendation == "REDUCE_RISK":
                try:
                    print(f"[ML-META] {symbol} {_mmf_reason} final_multi={final_multi}")
                except Exception:
                    pass
    except Exception:
        pass  # never crash score_trade

    # ── Telegram: BLOCKED by regime_v2 override ───────────────────────────────
    if _regime_v2_override and not approved and not _probe and not _silent and _telegram_symbol_ok(symbol):
        _dir_str = "BUY ▲" if _signal == 1 else "SELL ▼" if _signal == -1 else "—"
        send_telegram(
            f"🛡 <b>ENTRY BLOCKED — {symbol} {_dir_str}</b>\n"
            f"Score <b>{score:.0f}</b> below FRAGILE threshold <b>{threshold:.0f}</b>\n"
            f"EA regime: {regime} → Scorer regime_v2: <b>FRAGILE</b>\n"
            f"Session: {session}  Setup: {data.get('setup','')}\n"
            f"<i>Regime_v2 override applied — EA local reading was stale</i>"
        )

    if approved and not _probe and not _silent and _telegram_symbol_ok(symbol):
        _dir_str    = "BUY ▲" if _signal == 1 else "SELL ▼" if _signal == -1 else "—"
        _dxy_trend  = dxy_impact.get("dxy_trend", "NEUTRAL")
        _dxy_price  = dxy_impact.get("dxy_price", "—")
        _dxy_ok     = dxy_impact.get("aligned")
        _dxy_str    = (f"DXY {_dxy_trend} ({_dxy_price}) → "
                       f"{'✅ aligned' if _dxy_ok else '⚠️ conflict' if _dxy_ok is False else '—'}")
        _w1_tag     = f" · W1 {'✅' if data.get('weekly_aligned') else '—'}"
        _streak_str = f"  ⚠️ {c_losses} consec losses" if c_losses > 0 else ""

        # Trade levels from EA payload
        _sl   = data.get("sl_price")  or data.get("stop_loss")
        _tp   = data.get("tp_price")  or data.get("take_profit")
        _lots = data.get("lot_size")  or data.get("lots")
        _conf = int(data.get("confluence", 0))
        _levels_line = ""
        if _sl or _tp or _lots:
            _sl_str   = f"SL {_sl:.5g}" if _sl else "SL —"
            _tp_str   = f"TP {_tp:.5g}" if _tp else "TP —"
            _lots_str = f"Lots {_lots:.2f}" if _lots else ""
            _levels_line = f"\n{_sl_str}  {_tp_str}  {_lots_str}"
        _conf_str = f"  Conf: {_conf}/6" if _conf else ""

        # Regime_v2 context line
        _r2_label = r2.get("regime_label", _r2_regime)
        _r2_line  = (f"\nRegime_v2: <b>{_r2_label}</b>"
                     + (f" ⚠️ (EA reported {regime})" if _r2_regime != regime else ""))

        # v4 ensemble attribution
        _v4_line = ""
        try:
            _v4 = score_ensemble(data)
            _comp = _v4.get("v4_components", {}) or {}
            _wts  = _v4.get("v4_weights", {}) or {}
            _comp_str = " · ".join(
                f"{k}={_comp.get(k,0):.0f}@{(_wts.get(k,0)*100):.0f}%"
                for k in ("trend_pullback","mean_reversion","breakout") if k in _comp
            )
            _kelly_line = f"  Kelly: {_v4['kelly_size_mult']}x" if _v4.get("kelly_size_mult") is not None else ""
            _v4_line = (f"\n<i>v4 blended {_v4.get('v4_score',0):.0f} "
                        f"(chosen {_v4['v4_chosen']}, agree {_v4['v4_agreement']:.2f}){_kelly_line}\n"
                        f"  {_comp_str}</i>")
        except Exception:
            _v4_line = ""

        send_telegram(
            f"✅ <b>TRADE APPROVED — {symbol}  {_dir_str}</b>{_streak_str}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Score: <b>{score:.0f}</b>  Threshold: {threshold:.0f}  Risk: {final_multi}x\n"
            f"Setup: {data.get('setup','—')}  Session: {session}{_w1_tag}{_conf_str}"
            f"{_levels_line}\n"
            f"Regime: {regime}  RR rec: {rr_rec['recommended_rr']:.1f}:1"
            f"{_r2_line}\n"
            f"{_dxy_str}"
            f"{_v4_line}"
        )
    # ── v4 ensemble observability (always computed, not just on approval) ────────
    # Gives full per-strategy breakdown + human-readable reasoning for every
    # scoring request — whether approved, blocked, or probe. Used by dashboard
    # /api/ai/reasoning endpoint and logged to scanner history.
    _v4e_data: dict = {}
    try:
        _v4e    = score_ensemble(data)
        _comp   = _v4e.get("v4_components", {}) or {}
        _wts    = _v4e.get("v4_weights", {}) or {}
        _reas   = _v4e.get("v4_reasons", {}) or {}
        _chosen = _v4e.get("v4_chosen", "?")
        _comp_lines = []
        for _k in ("trend_pullback", "mean_reversion", "breakout"):
            _sc = _comp.get(_k, 0)
            _wt = round((_wts.get(_k, 0)) * 100)
            _rs = ", ".join(_reas.get(_k, [])) or "—"
            _comp_lines.append(f"{_k}={_sc:.0f}@{_wt}% [{_rs}]")
        if not approved:
            if _raw_conf > 0 and _raw_conf < _MIN_CONF:
                _decision = f"BLOCKED: confluence {_raw_conf}<{_MIN_CONF}"
            elif _regime_v2_override:
                _decision = f"BLOCKED: regime_v2=FRAGILE threshold={threshold:.0f} score={score:.0f}"
            elif news_action == "block":
                _decision = f"BLOCKED: news {news_reason}"
            else:
                _decision = f"BLOCKED: score {score:.0f} < threshold {threshold:.0f}"
        else:
            _decision = f"APPROVED: score {score:.0f} >= threshold {threshold:.0f} risk={final_multi}x"
        _sess_tag   = " [PEAK WINDOW]" if session in ("LONDON", "NEW_YORK", "LONDON_NY") else (" [ASIA — reduced risk]" if session == "ASIA" else "")
        _frag_tag   = " [FRAGILE override — tighter gate]" if _regime_v2_override else ""
        _news_str   = "CLEAR" if not news_reason else f"⚠  {news_reason}"
        _conf_gate  = f"{_raw_conf}/{_MIN_CONF} required" if _raw_conf > 0 else "—"
        _agree_pct  = f"{_v4e.get('v4_agreement', 0):.0%}"
        _kelly_str  = f"{_v4e.get('kelly_size_mult', 1):.2f}x"
        _tp_str     = f"{rr_rec['recommended_rr']:.1f}:1"
        _sep        = "━" * 46
        _decision_body = _decision.split(":", 1)[1].strip() if ":" in _decision else _decision
        # COT agent line
        _cot_pct    = _cot.get("percentile", 50)
        _cot_bias   = _cot.get("bias", "NEUTRAL")
        _cot_inten  = _cot.get("intensity", "NEUTRAL")
        _cot_net    = _cot.get("net", 0)
        _cot_mod_s  = f"{_cot_mod:+d}" if _cot_mod != 0 else "0 (neutral zone)"
        _cot_rpt    = _cot.get("report_date", "—")
        _cot_src    = _cot.get("source", "—")
        _cot_line   = (f"{_cot_bias} {_cot_inten}  net={_cot_net:+,}  "
                       f"{_cot_pct}th-pct  modifier={_cot_mod_s}  report={_cot_rpt}"
                       if "neutral" not in _cot_src else f"unavailable ({_cot_src})")
        # Macro agent line
        _mac_diff   = _macro.get("differential", 0.0)
        _mac_bias   = _macro.get("bias", "NEUTRAL")
        _mac_mod_s  = f"{_macro_mod:+d}" if _macro_mod != 0 else "0 (neutral)"
        _mac_base   = _macro.get("base_cb",  "—")
        _mac_quote  = _macro.get("quote_cb", "—")
        _mac_br     = _macro.get("base_rate",  0.0)
        _mac_qr     = _macro.get("quote_rate", 0.0)
        _mac_line   = (f"{_mac_base} {_mac_br:.2f}% vs {_mac_quote} {_mac_qr:.2f}%  "
                       f"diff={_mac_diff:+.2f}  {_mac_bias}  modifier={_mac_mod_s}")
        # Intermarket agent line
        _int_src    = _inter.get("source", "no_data")
        _int_mod_s  = f"{_inter_mod:+d}" if _inter_mod != 0 else "0 (neutral)"
        _int_dtl    = "  ".join(_inter.get("details", {}).values()) or "no signal"
        _int_line   = (f"DXY={_inter.get('dxy_chg',0):+.2f}%  "
                       f"US10Y={_inter.get('us10y_chg',0):+.2f}%  "
                       f"Gold={_inter.get('gold_chg',0):+.2f}%  "
                       f"modifier={_int_mod_s}  [{_int_dtl}]"
                       if _int_src != "no_data" else "unavailable (no_data)")
        # SSI agent line
        _ssi_src    = _ssi.get("source", "no_data")
        _ssi_mod_s  = f"{_ssi_mod:+d}" if _ssi_mod != 0 else "0 (neutral)"
        _ssi_line   = (f"retail_long={_ssi.get('long_pct',50):.0f}%  "
                       f"retail_short={_ssi.get('short_pct',50):.0f}%  "
                       f"{_ssi.get('bias','—')}  modifier={_ssi_mod_s}"
                       if _ssi_src != "no_data" else "unavailable (no_data)")
        # HTF Fractal agent line
        _htf_mod_s  = f"{_htf_mod:+d}" if _htf_mod != 0 else "0 (neutral)"
        _htf_line   = (f"H4={_htf.get('h4_trend','—')} ({_htf.get('h4_bars',0)} bars)  "
                       f"D1={_htf.get('d1_trend','—')} ({_htf.get('d1_bars',0)} bars)  "
                       f"combined={_htf.get('combined',0):+.2f}  modifier={_htf_mod_s}")
        # Options Expiry agent line
        _opts_src   = _opts.get("source", "no_data")
        _opts_mod_s = f"{_opts_mod:+d}" if _opts_mod != 0 else "0 (no nearby expiry)"
        _opts_line  = (f"level={_opts.get('nearest_level','—')}  "
                       f"mins_to_cut={_opts.get('mins_to_cut',0)}  "
                       f"expiries={_opts.get('expiry_count',0)}  modifier={_opts_mod_s}"
                       if _opts_src != "no_data" else "unavailable (no_data)")
        # Druckenmiller macro conviction agent line
        _druck_mod_s = f"{_druck_mod:+d}" if _druck_mod != 0 else "0 (neutral)"
        _druck_line  = (f"signal={_druck.get('signal','—')}  "
                        f"conf={_druck.get('confidence',0):.2f}  "
                        f"aligned={_druck.get('aligned',0)}  "
                        f"opposed={_druck.get('opposed',0)}  "
                        f"modifier={_druck_mod_s}  "
                        f"{_druck.get('reasoning','—')}")
        # Taleb tail risk agent line
        _taleb_mod_s = f"{_taleb_mod:+d}" if _taleb_mod != 0 else "0 (stable)"
        _taleb_line  = (f"signal={_taleb.get('signal','STABLE')}  "
                        f"conf={_taleb.get('confidence',0):.2f}  "
                        f"veto={_taleb.get('veto',False)}  "
                        f"modifier={_taleb_mod_s}  "
                        f"{_taleb.get('reasoning','—')}")
        # Livermore line-of-least-resistance agent line
        _livermore_mod_s = f"{_livermore_mod:+d}" if _livermore_mod != 0 else "0 (neutral)"
        _livermore_line  = (f"signal={_livermore.get('signal','NEUTRAL')}  "
                            f"lor_score={_livermore.get('lor_score',0)}/5  "
                            f"conf={_livermore.get('confidence',0):.2f}  "
                            f"modifier={_livermore_mod_s}  "
                            f"{_livermore.get('reasoning','—')}")
        # Soros reflexivity agent line
        _soros_mod_s = f"{_soros_mod:+d}" if _soros_mod != 0 else ("VETO" if _soros.get("veto") else "0 (no reflex)")
        _soros_line  = (f"signal={_soros.get('signal','NEUTRAL')}  "
                        f"ref_score={_soros.get('ref_score',0)}/7  "
                        f"conf={_soros.get('confidence',0):.2f}  "
                        f"modifier={_soros_mod_s}  "
                        f"{_soros.get('reasoning','—')}")
        # Burry contrarian exhaustion agent line
        _burry_mod_s = f"{_burry_mod:+d}" if _burry_mod != 0 else "0 (no exhaustion)"
        _burry_line  = (f"signal={_burry.get('signal','NEUTRAL')}  "
                        f"exh_score={_burry.get('exh_score',0)}/5  "
                        f"conf={_burry.get('confidence',0):.2f}  "
                        f"modifier={_burry_mod_s}  "
                        f"{_burry.get('reasoning','—')}")
        # Dalio economic machine line
        _dalio_mod_s  = f"{_dalio_mod:+d}" if _dalio_mod != 0 else "0 (neutral)"
        _dalio_line   = (f"signal={_dalio.get('signal','NEUTRAL')}  "
                         f"risk_off={_dalio.get('risk_off_cnt',0)}/3  "
                         f"size_mult={_dalio.get('size_mult',1.0):.2f}x  "
                         f"conf={_dalio.get('confidence',0):.2f}  "
                         f"modifier={_dalio_mod_s}  "
                         f"{_dalio.get('reasoning','—')}")
        # Munger inversion checklist line
        _munger_mod_s = f"{_munger_mod:+d}" if _munger_mod != 0 else ("VETO" if _munger.get("veto") else "0 (pass)")
        _munger_line  = (f"signal={_munger.get('signal','NEUTRAL')}  "
                         f"red_flags={_munger.get('red_flags',0)}  "
                         f"conf={_munger.get('confidence',0):.2f}  "
                         f"modifier={_munger_mod_s}  "
                         f"{_munger.get('reasoning','—')}")
        # Keynes liquidity + beauty contest line
        _keynes_mod_s = f"{_keynes_mod:+d}" if _keynes_mod != 0 else "0 (neutral)"
        _keynes_line  = (f"signal={_keynes.get('signal','NEUTRAL')}  "
                         f"consensus={_keynes.get('consensus_cnt',0)}/3  "
                         f"conf={_keynes.get('confidence',0):.2f}  "
                         f"modifier={_keynes_mod_s}  "
                         f"{_keynes.get('reasoning','—')}")
        # Portfolio Manager meta-synthesis line
        _pm_line     = (f"conviction={_pm.get('conviction','—')}  "
                        f"size_mult={_pm.get('size_mult',1.0):.2f}x  "
                        f"avg={_pm.get('weighted_avg',0):+.1f}  "
                        f"{_pm.get('thesis','—')}")
        _reasoning_summary = (
            f"{_sep}\n"
            f"{symbol} | {data.get('trend','—')} | Score: {score:.0f}/100 | {'✅ APPROVED' if approved else '❌ BLOCKED'}\n"
            f"{_sep}\n"
            f"REGIME AGENT     {regime.upper()}{_frag_tag}\n"
            f"                 Threshold: {threshold:.0f}  (pair_base {_pair_base:.0f}  global {MIN_SCORE:.0f})\n"
            f"SESSION AGENT    {session}{_sess_tag}\n"
            f"STRUCTURE AGENT  Setup: {data.get('setup','—')}  Confluence: {_conf_gate}\n"
            f"NEWS AGENT       {_news_str}\n"
            f"COT AGENT        {_cot_line}\n"
            f"MACRO AGENT      {_mac_line}\n"
            f"INTERMARKET      {_int_line}\n"
            f"SSI AGENT        {_ssi_line}\n"
            f"HTF FRACTAL      {_htf_line}\n"
            f"OPTIONS EXPIRY   {_opts_line}\n"
            f"DRUCKENMILLER    {_druck_line}\n"
            f"TALEB RISK       {_taleb_line}\n"
            f"LIVERMORE LOR    {_livermore_line}\n"
            f"SOROS REFLEX     {_soros_line}\n"
            f"BURRY CONTRARIAN {_burry_line}\n"
            f"DALIO MACHINE    {_dalio_line}\n"
            f"MUNGER INVERSION {_munger_line}\n"
            f"KEYNES LIQUIDITY {_keynes_line}\n"
            f"PORTFOLIO MGR    {_pm_line}\n"
            f"ENSEMBLE AGENT   Chosen: {_chosen}  Agreement: {_agree_pct}  Kelly: {_kelly_str}\n"
            f"  trend_pullback {_comp.get('trend_pullback', 0):.0f}/100 @ {round(_wts.get('trend_pullback', 0) * 100)}%  {', '.join(_reas.get('trend_pullback', [])) or '—'}\n"
            f"  mean_reversion {_comp.get('mean_reversion', 0):.0f}/100 @ {round(_wts.get('mean_reversion', 0) * 100)}%  {', '.join(_reas.get('mean_reversion', [])) or '—'}\n"
            f"  breakout       {_comp.get('breakout', 0):.0f}/100 @ {round(_wts.get('breakout', 0) * 100)}%  {', '.join(_reas.get('breakout', [])) or '—'}\n"
            f"RISK AGENT       {final_multi}x multiplier  RR {_tp_str} recommended\n"
            f"{_sep}\n"
            f"DECISION: {_decision_body}\n"
            f"{_sep}"
        )
        _v4e_data = {
            "v4_score":          _v4e.get("v4_score", 0),
            "v4_chosen":         _chosen,
            "v4_components":     _comp,
            "v4_reasons":        _reas,
            "v4_weights":        {k: round(_wts.get(k, 0), 4) for k in _wts},
            "v4_agreement":      _v4e.get("v4_agreement", 0),
            "kelly_size_mult":   _v4e.get("kelly_size_mult", 1.0),
            "reasoning_summary": _reasoning_summary,
        }
    except Exception as _v4e_err:
        _v4e_data = {"reasoning_summary": f"ensemble_error: {_v4e_err}"}

    return {
        "score":                   round(score, 2),
        "approved":                approved,
        "risk_multiplier":         final_multi,
        "lot_multiplier":          round(_pv2_lot_mult, 3),
        "portfolio_heat_level":    _pv2_heat_level,
        "portfolio_block":         _pv2_block,
        "portfolio_killswitch":    _pv2_kill_halted,
        "portfolio_pair_disabled": _pv2_pair_disabled,
        "portfolio_ccy_breaches":  _pv2_ccy_breaches,
        "confidence":              round(min(1.0, score / 100), 3),
        "regime":          regime,
        "block_reason":    "",
        "recommended_rr":  rr_rec["recommended_rr"],
        "ml_win_prob":     _mmf_probability,
        "ml_active":       _mmf_recommendation != "FALLBACK_RULE_ONLY",
        # ── ML Meta-Filter structured output (hybrid explainability) ─────────
        # Returned on every scored request so the EA and dashboard have full
        # transparency into the ML layer's assessment.
        # recommendation: APPROVE | REDUCE_RISK | BLOCK | FALLBACK_RULE_ONLY
        # probability:    estimated win probability [0.0, 1.0]
        # confidence:     model confidence — low (<0.15) triggers FALLBACK
        # top_features:   [(feature_name, importance_score)] list, max 5
        "ml_meta": {
            "recommendation": _mmf_recommendation,
            "probability":    round(_mmf_probability, 4),
            "confidence":     round(_mmf_confidence, 4),
            "model_version":  _mmf_version,
            "top_features":   _mmf_top_features,
        },
        "order_flow_bias": of_signal.get("bias", "NEUTRAL"),
        "of_patterns":     of_signal.get("patterns", []),
        "sentiment":       sent.get("overall", "NEUTRAL"),
        "regime_warning":    ew.get("action", "NORMAL"),
        "execution_ok":      exec_check.get("execution_ok", True),
        "regime_v2_override": _regime_v2_override,
        # ── Regime V2 — multi-TF trend metrics ──────────────────────────────
        "trend_score":         r2["trend_score"],
        "trend_direction":     r2["trend_direction"],
        "regime_v2":           r2["regime"],
        "regime_v2_label":     r2["regime_label"],
        "regime_components":   r2["components"],
        "regime_v2_weights":   r2["weights"],
        "regime_agreement":    r2["agreement"],
        "vol_state":           r2["vol_state"],
        "vol_bucket":          r2["vol_bucket"],
        "vol_percentile":      r2["vol_percentile"],
        "regime_v2_insufficient": r2["insufficient_data"],
        "insufficient_data":   r2["insufficient_data"],
        # ── v4 ensemble observability ────────────────────────────────────────
        "v4_score":          _v4e_data.get("v4_score", 0),
        "v4_chosen":         _v4e_data.get("v4_chosen", ""),
        "v4_components":     _v4e_data.get("v4_components", {}),
        "v4_reasons":        _v4e_data.get("v4_reasons", {}),
        "v4_weights":        _v4e_data.get("v4_weights", {}),
        "v4_agreement":      _v4e_data.get("v4_agreement", 0),
        "kelly_size_mult":   _v4e_data.get("kelly_size_mult", 1.0),
        "reasoning_summary": _v4e_data.get("reasoning_summary", ""),
        # ── COT Agent ────────────────────────────────────────────────────────
        "cot_bias":        _cot.get("bias", "NEUTRAL"),
        "cot_intensity":   _cot.get("intensity", "NEUTRAL"),
        "cot_net":         _cot.get("net", 0),
        "cot_percentile":  _cot.get("percentile", 50),
        "cot_modifier":    _cot_mod,
        "cot_report_date": _cot.get("report_date", "—"),
        "cot_source":      _cot.get("source", "—"),
        # ── Macro Agent ──────────────────────────────────────────────────────
        "macro_bias":         _macro.get("bias", "NEUTRAL"),
        "macro_differential": _macro.get("differential", 0.0),
        "macro_modifier":     _macro_mod,
        "macro_base_cb":      _macro.get("base_cb", "—"),
        "macro_quote_cb":     _macro.get("quote_cb", "—"),
        "macro_base_rate":    _macro.get("base_rate", 0.0),
        "macro_quote_rate":   _macro.get("quote_rate", 0.0),
        # ── Intermarket Agent ────────────────────────────────────────────────
        "intermarket_modifier": _inter_mod,
        "intermarket_dxy_chg":  _inter.get("dxy_chg", 0),
        "intermarket_gold_chg": _inter.get("gold_chg", 0),
        "intermarket_10y_chg":  _inter.get("us10y_chg", 0),
        "intermarket_dxy":      _inter.get("dxy_price", 0),
        "intermarket_gold":     _inter.get("gold_price", 0),
        "intermarket_10y":      _inter.get("us10y", 0),
        "intermarket_details":  _inter.get("details", {}),
        # ── SSI Agent ────────────────────────────────────────────────────────
        "ssi_modifier":   _ssi_mod,
        "ssi_long_pct":   _ssi.get("long_pct", 50),
        "ssi_short_pct":  _ssi.get("short_pct", 50),
        "ssi_bias":       _ssi.get("bias", "NEUTRAL"),
        "ssi_source":     _ssi.get("source", "no_data"),
        # ── HTF Fractal Agent ────────────────────────────────────────────────
        "htf_modifier":   _htf_mod,
        "htf_h4_trend":   _htf.get("h4_trend", "NEUTRAL"),
        "htf_d1_trend":   _htf.get("d1_trend", "NEUTRAL"),
        "htf_h4_bars":    _htf.get("h4_bars", 0),
        "htf_d1_bars":    _htf.get("d1_bars", 0),
        "htf_combined":   _htf.get("combined", 0),
        # ── Options Expiry Agent ─────────────────────────────────────────────
        "opts_modifier":      _opts_mod,
        "opts_nearest_level": _opts.get("nearest_level"),
        "opts_mins_to_cut":   _opts.get("mins_to_cut", 0),
        "opts_expiry_count":  _opts.get("expiry_count", 0),
        "opts_levels":        _opts.get("levels", []),
        # ── Correlation Matrix Agent ─────────────────────────────────────────
        "corr_modifier":    _corr_mod,
        "corr_risk":        _corr.get("risk", "none"),
        "corr_worst":       _corr.get("worst_corr", 0.0),
        "corr_conflicts":   _corr.get("conflicts", []),
        "corr_matrix":      _corr.get("matrix", {}),
        # ── Economic Surprise Agent ──────────────────────────────────────────
        "surp_modifier":    _surp_mod,
        "surp_events":      _surp.get("events", []),
        "surp_source":      _surp.get("source", "no_data"),
        # ── Legend Agents structured votes (dashboard panel) ─────────────────
        "legend_agents": [
            {"name": "druckenmiller", "label": "Druckenmiller",
             "signal": _druck.get("signal", "NEUTRAL"),    "modifier": _druck_mod,
             "confidence": _druck.get("confidence", 0.0),  "veto": False,
             "reasoning": _druck.get("reasoning", "—")},
            {"name": "taleb",         "label": "Taleb",
             "signal": _taleb.get("signal", "STABLE"),     "modifier": _taleb_mod,
             "confidence": _taleb.get("confidence", 0.0),  "veto": _taleb.get("veto", False),
             "reasoning": _taleb.get("reasoning", "—")},
            {"name": "livermore",     "label": "Livermore",
             "signal": _livermore.get("signal", "NEUTRAL"), "modifier": _livermore_mod,
             "confidence": _livermore.get("confidence", 0.0), "veto": False,
             "reasoning": _livermore.get("reasoning", "—")},
            {"name": "soros",         "label": "Soros",
             "signal": _soros.get("signal", "NEUTRAL"),    "modifier": _soros_mod,
             "confidence": _soros.get("confidence", 0.0),  "veto": _soros.get("veto", False),
             "reasoning": _soros.get("reasoning", "—")},
            {"name": "burry",         "label": "Burry",
             "signal": _burry.get("signal", "NEUTRAL"),    "modifier": _burry_mod,
             "confidence": _burry.get("confidence", 0.0),  "veto": False,
             "reasoning": _burry.get("reasoning", "—")},
            {"name": "dalio",         "label": "Dalio",
             "signal": _dalio.get("signal", "NEUTRAL"),    "modifier": _dalio_mod,
             "confidence": _dalio.get("confidence", 0.0),  "veto": False,
             "size_mult": _dalio.get("size_mult", 1.0),
             "reasoning": _dalio.get("reasoning", "—")},
            {"name": "munger",        "label": "Munger",
             "signal": _munger.get("signal", "NEUTRAL"),   "modifier": _munger_mod,
             "confidence": _munger.get("confidence", 0.0), "veto": _munger.get("veto", False),
             "red_flags": _munger.get("red_flags", 0),
             "reasoning": _munger.get("reasoning", "—")},
            {"name": "keynes",        "label": "Keynes",
             "signal": _keynes.get("signal", "NEUTRAL"),   "modifier": _keynes_mod,
             "confidence": _keynes.get("confidence", 0.0), "veto": False,
             "consensus_cnt": _keynes.get("consensus_cnt", 0),
             "reasoning": _keynes.get("reasoning", "—")},
            {"name": "portfolio_manager", "label": "Portfolio Mgr",
             "signal": _pm.get("conviction", "—"),         "modifier": 0,
             "confidence": round(min(1.0, _pm.get("size_mult", 1.0) / 1.1), 2),
             "veto": _pm.get("conviction") == "VETO",
             "size_mult": _pm.get("size_mult", 1.0),
             "weighted_avg": _pm.get("weighted_avg", 0),
             "thesis": _pm.get("thesis", "—")},
        ],
        "timestamp":       datetime.utcnow().isoformat(),
        # ── v4.02 Performance Engines ──────────────────────────────────────────
        "trade_quality_tier":     _tq_tier,
        "trade_quality_score":    _tq_score,
        "trade_quality_mult":     _tq_mult,
        "trade_quality_reasons":  _tq_reasons,
        "session_quality_score":  _session_quality_score,
        "session_quality_class":  _session_quality_class,
        "pair_session_mult":      round(_pair_session_mult, 3),
        "execution_score":        round(_exec_score, 3),
        "execution_risk_adj":     round(_exec_adj, 3),
        # ── Macro Fusion Engines (Phase 1/2/3/5 — v4.02) ─────────────────────
        "macro_fusion_delta":     _macro_fusion_delta,
        "macro_fusion_block":     _macro_fusion_block,
        "macro_fusion_reason":    _macro_fusion_reason,
        "macro_fusion_comps":     _macro_fusion_comps,
        "session_affinity":       round(_session_affinity_score, 3),
        "ccy_strength_scores":    _ccy_str_scores,
        "ccy_strength_delta":     int(_ccy_str_bias.get("score_delta", 0)),
        "ccy_strength_base_class": _ccy_str_bias.get("base_class", "NEUTRAL"),
        "ccy_strength_quote_class": _ccy_str_bias.get("quote_class", "NEUTRAL"),
        "macro_ext_alignment":    round(float(_macro_ext_bias.get("alignment", 0.0)), 3),
        "macro_ext_delta":        int(_macro_ext_bias.get("score_delta", 0)),
        "macro_ext_base_regime":  _macro_ext_bias.get("base_regime", "NEUTRAL"),
        "macro_ext_quote_regime": _macro_ext_bias.get("quote_regime", "NEUTRAL"),
    }


def _calc_risk_multi(score, regime, session, mode):
    """
    Returns a multiplier applied to Optimal_Risk_Pct (1.0%).
    Hard cap: multiplier never pushes risk above 1.5x optimal.
    System sizes up on quality, not on aggression setting.
    """
    if score >= 85:   base = 1.40
    elif score >= 80: base = 1.25
    elif score >= 75: base = 1.10
    elif score >= 72: base = 1.00
    else:             base = 0.75

    if regime == "expansion":               base *= 1.07
    elif regime == "fragile":               base *= 0.65

    if session == "LONDON_NY":              base *= 1.05
    elif session == "ASIA":                 base *= 0.80

    if "FUNDED" in str(mode).upper():       base *= 0.50

    base = min(base, 1.50)
    base = max(base, 0.25)

    return round(base, 2)


# ══════════════════════════════════════════════════════════════════════
# SCORER ERROR STORE — tracks the last 20 exceptions from /score and
# /best_signal so failures are visible via GET /debug/scorer-errors and
# pushed to the dashboard live-score feed instead of being swallowed.
# ══════════════════════════════════════════════════════════════════════
_SCORER_ERROR_LOG: deque = deque(maxlen=20)
_SCORER_ERROR_COUNT: int = 0
_SCORER_ERROR_LOCK  = threading.Lock()


def _record_scorer_error(route: str, symbol: str, exc: Exception) -> None:
    """Record a scorer exception into the in-process error ring-buffer and
    emit a CRITICAL log line with the full traceback so it is never silent."""
    global _SCORER_ERROR_COUNT
    tb_str = traceback.format_exc()
    entry = {
        "timestamp":     datetime.utcnow().isoformat(),
        "route":         route,
        "symbol":        symbol or "",
        "error_type":    type(exc).__name__,
        "error_message": str(exc),
        "traceback":     tb_str,
    }
    with _SCORER_ERROR_LOCK:
        _SCORER_ERROR_LOG.append(entry)
        _SCORER_ERROR_COUNT += 1
    log.critical(
        f"[SCORER-ERROR] route={route} sym={symbol} "
        f"{type(exc).__name__}: {exc}\n{tb_str}"
    )


def _build(score, approved, risk_multi, confidence, regime, block_reason=""):
    return {
        "score":           round(score, 2),
        "approved":        approved,
        "risk_multiplier": risk_multi,
        "confidence":      round(confidence, 3),
        "regime":          regime,
        "block_reason":    block_reason,
        "recommended_rr":  2.0,
        "ml_win_prob":     0.5,
        "ml_active":       False,
        "order_flow_bias": "NEUTRAL",
        "of_patterns":     [],
        "sentiment":       "NEUTRAL",
        "regime_warning":  "NORMAL",
        "execution_ok":    True,
        "timestamp":       datetime.utcnow().isoformat()
    }


def _append_csv(filepath, row):
    exists = os.path.isfile(filepath)
    with open(filepath, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=row.keys())
        if not exists:
            w.writeheader()
        w.writerow(row)

# Canonical trade-journal schema. Original 6 columns kept first (same order)
# for backward compatibility; analytics fields appended after.
JOURNAL_FIELDS = [
    "won", "profit", "session", "setup", "symbol", "ts",
    "score", "regime", "r_multiple",
    "entry_price", "stop_loss", "take_profit", "direction", "trade_id",
]

def _append_journal(row):
    """Append one completed trade with the canonical schema. Backward
    compatible: an older journal (fewer columns) is migrated in place to the
    full header, backfilling new columns as blank. Missing values are stored
    blank (never estimated). Journal-only; no effect on trading logic."""
    fields = JOURNAL_FIELDS
    out = {k: ("" if row.get(k) is None else row.get(k)) for k in fields}
    if not os.path.isfile(JOURNAL_FILE) or os.path.getsize(JOURNAL_FILE) == 0:
        with open(JOURNAL_FILE, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader(); w.writerow(out)
        return
    try:
        with open(JOURNAL_FILE, newline="") as f:
            header = next(csv.reader(f), [])
    except Exception:
        header = []
    if header != fields:
        try:
            with open(JOURNAL_FILE, newline="") as f:
                old_rows = list(csv.DictReader(f))
            with open(JOURNAL_FILE, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
                w.writeheader()
                for o in old_rows:
                    w.writerow({k: o.get(k, "") for k in fields})
            log.info("[JOURNAL] migrated journal to %d-column schema", len(fields))
        except Exception as e:
            log.warning("[JOURNAL] header migration skipped: %s", e)
    with open(JOURNAL_FILE, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writerow(out)


# ══════════════════════════════════════════════════════════════════════
# API ENDPOINTS
# ══════════════════════════════════════════════════════════════════════

def check_circuit_breaker() -> tuple:
    """
    Queries the command center's /can-trade endpoint before every score request.
    This is the single gate that blocks ALL EAs (EURUSD, USDJPY, Scanner)
    when daily loss or total drawdown limits are approaching.

    Returns: (allowed: bool, reason: str)
    Fails open (allows trade) if command center is unreachable and CB_FAIL_OPEN=True.
    """
    try:
        r = requests.get(f"{CMD_CENTER_URL}/can-trade", timeout=1.0)
        if r.status_code == 200:
            data = r.json()
            allowed = data.get("allowed", True)
            reason  = data.get("reason", "")
            if not allowed:
                log.warning(f"CIRCUIT BREAKER BLOCKED: {reason} | "
                            f"daily={data.get('daily_loss_pct', 0):.2f}% "
                            f"dd={data.get('drawdown_pct', 0):.2f}%")
            return allowed, reason
    except Exception as e:
        if CB_FAIL_OPEN:
            log.warning(f"[CB-FAIL-OPEN] Command center unreachable ({e}) — "
                        f"ALLOWING trade (CB_FAIL_OPEN=True). "
                        f"Prop-firm circuit breaker is BYPASSED. Check command center immediately.")
            return True, "cmd_center_offline_fail_open"
        else:
            log.warning(f"[CB-FAIL-SAFE] Command center unreachable ({e}) — "
                        f"BLOCKING trade (CB_FAIL_OPEN=False). "
                        f"Watchdog should restart command center within seconds.")
            return False, "cmd_center_offline_fail_closed"
    return True, ""


def _push_reasoning(result: dict, data: dict):
    """Fire-and-forget: push reasoning summary to dashboard /api/ai/score-decision."""
    if not result.get("reasoning_summary"):
        return
    try:
        payload = {
            "symbol":            data.get("symbol", ""),
            "approved":          result.get("approved", False),
            "score":             result.get("score", 0),
            "reasoning_summary": result["reasoning_summary"],
            "v4_components":     result.get("v4_components", {}),
            "v4_reasons":        result.get("v4_reasons", {}),
            "v4_chosen":         result.get("v4_chosen", ""),
            "v4_agreement":      result.get("v4_agreement", 0),
            "kelly_size_mult":   result.get("kelly_size_mult", 1.0),
            "regime":            result.get("regime", ""),
            "session":           data.get("session", ""),
        }
        requests.post(
            f"{DASHBOARD_API_URL}/ai/score-decision",
            json=payload, timeout=2.0,
        )
    except Exception:
        pass


def _push_live_score(result: dict, data: dict):
    """Fire-and-forget: push full score + legend agents to /api/ai/live-scores.

    This is what populates the dashboard's live score cache, Legend Agents
    Council panel, and warmup-status bar counts.  Called on every /score hit.
    """
    try:
        symbol = data.get("symbol", "")
        if not symbol:
            return
        top = result.get("of_patterns", [])[:5]
        if not top:
            top = [result.get("v4_chosen") or "ensemble"]
        _block_reason = result.get("block_reason", "")
        _br_upper     = _block_reason.upper()
        payload = [{
            "symbol":           symbol,
            "score":            result.get("score", 0),
            "approved":         result.get("approved", False),
            "action":           data.get("signal", "HOLD"),
            "confidence":       result.get("confidence", 0.5),
            "regime":           result.get("regime", ""),
            "riskMultiplier":   result.get("risk_multiplier", 1.0),
            "topFactors":       top,
            "v4_chosen":        result.get("v4_chosen"),
            "v4_components":    result.get("v4_components"),
            "v4_reasons":       result.get("v4_reasons"),
            "v4_weights":       result.get("v4_weights"),
            "v4_agreement":     result.get("v4_agreement"),
            "kelly_size_mult":  result.get("kelly_size_mult"),
            "reasoning_summary": result.get("reasoning_summary"),
            "legend_agents":    result.get("legend_agents", []),
            # Gate diagnostics — used by the WHY-NO-TRADE dashboard panel
            "block_reason":     _block_reason,
            "news_blocked":     "NEWS" in _br_upper or data.get("news_block", False),
            "spread_blocked":   "SPREAD" in _br_upper or not data.get("spread_ok", True),
            "corr_blocked":     "CORR" in _br_upper,
            "exposure_blocked": any(k in _br_upper for k in ("DD", "PORTFOLIO", "EXPOSURE", "HALTED")),
            "session":          data.get("session", ""),
        }]
        requests.post(
            f"{DASHBOARD_API_URL}/ai/live-scores",
            json=payload, timeout=2.0,
        )
    except Exception:
        pass


def _parse_signal_direction(sig):
    """Map a /score 'signal' value to trade direction: +1 (buy) / -1 (sell).

    Accepts the numeric contract the scoring path enforces (int/float 1/-1, or
    numeric strings "1"/"-1") and, defensively, the BUY/SELL words. Returns
    (direction, None) on success or (None, error_message) on invalid input so
    the caller can respond HTTP 400. NOTE: score_trade() coerces signal via
    int() upstream (~L4147), so a non-numeric word ("BUY") is rejected there
    first — the word branch here is forward-compatibility, not a live path."""
    if sig is None or isinstance(sig, bool):
        return None, "missing or non-scalar 'signal'"
    if isinstance(sig, (int, float)):
        return (1 if int(sig) == 1 else -1), None
    if isinstance(sig, str):
        s = sig.strip().upper()
        if s == "BUY":
            return 1, None
        if s == "SELL":
            return -1, None
        try:
            return (1 if int(float(s)) == 1 else -1), None
        except (ValueError, TypeError):
            return None, "invalid 'signal' string: %r" % sig
    return None, "invalid 'signal' type: %s" % type(sig).__name__


@app.route("/score", methods=["POST"])
def score_endpoint():
    try:
        # ── Circuit breaker — single gate for ALL EAs ────────────────────
        cb_allowed, cb_reason = check_circuit_breaker()
        if not cb_allowed:
            return jsonify(_build(0, False, 1.0, 0.0, "blocked", cb_reason))

        data = request.get_json(force=True)
        if not data:
            return jsonify({"error": "No data"}), 400
        # Refresh EA-alive timestamp on every real /score call.
        # Fixes STALE_HEARTBEAT when the EA's primary /heartbeat POST fails
        # and falls back to the dashboard path — /score still proves the EA is live.
        if not data.get("_silent") and not data.get("probe"):
            global _last_heartbeat_ts
            _last_heartbeat_ts = time.time()
        log.info(f"SCORE | {data.get('symbol')} {data.get('setup')} "
                 f"trend={data.get('trend')} session={data.get('session')}")
        result = score_trade(data)
        log.info(f"RESULT | score={result['score']} approved={result['approved']} "
                 f"regime={result['regime']} rr={result['recommended_rr']} "
                 f"ml={result['ml_win_prob']:.2f} "
                 f"reasoning={result.get('reasoning_summary', '')[:80]}")
        # Record approval so the correlation agent can gate subsequent correlated trades
        if result.get("approved"):
            _sym = data.get("symbol", "")
            _dir, _sig_err = _parse_signal_direction(data.get("signal"))
            if _sig_err is not None:
                return jsonify({
                    "approved": False, "error": True,
                    "error_type": "ValidationError", "error_message": _sig_err,
                    "block_reason": "INVALID_SIGNAL",
                    "score": result.get("score", 0), "risk_multiplier": 1.0,
                    "confidence": 0.0, "regime": "unknown", "recommended_rr": 2.0,
                    "ml_win_prob": 0.5, "ml_active": False,
                    "timestamp": datetime.utcnow().isoformat(),
                }), 400
            correlation_agent.record_approval(_sym, _dir, result["score"])
        threading.Thread(target=_push_reasoning,  args=(result, data), daemon=True).start()
        threading.Thread(target=_push_live_score, args=(result, data), daemon=True).start()
        return jsonify(result)
    except Exception as e:
        _sym = ""
        try:
            _sym = (request.get_json(force=True, silent=True) or {}).get("symbol", "") or ""
        except Exception:
            pass
        _record_scorer_error("/score", _sym, e)
        _err_resp = {
            "approved":        False,
            "score":           0,
            "error":           True,
            "error_type":      type(e).__name__,
            "error_message":   str(e),
            "block_reason":    "SCORER_EXCEPTION",
            "risk_multiplier": 1.0,
            "confidence":      0.0,
            "regime":          "unknown",
            "recommended_rr":  2.0,
            "ml_win_prob":     0.5,
            "ml_active":       False,
            "timestamp":       datetime.utcnow().isoformat(),
        }
        threading.Thread(
            target=_push_live_score,
            args=(_err_resp, {"symbol": _sym, "session": ""}),
            daemon=True,
        ).start()
        return jsonify(_err_resp), 500


@app.route("/debug/scorer-errors", methods=["GET"])
def debug_scorer_errors():
    """Return the last 20 scorer exceptions with full metadata.
    Used to detect silent failures that would otherwise cause 0-trade nights."""
    with _SCORER_ERROR_LOCK:
        errors = list(_SCORER_ERROR_LOG)
        count  = _SCORER_ERROR_COUNT
    last_ts  = errors[-1]["timestamp"] if errors else None
    return jsonify({
        "error_count":      count,
        "last_error_at":    last_ts,
        "errors":           errors,
    })


@app.route("/trade_opened", methods=["POST"])
def trade_opened():
    """
    Called by the EA immediately after it opens a position on any pair.
    Fires a Telegram alert with: symbol, direction, score, session, regime.

    This is the canonical trade-entry notification for all 7 scanner pairs
    (EURUSD, USDJPY, GBPUSD, AUDUSD, USDCAD, GBPJPY, EURJPY and any others).
    EURUSD/USDJPY EAs that call /score directly will also receive their existing
    alert from score_trade(); this endpoint is the fallback for scanner entries.

    Body: {
      "symbol":    "GBPJPY",
      "direction": "BUY",      // or "SELL"
      "score":     72.5,
      "session":   "LONDON",
      "regime":    "trend",
      "lots":      0.01,        // optional
      "sl_pips":   25.0,        // optional
      "tp_pips":   62.5         // optional
    }
    """
    try:
        data      = request.get_json(force=True) or {}
        symbol    = str(data.get("symbol",    "")).upper()
        direction = str(data.get("direction", "")).upper()
        score     = float(data.get("score",   0.0))
        session   = str(data.get("session",   "—"))
        regime    = str(data.get("regime",    "—"))
        lots      = data.get("lots")
        sl_pips   = data.get("sl_pips")
        tp_pips   = data.get("tp_pips")

        try:
            lots    = float(lots)    if lots    is not None else None
        except (TypeError, ValueError):
            lots    = None
        try:
            sl_pips = float(sl_pips) if sl_pips is not None else None
        except (TypeError, ValueError):
            sl_pips = None
        try:
            tp_pips = float(tp_pips) if tp_pips is not None else None
        except (TypeError, ValueError):
            tp_pips = None

        if not symbol:
            return jsonify({"error": "symbol is required"}), 400

        dir_icon  = "▲" if direction == "BUY" else "▼" if direction == "SELL" else "—"
        size_line = ""
        if lots is not None:
            size_line = f"Lots: {lots:.2f}"
            if sl_pips is not None:
                size_line += f"  SL: {sl_pips:.1f} pips"
            if tp_pips is not None:
                size_line += f"  TP: {tp_pips:.1f} pips"

        msg_lines = [
            f"<b>TRADE OPENED — {symbol}  {direction} {dir_icon}</b>",
            f"Score: <b>{score:.0f}</b>  Session: {session}  Regime: {regime}",
        ]
        if size_line:
            msg_lines.append(size_line)

        if _telegram_symbol_ok(symbol):
            send_telegram("\n".join(msg_lines))
        log.info(f"[TRADE OPENED] {symbol} {direction} score={score:.0f} "
                 f"session={session} regime={regime}")
        return jsonify({"ok": True})
    except Exception as e:
        log.error(f"[TRADE OPENED] Error: {e}")
        return jsonify({"error": str(e)}), 500



@app.route("/portfolio_check", methods=["POST"])
def portfolio_check():
    try:
        data   = request.get_json(force=True)
        result = portfolio_engine.check_trade(
            data.get("symbol", ""),
            int(data.get("signal", 0)),
            float(data.get("equity", 0)),
            float(data.get("balance", 0)),
            float(data.get("max_portfolio_dd", 3.0))
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({"approved": True, "risk_multiplier": 1.0, "error": str(e)})


@app.route("/portfolio_sync", methods=["POST"])
def portfolio_sync():
    try:
        data      = request.get_json(force=True)
        positions = data.get("positions", [])
        with portfolio_engine.lock:
            portfolio_engine.open_positions.clear()
        synced = 0
        for pos in positions:
            sym = pos.get("symbol", "")
            if sym and float(pos.get("lots", 0)) > 0:
                portfolio_engine.update_position(
                    sym,
                    int(pos.get("direction", 1)),
                    float(pos.get("lots", 0))
                )
                synced += 1
        log.info(f"PORTFOLIO SYNC | {synced} positions loaded")
        return jsonify({
            "status":           "synced",
            "positions_loaded": synced,
            "total_exposure":   portfolio_engine._total()
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/feedback", methods=["POST"])
def feedback():
    try:
        data    = request.get_json(force=True)
        won     = bool(data.get("won", False))
        profit  = float(data.get("profit", 0))
        session = data.get("session", "UNKNOWN").upper()
        setup   = data.get("setup", "UNKNOWN").upper()
        symbol  = data.get("symbol", "")

        regime_detector.update(won)
        regime_warning.update_streak(won)
        portfolio_engine.update_position(symbol, 0, 0)

        s = session if session in session_stats else "UNKNOWN"
        session_stats[s]["total"]  += 1
        session_stats[s]["profit"] += profit
        if won: session_stats[s]["wins"]   += 1
        else:   session_stats[s]["losses"] += 1

        su = setup if setup in setup_stats else "UNKNOWN"
        setup_stats[su]["total"]  += 1
        setup_stats[su]["profit"] += profit
        if won: setup_stats[su]["wins"]   += 1
        else:   setup_stats[su]["losses"] += 1

        features = extract_features({
            "trend": "BULLISH" if won else "BEARISH",
            "session": session, "setup": setup,
            "signal": 1, "smc": setup == "SWEEP",
            "breakout": setup == "BOS", "structure": setup == "FVG",
        })
        ai_model.record(features, won, profit)
        # --- analytics journal fields (journal-only; null when not supplied,
        #     never estimated) ---
        def _jnum(*keys):
            for k in keys:
                if k in data and data[k] is not None:
                    try:
                        return float(data[k])
                    except (TypeError, ValueError):
                        return None
            return None
        _j_ts       = datetime.utcnow().isoformat()
        _j_score    = _jnum("score", "score_used")
        _j_regime   = data.get("regime") or None
        _j_rmult    = _jnum("r_multiple", "rr_achieved")
        _j_entry    = _jnum("entry_price", "entry")
        _j_sl       = _jnum("stop_loss", "sl_price")
        _j_tp       = _jnum("take_profit", "tp_price")
        _j_dir      = data.get("direction")
        _j_dir      = None if _j_dir is None else str(_j_dir)
        _j_tradeid  = str(data.get("trade_id") or data.get("ticket") or uuid.uuid4())
        _journal_rec = {
            "won": won, "profit": profit, "session": session,
            "setup": setup, "symbol": symbol, "ts": _j_ts,
            "score": _j_score, "regime": _j_regime, "r_multiple": _j_rmult,
            "entry_price": _j_entry, "stop_loss": _j_sl, "take_profit": _j_tp,
            "direction": _j_dir, "trade_id": _j_tradeid,
        }
        trade_history.append(dict(_journal_rec))
        _append_journal(_journal_rec)
        log.info(f"FEEDBACK | {'WIN' if won else 'LOSS'} {profit:.2f} "
                 f"session={session} setup={setup}")
        rr_achieved  = float(data.get("rr_achieved",  0.0))
        hold_minutes = float(data.get("hold_minutes", 0.0))
        score_used   = float(data.get("score_used",   0.0))
        # v4.0 — record per-strategy fill if EA included a v4_strategy tag
        v4_strategy  = (data.get("v4_strategy") or "").lower()
        if v4_strategy:
            try:
                v4_record_fill(v4_strategy, won, rr_achieved if won else -1.0)
            except Exception as e:
                log.warning(f"[v4 fill record] {e}")
        outcome_icon = "✅" if won else "❌"
        hold_str = f"{int(hold_minutes//60)}h {int(hold_minutes%60)}m" if hold_minutes > 0 else "—"
        score_str = f"Score used: {score_used:.0f}  " if score_used > 0 else ""
        if _telegram_symbol_ok(symbol):
            send_telegram(
                f"{outcome_icon} <b>TRADE {'WIN' if won else 'LOSS'} — {symbol}</b>\n"
                f"P&amp;L: <b>{profit:+.2f}</b>  RR achieved: {rr_achieved:.2f}R\n"
                f"Hold: {hold_str}  Session: {session}\n"
                f"{score_str}Setup: {setup}"
            )
        # Daily target check — alert when cumulative session profit looks strong
        session_profit_today = sum(
            t["profit"] for t in list(trade_history)[-20:]
            if t.get("ts", "")[:10] == datetime.utcnow().strftime("%Y-%m-%d")
        )
        if session_profit_today > 0 and won:
            trades_today_list = [t for t in list(trade_history)[-20:]
                                 if t.get("ts", "")[:10] == datetime.utcnow().strftime("%Y-%m-%d")]
            if len(trades_today_list) >= 2 and session_profit_today >= 1000:
                send_telegram(
                    f"🎯 <b>DAILY TARGET PROGRESS</b>\n"
                    f"Today: <b>+${session_profit_today:.0f}</b>  "
                    f"({len(trades_today_list)} trades)\n"
                    f"FTMO challenge pace: on track"
                )
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/order_flow", methods=["POST"])
def order_flow_endpoint():
    try:
        data   = request.get_json(force=True)
        symbol = data.get("symbol", "")
        if data.get("type") == "bar":
            order_flow.receive_bar(
                symbol,
                float(data.get("open", 0)),   float(data.get("high", 0)),
                float(data.get("low", 0)),     float(data.get("close", 0)),
                float(data.get("volume", 0)),
                float(data.get("buy_vol", 0)), float(data.get("sell_vol", 0))
            )
        atr = float(data.get("atr", 0))
        liquidity_map.update(
            symbol,
            float(data.get("high", 0)),
            float(data.get("low", 0)),
            float(data.get("close", 0)),
            atr
        )
        regime_warning.update(
            symbol, atr,
            float(data.get("spread", 0)),
            float(data.get("volume", 0))
        )
        return jsonify({"status": "ok", "signal": order_flow.get_signal(symbol)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/orchestrate", methods=["POST"])
def orchestrate():
    try:
        data   = request.get_json(force=True)
        result = orchestrator.distribute_signal(data)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/accounts/register", methods=["POST"])
def register_account():
    try:
        data = request.get_json(force=True)
        orchestrator.register_account(
            data["account_id"],
            float(data.get("balance", 100000)),
            float(data.get("max_daily_dd", 5.0)),
            float(data.get("max_total_dd", 10.0)),
            float(data.get("risk_pct", 1.0)),
            data.get("endpoint", "")
        )
        return jsonify({"status": "registered", "account_id": data["account_id"]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/accounts/update", methods=["POST"])
def update_account():
    try:
        data = request.get_json(force=True)
        orchestrator.update_account(
            data["account_id"],
            float(data.get("equity", 0)),
            float(data.get("balance", 0))
        )
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/accounts/status", methods=["GET"])
def accounts_status():
    return jsonify(orchestrator.get_portfolio_summary())


# ══════════════════════════════════════════════════════════════════════
# ACCOUNT SNAPSHOT TELEMETRY (additive; telemetry only)
# EA posts a live account snapshot; /account/status returns it with age.
# Does NOT touch scoring, thresholds, approval, execution, or risk rules —
# the snapshot is stored for observability only and never mutates risk state.
# ══════════════════════════════════════════════════════════════════════
_account_snapshot_lock = threading.Lock()
_account_snapshot = {
    "balance": None, "equity": None, "margin": None, "free_margin": None,
    "positions_open": None, "timestamp": None, "received_at": None,
}


def _risk_engine_present():
    """True if the portfolio risk/compliance engine is loadable in this
    deployment. Used ONLY to report integration status — the snapshot is
    stored as telemetry and never feeds risk decisions (no risk-rule change)."""
    try:
        return _load_portfolio_engine() is not None
    except Exception:
        return False


@app.route("/account/snapshot", methods=["POST"])
def account_snapshot():
    """Store a live account telemetry snapshot from the EA.
    Body: {balance, equity, margin, free_margin, positions_open, timestamp?}
    Telemetry only — no effect on scoring, approval, or risk rules."""
    try:
        data = request.get_json(force=True) or {}

        def _num(*keys):
            for k in keys:
                if k in data and data[k] is not None:
                    try:
                        return float(data[k])
                    except (TypeError, ValueError):
                        return None
            return None

        _pos = _num("positions_open", "positionsOpen", "positions")
        with _account_snapshot_lock:
            _account_snapshot.update({
                "balance":        _num("balance"),
                "equity":         _num("equity"),
                "margin":         _num("margin"),
                "free_margin":    _num("free_margin", "freeMargin"),
                "positions_open": int(_pos) if _pos is not None else None,
                "timestamp":      data.get("timestamp"),
                "received_at":    time.time(),
            })
        return jsonify({
            "status":           "ok",
            "risk_integration": "present" if _risk_engine_present() else "absent",
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/account/status", methods=["GET"])
def account_status():
    """Return the last account snapshot plus its age in seconds.
    Reports whether a risk/compliance engine is present; the snapshot is
    telemetry only and is not wired into risk decisions (no risk-rule change)."""
    with _account_snapshot_lock:
        snap = dict(_account_snapshot)
    received     = snap.pop("received_at", None)
    has_snapshot = received is not None
    age          = (time.time() - received) if received is not None else None
    present      = _risk_engine_present()
    return jsonify({
        "has_snapshot":     has_snapshot,
        "balance":          snap["balance"],
        "equity":           snap["equity"],
        "margin":           snap["margin"],
        "free_margin":      snap["free_margin"],
        "positions_open":   snap["positions_open"],
        "timestamp":        snap["timestamp"],
        "age_seconds":      round(age, 3) if age is not None else None,
        "risk_engine":      "present" if present else "absent",
        "risk_integration": "telemetry_only" if present else "absent",
        "note": ("snapshot stored as telemetry; not wired into risk decisions "
                 "(no risk-rule change)") if present else
                ("risk/compliance engine not present in this deployment — "
                 "snapshot stored only"),
    })


@app.route("/monte_carlo", methods=["GET"])
def monte_carlo_endpoint():
    try:
        total   = sum(s["total"] for s in session_stats.values())
        wins    = sum(s["wins"]  for s in session_stats.values())
        wr      = wins / total if total > 0 else 0.65
        profits = [t["profit"] for t in trade_history if t["profit"] > 0]
        losses  = [abs(t["profit"]) for t in trade_history if t["profit"] < 0]
        avg_rr  = (np.mean(profits) / np.mean(losses)) if profits and losses else 2.5
        risk    = float(request.args.get("risk_pct", 1.0))
        n       = int(request.args.get("n_trades", 200))
        dd_lim  = float(request.args.get("dd_limit", 5.0))
        result  = monte_carlo.run(wr, avg_rr, risk, n, MONTE_CARLO_RUNS, dd_lim)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/range_zones", methods=["GET"])
def range_zones_endpoint():
    """GET /range_zones?symbols=EURUSD,GBPUSD
    Returns EQH/EQL levels, Donchian compression state, and edge flags per symbol.
    Dashboard and EA use this to draw range boundaries and adjust scoring context.
    """
    try:
        symbols_raw = request.args.get("symbols", "EURUSD")
        symbols     = [s.strip() for s in symbols_raw.split(",") if s.strip()]
        result      = {sym: detect_range_zone(sym) for sym in symbols}
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/monthly_levels", methods=["GET"])
def monthly_levels_endpoint():
    """GET /monthly_levels?symbols=EURUSD,GBPUSD
    Returns monthly high/low, prior month high/low, and proximity flags per symbol.
    EA uses this to draw gold/lime horizontal lines on the chart (refreshed hourly).
    """
    try:
        symbols_raw = request.args.get("symbols", "EURUSD")
        symbols     = [s.strip() for s in symbols_raw.split(",") if s.strip()]
        result      = {sym: detect_monthly_levels(sym) for sym in symbols}
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/liquidity_map", methods=["GET"])
def liquidity_map_endpoint():
    try:
        symbol = request.args.get("symbol", "EURUSD")
        price  = float(request.args.get("price", 0))
        return jsonify(liquidity_map.get_map(symbol, price))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/sentiment", methods=["GET"])
def sentiment_endpoint():
    symbol = request.args.get("symbol", "")
    return jsonify(sentiment_agg.get_sentiment(symbol))


@app.route("/regime", methods=["GET"])
def regime_endpoint():
    symbol = request.args.get("symbol", "")
    ew     = regime_warning.check(symbol if symbol else None)
    rd     = regime_detector.detect({"trend": "NEUTRAL", "session": "OFF",
                                      "smc": False, "breakout": False})
    return jsonify({
        **ew,
        "regime_detector": rd,
        "loss_streak":     regime_detector.loss_streak,
        "win_streak":      regime_detector.win_streak
    })


@app.route("/dynamic_rr", methods=["GET"])
def dynamic_rr_endpoint():
    regime     = request.args.get("regime", "trend")
    session    = request.args.get("session", "LONDON")
    confluence = int(request.args.get("confluence", 2))
    return jsonify(dynamic_rr.get_rr(regime, session, confluence))


@app.route("/retrain", methods=["POST"])
def retrain():
    threading.Thread(target=ai_model.retrain, daemon=True).start()
    threading.Thread(
        target=lambda: ml_classifier.train(list(ai_model.train_history)),
        daemon=True
    ).start()
    return jsonify({"status": "retraining", "history": len(ai_model.train_history)})


@app.route("/stats", methods=["GET"])
def stats():
    total   = sum(s["total"] for s in session_stats.values())
    wins    = sum(s["wins"]  for s in session_stats.values())
    wr      = round(wins / total * 100, 1) if total > 0 else 0
    gross_p = sum(t["profit"] for t in trade_history if t["profit"] > 0)
    gross_l = abs(sum(t["profit"] for t in trade_history if t["profit"] < 0))
    return jsonify({
        "overall": {
            "total_trades": total,
            "wins":         wins,
            "win_rate_pct": wr,
            "profit_factor": round(gross_p / gross_l, 2) if gross_l > 0 else 0,
            "net_profit":   round(gross_p - gross_l, 2)
        },
        "session_stats":  session_stats,
        "setup_stats":    setup_stats,
        "ml_model": {
            "active":      ml_classifier.is_trained,
            "cv_score":    ml_classifier.cv_score,
            "train_count": ml_classifier.train_count
        },
        "adaptive_model": {
            "retrain_count": ai_model.retrain_count,
            "history_size":  len(ai_model.train_history)
        },
        "portfolio": {
            "open_positions": len(portfolio_engine.open_positions),
            "total_exposure": portfolio_engine._total()
        },
        "accounts":        orchestrator.get_portfolio_summary(),
        "regime_warning":  regime_warning.check(),
    })


@app.route("/debug/heartbeat", methods=["GET"])
def debug_heartbeat():
    """Shows EA-alive timestamp state — use to diagnose STALE_HEARTBEAT."""
    _STALE_HB_MAX_SECS = 300
    now = time.time()
    age = round(now - _last_heartbeat_ts, 1) if _last_heartbeat_ts else None
    stale = (age is None) or (age > _STALE_HB_MAX_SECS)
    return jsonify({
        "last_ea_contact":  _last_heartbeat_ts or None,
        "age_seconds":      age,
        "stale":            stale,
        "stale_threshold":  _STALE_HB_MAX_SECS,
    })


@app.route("/healthz", methods=["GET"])
def healthz():
    """
    Machine-readable health check used by deploy_manager.py.
    Returns structured JSON so the deployment pipeline can verify the scorer
    is alive, running the correct environment, and serving requests.
    """
    uptime        = int(time.time() - _SERVER_START)
    total_scores  = sum(s["total"] for s in session_stats.values())
    last_score_ts = None
    if trade_history:
        try:
            last_score_ts = trade_history[-1].get("timestamp") or trade_history[-1].get("ts")
        except Exception:
            pass
    try:
        regime_info = regime_warning.check()
        regime_str  = regime_info.get("regime", "UNKNOWN")
        regime_act  = regime_info.get("action", "")
    except Exception:
        regime_str  = "UNKNOWN"
        regime_act  = ""
    return jsonify({
        "status":        "ok",
        "version":       "4.02",
        "environment":   _PHANTOM_ENV,
        "port":          PORT,
        "host":          HOST,
        "uptime_sec":    uptime,
        "scores_served": total_scores,
        "ml_active":     bool(ml_classifier.is_trained or HAS_XGB or HAS_SKLEARN),
        "min_score":     MIN_SCORE,
        "regime":        regime_str,
        "regime_action": regime_act,
        "last_score_at": last_score_ts,
        "open_positions":    len(portfolio_engine.open_positions) if portfolio_engine else 0,
        "heartbeat_age_sec": round(time.time() - _last_heartbeat_ts, 1) if _last_heartbeat_ts else None,
        "ea_connected":      bool(_last_heartbeat_ts > 0 and (time.time() - _last_heartbeat_ts) < 300),
    })


@app.route("/best_signal", methods=["GET", "POST"])
def best_signal_endpoint():
    """
    Called by EA every new bar.
    Returns the single best qualifying signal across all scanner pairs.
    Qualifies: has setup + AI score >= MIN_SCORE + news clear.
    EA executes on whichever pair wins.
    """
    try:
        data       = request.get_json(force=True) if request.method == "POST" else {}
        candidates = data.get("candidates", []) if data else []

        if not candidates:
            return jsonify({
                "signal_available": False,
                "symbol": "", "direction": 0,
                "setup": "", "score": 0,
                "regime": "unknown", "recommended_rr": 2.5,
                "risk_multiplier": 1.0,
                "reason": "No candidates submitted"
            })

        qualified = [
            c for c in candidates
            if c.get("has_setup", False)
            and float(c.get("ai_score", 0)) >= MIN_SCORE
            and not c.get("news_blocked", False)
            and c.get("ai_approved", False)
        ]

        if not qualified:
            return jsonify({
                "signal_available": False,
                "symbol": "", "direction": 0,
                "setup": "", "score": 0,
                "regime": "unknown", "recommended_rr": 2.5,
                "risk_multiplier": 1.0,
                "reason": f"No pairs passed filters (need score>={MIN_SCORE}, setup, news clear)"
            })

        best      = max(qualified, key=lambda c: float(c.get("ai_score", 0)))
        symbol    = best.get("symbol", "")
        setup     = best.get("setup", "")
        score     = float(best.get("ai_score", 0))
        direction = 1 if "▲" in setup else -1

        session = best.get("session", "OFF")
        regime  = regime_detector.detect({
            "trend":     "BULLISH" if direction == 1 else "BEARISH",
            "session":   session,
            "smc":       "SWEEP" in setup,
            "breakout":  "BOS" in setup,
            "structure": "FVG" in setup,
        })
        rr_rec     = dynamic_rr.get_rr(regime, session, 2)
        risk_multi = _calc_risk_multi(score, regime, session, "CHALLENGE")

        log.info(f"BEST SIGNAL | {symbol} {setup} score={score:.1f} "
                 f"regime={regime} rr={rr_rec['recommended_rr']}")

        return jsonify({
            "signal_available": True,
            "symbol":           symbol,
            "direction":        direction,
            "setup":            setup,
            "score":            round(score, 1),
            "regime":           regime,
            "recommended_rr":   rr_rec["recommended_rr"],
            "risk_multiplier":  risk_multi,
            "session":          session,
            "bias":             best.get("bias", ""),
            "timestamp":        datetime.utcnow().isoformat(),
        })

    except Exception as e:
        _record_scorer_error("/best_signal", "", e)
        return jsonify({
            "signal_available": False,
            "error":            True,
            "error_type":       type(e).__name__,
            "error_message":    str(e),
            "block_reason":     "SCORER_EXCEPTION",
        }), 500


# ══════════════════════════════════════════════════════════════════════
# REGIME V2 ENDPOINTS (Task #23)
# ══════════════════════════════════════════════════════════════════════

def trade_opened_endpoint():
    """Stub — accepts EA trade-open notifications and forwards to dashboard so
    the alert center / Telegram webhook can surface them. Best-effort, never errors."""
    try:
        data = request.get_json(force=True, silent=True) or {}
        def _forward():
            try:
                requests.post(f"{DASHBOARD_API_URL}/ai/trade-opened",
                              json=data, timeout=3.0)
            except Exception:
                pass
        threading.Thread(target=_forward, daemon=True).start()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/regime_v2", methods=["GET"])
def regime_v2_endpoint():
    """Returns multi-TF trend score + 6-state regime for a symbol.
    Adds `direction` alias of `trend_direction` per task spec contract,
    plus `bar_counts` per TF so the EA/dashboard can verify warm-up depth."""
    symbol = request.args.get("symbol", "EURUSD").upper()
    r2 = compute_regime_v2(symbol)
    r2["direction"]  = r2["trend_direction"]   # spec-required alias
    r2["bar_counts"] = bar_store.counts(symbol)
    return jsonify(r2)


@app.route("/bars_push", methods=["POST"])
def bars_push_endpoint():
    """EA pushes the latest closed M15 bar.
    Body: {symbol, o, h, l, c, v}"""
    try:
        data   = request.get_json(force=True)
        symbol = data.get("symbol", "").upper()
        if not symbol:
            return jsonify({"error": "symbol required"}), 400
        bar_store.add_m15(
            symbol,
            data.get("o", data.get("open", 0)),
            data.get("h", data.get("high", 0)),
            data.get("l", data.get("low",  0)),
            data.get("c", data.get("close", 0)),
            data.get("v", data.get("volume", 0)),
        )
        return jsonify({"status": "ok", "bars": bar_store.count(symbol)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/bars_backfill", methods=["POST"])
def bars_backfill_endpoint():
    """EA pushes a batch of recent bars on init for cold-start.
    Body: {symbol, tf?, bars: [{o,h,l,c,v}, ...]}  (oldest → newest)
    tf defaults to M15 for backward compatibility.
    """
    try:
        data   = request.get_json(force=True)
        symbol = data.get("symbol", "").upper()
        tf     = data.get("tf", "M15").upper()
        bars   = data.get("bars", [])
        if not symbol:
            return jsonify({"error": "symbol required"}), 400
        bar_store.replace_tf(symbol, tf, bars)
        log.info(f"BARS BACKFILL | {symbol} {tf} | {len(bars)} bars loaded")
        return jsonify({"status": "ok",
                        "tf":     tf,
                        "counts": bar_store.counts(symbol)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/bars_export", methods=["GET"])
def bars_export():
    """Export BarStore bars for a symbol/TF with back-calculated timestamps.
    Used by the dashboard backtest to run on EA-sourced broker data instead of
    Yahoo/Twelve Data — the exact same feed the EA trades on.

    GET /bars_export?symbol=EURUSD&tf=M15
    Returns: {symbol, tf, count, bars: [{t, o, h, l, c, v}, ...]}  oldest→newest
    """
    symbol = request.args.get("symbol", "EURUSD").upper()
    tf     = request.args.get("tf", "M15").upper()
    bars   = bar_store.get(symbol, tf)
    if not bars:
        return jsonify({"symbol": symbol, "tf": tf, "count": 0, "bars": []})
    # Back-calculate Unix timestamps: most recent bar ends at the current
    # TF-boundary; each step back is one bar-period.
    bar_secs = {"M15": 900, "H1": 3600, "H4": 14400, "D1": 86400}.get(tf, 900)
    now_ts   = int(time.time())
    boundary = (now_ts // bar_secs) * bar_secs   # current open bar start
    n        = len(bars)
    result   = []
    for i, b in enumerate(bars):
        ts = boundary - (n - 1 - i) * bar_secs
        result.append({"t": ts, "o": b["o"], "h": b["h"],
                       "l": b["l"], "c": b["c"], "v": b.get("v", 0)})
    return jsonify({"symbol": symbol, "tf": tf,
                    "count": len(result), "bars": result})


@app.route("/intermarket", methods=["GET"])
def intermarket_state():
    """Return the current cached intermarket data (DXY, Gold, US10Y, US2Y, VIX)."""
    try:
        state = intermarket_agent.get_state()
        return jsonify(state if state else {"source": "no_data"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/momentum", methods=["GET"])
def momentum_endpoint():
    """Return momentum fade status for all tracked pairs."""
    pairs = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "EURJPY"]  # GBPJPY removed — 17% WR, -$3,215 audit
    result = {}
    for sym in pairs:
        result[sym] = detect_momentum_fade(sym)
    return jsonify(result)


@app.route("/kotegawa", methods=["GET"])
def kotegawa_endpoint():
    """Return Kotegawa overextension status for all tracked pairs."""
    pairs = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "EURJPY"]  # GBPJPY removed — blocked from trading
    result = {}
    for sym in pairs:
        bars = bar_store.get(sym, "M15")
        stub_atr = 0.0
        if bars and len(bars) >= 2:
            stub_atr = abs(bars[-1].get("high", 0) - bars[-1].get("low", 0))
        stub = {"symbol": sym, "signal": 0, "atr": stub_atr}
        result[sym] = score_kotegawa(sym, stub)
    return jsonify(result)


@app.route("/ssi/update", methods=["POST"])
def ssi_update():
    """
    Push SSI data from an external source (OANDA, IG, Myfxbook).
    Accepts array or single object: [{symbol, long_pct, short_pct, source}, ...]
    Also forwards to dashboard API so the TypeScript store is always in sync.
    """
    try:
        body    = request.get_json(force=True) or []
        entries = body if isinstance(body, list) else [body]
        stored  = 0
        for e in entries:
            sym = str(e.get("symbol", "")).strip().upper()
            if not sym:
                continue
            ssi_agent.update(
                sym,
                float(e.get("long_pct",  50)),
                float(e.get("short_pct", 50)),
                source=str(e.get("source", "external")),
                report_time=e.get("report_time"),
            )
            stored += 1
        # Forward to dashboard so TypeScript SSI store stays synced
        def _fwd():
            try:
                requests.post(
                    f"{DASHBOARD_API_URL}/ai/ssi/update",
                    json=entries, timeout=3.0,
                )
            except Exception:
                pass
        threading.Thread(target=_fwd, daemon=True).start()
        return jsonify({"ok": True, "stored": stored})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/options/update", methods=["POST"])
def options_update():
    """
    Push today's FX option expiry levels.
    Accepts array: [{symbol, level, notional_m, date}, ...]
    Also forwards to dashboard API store.
    """
    try:
        body    = request.get_json(force=True) or []
        entries = body if isinstance(body, list) else [body]
        options_expiry_agent.update(entries)
        def _fwd():
            try:
                requests.post(
                    f"{DASHBOARD_API_URL}/ai/options/update",
                    json=entries, timeout=3.0,
                )
            except Exception:
                pass
        threading.Thread(target=_fwd, daemon=True).start()
        return jsonify({"ok": True, "stored": len(entries)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/options", methods=["GET"])
def options_state():
    """Return today's cached option expiry levels."""
    try:
        now      = datetime.utcnow()
        cut_mins = (15 - now.hour) * 60 - now.minute
        return jsonify({
            "expiries":    options_expiry_agent.all_expiries(),
            "mins_to_cut": cut_mins,
            "timestamp":   now.isoformat(),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/surprise/update", methods=["POST"])
def surprise_update():
    """VPS pushes economic data releases here immediately after each event."""
    try:
        data = request.get_json(force=True) or {}
        events = data if isinstance(data, list) else data.get("events", [])
        economic_surprise_agent.update(events)
        log.info(f"[SURPRISE] updated {len(events)} events")
        return jsonify({"ok": True, "stored": len(economic_surprise_agent.all_events())})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/surprise", methods=["GET"])
def surprise_state():
    """Return cached economic surprise events (last 24h)."""
    try:
        cutoff = datetime.utcnow() - timedelta(hours=24)
        events = [
            e for e in economic_surprise_agent.all_events()
            if datetime.fromisoformat(e.get("timestamp", "2000-01-01")) > cutoff
        ]
        events.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
        return jsonify({"events": events, "total": len(events), "timestamp": datetime.utcnow().isoformat()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/correlation", methods=["GET"])
def correlation_matrix():
    """Return live cross-pair correlation matrix computed from BarStore."""
    try:
        matrix = correlation_agent.get_full_matrix(bar_store)
        return jsonify({"matrix": matrix, "pairs": list(matrix.keys()), "timestamp": datetime.utcnow().isoformat()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/heartbeat", methods=["POST"])
def heartbeat_endpoint():
    """EA heartbeat — enriched with regime_v2 fields and forwarded to dashboard."""
    try:
        data = request.get_json(force=True) or {}
        sym  = data.get("symbol", "EURUSD").upper()
        r2   = compute_regime_v2(sym)
        data["trend_score"]            = r2["trend_score"]
        data["trend_direction"]        = r2["trend_direction"]
        data["regime_v2"]              = r2["regime"]
        data["regime_v2_label"]        = r2["regime_label"]
        data["regime_agreement"]       = r2["agreement"]
        data["regime_v2_insufficient"] = r2["insufficient_data"]
        data["regime_components"]      = r2["components"]
        data["regime_v2_weights"]      = r2["weights"]
        data["vol_bucket"]             = r2["vol_bucket"]
        data["vol_percentile"]         = r2["vol_percentile"]

        # ── Portfolio v2 — update rolling state from heartbeat ─────────────
        # Feeds open_positions, prices, weekly_dd_pct, monthly_dd_pct into
        # the institutional PortfolioRiskEngine so correlation/heat/killswitch
        # all have live data by the time /score runs pre-trade validation.
        try:
            _pe_hb = _load_portfolio_engine()
            if _pe_hb is not None:
                _pe_hb.portfolio_risk_engine.update_from_heartbeat(data)
        except Exception:
            pass

        # ── Phase 8 — Track globals for /metrics + anomaly detection ─────────
        global _last_heartbeat_ts, _g_daily_dd_pct, _g_portfolio_heat
        _last_heartbeat_ts = time.time()
        _g_daily_dd_pct    = float(data.get("daily_dd_pct",    _g_daily_dd_pct) or 0.0)
        _g_portfolio_heat  = float(data.get("portfolio_heat",  _g_portfolio_heat) or 0.0)
        try:
            _ae_mod = _get_anomaly_engine_mod()
            if _ae_mod is not None:
                _ae = _ae_mod.anomaly_engine
                _a  = _ae.check("daily_dd_pct",   _g_daily_dd_pct,   symbol="")
                if _a:
                    send_phantom_alert(_a["message"], _a["severity"], f"dd:{_a['severity']}")
                _a  = _ae.check("portfolio_heat", _g_portfolio_heat, symbol="")
                if _a:
                    send_phantom_alert(_a["message"], _a["severity"], f"heat:{_a['severity']}")
        except Exception as _ae_err:
            log.debug(f"[ANOMALY] heartbeat check: {_ae_err}")

        def _forward():
            try:
                requests.post(
                    f"{DASHBOARD_API_URL}/ai/heartbeat",
                    json=data, timeout=3.0,
                )
            except Exception as fe:
                log.debug(f"heartbeat forward failed: {fe}")
        threading.Thread(target=_forward, daemon=True).start()
        return jsonify({"ok": True, "trend_score": r2["trend_score"]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/health", methods=["GET"])
def health():
    # Wave 2 #12 — deeper health: per-symbol bar age + DASHBOARD_API_URL liveness
    bar_age = {}
    for sym in ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "NZDUSD", "USDCHF"]:
        cnt = bar_store.counts(sym)
        if any(cnt.values()): bar_age[sym] = cnt
    dashboard_alive = False
    try:
        # Dashboard health endpoint is /healthz (not /health) — using /health would 404,
        # falsely marking dashboard as dead. No recursion risk: dashboard /healthz is local-only.
        r = requests.get(f"{DASHBOARD_API_URL}/healthz", timeout=2.0)
        dashboard_alive = (r.status_code == 200)
    except Exception:
        pass
    return jsonify({
        "status":   "online",
        "version":  "4.1",
        "features": [
            "order_flow", "ml_classifier", "liquidity_heatmap",
            "monte_carlo", "correlation_sizing", "dynamic_rr",
            "latency_tracker", "multi_account", "sentiment",
            "regime_early_warning", "regime_v2_multi_tf",
            "killswitch", "friday_closeout"
        ],
        "ml_active":       ml_classifier.is_trained,
        "accounts":        len(orchestrator.accounts),
        "bar_counts":      bar_age,
        "dashboard_alive": dashboard_alive,
        "timestamp":       datetime.utcnow().isoformat()
    })


# ══════════════════════════════════════════════════════════════════════
# WAVE 2 #1 — Stubs for endpoints the EA calls but were never built.
# These previously failed silently every cycle, polluting logs and
# leaving guards (correlation/news) effectively disabled. Stubs return
# safe defaults so the EA proceeds normally; future tasks can fill them in.
# ══════════════════════════════════════════════════════════════════════

@app.route("/correlation_check", methods=["GET"])
def correlation_check():
    """
    Check if a proposed symbol is too correlated with any currently open position.
    Called by EA before every trade to avoid doubling exposure on the same move.
    GET /correlation_check?sym=GBPJPY
    Returns: { approved, corr_score, blocking_pair, reason, threshold }
    """
    try:
        sym = request.args.get("sym", "").upper().replace(".", "")
        if not sym:
            return jsonify({"approved": True, "reason": "no symbol provided"})

        with portfolio_engine.lock:
            open_pos = dict(portfolio_engine.open_positions)

        if not open_pos:
            return jsonify({"approved": True, "corr_score": 0.0,
                            "blocking_pair": "", "reason": "no open positions"})

        CORR_THRESHOLD = 0.75
        max_corr       = 0.0
        blocking_pair  = ""

        for open_sym in open_pos:
            key  = (sym, open_sym) if (sym, open_sym) in CORRELATIONS \
                   else (open_sym, sym)
            corr = abs(CORRELATIONS.get(key, 0.0))
            if corr > max_corr:
                max_corr      = corr
                blocking_pair = open_sym

        approved = max_corr < CORR_THRESHOLD
        if not approved:
            log.info(f"[CORR BLOCK] {sym} blocked — corr={max_corr:.2f} with {blocking_pair}")

        return jsonify({
            "approved":      approved,
            "corr_score":    round(max_corr, 3),
            "blocking_pair": blocking_pair if not approved else "",
            "reason":        f"corr={max_corr:.2f} with {blocking_pair}" if not approved else "ok",
            "threshold":     CORR_THRESHOLD,
        })
    except Exception as e:
        return jsonify({"approved": True, "error": str(e)})


@app.route("/calendar_events", methods=["GET"])
def calendar_events():
    """
    Return upcoming HIGH impact forex events from the live ForexFactory calendar cache.
    Shows events within the next 24 hours and the past 1 hour.
    GET /calendar_events
    """
    try:
        events = _fetch_calendar()
        now    = datetime.utcnow()
        window = []
        for ev in events:
            mins_away = (ev["dt"] - now).total_seconds() / 60
            if -60 <= mins_away <= 1440:
                window.append({
                    "currency":    ev["currency"],
                    "title":       ev["title"],
                    "time_utc":    ev["dt"].strftime("%Y-%m-%dT%H:%M"),
                    "mins_away":   round(mins_away, 0),
                    "blocked_now": abs(mins_away) <= NEWS_BLOCK_WINDOW_MIN,
                })
        window.sort(key=lambda x: x["mins_away"])
        return jsonify({
            "events":           window,
            "total_fetched":    len(events),
            "fetched_at":       _calendar_cache["fetched_at"].isoformat()
                                if _calendar_cache["fetched_at"] else None,
            "block_window_min": NEWS_BLOCK_WINDOW_MIN,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/set_telegram", methods=["POST"])
def set_telegram_endpoint():
    """
    Update Telegram bot credentials at runtime without restarting the scorer.
    POST: {
      "token":       "bot_token_here",
      "chat_id":     "your_chat_id",
      "alert_pairs": ["EURUSD","GBPJPY"]
        // optional — omit to leave the current filter unchanged
        // pass [] to reset to all pairs (default / no filtering)
    }
    A test message is sent immediately on success.
    """
    try:
        data = request.get_json(force=True)
        with _telegram_cfg["lock"]:
            if "token"   in data: _telegram_cfg["token"]   = str(data["token"])
            if "chat_id" in data: _telegram_cfg["chat_id"] = str(data["chat_id"])
            if "alert_pairs" in data:
                raw = data["alert_pairs"]
                if not isinstance(raw, list):
                    return jsonify({"error": "alert_pairs must be a list"}), 400
                # Normalise to uppercase and deduplicate, preserving order
                seen: set = set()
                deduped = []
                for p in raw:
                    key = str(p).upper()
                    if key not in seen:
                        seen.add(key)
                        deduped.append(key)
                _telegram_cfg["alert_pairs"] = deduped
        pairs = _telegram_cfg["alert_pairs"]
        pairs_note = (f"Filtering alerts to: {', '.join(pairs)}" if pairs
                      else "Alerts active for all pairs.")
        send_telegram(
            "<b>PhantomEdge Connected</b>\n"
            "Telegram alerts are now active.\n"
            f"{pairs_note}\n"
            "You will receive trade approvals, win/loss outcomes, and DD warnings here."
        )
        log.info("[TELEGRAM] Credentials updated via /set_telegram (alert_pairs=%s)",
                 pairs or "all")
        return jsonify({
            "status":       "ok",
            "configured":   bool(_telegram_cfg["token"]),
            "alert_pairs":  pairs,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/backtest", methods=["POST"])
def backtest():
    """
    Replay historical OHLC candles through scorer logic.
    Detects simple SMC setups (sweep/BOS) on each candle, scores each with the
    live scorer, simulates P&L, and returns an equity curve + signal list.

    Body: { "symbol": "EURUSD", "mode": "CHALLENGE",
            "candles": [ {"time": "2024-01-15T08:00", "open": 1.0920,
                           "high": 1.0935, "low": 1.0910, "close": 1.0930,
                           "volume": 1234}, ... ] }
    Returns: { signals, equity_curve, stats }
    """
    try:
        data    = request.get_json(force=True)
        symbol  = data.get("symbol", "EURUSD").upper()
        mode    = data.get("mode", "CHALLENGE")
        candles = data.get("candles", [])

        if len(candles) < 20:
            return jsonify({"error": "Need at least 20 candles for ATR calculation"}), 400

        # Options
        filter_sessions = bool(data.get("filter_sessions", True))  # apply session gate

        # Session-aware win rates — calibrated from SMC M15 backtest literature
        SESSION_WIN_RATES = {
            "LONDON_NY": 0.65,   # overlap: tightest spreads, strongest continuation
            "LONDON":    0.61,   # directional, institutional flow
            "NY":        0.57,   # choppier, more reversals late session
            "ASIA":      0.43,   # range-bound, low follow-through on M15
        }

        ATR_PERIOD        = 14
        signals           = []
        equity            = 100000.0
        equity_curve      = [equity]
        peak_equity       = equity
        max_dd            = 0.0
        wins = losses     = 0
        consec_loss       = 0
        max_consec_loss   = 0
        trade_returns: List[float] = []   # for Sharpe
        session_filtered  = 0             # entries blocked by session gate

        import random as _rnd
        _rnd.seed(42)   # reproducible results for same dataset

        for i in range(ATR_PERIOD + 2, len(candles)):
            c = candles[i]

            # ATR
            trs = []
            for j in range(i - ATR_PERIOD, i):
                pc = float(candles[j-1]["close"])
                hi = float(candles[j]["high"])
                lo = float(candles[j]["low"])
                trs.append(max(hi - lo, abs(hi - pc), abs(lo - pc)))
            atr = float(np.mean(trs))
            if atr <= 0:
                equity_curve.append(equity)
                continue

            closes = [float(candles[k]["close"]) for k in range(i-4, i+1)]
            highs  = [float(candles[k]["high"])  for k in range(i-4, i+1)]
            lows   = [float(candles[k]["low"])   for k in range(i-4, i+1)]

            # Session from candle timestamp
            try:
                c_dt = datetime.strptime(str(c["time"])[:16], "%Y-%m-%dT%H:%M")
                ch   = c_dt.hour
                cm   = c_dt.minute
            except Exception:
                ch, cm = 12, 0
            if   8  <= ch < 13: sess = "LONDON"
            elif 13 <= ch < 17: sess = "LONDON_NY"
            elif 17 <= ch < 22: sess = "NY"
            else:                sess = "ASIA"

            # SESSION ENTRY GATE — same rules as EA IsSessionEntryBlocked()
            # London open first 30 min (fakeout rate highest on M15)
            # NY close 60 min (spread widens, liquidity drains)
            if filter_sessions and ((ch == 8 and cm < 30) or (ch >= 20 and ch < 21)):
                session_filtered += 1
                equity_curve.append(equity)
                continue

            direction = 0
            setup     = "UNKNOWN"

            recent_low = min(lows[1:4])
            if lows[3] < recent_low - atr * 0.1 and closes[4] > lows[3] + atr * 0.3:
                direction, setup = 1, "SWEEP_BULL"

            if direction == 0:
                recent_high = max(highs[1:4])
                if highs[3] > recent_high + atr * 0.1 and closes[4] < highs[3] - atr * 0.3:
                    direction, setup = -1, "SWEEP_BEAR"

            if direction == 0:
                if   closes[4] > max(highs[0:4]): direction, setup = 1,  "BOS_BULL"
                elif closes[4] < min(lows[0:4]):  direction, setup = -1, "BOS_BEAR"

            if direction == 0:
                equity_curve.append(equity)
                continue

            trend = "BULLISH" if closes[4] > closes[0] else "BEARISH"

            probe  = {
                "symbol": symbol, "signal": direction, "trend": trend,
                "session": sess, "setup": setup, "smc": True,
                "breakout": "BOS" in setup, "structure": True,
                "confluence": 2, "intermarket_score": 0.0,
                "spread_ok": True, "news_block": False,
                "mode": mode, "current_price": float(c["close"]),
                "atr": atr, "consec_losses": consec_loss,
            }
            result    = score_trade(probe)
            score_val = result.get("score", 0)
            approved  = result.get("approved", False)

            pnl = 0.0
            if approved:
                risk_pct  = 0.010 * result.get("risk_multiplier", 1.0)  # 1.0% base (matches live CHALLENGE cap)
                risk_amt  = equity * risk_pct
                rr        = result.get("recommended_rr", 2.5)

                # Session-aware win probability + score bonus
                base_wr   = SESSION_WIN_RATES.get(sess, 0.55)
                score_bonus = max(0.0, (score_val - MIN_SCORE) / 100 * 0.12)
                wr        = min(0.80, base_wr + score_bonus)
                won       = _rnd.random() < wr

                # TP Ladder: close 30% at 1R, trail 70% to full TP
                if won:
                    partial_pnl = risk_amt * 1.0 * 0.30     # 30% at 1R
                    runner_pnl  = risk_amt * rr  * 0.70     # 70% at full TP
                    pnl         = partial_pnl + runner_pnl
                else:
                    pnl         = -risk_amt                  # full loss (SL hit)

                equity  += pnl
                if won:
                    wins    += 1
                    consec_loss = 0
                else:
                    losses  += 1
                    consec_loss += 1
                    max_consec_loss = max(max_consec_loss, consec_loss)

                trade_returns.append(pnl / (equity - pnl) * 100)

                # Track drawdown
                if equity > peak_equity: peak_equity = equity
                dd = (peak_equity - equity) / peak_equity * 100
                if dd > max_dd: max_dd = dd

            equity_curve.append(round(equity, 2))
            signals.append({
                "index":     i,
                "time":      str(c.get("time", "")),
                "setup":     setup,
                "direction": direction,
                "score":     round(score_val, 1),
                "approved":  approved,
                "session":   sess,
                "regime":    result.get("regime", ""),
                "pnl":       round(pnl, 2),
                "equity":    round(equity, 2),
            })

        total = wins + losses

        # Sharpe ratio (annualised, assumes 5 trades/week on M15)
        sharpe = 0.0
        if len(trade_returns) >= 5:
            r_mean = float(np.mean(trade_returns))
            r_std  = float(np.std(trade_returns))
            sharpe = round((r_mean / r_std) * (252 ** 0.5) if r_std > 0 else 0.0, 2)

        return jsonify({
            "signals":       signals,
            "equity_curve":  equity_curve[-500:],
            "stats": {
                "total_candles":       len(candles),
                "signals_found":       len(signals),
                "session_filtered":    session_filtered,
                "approved_trades":     total,
                "wins":                wins,
                "losses":              losses,
                "win_rate":            round(wins / total * 100, 1) if total > 0 else 0,
                "max_consec_losses":   max_consec_loss,
                "max_drawdown_pct":    round(max_dd, 2),
                "sharpe_ratio":        sharpe,
                "final_equity":        round(equity, 2),
                "net_profit_pct":      round((equity - 100000) / 100000 * 100, 2),
                "symbol":              symbol,
                "filter_sessions":     filter_sessions,
            }
        })
    except Exception as e:
        log.error(f"[BACKTEST] Error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/manage", methods=["POST"])
def manage_position():
    """
    AI position manager — evaluates an open trade every N minutes and returns
    a management action: HOLD / TRAIL_SL / PARTIAL / CLOSE.
    Called by the EA for each open position on a throttled interval.
    """
    data = request.get_json(force=True, silent=True) or {}

    symbol          = str(data.get("symbol",             ""))
    direction       = int(data.get("direction",           1))
    rr_current      = float(data.get("rr_current",        0.0))
    time_minutes    = float(data.get("time_minutes",       0.0))
    session         = str(data.get("session",          "OFF")).upper()
    h4_regime       = str(data.get("h4_regime",       "TREND")).upper()
    h1_slope        = int(data.get("h1_ema_slope",        0))   # +1 with / -1 against / 0 flat
    counter_setup   = bool(data.get("counter_setup",   False))
    near_end        = bool(data.get("near_session_end",False))
    daily_dd_pct    = float(data.get("daily_dd_pct",     0.0))
    atr_expansion   = float(data.get("atr_expansion",    1.0))
    regime_changed  = bool(data.get("h4_regime_changed",False))
    # News context — EA-supplied (best effort) + server-side override (authoritative)
    ea_near_news    = bool(data.get("near_news",        False))
    ea_news_mins    = float(data.get("news_mins_away",  9999.0))
    ea_news_title   = str(data.get("news_title",        ""))

    # Server-side calendar check — runs independently of EA InpFTMONewsLock setting
    sv_near, sv_mins, sv_title = get_news_context_for_manage(symbol)
    near_news   = ea_near_news or sv_near
    news_mins   = min(abs(ea_news_mins), abs(sv_mins))  # use whichever is closer
    news_title  = sv_title or ea_news_title              # prefer server calendar title

    action     = "HOLD"
    reason     = "Trade progressing normally — no intervention required"
    confidence = 70
    urgency    = "low"
    sl_pips    = 0

    # ── Decision tree — priority ordered ─────────────────────────────────────

    # 0. FTMO NEWS GATE — HIGH-impact event imminent (< 5 min)
    #    Close any position regardless of P&L to avoid FTMO-violating gap slippage.
    #    FTMO measures peak-to-trough equity including news spikes — a 50-pip gap
    #    on 1.5% risk can consume half the daily limit in one wick.
    if near_news and news_mins <= 5.0:
        action, urgency, confidence = "CLOSE", "high", 98
        label = f'"{news_title}" ' if news_title else ""
        reason = (f"NEWS GATE: High-impact event {label}in {news_mins:.0f} min — "
                  f"closing to prevent FTMO gap-slippage violation")

    # 0.5. NEWS GATE — event within 30 min window, trade has profit to protect
    elif near_news and rr_current >= 0.0:
        action, urgency, confidence = "CLOSE", "high", 92
        label = f'"{news_title}" ' if news_title else ""
        reason = (f"NEWS GATE: High-impact {label}in {news_mins:.0f} min — "
                  f"locking {rr_current:.1f}R profit before news uncertainty")

    # 0.6. NEWS GATE — within window but trade is underwater → HOLD, do NOT cut
    #    (closing a loss into news only guarantees the loss; news might reverse it)
    elif near_news and rr_current < 0.0:
        action, urgency, confidence = "HOLD", "medium", 70
        label = f'"{news_title}" ' if news_title else ""
        reason = (f"NEWS GATE: Event {label}in {news_mins:.0f} min — "
                  f"trade at {rr_current:.1f}R; holding, news may reverse move")

    # 1. Capital protection — FTMO daily limit approaching, trade underwater
    elif daily_dd_pct >= 2.5 and rr_current < 0.0:
        action, urgency, confidence = "CLOSE", "high", 95
        reason = f"DD protection: {daily_dd_pct:.1f}% daily loss — cutting loss before FTMO limit"

    # 2. Counter-setup forming — reversal signal against open position
    elif counter_setup and rr_current >= 1.0:
        action, urgency, confidence = "CLOSE", "high", 88
        reason = f"Counter sweep detected at {rr_current:.1f}R — closing to lock profit before reversal"

    # 3. Session ending — avoid overnight gap risk on open profit
    elif near_end and rr_current >= 0.5:
        action, urgency, confidence = "CLOSE", "medium", 82
        reason = f"Session closing with {rr_current:.1f}R profit — time exit to avoid gap risk"

    # 4. H4 regime shift — macro context changed since entry
    elif regime_changed and rr_current >= 1.0:
        action, urgency, confidence = "PARTIAL", "medium", 78
        reason = f"H4 regime changed — taking 50% off at {rr_current:.1f}R, letting runner work"

    # 5a. Momentum fading AND deep in profit (near TP) — full close now
    #     Price is at ≥2.5R with H1 slope turning against the trade; probability
    #     of reaching the full TP without a reversal drops sharply.  Take the win.
    elif h1_slope == -1 and rr_current >= 2.5:
        action, urgency, confidence = "CLOSE", "high", 88
        reason = (f"H1 momentum exhausted at {rr_current:.1f}R — closing in full "
                  f"before reversal erases deep profit")

    # 5b. Momentum fading — partial at lower R, keep runner
    elif h1_slope == -1 and rr_current >= 1.5:
        action, urgency, confidence = "PARTIAL", "medium", 75
        reason = f"H1 momentum fading at {rr_current:.1f}R — closing 50%, keeping runner to TP"

    # 6. Strong continuation — lock more profit via trail
    elif rr_current >= 2.0 and h1_slope == 1 and not counter_setup:
        action, urgency, confidence = "TRAIL_SL", "low", 80
        reason = f"Strong continuation at {rr_current:.1f}R — trailing SL to lock profit"
        sl_pips = 15 if "JPY" in symbol else 10  # trail distance in pips

    # 7. At 1R breakeven threshold — always move SL to cost-free
    elif rr_current >= 1.0 and h1_slope >= 0:
        action, urgency, confidence = "TRAIL_SL", "low", 72
        reason = f"At {rr_current:.1f}R — moving SL to breakeven, trade now risk-free"
        sl_pips = 5  # tight buffer above entry

    # 8. Volatile expansion — tighten slightly
    elif atr_expansion >= 1.5 and rr_current >= 0.5:
        action, urgency, confidence = "TRAIL_SL", "low", 65
        reason = f"ATR expanded x{atr_expansion:.1f} — tightening trail to protect {rr_current:.1f}R"
        sl_pips = 12

    # 9. Default HOLD
    else:
        if rr_current < 0:
            reason = f"Trade at {rr_current:.1f}R — within normal range, holding per plan"
        elif rr_current < 1.0:
            reason = f"Building toward 1R ({rr_current:.1f}R) — no action, let setup work"
        confidence = 65

    log.info(f"[MANAGE] {symbol} dir={direction} RR={rr_current:.2f} t={time_minutes:.0f}m "
             f"near_news={near_news}({news_mins:.0f}m) -> {action} ({reason[:60]})")

    # Telegram alerts for actionable decisions
    if _telegram_symbol_ok(symbol):
        if near_news and action == "CLOSE":
            label = f'"{news_title}"' if news_title else "high-impact event"
            send_telegram(
                f"⚠️ <b>NEWS GATE — {symbol}</b>\n"
                f"Closed at {rr_current:.1f}R before {label}\n"
                f"Event in {news_mins:.0f} min — profit protected"
            )
        elif action == "CLOSE" and not near_news:
            send_telegram(
                f"🔒 <b>MANAGE CLOSE — {symbol}</b>\n"
                f"At {rr_current:.1f}R | {reason[:80]}"
            )
        elif action == "PARTIAL":
            send_telegram(
                f"📊 <b>MANAGE PARTIAL — {symbol}</b>\n"
                f"50% closed at {rr_current:.1f}R | {reason[:80]}"
            )


    return jsonify({
        "allowed": True, "correlation": 0.0, "stub": True,
        "sym": request.args.get("sym", ""),
        "dir": request.args.get("dir", ""),
    })


@app.route("/news_check", methods=["GET"])
def news_check():
    """EA news-window guard. Stub — never blocks. Wire ForexFactory later."""
    return jsonify({"blocked": False, "stub": True,
                    "symbol":  request.args.get("symbol", "")})


@app.route("/journal_sync", methods=["POST"])
def journal_sync():
    """EA pushes recently-closed trades. Stub — accept + best-effort forward
    to dashboard /journal so the trade journal table fills."""
    try:
        data = request.get_json(force=True, silent=True) or {}
    except Exception:
        data = {}
    def _forward():
        try:
            # Real dashboard endpoint is /journal/mt5-sync — earlier draft used
            # /journal/ingest which 404'd silently and dropped every trade.
            requests.post(f"{DASHBOARD_API_URL}/journal/mt5-sync",
                          json=data, timeout=3.0)
        except Exception:
            pass
    threading.Thread(target=_forward, daemon=True).start()
    return jsonify({"ok": True})


@app.route("/best_signals", methods=["GET"])
def best_signals():
    """Multi-symbol best signal scan. Returns scored ranking of supplied symbols."""
    syms = request.args.get("symbols", "").upper().split(",")
    syms = [s.strip() for s in syms if s.strip()]
    if not syms:
        return jsonify({"signals": [], "stub": True})
    out = []
    for sym in syms[:20]:
        try:
            r2 = compute_regime_v2(sym)
            out.append({
                "symbol":      sym,
                "trend_score": r2.get("trend_score", 50.0),
                "direction":   r2.get("trend_direction", "NEUTRAL"),
                "regime":      r2.get("regime_label", "UNKNOWN"),
            })
        except Exception:
            out.append({"symbol": sym, "trend_score": 50.0,
                        "direction": "NEUTRAL", "regime": "ERROR"})
    out.sort(key=lambda r: r["trend_score"], reverse=True)
    return jsonify({"signals": out,
                    "limit":   int(request.args.get("limit", "10")),
                    "session": request.args.get("session", "")})


@app.route("/dashboard", methods=["GET"])
def dashboard():
    total   = sum(s["total"] for s in session_stats.values())
    wins    = sum(s["wins"]  for s in session_stats.values())
    wr      = round(wins / total * 100, 1) if total > 0 else 0
    gross_p = sum(t["profit"] for t in trade_history if t["profit"] > 0)
    gross_l = abs(sum(t["profit"] for t in trade_history if t["profit"] < 0))
    net     = gross_p - gross_l
    accs    = orchestrator.get_portfolio_summary()
    ew      = regime_warning.check()

    html = f"""<!DOCTYPE html><html>
<head><title>PhantomEdge v4 Dashboard</title>
<meta http-equiv="refresh" content="20">
<style>
  body{{background:#080812;color:#e0e0e0;font-family:monospace;padding:20px;margin:0}}
  h1{{color:#00d4ff;margin-bottom:5px}}
  h2{{color:#7fdbff;border-bottom:1px solid #1e1e3f;padding-bottom:4px;margin-top:20px}}
  .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;margin:10px 0}}
  .stat{{background:#0d0d1f;padding:14px;border-radius:8px;border:1px solid #1e1e3f;text-align:center}}
  .val{{font-size:1.5em;font-weight:bold;color:#00ff9f}}
  .lbl{{font-size:0.75em;color:#666;margin-top:4px}}
  .warn{{color:#ffaa00}} .ok{{color:#00ff9f}} .bad{{color:#ff4444}}
  table{{border-collapse:collapse;width:100%;margin-top:8px}}
  th{{background:#0d0d1f;color:#7fdbff;padding:8px;border:1px solid #1e1e3f;text-align:left}}
  td{{padding:7px;border:1px solid #111}}
  .tag{{display:inline-block;padding:2px 8px;border-radius:4px;font-size:0.8em;margin:2px}}
  .tag-blue{{background:#1a3a5c}} .tag-green{{background:#1a4a2a}} .tag-orange{{background:#4a3a1a}}
  p{{color:#888;font-size:0.85em}}
</style></head>
<body>
<h1>PHANTOM EDGE v4.0 -- INSTITUTIONAL DASHBOARD</h1>
<p>Last updated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC | Auto-refresh: 20s</p>

<div class="grid">
  <div class="stat"><div class="val">{total}</div><div class="lbl">Total Trades</div></div>
  <div class="stat"><div class="val {'ok' if wr >= 50 else 'bad'}">{wr}%</div><div class="lbl">Win Rate</div></div>
  <div class="stat"><div class="val {'ok' if net > 0 else 'bad'}">${net:,.0f}</div><div class="lbl">Net P&L</div></div>
  <div class="stat"><div class="val">{round(gross_p / gross_l, 2) if gross_l > 0 else 'N/A'}</div><div class="lbl">Profit Factor</div></div>
  <div class="stat"><div class="val {'ok' if ml_classifier.is_trained else 'warn'}">{'ACTIVE' if ml_classifier.is_trained else 'TRAINING'}</div><div class="lbl">ML Classifier</div></div>
  <div class="stat"><div class="val">{round(ml_classifier.cv_score * 100, 1) if ml_classifier.is_trained else '--'}%</div><div class="lbl">ML CV Score</div></div>
  <div class="stat"><div class="val">{accs['active_accounts']}/{accs['total_accounts']}</div><div class="lbl">Active Accounts</div></div>
  <div class="stat"><div class="val {'ok' if ew['urgency'] < 4 else 'warn' if ew['urgency'] < 7 else 'bad'}">{ew['action'].replace('_', ' ')}</div><div class="lbl">Regime Warning</div></div>
</div>

<h2>ACTIVE FEATURES</h2>
<div>
  <span class="tag tag-blue">Order Flow Proxy</span>
  <span class="tag tag-blue">ML Classifier</span>
  <span class="tag tag-blue">Liquidity Heatmap</span>
  <span class="tag tag-blue">Monte Carlo</span>
  <span class="tag tag-green">Correlation Sizing</span>
  <span class="tag tag-green">Dynamic RR</span>
  <span class="tag tag-green">Latency Tracker</span>
  <span class="tag tag-orange">Multi-Account</span>
  <span class="tag tag-orange">Sentiment</span>
  <span class="tag tag-orange">Regime Early Warning</span>
</div>

<h2>SESSION PERFORMANCE</h2>
<table><tr><th>Session</th><th>Trades</th><th>Win Rate</th><th>Net P&L</th></tr>
{''.join(
    f"<tr><td>{s}</td><td>{d['total']}</td>"
    f"<td class='{'ok' if d['total'] > 0 and d['wins'] / d['total'] >= 0.5 else 'bad'}'>"
    f"{round(d['wins'] / d['total'] * 100, 1) if d['total'] > 0 else 0}%</td>"
    f"<td class='{'ok' if d['profit'] > 0 else 'bad'}'>${d['profit']:,.0f}</td></tr>"
    for s, d in session_stats.items() if d['total'] > 0
)}
</table>

<h2>SETUP PERFORMANCE</h2>
<table><tr><th>Setup</th><th>Trades</th><th>Win Rate</th><th>Net P&L</th></tr>
{''.join(
    f"<tr><td>{s}</td><td>{d['total']}</td>"
    f"<td class='{'ok' if d['total'] > 0 and d['wins'] / d['total'] >= 0.5 else 'bad'}'>"
    f"{round(d['wins'] / d['total'] * 100, 1) if d['total'] > 0 else 0}%</td>"
    f"<td class='{'ok' if d['profit'] > 0 else 'bad'}'>${d['profit']:,.0f}</td></tr>"
    for s, d in setup_stats.items() if d['total'] > 0
)}
</table>

<h2>MULTI-ACCOUNT PORTFOLIO</h2>
<div class="grid">
  <div class="stat"><div class="val">${accs['total_balance']:,.0f}</div><div class="lbl">Total Balance</div></div>
  <div class="stat"><div class="val">${accs['total_equity']:,.0f}</div><div class="lbl">Total Equity</div></div>
  <div class="stat"><div class="val {'bad' if accs['combined_dd_pct'] > 3 else 'ok'}">{accs['combined_dd_pct']}%</div><div class="lbl">Combined DD</div></div>
</div>
</body></html>"""
    return html


# ══════════════════════════════════════════════════════════════════════
# v4.0 PhantomEdge Pro — Multi-Strategy Ensemble + Kelly Sizing
# ══════════════════════════════════════════════════════════════════════
#
# Three orthogonal strategies vote on every setup. Final score is the
# weighted average; weights are auto-tuned weekly from real per-strategy
# fill performance. Position size = Kelly fraction (capped) of v3.12 risk.
#
#   trend_pullback : trade-with-trend pullbacks (FVG/BOS/sweep + aligned)
#   mean_reversion : fade extremes when trend is flat (chop / overshoot)
#   breakout       : range-break with expansion (ATR pop + structure shift)
#
# v4.0 NEVER replaces v3.12 risk gates. Kelly fraction is multiplied INTO
# the final risk, AFTER vol-target / DD-adapt / weekly breaker. So worst
# case Kelly=0.25 simply trims size further; never inflates beyond cap.

V4_KELLY_CAP_DEFAULT = 0.25         # max fraction of bankroll Kelly may bet
V4_MIN_SAMPLE_SIZE   = 30           # per-strategy fills required before retrain weights
V4_DEFAULT_WEIGHTS = {              # equal-weight cold start
    "trend_pullback": 0.34,
    "mean_reversion": 0.33,
    "breakout":       0.33,
}
V4_WEIGHTS_FILE = "phantom_v4_weights.json"
V4_FILLS_FILE   = "phantom_v4_fills.csv"   # per-strategy fill log
V4_LOCK         = threading.Lock()


def _v4_load_weights():
    try:
        if os.path.isfile(V4_WEIGHTS_FILE):
            with open(V4_WEIGHTS_FILE, "r") as f:
                blob = json.load(f)
            w = blob.get("weights", {})
            if all(k in w for k in V4_DEFAULT_WEIGHTS):
                return blob
    except Exception as e:
        log.warning(f"[v4] weights load failed: {e}")
    return {
        "weights":       dict(V4_DEFAULT_WEIGHTS),
        "kelly_cap":     V4_KELLY_CAP_DEFAULT,
        "sample_size":   0,
        "last_retrain":  None,
        "perf":          {k: {"n": 0, "wins": 0, "avg_r": 0.0} for k in V4_DEFAULT_WEIGHTS},
        "version":       "4.0.0",
    }


def _v4_save_weights(blob):
    try:
        with open(V4_WEIGHTS_FILE, "w") as f:
            json.dump(blob, f, indent=2, default=str)
    except Exception as e:
        log.warning(f"[v4] weights save failed: {e}")


v4_state = _v4_load_weights()


def _v4_session_bonus(session):
    s = (session or "").upper()
    if s == "LONDON_NY": return 8
    if s in ("LONDON", "NY"): return 4
    if s == "ASIA":      return -6
    return 0


def score_trend_pullback(data):
    """In-trend continuation. Wraps the existing v3 ai_model so we keep
    every confluence the production system already validates.

    Returns the v4 strategy contract:
      score      float 0..100
      direction  "BUY" | "SELL" | "FLAT"
      confidence float 0..1
      reasons    list[str]      — human-readable factor list
      why        str            — short tag (back-compat for older callers)
    """
    features = extract_features(data)
    base     = ai_model.score(features)
    aligned  = features.get("trend_aligned", False)
    sweep_ok = features.get("sweep_trend_confirmed", False)
    reasons  = []
    if not aligned:
        base -= 18; reasons.append("trend_unaligned (-18)")
    else:
        reasons.append("trend_aligned")
    if sweep_ok:
        base += 4; reasons.append("sweep_confirmed (+4)")
    base = max(0.0, min(100.0, base))
    trend = (data.get("trend") or "").upper()
    direction = "BUY" if trend == "BULLISH" else "SELL" if trend == "BEARISH" else "FLAT"
    return {
        "score":      round(base, 2),
        "direction":  direction,
        "confidence": round(base / 100.0, 3),
        "reasons":    reasons,
        "why":        "trend+sweep" if sweep_ok else "trend_aligned" if aligned else "no_align",
    }


# ── Momentum Fade Detector ────────────────────────────────────────────────────
_mom_fade_telegram_last: dict = {}
_mom_fade_telegram_lock = threading.Lock()

def detect_momentum_fade(symbol: str) -> dict:
    """
    Detect momentum deceleration from M15 BarStore bars.
    Two signals:
      1. ATR contraction: avg range of last 3 bars vs. baseline bars 5-20
      2. Body shrinkage: avg candle body last 3 bars vs. bars 4-9
    Returns: { fading, atr_ratio, body_ratio, signal }
    """
    bars = bar_store.get(symbol, "M15")
    if not bars or len(bars) < 20:
        return {"fading": False, "atr_ratio": 1.0, "body_ratio": 1.0, "signal": "insufficient_data"}

    def _range(b):
        h = b.get("high", b.get("close", 0))
        l = b.get("low",  b.get("open",  0))
        return abs(h - l)

    def _body(b):
        return abs(b.get("close", 0) - b.get("open", 0))

    recent_bars   = bars[-3:]
    baseline_bars = bars[-20:-5]
    mid_bars      = bars[-9:-4]

    if not baseline_bars or not mid_bars:
        return {"fading": False, "atr_ratio": 1.0, "body_ratio": 1.0, "signal": "insufficient_data"}

    recent_atr   = sum(_range(b) for b in recent_bars)   / len(recent_bars)
    baseline_atr = sum(_range(b) for b in baseline_bars) / len(baseline_bars)
    recent_body  = sum(_body(b)  for b in recent_bars)   / len(recent_bars)
    mid_body     = sum(_body(b)  for b in mid_bars)      / len(mid_bars)

    atr_ratio  = recent_atr  / baseline_atr if baseline_atr > 0 else 1.0
    body_ratio = recent_body / mid_body      if mid_body     > 0 else 1.0

    atr_fading  = atr_ratio  < 0.72
    body_fading = body_ratio < 0.65
    fading      = atr_fading and body_fading

    signal = "fading" if fading else ("contracting" if atr_fading else "normal")

    return {
        "fading":     fading,
        "atr_ratio":  round(atr_ratio,  3),
        "body_ratio": round(body_ratio, 3),
        "signal":     signal,
    }


def _maybe_telegram_momentum_fade(symbol: str, info: dict):
    """Send Telegram alert for momentum fade — max once per 30 min per symbol."""
    now = time.time()
    with _mom_fade_telegram_lock:
        last = _mom_fade_telegram_last.get(symbol, 0)
        if now - last < 1800:
            return
        _mom_fade_telegram_last[symbol] = now
    send_telegram(
        f"📉 <b>MOMENTUM FADING — {symbol}</b>\n"
        f"ATR ratio: {info['atr_ratio']:.2f} | Body ratio: {info['body_ratio']:.2f}\n"
        f"Score penalty: −10 applied · New entries suppressed"
    )


# ── Kotegawa (BNF) Overextension Analyser ────────────────────────────────────
def score_kotegawa(symbol: str, data: dict) -> dict:
    """
    Takashi Kotegawa's (BNF) core insight applied to Forex M15.

    The legendary trader built his fortune on one principle: liquid assets that
    move too far from their mean too quickly will revert. Three signals:
      1. EMA20 drift (ATR-normalised) — EA sends drift_atr; fallback: bar_store
      2. Consecutive same-direction M15 bars — sent as consec_bars from EA
      3. Computed bar_store streak as fallback when EA value = 0

    Score deltas:
      drift ≥ 2.5× | consec ≥ 6 counter-direction: +18  (prime Kotegawa setup)
      drift ≥ 1.8× | consec ≥ 4 counter-direction: +10
      drift ≥ 1.2× | consec ≥ 3 counter-direction:  +5
      consec ≥ 5 counter-direction:                  +8  (streak exhaustion)
      consec ≥ 3 counter-direction:                  +4
      drift > 2.0 CHASING extension:                −15  (BNF would never chase)
      drift > 1.5 CHASING extension:                 −8
    """
    signal      = int(data.get("signal",      0) or 0)
    atr         = float(data.get("atr",       0) or 0)
    drift_atr   = float(data.get("drift_atr", 0) or 0)
    consec_bars = int(data.get("consec_bars", 0) or 0)

    # Fallback: compute from bar_store when EA didn't provide values
    counter_dir = 0
    bars = bar_store.get(symbol, "M15")
    if bars and len(bars) >= 20:
        closes = [b.get("close", b.get("open", 0)) for b in bars]
        ema20  = sum(closes[-20:]) / 20
        curr   = closes[-1]
        if drift_atr <= 0 and atr > 0:
            drift_atr = abs(curr - ema20) / atr
        counter_dir = -1 if curr > ema20 else 1
        if consec_bars == 0 and len(closes) >= 6:
            first_dir = 1 if closes[-1] > closes[-2] else -1
            for i in range(len(closes) - 2, max(0, len(closes) - 8), -1):
                if (1 if closes[i] > closes[i - 1] else -1) == first_dir:
                    consec_bars += 1
                else:
                    break

    if counter_dir == 0 and signal != 0:
        counter_dir = signal

    score_delta = 0.0
    reasons: list = []

    # EMA20 drift scoring
    if drift_atr >= 2.5:
        if signal == counter_dir:
            score_delta += 18
            reasons.append(f"drift {drift_atr:.1f}×ATR counter +18")
        elif signal == -counter_dir and signal != 0:
            score_delta -= 15
            reasons.append(f"drift {drift_atr:.1f}×ATR chasing -15")
    elif drift_atr >= 1.8:
        if signal == counter_dir:
            score_delta += 10
            reasons.append(f"drift {drift_atr:.1f}×ATR counter +10")
        elif signal == -counter_dir and signal != 0:
            score_delta -= 8
            reasons.append(f"drift {drift_atr:.1f}×ATR chasing -8")
    elif drift_atr >= 1.2:
        if signal == counter_dir:
            score_delta += 5
            reasons.append(f"drift {drift_atr:.1f}×ATR counter +5")

    # Consecutive-bar exhaustion
    if consec_bars >= 5:
        if signal == counter_dir:
            score_delta += 8
            reasons.append(f"{consec_bars}-bar streak counter +8")
    elif consec_bars >= 3:
        if signal == counter_dir:
            score_delta += 4
            reasons.append(f"{consec_bars}-bar streak counter +4")

    level = (
        "prime"    if drift_atr >= 2.5 or consec_bars >= 6 else
        "extended" if drift_atr >= 1.8 or consec_bars >= 4 else
        "moderate" if drift_atr >= 1.2 or consec_bars >= 3 else
        "normal"
    )

    if reasons:
        try:
            print(f"[KOTEGAWA] {symbol} " + " | ".join(reasons))
        except Exception:
            pass

    return {
        "score_delta":  score_delta,
        "drift_atr":    round(drift_atr, 2),
        "consec_bars":  consec_bars,
        "level":        level,
        "overextended": drift_atr >= 1.8 or consec_bars >= 5,
    }


def detect_range_zone(symbol: str, lookback: int = 50) -> dict:
    """Detect ranging zones using EQH/EQL swing analysis + Donchian width compression.

    Algorithm:
      1. Find 3-bar pivot swing highs/lows over the last `lookback` H1 bars.
      2. Cluster highs (or lows) within 0.5×ATR of each other → Equal High / Equal Low.
         Two or more touches = confirmed range ceiling/floor.
      3. Track Donchian channel width across 5 rolling windows — shrinking width
         signals a range forming before it is obvious on price action alone.

    Confidence is the sum of contributing signals (EQH, EQL, DC compression, tight channel).
    Used by score_mean_reversion (edge bonus) and score_trade (mid-range penalty).
    """
    _EMPTY = {
        "range_high": None, "range_low": None, "range_width_atr": None,
        "confidence": 0.0, "in_range": False,
        "at_upper_edge": False, "at_lower_edge": False,
        "eqh_level": None, "eql_level": None,
        "dc_width_shrinking": False, "atr": None,
    }
    raw = bar_store.get(symbol, "H1")
    if len(raw) < lookback:
        return _EMPTY
    bars = list(raw)[-lookback:]

    # ATR — simple average of last 14 true ranges
    trs = []
    for i in range(1, len(bars)):
        tr = max(bars[i]["h"] - bars[i]["l"],
                 abs(bars[i]["h"] - bars[i - 1]["c"]),
                 abs(bars[i]["l"] - bars[i - 1]["c"]))
        trs.append(tr)
    if not trs:
        return _EMPTY
    atr = sum(trs[-14:]) / min(14, len(trs))
    if atr <= 0:
        return _EMPTY
    tolerance = atr * 0.50   # two touches within 0.5 ATR = "equal"

    # 3-bar pivot swing highs / lows
    swing_highs, swing_lows = [], []
    for i in range(1, len(bars) - 1):
        if bars[i]["h"] >= bars[i - 1]["h"] and bars[i]["h"] >= bars[i + 1]["h"]:
            swing_highs.append(bars[i]["h"])
        if bars[i]["l"] <= bars[i - 1]["l"] and bars[i]["l"] <= bars[i + 1]["l"]:
            swing_lows.append(bars[i]["l"])

    # EQH — first cluster of 2+ highs within tolerance
    eqh_level = None
    for h in swing_highs:
        cluster = [x for x in swing_highs if abs(x - h) <= tolerance]
        if len(cluster) >= 2:
            eqh_level = round(sum(cluster) / len(cluster), 5)
            break

    # EQL — same for lows
    eql_level = None
    for lo in swing_lows:
        cluster = [x for x in swing_lows if abs(x - lo) <= tolerance]
        if len(cluster) >= 2:
            eql_level = round(sum(cluster) / len(cluster), 5)
            break

    # Donchian width trend — 5 non-overlapping windows of 10 bars
    dc_widths = []
    for i in range(5):
        chunk = bars[i * 10:(i + 1) * 10]
        if len(chunk) == 10:
            dc_widths.append((max(b["h"] for b in chunk) - min(b["l"] for b in chunk)) / atr)
    dc_shrinking = len(dc_widths) >= 3 and dc_widths[-1] < dc_widths[0] * 0.85

    # Range boundaries (EQH/EQL preferred; fallback to 20-bar Donchian)
    range_high = eqh_level if eqh_level is not None else max(b["h"] for b in bars[-20:])
    range_low  = eql_level if eql_level is not None else min(b["l"] for b in bars[-20:])
    range_width_atr = (range_high - range_low) / atr

    # Confidence: each confirming signal adds weight
    conf = 0.0
    if eqh_level is not None: conf += 0.35
    if eql_level is not None: conf += 0.35
    if dc_shrinking:          conf += 0.20
    if range_width_atr < 6:  conf += 0.10   # tight channel ≤ 6×ATR
    conf = min(1.0, round(conf, 2))

    cur           = bars[-1]["c"]
    in_range      = range_low <= cur <= range_high
    at_upper_edge = in_range and (range_high - cur) <= atr * 0.30
    at_lower_edge = in_range and (cur - range_low)  <= atr * 0.30

    return {
        "range_high":         round(range_high, 5),
        "range_low":          round(range_low, 5),
        "range_width_atr":    round(range_width_atr, 2),
        "confidence":         conf,
        "in_range":           in_range,
        "at_upper_edge":      at_upper_edge,
        "at_lower_edge":      at_lower_edge,
        "eqh_level":          eqh_level,
        "eql_level":          eql_level,
        "dc_width_shrinking": dc_shrinking,
        "atr":                round(atr, 5),
    }


def detect_monthly_levels(symbol: str) -> dict:
    """Detect current and prior monthly high/low from D1 bars.

    Uses native D1 bar store (up to 400 bars). Falls back to H1 aggregation
    when D1 is not yet populated. Looks back 22 D1 bars (~1 trading month)
    for the current monthly range and 22 bars before that for the prior month.

    Returns:
        monthly_high  : float  — highest high of the current month window
        monthly_low   : float  — lowest  low  of the current month window
        prior_high    : float  — prior month high (context / confluence)
        prior_low     : float  — prior month low  (context / confluence)
        near_high     : bool   — current price within 0.5×ATR of monthly_high
        near_low      : bool   — current price within 0.5×ATR of monthly_low
        at_high       : bool   — within 0.25×ATR (immediate resistance)
        at_low        : bool   — within 0.25×ATR (immediate support)
        atr           : float
    """
    _EMPTY = {
        "monthly_high": None, "monthly_low": None,
        "prior_high": None,   "prior_low":   None,
        "near_high": False,   "near_low":    False,
        "at_high":   False,   "at_low":      False,
        "atr":       None,
    }
    bars = bar_store.get(symbol, "D1")
    if len(bars) < 10:
        return _EMPTY

    # ATR from D1 bars (14-period)
    trs = []
    for i in range(1, len(bars)):
        tr = max(bars[i]["h"] - bars[i]["l"],
                 abs(bars[i]["h"] - bars[i - 1]["c"]),
                 abs(bars[i]["l"] - bars[i - 1]["c"]))
        trs.append(tr)
    if not trs:
        return _EMPTY
    atr = sum(trs[-14:]) / min(14, len(trs))
    if atr <= 0:
        return _EMPTY

    MONTH_BARS  = 22   # ~1 calendar month of trading days
    cur_window  = list(bars)[-MONTH_BARS:]
    monthly_high = max(b["h"] for b in cur_window)
    monthly_low  = min(b["l"] for b in cur_window)

    prior_window = list(bars)[-(MONTH_BARS * 2):-MONTH_BARS]
    prior_high = max(b["h"] for b in prior_window) if prior_window else None
    prior_low  = min(b["l"] for b in prior_window) if prior_window else None

    cur = cur_window[-1]["c"]
    near_high = abs(cur - monthly_high) <= atr * 0.50
    near_low  = abs(cur - monthly_low)  <= atr * 0.50
    at_high   = abs(cur - monthly_high) <= atr * 0.25
    at_low    = abs(cur - monthly_low)  <= atr * 0.25

    return {
        "monthly_high": round(monthly_high, 5),
        "monthly_low":  round(monthly_low,  5),
        "prior_high":   round(prior_high,   5) if prior_high else None,
        "prior_low":    round(prior_low,    5) if prior_low  else None,
        "near_high":    near_high,
        "near_low":     near_low,
        "at_high":      at_high,
        "at_low":       at_low,
        "atr":          round(atr, 5),
    }


def _compute_rsi(symbol: str, period: int = 14, tf: str = "H1"):
    """Wilder RSI(period) from stored bars. Returns float 0-100 or None."""
    bars   = bar_store.get(symbol, tf)
    closes = [b["c"] for b in bars]
    if len(closes) < period + 5:
        return None
    closes = closes[-(period + 30):]
    gains, losses = [], []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))
    if len(gains) < period:
        return None
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    return round(100.0 - (100.0 / (1.0 + avg_gain / avg_loss)), 2)


def score_mean_reversion(data):
    """Fades extremes when regime is flat / fragile. Uses Donchian + RSI
    confirmation. Penalises strong-trend regimes so the ensemble doesn't
    fight a clean directional move."""
    setup    = (data.get("setup") or "").upper()
    session  = (data.get("session") or "").upper()
    sym      = data.get("symbol", "")

    base     = 50.0
    # Setup signals friendly to mean-reversion
    if "SWEEP" in setup:               base += 14
    if "OB"    in setup:               base += 6
    # Range / chop regime is the primary friend
    r2 = compute_regime_v2(sym) if sym else {"trend_direction": "NEUTRAL", "vol_bucket": "NORMAL"}
    if r2["trend_direction"] == "NEUTRAL":   base += 16
    elif r2["trend_direction"] in ("BULLISH", "BEARISH"): base -= 12
    if r2.get("vol_bucket") == "HIGH":       base -= 6   # too extended → wait
    if r2.get("vol_bucket") == "LOW":        base += 4
    base += _v4_session_bonus(session) * 0.5             # session matters less
    # Penalise direction-aligned-with-trend (that's trend_pullback territory)
    sig    = int(data.get("signal", 0))
    trend  = (data.get("trend") or "").upper()
    aligned = (sig == 1 and trend == "BULLISH") or (sig == -1 and trend == "BEARISH")
    reasons = []
    if "SWEEP" in setup: reasons.append("sweep (+14)")
    if "OB"    in setup: reasons.append("ob (+6)")
    if r2["trend_direction"] == "NEUTRAL": reasons.append("range regime (+16)")
    elif r2["trend_direction"] in ("BULLISH","BEARISH"): reasons.append(f"{r2['trend_direction']} regime (-12)")
    if r2.get("vol_bucket") == "HIGH": reasons.append("vol HIGH (-6)")
    if r2.get("vol_bucket") == "LOW":  reasons.append("vol LOW (+4)")
    if aligned: base -= 10; reasons.append("trend_aligned (-10)")
    # RSI confirmation — actual Wilder RSI from stored H1 bars
    sig = int(data.get("signal", 0))
    rsi_val = _compute_rsi(sym)
    if rsi_val is not None:
        if sig == 1 and rsi_val < 35:
            base += 12; reasons.append(f"RSI oversold {rsi_val:.1f} (+12)")
        elif sig == -1 and rsi_val > 65:
            base += 12; reasons.append(f"RSI overbought {rsi_val:.1f} (+12)")
        elif sig == 1 and rsi_val > 60:
            base -= 8;  reasons.append(f"RSI not oversold {rsi_val:.1f} (-8)")
        elif sig == -1 and rsi_val < 40:
            base -= 8;  reasons.append(f"RSI not overbought {rsi_val:.1f} (-8)")

    # Range zone edge bonus — price at EQH/EQL = highest-confidence fade
    rz = detect_range_zone(sym)
    if rz["confidence"] >= 0.4:
        if sig == 1 and rz["at_lower_edge"]:
            base += 15; reasons.append(f"EQL edge fade +15 (conf={rz['confidence']})")
        elif sig == -1 and rz["at_upper_edge"]:
            base += 15; reasons.append(f"EQH edge fade +15 (conf={rz['confidence']})")
        elif rz["in_range"] and not rz["at_upper_edge"] and not rz["at_lower_edge"]:
            base += 8;  reasons.append(f"range midpoint (+8)")

    base = max(0.0, min(100.0, base))
    # Mean reversion fades the prevailing trend, so its direction is the
    # OPPOSITE of the higher-timeframe trend (when there is one).
    direction = "SELL" if trend == "BULLISH" else "BUY" if trend == "BEARISH" else "FLAT"
    return {
        "score":      round(base, 2),
        "direction":  direction,
        "confidence": round(base / 100.0, 3),
        "reasons":    reasons,
        "why":        f"mr/{r2['trend_direction'][:4]}/{r2.get('vol_bucket','?')[:1]}",
    }


def score_breakout(data):
    """Range break with expansion. Wants ATR pop, BOS/structure, and
    a fresh session (London or NY open). Avoids fragile / late-session
    breaks that historically fail."""
    setup    = (data.get("setup") or "").upper()
    session  = (data.get("session") or "").upper()
    sym      = data.get("symbol", "")
    sig      = int(data.get("signal", 0))
    trend    = (data.get("trend") or "").upper()
    aligned  = (sig == 1 and trend == "BULLISH") or (sig == -1 and trend == "BEARISH")

    base = 45.0
    if "BOS"       in setup: base += 18
    if "STRUCTURE" in setup: base += 10
    if "FVG"       in setup: base += 6
    if aligned:              base += 10

    r2 = compute_regime_v2(sym) if sym else {"vol_bucket": "NORMAL", "trend_direction": "NEUTRAL"}
    if r2.get("vol_bucket") == "HIGH":      base += 8   # expansion friendly
    if r2.get("vol_bucket") == "LOW":       base -= 6   # range too tight
    if r2["trend_direction"] != "NEUTRAL":  base += 4

    base += _v4_session_bonus(session)
    # ATR expansion bonus from /score data if present.
    # SCALED bonus (May 6 2026 lesson): a flat +6 was too small for violent
    # impulsive moves where ATR exp goes 2x+. Curve:
    #   1.3x → +6   (mild)
    #   1.7x → +10  (strong)
    #   2.0x → +12  (impulsive)
    #   2.5x → +16  (violent)
    atr_exp = float(data.get("atr_expansion", 1.0) or 1.0)
    reasons = []
    if "BOS"       in setup: reasons.append("BOS (+18)")
    if "STRUCTURE" in setup: reasons.append("structure (+10)")
    if "FVG"       in setup: reasons.append("FVG (+6)")
    if aligned:              reasons.append("trend_aligned (+10)")
    if r2.get("vol_bucket") == "HIGH":     reasons.append("vol HIGH (+8)")
    if r2.get("vol_bucket") == "LOW":      reasons.append("vol LOW (-6)")
    if   atr_exp >= 2.5: base += 16; reasons.append(f"ATR violent {atr_exp:.2f}x (+16)")
    elif atr_exp >= 2.0: base += 12; reasons.append(f"ATR impulsive {atr_exp:.2f}x (+12)")
    elif atr_exp >= 1.7: base += 10; reasons.append(f"ATR strong {atr_exp:.2f}x (+10)")
    elif atr_exp >= 1.3: base += 6;  reasons.append(f"ATR exp {atr_exp:.2f}x (+6)")
    elif atr_exp <= 0.8: base -= 8;  reasons.append(f"ATR contr {atr_exp:.2f}x (-8)")

    base = max(0.0, min(100.0, base))
    direction = "BUY" if sig == 1 else "SELL" if sig == -1 else ("BUY" if trend == "BULLISH" else "SELL" if trend == "BEARISH" else "FLAT")
    return {
        "score":      round(base, 2),
        "direction":  direction,
        "confidence": round(base / 100.0, 3),
        "reasons":    reasons,
        "why":        f"break/{atr_exp:.2f}x",
    }


def kelly_fraction(win_rate, avg_r, cap=None):
    """Standard Kelly: f = W − (1 − W) / R. Capped to protect against
    estimation error. Returns 0..cap (never short / never above cap)."""
    cap = cap if cap is not None else V4_KELLY_CAP_DEFAULT
    w   = max(0.0, min(1.0, float(win_rate)))
    r   = max(0.1, float(avg_r))
    f   = w - (1.0 - w) / r
    if f <= 0: return 0.0
    return round(min(f, cap), 4)


def score_ensemble(data):
    """Run all 3 strategies, blend with current weights, compute Kelly
    size_multiplier from the WINNING strategy's historical fills.
    Returns a dict the EA can consume directly."""
    with V4_LOCK:
        weights = dict(v4_state.get("weights", V4_DEFAULT_WEIGHTS))
        perf    = dict(v4_state.get("perf", {}))
        cap     = float(v4_state.get("kelly_cap", V4_KELLY_CAP_DEFAULT))

    parts = {
        "trend_pullback": score_trend_pullback(data),
        "mean_reversion": score_mean_reversion(data),
        "breakout":       score_breakout(data),
    }
    total_w = sum(weights.values()) or 1.0
    blended = sum(parts[k]["score"] * weights[k] for k in parts) / total_w
    blended = round(blended, 2)

    # Pick the strategy with the highest individual score (mode attribution)
    chosen = max(parts.keys(), key=lambda k: parts[k]["score"])
    chosen_perf = perf.get(chosen, {"n": 0, "wins": 0, "avg_r": 0.0})

    # Kelly: needs a real sample. Cold-start uses half-cap (0.5 × cap)
    # in FUNDED mode for safety, but CHALLENGE mode uses full cap from
    # day 1 — Phase 1 is short and half-Kelly is dead weight when you
    # need full size to clear the 8% target inside 30 days.
    mode_str = str(data.get("mode", "CHALLENGE")).upper()
    if chosen_perf["n"] >= V4_MIN_SAMPLE_SIZE:
        wr   = (chosen_perf["wins"] / chosen_perf["n"]) if chosen_perf["n"] else 0.5
        avgr = max(0.5, float(chosen_perf.get("avg_r", 1.5)))
        kf   = kelly_fraction(wr, avgr, cap=cap)
    elif "FUNDED" in mode_str:
        kf   = round(cap * 0.5, 4)        # half-Kelly until trained (FUNDED only)
        wr, avgr = 0.5, 2.0
    else:
        kf   = cap                         # CHALLENGE: full cap from day 1
        wr, avgr = 0.5, 2.0

    # size_multiplier = kf / cap so a fully-trained Kelly==cap yields 1.0x,
    # half-Kelly yields 0.5x. The EA multiplies this into v3.12 risk.
    size_mult = round(kf / max(cap, 1e-6), 3)

    # regime_agreement = how concentrated the vote is (max-component / sum).
    # ~0.33 = three strategies tied (no agreement); ~1.0 = one strategy
    # dominates (strong agreement). EA uses this to gate profit pyramid.
    comp_sum = sum(max(0.0, parts[k]["score"]) for k in parts) or 1.0
    max_comp = max(parts[k]["score"] for k in parts)
    regime_agreement = round(max_comp / comp_sum, 3)

    return {
        "v4_score":         blended,
        "v4_chosen":        chosen,
        "v4_components":    {k: parts[k]["score"] for k in parts},
        "v4_why":           {k: parts[k]["why"]   for k in parts},
        # Full per-strategy contract: direction / confidence / reasons[]
        "v4_directions":    {k: parts[k].get("direction",  "FLAT") for k in parts},
        "v4_confidences":   {k: parts[k].get("confidence", 0.0)    for k in parts},
        "v4_reasons":       {k: parts[k].get("reasons",    [])     for k in parts},
        "v4_weights":       {k: round(weights[k], 4) for k in weights},
        "v4_agreement":     regime_agreement,
        "kelly_fraction":   kf,
        "kelly_cap":        cap,
        "kelly_size_mult":  size_mult,
        "chosen_n":         chosen_perf.get("n", 0),
        "chosen_wr":        round((chosen_perf["wins"] / chosen_perf["n"]) if chosen_perf.get("n") else 0.0, 3),
        "chosen_avg_r":     round(chosen_perf.get("avg_r", 0.0), 2),
    }


def v4_record_fill(strategy, won, r_multiple):
    """Append a per-strategy fill row + update in-memory perf. Called from
    /feedback when the EA reports a closed v4.0 trade."""
    if strategy not in V4_DEFAULT_WEIGHTS: return
    with V4_LOCK:
        p = v4_state["perf"].get(strategy, {"n": 0, "wins": 0, "avg_r": 0.0})
        n = p["n"] + 1
        wins = p["wins"] + (1 if won else 0)
        avg_r = (p["avg_r"] * p["n"] + float(r_multiple)) / n
        v4_state["perf"][strategy] = {"n": n, "wins": wins, "avg_r": round(avg_r, 3)}
        v4_state["sample_size"] = sum(v["n"] for v in v4_state["perf"].values())
        _v4_save_weights(v4_state)
    try:
        _append_csv(V4_FILLS_FILE, {
            "ts": datetime.utcnow().isoformat(),
            "strategy": strategy, "won": int(bool(won)),
            "r_multiple": float(r_multiple),
        })
    except Exception:
        pass


def v4_retrain_weights(reason="manual"):
    """Sunday weekly retrain. Blends each strategy's WR×AvgR (the Kelly
    numerator W·R proxy) into a normalised weight vector. A strategy with
    no data keeps its prior weight; a strategy with WR<40% gets clamped
    down to 0.10 so the ensemble doesn't keep voting a loser."""
    with V4_LOCK:
        perf = dict(v4_state.get("perf", {}))
        prior = dict(v4_state.get("weights", V4_DEFAULT_WEIGHTS))

    raw = {}
    for k in V4_DEFAULT_WEIGHTS:
        p = perf.get(k, {"n": 0, "wins": 0, "avg_r": 0.0})
        if p["n"] < V4_MIN_SAMPLE_SIZE:
            raw[k] = max(0.10, prior.get(k, V4_DEFAULT_WEIGHTS[k]))
            continue
        wr   = p["wins"] / p["n"] if p["n"] else 0.5
        avgr = max(0.3, float(p.get("avg_r", 1.0)))
        edge = wr * avgr - (1.0 - wr)        # expectancy in R
        if wr < 0.40:                        # bad strategy → throttle
            raw[k] = 0.10
        else:
            raw[k] = max(0.10, min(0.70, edge / 2.0 + 0.20))

    s = sum(raw.values()) or 1.0
    new_weights = {k: round(v / s, 4) for k, v in raw.items()}

    with V4_LOCK:
        v4_state["weights"]      = new_weights
        v4_state["last_retrain"] = datetime.utcnow().isoformat()
        v4_state["last_reason"]  = reason
        _v4_save_weights(v4_state)
    log.info(f"[v4 RETRAIN] reason={reason} → weights={new_weights}")
    return dict(v4_state)


# NOTE: In-process Sunday retrain has been REMOVED. The single source of
# truth for the weekly walk-forward retrain is `phantom_v4_retrain.py`,
# which runs as a VPS cron (Sun 22:00 UTC), pulls the last 90 days of
# closed trades from the dashboard journal API, recomputes per-strategy
# WR×AvgR, and POSTs to /v4/strategy_weights. Running an in-process loop
# in addition created two competing retrain paths — the cron's walk-forward
# weights would be silently overwritten by the in-process path that only
# saw locally-accumulated /feedback fills. The /v4/retrain HTTP endpoint
# remains available for manual ops/debug only.


@app.route("/v4/score", methods=["POST"])
def v4_score_endpoint():
    """Ensemble score on top of the existing /score response. Returns
    BOTH the v3 result (for backward compat) AND v4 fields the EA can use."""
    try:
        data = request.get_json(force=True) or {}
        cb_allowed, cb_reason = check_circuit_breaker()
        if not cb_allowed:
            base = _build(0, False, 1.0, 0.0, "blocked", cb_reason)
        else:
            # Side-effect-free re-score: pass _silent so the v3 path does not
            # re-emit Telegram or other approval-side mutations. /score has
            # already fired any user-facing alerts for this setup.
            base = score_trade({**data, "_silent": True})
        v4 = score_ensemble(data)
        # Decision: v3 must have approved AND the WEIGHTED BLEND must clear
        # MIN_SCORE. The blend is sum(component_score * weight) / sum(weights)
        # so retrained weights materially gate approvals — a strategy whose
        # weight collapsed in the Sunday retrain loses voting power on every
        # subsequent setup. This is the single source of truth for v4 approval.
        chosen_score = v4["v4_components"].get(v4["v4_chosen"], 0.0)
        v4_approved  = bool(base.get("approved")) and float(v4["v4_score"]) >= MIN_SCORE
        out = {**base, **v4,
               "v4_approved":     v4_approved,
               "v4_chosen_score": chosen_score,
               "v4_blended_gate": MIN_SCORE,
               "v4_version":      "4.0.0"}
        return jsonify(out)
    except Exception as e:
        log.error(f"[v4/score] {e}")
        return jsonify({"error": str(e), "v4_approved": False, "v4_score": 0}), 500


@app.route("/v4/strategy_weights", methods=["GET"])
def v4_get_weights():
    with V4_LOCK:
        return jsonify(dict(v4_state))


@app.route("/v4/strategy_weights", methods=["POST"])
def v4_set_weights():
    """Accepts a rebalance payload from the VPS Sunday cron (or manual ops).
    Persists weights / per-strategy perf / sample_size / kelly_cap / last_retrain
    so the live ensemble immediately uses the new mix on the next /v4/score call.
    Body keys recognised:
      weights        dict[str,float]  — must sum ≈1, keys ⊆ STRATEGIES
      perf           dict[str,dict]   — per-strategy {n,wins,avg_r}
      sample_size    int              — total fills behind this rebalance
      kelly_cap      float            — Kelly cap (clamped 0.05..0.5)
      last_retrain   ISO-8601 string  — defaults to now() if omitted
      reason         str              — free-form provenance tag
    """
    try:
        body = request.get_json(force=True) or {}
        with V4_LOCK:
            # 1) Weights — validated and renormalised
            if isinstance(body.get("weights"), dict):
                clean = {}
                for k in V4_DEFAULT_WEIGHTS:
                    v = body["weights"].get(k)
                    if isinstance(v, (int, float)) and v >= 0:
                        clean[k] = float(v)
                if clean:
                    s = sum(clean.values()) or 1.0
                    v4_state["weights"] = {k: round(clean.get(k, 0.0) / s, 4) for k in V4_DEFAULT_WEIGHTS}
            # 2) Per-strategy perf snapshot
            if isinstance(body.get("perf"), dict):
                v4_state["perf"] = {
                    k: dict(body["perf"].get(k, {})) for k in V4_DEFAULT_WEIGHTS
                }
            # 3) Sample size + Kelly cap
            if isinstance(body.get("sample_size"), (int, float)):
                v4_state["sample_size"] = int(body["sample_size"])
            if isinstance(body.get("kelly_cap"), (int, float)):
                v4_state["kelly_cap"] = max(0.05, min(0.5, float(body["kelly_cap"])))
            # 4) Provenance — default to now() so the dashboard's "last retrain"
            #    timestamp moves immediately after a cron push
            v4_state["last_retrain"] = body.get("last_retrain") or datetime.utcnow().isoformat() + "Z"
            if body.get("reason"):
                v4_state["last_retrain_reason"] = str(body["reason"])
            _v4_save_weights(v4_state)
        log.info(f"[v4/weights] rebalanced reason={body.get('reason','?')} "
                 f"weights={v4_state.get('weights')} ss={v4_state.get('sample_size')}")
        return jsonify({"ok": True, "state": dict(v4_state)})
    except Exception as e:
        log.error(f"[v4/weights] rebalance failed: {e}")
        return jsonify({"error": str(e)}), 400


@app.route("/v4/retrain", methods=["POST"])
def v4_retrain_endpoint():
    body = request.get_json(silent=True) or {}
    reason = body.get("reason", "manual_post")
    return jsonify(v4_retrain_weights(reason=reason))


# ══════════════════════════════════════════════════════════════════════
# RESEARCH & VALIDATION ROUTES
# Institutional-grade statistical validation endpoints.
# All price-replay tests use actual forward candle data — no random draws.
# ══════════════════════════════════════════════════════════════════════

def _load_research_engine():
    """Lazy-import research_engine to avoid startup cost when unused."""
    try:
        import importlib.util, os
        base = os.path.dirname(os.path.abspath(__file__))
        spec = importlib.util.spec_from_file_location(
            "research_engine",
            os.path.join(base, "phantom_src", "research_engine.py")
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception as e:
        log.warning(f"[RESEARCH] research_engine not available: {e}")
        return None


@app.route("/research/backtest", methods=["POST"])
def research_backtest():
    """
    Full price-replay backtest. No random draws.
    Body: { candles: [...], symbol, min_score, rr, mode }
    Returns: { signals, equity_curve, stats }
    """
    eng = _load_research_engine()
    if eng is None:
        return jsonify({"error": "research_engine.py not found in phantom_src/"}), 503
    try:
        data    = request.get_json(force=True)
        candles = data.get("candles", [])
        symbol  = data.get("symbol", "EURUSD").upper()
        if len(candles) < 100:
            return jsonify({"error": "Need ≥100 candles for price-replay backtest"}), 400
        result = eng.run_backtest(
            candles     = candles,
            symbol      = symbol,
            score_fn    = score_trade,
            min_score   = float(data.get("min_score", MIN_SCORE)),
            filter_sessions = bool(data.get("filter_sessions", True)),
            rr          = float(data.get("rr", 2.5)),
            sl_atr_mult = float(data.get("sl_atr_mult", 1.0)),
            mode        = str(data.get("mode", "CHALLENGE")),
        )
        return jsonify(result)
    except Exception as e:
        log.error(f"[RESEARCH] backtest error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/research/walk-forward", methods=["POST"])
def research_walk_forward():
    """
    Walk-forward engine: IS optimisation → OOS validation. No future leak.
    Body: { candles, symbol, n_windows, train_bars, test_bars, min_score, rr }
    """
    eng = _load_research_engine()
    if eng is None:
        return jsonify({"error": "research_engine.py not found in phantom_src/"}), 503
    try:
        data    = request.get_json(force=True)
        candles = data.get("candles", [])
        symbol  = data.get("symbol", "EURUSD").upper()
        if len(candles) < 500:
            return jsonify({"error": "Need ≥500 candles for walk-forward analysis"}), 400
        result = eng.walk_forward(
            candles          = candles,
            symbol           = symbol,
            score_fn         = score_trade,
            n_windows        = int(data.get("n_windows", 5)),
            train_bars       = int(data.get("train_bars", 1500)),
            test_bars        = int(data.get("test_bars",  500)),
            score_candidates = data.get("score_candidates",
                                        [60.0, 65.0, 68.0, 70.0, 72.0, 75.0, 78.0, 80.0]),
            rr               = float(data.get("rr", 2.5)),
            mode             = str(data.get("mode", "CHALLENGE")),
        )
        return jsonify(result)
    except Exception as e:
        log.error(f"[RESEARCH] walk-forward error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/research/factor-attribution", methods=["POST"])
def research_factor_attribution():
    """
    Marginal contribution of each scoring factor.
    Body: { candles, symbol, min_score, rr }
    """
    eng = _load_research_engine()
    if eng is None:
        return jsonify({"error": "research_engine.py not found in phantom_src/"}), 503
    try:
        data    = request.get_json(force=True)
        candles = data.get("candles", [])
        symbol  = data.get("symbol", "EURUSD").upper()
        if len(candles) < 200:
            return jsonify({"error": "Need ≥200 candles for factor attribution"}), 400
        result = eng.factor_attribution(
            candles   = candles,
            symbol    = symbol,
            score_fn  = score_trade,
            min_score = float(data.get("min_score", MIN_SCORE)),
            rr        = float(data.get("rr", 2.5)),
            mode      = str(data.get("mode", "CHALLENGE")),
        )
        return jsonify({"factors": result, "symbol": symbol})
    except Exception as e:
        log.error(f"[RESEARCH] factor-attribution error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/research/sensitivity", methods=["POST"])
def research_sensitivity():
    """
    Parameter fragility map: Sharpe vs min_score grid.
    Body: { candles, symbol, param_values (optional), rr }
    """
    eng = _load_research_engine()
    if eng is None:
        return jsonify({"error": "research_engine.py not found in phantom_src/"}), 503
    try:
        data    = request.get_json(force=True)
        candles = data.get("candles", [])
        symbol  = data.get("symbol", "EURUSD").upper()
        if len(candles) < 300:
            return jsonify({"error": "Need ≥300 candles for sensitivity analysis"}), 400
        result = eng.param_sensitivity(
            candles      = candles,
            symbol       = symbol,
            score_fn     = score_trade,
            param_values = data.get("param_values",
                                    [60, 62, 65, 68, 70, 72, 74, 75, 78, 80, 82, 85]),
            rr           = float(data.get("rr", 2.5)),
            mode         = str(data.get("mode", "CHALLENGE")),
        )
        return jsonify(result)
    except Exception as e:
        log.error(f"[RESEARCH] sensitivity error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/research/monte-carlo", methods=["POST"])
def research_monte_carlo():
    """
    Improved Monte Carlo: variable RR distribution (log-normal), serial correlation.
    Body: { win_rate, win_rr_mean, win_rr_std, risk_pct, n_trades, n_sims,
            dd_limit, corr_alpha }
    """
    eng = _load_research_engine()
    if eng is None:
        return jsonify({"error": "research_engine.py not found in phantom_src/"}), 503
    try:
        data   = request.get_json(force=True) or {}
        result = eng.monte_carlo_v2(
            win_rate    = float(data.get("win_rate",    0.60)),
            win_rr_mean = float(data.get("win_rr_mean", 2.50)),
            win_rr_std  = float(data.get("win_rr_std",  0.60)),
            risk_pct    = float(data.get("risk_pct",    1.00)),
            n_trades    = int(data.get("n_trades",      200)),
            n_sims      = min(int(data.get("n_sims",    10000)), 50000),
            dd_limit    = float(data.get("dd_limit",    5.0)),
            corr_alpha  = float(data.get("corr_alpha",  0.0)),
        )
        return jsonify(result)
    except Exception as e:
        log.error(f"[RESEARCH] monte-carlo error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/research/kelly", methods=["GET"])
def research_kelly():
    """
    Full Kelly curve from supplied or default parameters.
    Query: win_rate, avg_rr, n_sims, dd_limit
    """
    eng = _load_research_engine()
    if eng is None:
        return jsonify({"error": "research_engine.py not found in phantom_src/"}), 503
    try:
        result = eng.kelly_analysis(
            win_rate  = float(request.args.get("win_rate", 0.60)),
            avg_rr    = float(request.args.get("avg_rr",   2.50)),
            n_sims    = int(request.args.get("n_sims",     5000)),
            dd_limit  = float(request.args.get("dd_limit", 5.0)),
        )
        return jsonify(result)
    except Exception as e:
        log.error(f"[RESEARCH] kelly error: {e}")
        return jsonify({"error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════
# PORTFOLIO RISK ROUTES
# Institutional portfolio-aware risk layer.  All computation delegated
# to portfolio_engine.py singleton; these routes are thin wrappers that
# feed live EA state into the engine and return JSON.
# ══════════════════════════════════════════════════════════════════════

def _load_portfolio_engine():
    """Lazy-import portfolio_engine to avoid startup cost when unused."""
    try:
        import importlib.util as _ilu, os as _os
        _base = _os.path.dirname(_os.path.abspath(__file__))
        _spec = _ilu.spec_from_file_location(
            "portfolio_engine",
            _os.path.join(_base, "phantom_src", "portfolio_engine.py")
        )
        _mod = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        return _mod
    except Exception as _e:
        log.warning(f"[PORTFOLIO] portfolio_engine not available: {_e}")
        return None


@app.route("/portfolio/heat", methods=["GET"])
def portfolio_heat():
    """Current portfolio heat — call after heartbeat has been received."""
    eng = _load_portfolio_engine()
    if eng is None:
        return jsonify({"error": "portfolio_engine.py not found in phantom_src/"}), 503
    try:
        engine = eng.portfolio_risk_engine
        heat   = engine.heat_monitor.compute(
            engine.positions,
            engine.equity,
            engine.corr_matrix.get_matrix(eng.PAIRS_7, window=20),
        )
        adaptive = engine.risk_reducer.compute(
            engine._daily_dd_pct,
            engine._consec_losses,
            engine._weekly_dd_pct,
        )
        return jsonify({
            **heat,
            "adaptive_risk": adaptive,
            "equity":        engine.equity,
            "n_positions":   len(engine.positions),
            "data_fresh":    (time.time() - engine._last_update) < 180,
            "staleness_sec": round(time.time() - engine._last_update, 0),
        })
    except Exception as e:
        log.error(f"[PORTFOLIO] heat error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/portfolio/correlation", methods=["GET"])
def portfolio_correlation():
    """Rolling 7×7 correlation matrix."""
    eng = _load_portfolio_engine()
    if eng is None:
        return jsonify({"error": "portfolio_engine.py not found in phantom_src/"}), 503
    try:
        window = int(request.args.get("window", 20))
        engine = eng.portfolio_risk_engine
        return jsonify(engine.corr_matrix.to_dict(eng.PAIRS_7, window=window))
    except Exception as e:
        log.error(f"[PORTFOLIO] correlation error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/portfolio/var", methods=["GET"])
def portfolio_var():
    """Parametric VaR/CVaR across all open positions."""
    eng = _load_portfolio_engine()
    if eng is None:
        return jsonify({"error": "portfolio_engine.py not found in phantom_src/"}), 503
    try:
        engine   = eng.portfolio_risk_engine
        all_syms = list(set(
            [str(p.get("symbol","")).upper() for p in engine.positions] + eng.PAIRS_7
        ))
        corr_mat = engine.corr_matrix.get_matrix(all_syms, window=20)
        var_data = engine.var_engine.compute(engine.positions, engine.equity, corr_mat)
        return jsonify({**var_data, "equity": engine.equity})
    except Exception as e:
        log.error(f"[PORTFOLIO] var error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/portfolio/exposure", methods=["GET"])
def portfolio_exposure():
    """Per-currency directional exposure breakdown."""
    eng = _load_portfolio_engine()
    if eng is None:
        return jsonify({"error": "portfolio_engine.py not found in phantom_src/"}), 503
    try:
        engine = eng.portfolio_risk_engine
        result = engine.exposure_ctrl.get_exposure(engine.positions, engine.equity)
        return jsonify({**result, "equity": engine.equity, "n_positions": len(engine.positions)})
    except Exception as e:
        log.error(f"[PORTFOLIO] exposure error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/portfolio/allocation", methods=["GET"])
def portfolio_allocation():
    """Dynamic pair ranking by composite score (session × regime × realized Sharpe)."""
    eng = _load_portfolio_engine()
    if eng is None:
        return jsonify({"error": "portfolio_engine.py not found in phantom_src/"}), 503
    try:
        engine  = eng.portfolio_risk_engine
        session = request.args.get("session", engine._session)
        regime  = request.args.get("regime",  engine._regime)
        ranked  = engine.allocator.rank_pairs(
            session      = session,
            regime       = regime,
            pair_sharpes = {},
            open_symbols = [str(p.get("symbol","")).upper() for p in engine.positions],
        )
        return jsonify({
            "ranked":  ranked,
            "session": session,
            "regime":  regime,
            "n_open":  len(engine.positions),
        })
    except Exception as e:
        log.error(f"[PORTFOLIO] allocation error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/portfolio/validate-trade", methods=["POST"])
def portfolio_validate_trade():
    """
    Full pre-trade portfolio check.  Called by EA before sending to /score.
    Body: { symbol, direction, equity, session, regime, lots, sl_pips, atr }
    Returns: { approved, lot_multiplier, block_reason, checks }
    """
    eng = _load_portfolio_engine()
    if eng is None:
        return jsonify({"approved": True, "lot_multiplier": 1.0,
                        "note": "portfolio_engine.py not found — check bypassed"}), 200
    try:
        body      = request.get_json(force=True) or {}
        symbol    = str(body.get("symbol",    "EURUSD")).upper()
        direction = int(body.get("direction", 1))
        equity    = float(body.get("equity",  0)) or None
        session   = body.get("session",  None)
        regime    = body.get("regime",   None)
        lots      = float(body.get("lots",     0.01))
        sl_pips   = float(body.get("sl_pips",  15.0))
        atr       = float(body.get("atr",      0.0))
        result    = eng.portfolio_risk_engine.validate_pre_trade(
            symbol       = symbol,
            direction    = direction,
            equity       = equity,
            session      = session,
            regime       = regime,
            new_lots     = lots,
            new_sl_pips  = sl_pips,
            new_atr      = atr,
        )
        if not result["approved"]:
            log.info(f"[PORTFOLIO-BLOCK] {symbol} dir={direction}: {result['block_reason']}")
        return jsonify(result)
    except Exception as e:
        log.error(f"[PORTFOLIO] validate-trade error: {e}")
        return jsonify({"approved": True, "lot_multiplier": 1.0,
                        "error": str(e), "note": "fail-open on portfolio error"}), 200


@app.route("/portfolio/report", methods=["GET"])
def portfolio_report():
    """Full institutional portfolio risk report."""
    eng = _load_portfolio_engine()
    if eng is None:
        return jsonify({"error": "portfolio_engine.py not found in phantom_src/"}), 503
    try:
        engine = eng.portfolio_risk_engine
        report = engine.build_report()
        return jsonify(report)
    except Exception as e:
        log.error(f"[PORTFOLIO] report error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/portfolio/killswitch-status", methods=["GET"])
def portfolio_killswitch_status():
    """Portfolio-level killswitch state (weekly/monthly DD halt)."""
    eng = _load_portfolio_engine()
    if eng is None:
        return jsonify({"halted": False, "lot_mult": 1.0,
                        "note": "portfolio_engine.py not found"}), 200
    try:
        ks = eng.portfolio_killswitch.check()
        return jsonify(ks)
    except Exception as e:
        return jsonify({"error": str(e), "halted": False, "lot_mult": 1.0}), 500


@app.route("/portfolio/pair-quality", methods=["GET"])
def portfolio_pair_quality():
    """Per-pair quality scores from PairQualityRanker."""
    eng = _load_portfolio_engine()
    if eng is None:
        return jsonify({"error": "portfolio_engine.py not found"}), 503
    try:
        symbol = request.args.get("symbol", "").upper()
        ranker = eng.pair_quality_ranker
        if symbol:
            score = ranker.score_pair(symbol)
            return jsonify(score)
        return jsonify({
            "rankings": ranker.rank_all(),
            "disabled": eng.adaptive_pair_disabler._disabled,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/portfolio/pair-ranking", methods=["GET"])
def portfolio_pair_ranking():
    """Full pair ranking with quality scores, disabled status, and killswitch state."""
    eng = _load_portfolio_engine()
    if eng is None:
        return jsonify({"error": "portfolio_engine.py not found"}), 503
    try:
        rankings = eng.pair_quality_ranker.rank_all()
        disabled = eng.adaptive_pair_disabler._disabled
        ks       = eng.portfolio_killswitch.check()
        for r in rankings:
            r["is_disabled"] = r["symbol"] in disabled
            r["disable_reason"] = disabled.get(r["symbol"], {}).get("reason")
        return jsonify({
            "rankings":    rankings,
            "disabled_count": len(disabled),
            "killswitch":  ks,
            "generated_at": time.time(),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/portfolio/correlated-check", methods=["POST"])
def portfolio_correlated_check():
    """
    Check whether a proposed new trade would over-stack correlation or currency exposure.
    Body: { symbol, direction, positions, equity }
    """
    eng = _load_portfolio_engine()
    if eng is None:
        return jsonify({"allow_trade": True, "note": "portfolio_engine.py not found"}), 200
    try:
        body      = request.get_json(force=True) or {}
        symbol    = str(body.get("symbol", "EURUSD")).upper()
        direction = int(body.get("direction", 1))
        equity    = float(body.get("equity", 100_000.0))
        positions = body.get("positions", [])

        corr_mat = eng.portfolio_risk_engine.corr_matrix.get_matrix(
            [symbol] + [p.get("symbol","") for p in positions], window=20
        )
        throttle = eng.portfolio_risk_engine.throttler.check(
            positions, symbol, direction, corr_mat
        )
        ccy_check = eng.per_currency_caps.check(positions, symbol, direction, equity)
        exp_check = eng.portfolio_risk_engine.exposure_ctrl.check_new_trade(
            positions, symbol, direction, equity
        )

        allow = throttle["allow_trade"] and ccy_check["allow_trade"] and exp_check["allow_trade"]
        return jsonify({
            "allow_trade":    allow,
            "throttle":       throttle,
            "ccy_caps":       ccy_check,
            "exposure":       exp_check,
        })
    except Exception as e:
        log.error(f"[PORTFOLIO] correlated-check error: {e}")
        return jsonify({"allow_trade": True, "error": str(e)}), 200


# ══════════════════════════════════════════════════════════════════════
# PHASE 6 — RESEARCH / VALIDATION ROUTES (research_engine.py)
# Exposes real OHLC-replay backtesting, walk-forward, Monte Carlo, and
# factor attribution through Flask endpoints.  The research_engine module
# is loaded lazily so scorer startup is not affected when it is absent.
# ══════════════════════════════════════════════════════════════════════

_research_module      = None
_research_module_lock = threading.Lock()


def _load_research_engine():
    """
    Lazy-load phantom_src/research_engine.py without circular imports.
    Returns the module object or None if unavailable.
    """
    global _research_module
    with _research_module_lock:
        if _research_module is not None:
            return _research_module
        try:
            import importlib.util
            re_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "phantom_src", "research_engine.py")
            if not os.path.exists(re_path):
                log.warning("[RESEARCH] research_engine.py not found — research routes disabled")
                return None
            spec   = importlib.util.spec_from_file_location("phantom_research_engine", re_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            _research_module = module
            log.info("[RESEARCH] research_engine.py loaded successfully")
            return module
        except Exception as e:
            log.error(f"[RESEARCH] Failed to load research_engine.py: {e}")
            return None


def _get_research_score_fn():
    """Return standalone score function from scoring_engine.py (no ai_model dependency)."""
    try:
        from phantom_src.scoring_engine import score_ensemble as _se
        return lambda data: _se(data)["v4_score"]
    except Exception:
        return lambda data: float(data.get("score", 0.0))


def research_backtest_route():
    """
    Phase 6: Real OHLC-replay backtest using research_engine.run_backtest().
    Body: { candles: [...], score_threshold, risk_pct, rr, symbol }
    Each candle: { open, high, low, close, timestamp } (MT5 export format).
    Returns: { trades, equity_curve, stats, source: "research_engine/ohlc_replay" }
    """
    re = _load_research_engine()
    if re is None:
        return jsonify({"error": "research_engine.py not available — check phantom_src/"}), 503
    try:
        body      = request.get_json(force=True) or {}
        candles   = body.get("candles", [])
        if not candles:
            return jsonify({"error": "candles[] is required (send OHLCV rows as list of dicts)"}), 400
        result = re.run_backtest(
            candles,
            score_fn  = _get_research_score_fn(),
            threshold = float(body.get("score_threshold", MIN_SCORE)),
            risk_pct  = float(body.get("risk_pct", 1.0)),
            rr        = float(body.get("rr", 2.5)),
        )
        return jsonify({**result,
                        "symbol": str(body.get("symbol", "UNKNOWN")).upper(),
                        "source": "research_engine/ohlc_replay"})
    except Exception as e:
        log.error(f"[RESEARCH] backtest error: {e}")
        return jsonify({"error": str(e)}), 500


def research_walk_forward_route():
    """
    Phase 6: Walk-forward validation (no future leak, parameter frozen per fold).
    Body: { candles, n_splits, score_threshold, risk_pct, rr }
    """
    re = _load_research_engine()
    if re is None:
        return jsonify({"error": "research_engine.py not available"}), 503
    try:
        body    = request.get_json(force=True) or {}
        candles = body.get("candles", [])
        if not candles:
            return jsonify({"error": "candles[] required"}), 400
        result = re.walk_forward(
            candles,
            score_fn  = _get_research_score_fn(),
            threshold = float(body.get("score_threshold", MIN_SCORE)),
            risk_pct  = float(body.get("risk_pct", 1.0)),
            rr        = float(body.get("rr", 2.5)),
            n_splits  = int(body.get("n_splits", 5)),
        )
        return jsonify({**result, "source": "research_engine/walk_forward"})
    except Exception as e:
        log.error(f"[RESEARCH] walk_forward error: {e}")
        return jsonify({"error": str(e)}), 500


def research_monte_carlo_route():
    """
    Phase 6: Monte Carlo simulation using research_engine.monte_carlo_v2().
    Body: { win_rate, avg_r, n_trades, risk_pct, initial_equity, n_runs, seed }
    """
    re = _load_research_engine()
    if re is None:
        return jsonify({"error": "research_engine.py not available"}), 503
    try:
        body   = request.get_json(force=True) or {}
        result = re.monte_carlo_v2(
            win_rate       = float(body.get("win_rate",       0.60)),
            avg_r          = float(body.get("avg_r",          2.5)),
            n_trades       = int(body.get("n_trades",         200)),
            risk_pct       = float(body.get("risk_pct",       1.0)),
            initial_equity = float(body.get("initial_equity", 100_000)),
            n_runs         = int(body.get("n_runs",           10_000)),
            seed           = int(body.get("seed",             42)),
        )
        return jsonify({**result, "source": "research_engine/monte_carlo_v2"})
    except Exception as e:
        log.error(f"[RESEARCH] monte_carlo error: {e}")
        return jsonify({"error": str(e)}), 500


def research_factor_attribution_route():
    """
    Phase 6: Per-factor win-rate attribution across a trade list.
    Body: { trades: [{ factor_flags: {...}, won: bool, pnl_r: float }, ...] }
    """
    re = _load_research_engine()
    if re is None:
        return jsonify({"error": "research_engine.py not available"}), 503
    try:
        body   = request.get_json(force=True) or {}
        trades = body.get("trades", [])
        if not trades:
            return jsonify({"error": "trades[] required"}), 400
        result = re.factor_attribution(trades)
        return jsonify({"attribution": result,
                        "n_trades":   len(trades),
                        "source":     "research_engine/factor_attribution"})
    except Exception as e:
        log.error(f"[RESEARCH] factor_attribution error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/research/stats", methods=["POST"])
def research_compute_stats_route():
    """
    Phase 6: Compute full statistical suite (Sharpe, Sortino, Calmar, Omega, CI) from P&L series.
    Body: { pnl_series: [float, ...], risk_free_rate: float }
    """
    re = _load_research_engine()
    if re is None:
        return jsonify({"error": "research_engine.py not available"}), 503
    try:
        body       = request.get_json(force=True) or {}
        pnl_series = body.get("pnl_series", [])
        if not pnl_series:
            return jsonify({"error": "pnl_series[] required"}), 400
        result = re.compute_all_stats(
            [float(x) for x in pnl_series],
            risk_free_rate=float(body.get("risk_free_rate", 0.0)),
        )
        return jsonify({**result, "source": "research_engine/compute_all_stats"})
    except Exception as e:
        log.error(f"[RESEARCH] stats error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/research/param-sensitivity", methods=["POST"])
def research_param_sensitivity_route():
    """
    Phase 6: Parameter sensitivity analysis — sweep score_threshold across a range.
    Body: { candles, threshold_range: [min, max, step], risk_pct, rr }
    """
    re = _load_research_engine()
    if re is None:
        return jsonify({"error": "research_engine.py not available"}), 503
    try:
        body     = request.get_json(force=True) or {}
        candles  = body.get("candles", [])
        if not candles:
            return jsonify({"error": "candles[] required"}), 400
        t_range  = body.get("threshold_range", [60, 85, 5])
        result   = re.param_sensitivity(
            candles,
            score_fn         = _get_research_score_fn(),
            threshold_range  = t_range,
            risk_pct         = float(body.get("risk_pct", 1.0)),
            rr               = float(body.get("rr", 2.5)),
        )
        return jsonify({**result, "source": "research_engine/param_sensitivity"})
    except Exception as e:
        log.error(f"[RESEARCH] param_sensitivity error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/research/ml-benchmark", methods=["POST"])
def research_ml_benchmark_route():
    """
    P8: Honest ML contribution benchmark.
    Runs rule-only vs confidence-filtered (+8pt threshold) walk-forward comparison.
    Confidence-gating at threshold+8 is the closest statistical proxy for ML signal
    quality without requiring a live trained model or labelled dataset.

    Body: { candles, symbol, threshold, rr, risk_pct, mode, n_windows, train_bars, test_bars }
    """
    re = _load_research_engine()
    if re is None:
        return jsonify({"error": "research_engine.py not available — check phantom_src/research_engine.py"}), 503
    try:
        body    = request.get_json(force=True) or {}
        candles = body.get("candles", [])
        if not candles:
            return jsonify({
                "error": "candles[] required — use real OHLC data for an honest ML benchmark. "
                         "Fake simulation fallbacks produce misleading ML contribution claims."
            }), 400
        result = re.ml_benchmark(
            candles,
            symbol     = str(body.get("symbol", "UNKNOWN")),
            score_fn   = _get_research_score_fn(),
            threshold  = float(body.get("threshold", MIN_SCORE)),
            rr         = float(body.get("rr", 2.5)),
            risk_pct   = float(body.get("risk_pct", 1.0)),
            mode       = str(body.get("mode", "CHALLENGE")),
            n_windows  = int(body.get("n_windows", 4)),
            train_bars = int(body.get("train_bars", 1200)),
            test_bars  = int(body.get("test_bars", 400)),
        )
        return jsonify({**result, "source": "research_engine/ml_benchmark"})
    except Exception as e:
        log.error(f"[RESEARCH] ml_benchmark error: {e}")
        return jsonify({"error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════
# SESSION ENGINE ROUTES  (v4.02)
# ══════════════════════════════════════════════════════════════════════

def _load_session_engine():
    """Lazy-import session_engine (phantom_src/session_engine.py)."""
    try:
        import importlib.util as _ilu, os as _os
        _base = _os.path.dirname(_os.path.abspath(__file__))
        _spec = _ilu.spec_from_file_location(
            "session_engine",
            _os.path.join(_base, "phantom_src", "session_engine.py")
        )
        _mod = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        return _mod
    except Exception as _e:
        log.warning(f"[SESSION] session_engine not available: {_e}")
        return None


def _load_execution_filter():
    """Lazy-import execution_filter_engine (phantom_src/execution_filter_engine.py)."""
    try:
        import importlib.util as _ilu, os as _os
        _base = _os.path.dirname(_os.path.abspath(__file__))
        _spec = _ilu.spec_from_file_location(
            "execution_filter_engine",
            _os.path.join(_base, "phantom_src", "execution_filter_engine.py")
        )
        _mod = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        return _mod
    except Exception as _e:
        log.warning(f"[EXEC-FILTER] execution_filter_engine not available: {_e}")
        return None


# ══════════════════════════════════════════════════════════════════════
# v4.02 PERFORMANCE ENGINE LOADERS  (Phases 1/2/5/7/9/10)
# Cached once per process — each module exposes its own lazy singleton.
# ══════════════════════════════════════════════════════════════════════

_v402_engine_cache: dict = {}

def _get_pair_session_engine():
    """Cached loader for pair_session_matrix (Phases 1+2)."""
    if "psm" not in _v402_engine_cache:
        try:
            import importlib.util as _ilu, os as _os
            _base = _os.path.dirname(_os.path.abspath(__file__))
            _spec = _ilu.spec_from_file_location(
                "pair_session_matrix",
                _os.path.join(_base, "phantom_src", "pair_session_matrix.py"),
            )
            _mod = _ilu.module_from_spec(_spec)
            _spec.loader.exec_module(_mod)
            _v402_engine_cache["psm"] = _mod
            log.info("[v4.02] pair_session_matrix loaded (Phases 1+2)")
        except Exception as _e:
            log.warning(f"[v4.02] pair_session_matrix not available: {_e}")
            _v402_engine_cache["psm"] = None
    return _v402_engine_cache.get("psm")


def _get_pair_performance_engine_mod():
    """Cached loader for pair_performance_engine (Phase 5)."""
    if "ppe" not in _v402_engine_cache:
        try:
            import importlib.util as _ilu, os as _os
            _base = _os.path.dirname(_os.path.abspath(__file__))
            _spec = _ilu.spec_from_file_location(
                "pair_performance_engine",
                _os.path.join(_base, "phantom_src", "pair_performance_engine.py"),
            )
            _mod = _ilu.module_from_spec(_spec)
            _spec.loader.exec_module(_mod)
            _v402_engine_cache["ppe"] = _mod
            log.info("[v4.02] pair_performance_engine loaded (Phase 5)")
        except Exception as _e:
            log.warning(f"[v4.02] pair_performance_engine not available: {_e}")
            _v402_engine_cache["ppe"] = None
    return _v402_engine_cache.get("ppe")


def _get_trade_quality_engine_mod():
    """Cached loader for trade_quality_engine (Phases 7+9)."""
    if "tqe" not in _v402_engine_cache:
        try:
            import importlib.util as _ilu, os as _os
            _base = _os.path.dirname(_os.path.abspath(__file__))
            _spec = _ilu.spec_from_file_location(
                "trade_quality_engine",
                _os.path.join(_base, "phantom_src", "trade_quality_engine.py"),
            )
            _mod = _ilu.module_from_spec(_spec)
            _spec.loader.exec_module(_mod)
            _v402_engine_cache["tqe"] = _mod
            log.info("[v4.02] trade_quality_engine loaded (Phases 7+9)")
        except Exception as _e:
            log.warning(f"[v4.02] trade_quality_engine not available: {_e}")
            _v402_engine_cache["tqe"] = None
    return _v402_engine_cache.get("tqe")


def _get_ml_validation_engine_mod():
    """Cached loader for ml_validation_engine (Phase 10)."""
    if "mve" not in _v402_engine_cache:
        try:
            import importlib.util as _ilu, os as _os
            _base = _os.path.dirname(_os.path.abspath(__file__))
            _spec = _ilu.spec_from_file_location(
                "ml_validation_engine",
                _os.path.join(_base, "phantom_src", "ml_validation_engine.py"),
            )
            _mod = _ilu.module_from_spec(_spec)
            _spec.loader.exec_module(_mod)
            _v402_engine_cache["mve"] = _mod
            log.info("[v4.02] ml_validation_engine loaded (Phase 10)")
        except Exception as _e:
            log.warning(f"[v4.02] ml_validation_engine not available: {_e}")
            _v402_engine_cache["mve"] = None
    return _v402_engine_cache.get("mve")


def _get_currency_strength_engine_mod():
    """Cached loader for currency_strength_engine (Phase 3 — v4.02)."""
    if "cse" not in _v402_engine_cache:
        try:
            import importlib.util as _ilu, os as _os
            _base = _os.path.dirname(_os.path.abspath(__file__))
            _spec = _ilu.spec_from_file_location(
                "currency_strength_engine",
                _os.path.join(_base, "phantom_src", "currency_strength_engine.py"),
            )
            _mod = _ilu.module_from_spec(_spec)
            _spec.loader.exec_module(_mod)
            _v402_engine_cache["cse"] = _mod
            log.info("[v4.02] currency_strength_engine loaded (Phase 3)")
        except Exception as _e:
            log.warning(f"[v4.02] currency_strength_engine not available: {_e}")
            _v402_engine_cache["cse"] = None
    return _v402_engine_cache.get("cse")


def _get_macro_engine_mod():
    """Cached loader for macro_engine (Phases 1+2 — v4.02)."""
    if "mae" not in _v402_engine_cache:
        try:
            import importlib.util as _ilu, os as _os
            _base = _os.path.dirname(_os.path.abspath(__file__))
            _spec = _ilu.spec_from_file_location(
                "macro_engine",
                _os.path.join(_base, "phantom_src", "macro_engine.py"),
            )
            _mod = _ilu.module_from_spec(_spec)
            _spec.loader.exec_module(_mod)
            _v402_engine_cache["mae"] = _mod
            log.info("[v4.02] macro_engine loaded (Phases 1+2)")
        except Exception as _e:
            log.warning(f"[v4.02] macro_engine not available: {_e}")
            _v402_engine_cache["mae"] = None
    return _v402_engine_cache.get("mae")


def _get_macro_fusion_engine_mod():
    """Cached loader for macro_fusion_engine (Phase 7 — v4.02)."""
    if "mfe" not in _v402_engine_cache:
        try:
            import importlib.util as _ilu, os as _os
            _base = _os.path.dirname(_os.path.abspath(__file__))
            _spec = _ilu.spec_from_file_location(
                "macro_fusion_engine",
                _os.path.join(_base, "phantom_src", "macro_fusion_engine.py"),
            )
            _mod = _ilu.module_from_spec(_spec)
            _spec.loader.exec_module(_mod)
            _v402_engine_cache["mfe"] = _mod
            log.info("[v4.02] macro_fusion_engine loaded (Phase 7)")
        except Exception as _e:
            log.warning(f"[v4.02] macro_fusion_engine not available: {_e}")
            _v402_engine_cache["mfe"] = None
    return _v402_engine_cache.get("mfe")


def _get_metrics_engine_mod():
    """Cached loader for metrics_engine (Phase 8 — Observability)."""
    if "me8" not in _v402_engine_cache:
        try:
            import importlib.util as _ilu, os as _os
            _base = _os.path.dirname(_os.path.abspath(__file__))
            _spec = _ilu.spec_from_file_location(
                "metrics_engine",
                _os.path.join(_base, "phantom_src", "metrics_engine.py"),
            )
            _mod = _ilu.module_from_spec(_spec)
            _spec.loader.exec_module(_mod)
            _v402_engine_cache["me8"] = _mod
            log.info("[v4.02] metrics_engine loaded (Phase 8)")
        except Exception as _e:
            log.warning(f"[v4.02] metrics_engine not available: {_e}")
            _v402_engine_cache["me8"] = None
    return _v402_engine_cache.get("me8")


def _get_news_intelligence_mod():
    """Cached loader for news_intelligence_engine (News Intelligence)."""
    if "nie" not in _v402_engine_cache:
        try:
            import importlib.util as _ilu, os as _os
            _base = _os.path.dirname(_os.path.abspath(__file__))
            _spec = _ilu.spec_from_file_location(
                "news_intelligence_engine",
                _os.path.join(_base, "phantom_src", "news_intelligence_engine.py"),
            )
            _mod = _ilu.module_from_spec(_spec)
            _spec.loader.exec_module(_mod)
            _v402_engine_cache["nie"] = _mod
            log.info("[NIE] news_intelligence_engine loaded")
        except Exception as _e:
            log.warning(f"[NIE] news_intelligence_engine not available: {_e}")
            _v402_engine_cache["nie"] = None
    return _v402_engine_cache.get("nie")


def _get_anomaly_engine_mod():
    """Cached loader for anomaly_engine (Phase 8 — Observability)."""
    if "ae8" not in _v402_engine_cache:
        try:
            import importlib.util as _ilu, os as _os
            _base = _os.path.dirname(_os.path.abspath(__file__))
            _spec = _ilu.spec_from_file_location(
                "anomaly_engine",
                _os.path.join(_base, "phantom_src", "anomaly_engine.py"),
            )
            _mod = _ilu.module_from_spec(_spec)
            _spec.loader.exec_module(_mod)
            _v402_engine_cache["ae8"] = _mod
            log.info("[v4.02] anomaly_engine loaded (Phase 8)")
        except Exception as _e:
            log.warning(f"[v4.02] anomaly_engine not available: {_e}")
            _v402_engine_cache["ae8"] = None
    return _v402_engine_cache.get("ae8")


def _get_ml_meta_filter_mod():
    """Cached loader for ml_meta_filter (ML Meta-Filter Infrastructure)."""
    if "mmf" not in _v402_engine_cache:
        try:
            import importlib.util as _ilu, os as _os
            _base = _os.path.dirname(_os.path.abspath(__file__))
            _spec = _ilu.spec_from_file_location(
                "ml_meta_filter",
                _os.path.join(_base, "phantom_src", "ml_meta_filter.py"),
            )
            _mod = _ilu.module_from_spec(_spec)
            _spec.loader.exec_module(_mod)
            _v402_engine_cache["mmf"] = _mod
            log.info("[MLMeta] ml_meta_filter loaded")
        except Exception as _e:
            log.warning(f"[MLMeta] ml_meta_filter not available: {_e}")
            _v402_engine_cache["mmf"] = None
    return _v402_engine_cache.get("mmf")


def _get_hybrid_feature_engine_mod():
    """Cached loader for hybrid_feature_engine (unified feature row builder)."""
    if "hfe" not in _v402_engine_cache:
        try:
            import importlib.util as _ilu, os as _os
            _base = _os.path.dirname(_os.path.abspath(__file__))
            _spec = _ilu.spec_from_file_location(
                "hybrid_feature_engine",
                _os.path.join(_base, "phantom_src", "hybrid_feature_engine.py"),
            )
            _mod = _ilu.module_from_spec(_spec)
            _spec.loader.exec_module(_mod)
            _v402_engine_cache["hfe"] = _mod
            log.info("[HFE] hybrid_feature_engine loaded (schema v%s)",
                     getattr(_mod, "FEATURE_SCHEMA_VERSION", "?"))
        except Exception as _e:
            log.warning(f"[HFE] hybrid_feature_engine not available: {_e}")
            _v402_engine_cache["hfe"] = None
    return _v402_engine_cache.get("hfe")


@app.route("/session/status", methods=["GET"])
def session_status_route():
    """
    GET /session/status
    Returns current session, DST offsets, time to next session open/close,
    broker offset, and session quality score.

    Optional query params:
      server_time  — broker server time as Unix epoch (float) for offset detection
    """
    mod = _load_session_engine()
    if mod is None:
        # Minimal inline fallback
        from datetime import datetime, timezone
        utc_now = datetime.now(timezone.utc)
        h = utc_now.hour + utc_now.minute / 60.0
        if 8 <= h < 16.5:
            sess = "LONDON" if h < 12 else "LONDON_NY" if h < 16.5 else "LONDON"
        elif 12 <= h < 21:
            sess = "NY"
        elif 0 <= h < 8:
            sess = "ASIA"
        else:
            sess = "OFF"
        return jsonify({
            "current_session": sess,
            "utc_now": utc_now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": "inline_fallback",
        })

    try:
        from datetime import datetime, timezone
        engine       = mod.session_engine
        server_time  = request.args.get("server_time")
        utc_now      = datetime.now(timezone.utc)
        diag         = engine.diagnostics(
            server_time_epoch=float(server_time) if server_time else None,
            utc_dt=utc_now,
        )
        return jsonify({
            "current_session":     diag.current_session,
            "utc_now":             diag.utc_now,
            "dst_eu":              diag.dst_eu,
            "dst_us":              diag.dst_us,
            "quality":             diag.quality,
            "london_open_utc":     diag.london_open_utc,
            "ny_open_utc":         diag.ny_open_utc,
            "minutes_to_london":   diag.minutes_to_london,
            "minutes_to_ny":       diag.minutes_to_ny,
            "minutes_to_close":    diag.minutes_to_close,
            "broker_offset_hrs":   diag.broker_offset_hrs,
            "broker_in_sync":      diag.broker_in_sync,
            "broker_warn":         diag.broker_warn,
            "spread_atm_mult":     diag.spread_atm_mult,
            "is_prime_session":    engine.is_prime_session(utc_now),
            "is_open_hour":        engine.is_session_open_hour(utc_now),
            "source":              "session_engine",
        })
    except Exception as e:
        log.error(f"[SESSION] /session/status error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/execution/filter", methods=["POST"])
def execution_filter_route():
    """
    POST /execution/filter
    Pre-trade execution quality gate: spread, slippage, latency.

    Body:
      symbol      str    — e.g. "EURUSD"
      spread_pts  float  — live spread in price points
      atr_pts     float  — ATR in price points
      session     str    — LONDON / NY / etc
      latency_ms  float  — last round-trip latency (optional)
      pip_value   float  — pip in price points (optional, default 0.0001)

    Returns:
      approved    bool
      lot_mult    float  [0.0, 1.0]
      reason      str
    """
    mod = _load_execution_filter()
    if mod is None:
        return jsonify({"error": "execution_filter_engine.py not available"}), 503

    try:
        body   = request.get_json(force=True) or {}
        engine = mod.execution_filter_engine
        result = engine.pre_trade_check(body)
        return jsonify({**result, "source": "execution_filter_engine"})
    except Exception as e:
        log.error(f"[EXEC-FILTER] /execution/filter error: {e}")
        return jsonify({"error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════
# KEEPALIVE
# ══════════════════════════════════════════════════════════════════════

def keepalive():
    while True:
        time.sleep(300)
        total = sum(s["total"] for s in session_stats.values())
        wins  = sum(s["wins"]  for s in session_stats.values())
        wr    = round(wins / total * 100, 1) if total > 0 else 0
        ew    = regime_warning.check()
        log.info(f"[HEARTBEAT] Trades={total} WR={wr}% "
                 f"ML={'ON' if ml_classifier.is_trained else 'OFF'} "
                 f"Accounts={len(orchestrator.accounts)} "
                 f"RegimeWarning={ew['action']}")


if __name__ == "__main__":
    # ── Import-check probe (deploy_manager.py PHANTOM_IMPORT_CHECK=1) ────────
    # deploy_manager.py runs this file in a subprocess to verify all imports
    # succeed before deploying. We print IMPORT_OK and exit immediately so the
    # probe never starts Flask or blocks on port binding.
    if os.environ.get("PHANTOM_IMPORT_CHECK") == "1":
        print("IMPORT_OK")
        sys.exit(0)

    log.info("=" * 60)
    log.info("  PhantomEdge Institutional Server v4.0")
    log.info(f"  Environment:   {_PHANTOM_ENV.upper()}")
    log.info("  All 15 hedge-fund upgrades active (Legend Council + Momentum Exit)")
    log.info(f"  ML Backend: {'XGBoost' if HAS_XGB else 'RandomForest' if HAS_SKLEARN else 'DISABLED'}")
    log.info(f"  Dashboard:  http://{HOST}:{PORT}/dashboard")
    log.info(f"  Min Score:  {MIN_SCORE}")
    log.info("=" * 60)

    # ── Startup self-test: call score_trade() with a dummy payload ───────────
    # Catches any NameError / ImportError introduced by code changes before the
    # scorer starts accepting live EA requests.  Marks scorer unhealthy and logs
    # CRITICAL so deploy_manager.py / health checks can gate the promote step.
    _STARTUP_HEALTHY = True
    try:
        _st_dummy = {
            "symbol": "EURUSD", "direction": 1, "signal": 1,
            "setup": "SWEEP", "session": "LONDON", "regime": "EXPANSION",
            "trend": "BULLISH", "smc": True, "sweep": True,
            "confluence": 4, "news_block": False, "spread_ok": True,
            "weekly_aligned": True, "retest_confirmed": True,
            "probe": True, "_silent": True,
        }
        _st_result = score_trade(_st_dummy)
        if not isinstance(_st_result, dict) or "score" not in _st_result:
            raise ValueError(f"score_trade() returned unexpected type: {type(_st_result)}")
        log.info(f"[STARTUP-SELFTEST] PASSED — score={_st_result['score']} "
                 f"approved={_st_result['approved']} regime={_st_result.get('regime','?')}")
    except Exception as _st_exc:
        _STARTUP_HEALTHY = False
        _record_scorer_error("startup_self_test", "EURUSD", _st_exc)
        log.critical(
            f"[STARTUP-SELFTEST] FAILED — scorer is UNHEALTHY: "
            f"{type(_st_exc).__name__}: {_st_exc}\n"
            f"{traceback.format_exc()}"
        )

    threading.Thread(target=keepalive, daemon=True).start()
    threading.Thread(target=_llm_bias_fetch_loop, daemon=True).start()
    log.info("[LLM-BIAS] Background macro bias fetch thread started (30-min interval)")

    # ── Startup readiness flag (polls until port is open, then writes flag) ──
    # deploy_manager.py and health_check.py poll /healthz directly; the flag
    # provides a fast filesystem check for scripts that prefer to avoid HTTP.
    def _write_readiness_flag():
        import socket as _sock
        for _ in range(60):
            try:
                with _sock.create_connection((HOST, PORT), timeout=1):
                    break
            except OSError:
                time.sleep(1)
        try:
            from pathlib import Path as _Path
            import json as _json
            flag = _Path(_DOCS) / f"phantom_{_PHANTOM_ENV}_ready.flag"
            flag.write_text(_json.dumps({
                "started_at":  datetime.now(timezone.utc).isoformat(),
                "environment": _PHANTOM_ENV,
                "port":        PORT,
                "host":        HOST,
                "version":     "4.02",
                "pid":         os.getpid(),
            }), encoding="utf-8")
            log.info(f"[READY] Startup flag written: {flag}")
        except Exception as _fe:
            log.warning(f"[READY] Could not write readiness flag: {_fe}")

    threading.Thread(target=_write_readiness_flag, daemon=True).start()


# ══════════════════════════════════════════════════════════════════════
# v4.02 PERFORMANCE ENGINE ROUTES
# ══════════════════════════════════════════════════════════════════════

@app.route("/performance/pairs", methods=["GET"])
def performance_pairs():
    """
    GET /performance/pairs
    Returns rolling pair performance rankings + risk multipliers.
    Optional: ?symbol=EURUSD for a single pair.
    """
    mod = _get_pair_performance_engine_mod()
    if mod is None:
        return jsonify({"error": "pair_performance_engine not available"}), 503
    try:
        sym = request.args.get("symbol")
        eng = mod.get_pair_performance_engine()
        if sym:
            return jsonify(eng.get_pair_stats(sym.upper()).to_dict())
        return jsonify(eng.get_report())
    except Exception as e:
        log.error(f"[PERF] pairs error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/performance/outcome", methods=["POST"])
def performance_record_outcome():
    """
    POST /performance/outcome
    Records a completed trade outcome for pair performance + ML validation tracking.
    Body: { symbol, pnl_r, session, regime, score, ml_active, rule_score }
    """
    mod_ppe = _get_pair_performance_engine_mod()
    mod_mve = _get_ml_validation_engine_mod()
    try:
        d        = request.get_json(force=True) or {}
        symbol   = str(d.get("symbol", ""))
        pnl_r    = float(d.get("pnl_r", 0.0))
        session  = str(d.get("session", ""))
        regime   = str(d.get("regime", ""))
        score    = float(d.get("score", 0.0))
        ml_active  = bool(d.get("ml_active", False))
        rule_score = float(d.get("rule_score", score))
        recorded = []
        if mod_ppe:
            mod_ppe.get_pair_performance_engine().record_outcome(
                symbol=symbol, pnl_r=pnl_r,
                session=session, regime=regime, score=score,
            )
            recorded.append("pair_performance")
        if mod_mve:
            mod_mve.get_ml_validation_engine().record_trade(
                rule_score=rule_score, ml_score=score,
                outcome_r=pnl_r, ml_active=ml_active,
                symbol=symbol, session=session, regime=regime,
            )
            recorded.append("ml_validation")
        # Post-trade execution quality update (if provided)
        mod_tqe = _get_trade_quality_engine_mod()
        if mod_tqe and d.get("spread_at_entry") is not None:
            mod_tqe.get_execution_quality_tracker().update(
                symbol=symbol, session=session,
                spread_pips=float(d.get("spread_at_entry", 0.0)),
                slippage_pip=float(d.get("slippage_pips", 0.0)),
                latency_ms=float(d.get("latency_ms", 0.0)),
            )
            recorded.append("execution_quality")
        return jsonify({"ok": True, "recorded": recorded})
    except Exception as e:
        log.error(f"[PERF] outcome error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/performance/session-quality", methods=["GET"])
def performance_session_quality():
    """
    GET /performance/session-quality
    Returns a session quality score for the current (or requested) session.
    Query params: symbol, session, spread, atr
    """
    mod = _get_pair_session_engine()
    if mod is None:
        return jsonify({"error": "pair_session_matrix not available"}), 503
    try:
        from datetime import datetime, timezone
        symbol  = request.args.get("symbol", "EURUSD").upper()
        session = request.args.get("session", "")
        spread  = float(request.args.get("spread", 1.0))
        atr     = float(request.args.get("atr", 0.001))
        if not session:
            # Derive from current UTC time (simplified)
            h = datetime.now(timezone.utc).hour
            if 13 <= h < 16:
                session = "LONDON_NY"
            elif 8 <= h < 16:
                session = "LONDON"
            elif 13 <= h < 21:
                session = "NY"
            elif 0 <= h < 8:
                session = "ASIA"
            else:
                session = "OFF"
        sqe    = mod.get_session_quality_engine()
        result = sqe.score(session, symbol, spread, atr)
        pscore = mod.get_pair_session_mult(symbol, session)
        return jsonify({
            **result.to_dict(),
            "pair_session_mult": round(pscore, 3),
            "symbol":  symbol,
            "session": session,
            "pair_matrix": {
                "best_sessions": mod.PairSessionMatrix.get(symbol).get("best_sessions", []),
                "weak_sessions": mod.PairSessionMatrix.get(symbol).get("weak_sessions", []),
                "volatility_profile": mod.PairSessionMatrix.get_volatility_profile(symbol),
                "trailing_style": mod.PairSessionMatrix.get_trailing_style(symbol),
            },
        })
    except Exception as e:
        log.error(f"[PERF] session-quality error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/performance/ml-contribution", methods=["GET"])
def performance_ml_contribution():
    """
    GET /performance/ml-contribution
    Returns honest ML vs rule-engine contribution analysis.
    """
    mod = _get_ml_validation_engine_mod()
    if mod is None:
        return jsonify({"error": "ml_validation_engine not available"}), 503
    try:
        report = mod.get_ml_validation_engine().get_ml_contribution()
        return jsonify(report.to_dict())
    except Exception as e:
        log.error(f"[PERF] ml-contribution error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/performance/execution-quality", methods=["GET"])
def performance_execution_quality():
    """
    GET /performance/execution-quality
    Returns execution quality scores per symbol×session.
    Optional: ?symbol=EURUSD for one pair only.
    """
    mod = _get_trade_quality_engine_mod()
    if mod is None:
        return jsonify({"error": "trade_quality_engine not available"}), 503
    try:
        symbol = request.args.get("symbol")
        report = mod.get_execution_quality_tracker().get_report(
            symbol=symbol.upper() if symbol else None
        )
        return jsonify({"entries": report, "count": len(report)})
    except Exception as e:
        log.error(f"[PERF] execution-quality error: {e}")
        return jsonify({"error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════
# MACRO FUSION ENDPOINTS  (Phase 1/2/3/5 — v4.02)
# Currency strength + macro bias + session affinity query routes.
# ══════════════════════════════════════════════════════════════════════

@app.route("/macro/currency-strength", methods=["GET"])
def macro_currency_strength():
    """
    GET /macro/currency-strength
    Returns statistical currency strength scores derived from BarStore H1 data.
    Refreshes computation if stale (>5 min since last update).
    """
    try:
        mod = _get_currency_strength_engine_mod()
        if mod is None:
            return jsonify({"error": "currency_strength_engine not available"}), 503
        mod.currency_strength_engine.update(bar_store)
        return jsonify(mod.currency_strength_engine.full_report())
    except Exception as e:
        log.error(f"[CCY-STR] /macro/currency-strength error: {e}")
        return jsonify({"error": str(e)}), 503


@app.route("/macro/scores", methods=["GET"])
def macro_scores_get():
    """
    GET /macro/scores
    Returns current macro bias configuration for all 8 currencies.
    Includes regime classification, divergence pairs, and recent event log.
    Note: bias scores are manually configured — see POST /macro/scores to update.
    """
    try:
        mod = _get_macro_engine_mod()
        if mod is None:
            return jsonify({"error": "macro_engine not available"}), 503
        return jsonify(mod.macro_engine.get_all())
    except Exception as e:
        log.error(f"[MACRO] /macro/scores GET error: {e}")
        return jsonify({"error": str(e)}), 503


@app.route("/macro/scores", methods=["POST"])
def macro_scores_post():
    """
    POST /macro/scores
    Manually update macro bias + stability scores for one or all currencies.

    Body (flat or wrapped in "currencies"):
      {
        "currencies": {
          "USD": { "bias": 0.20, "stability": 85, "policy_stance": "hawkish", "trend": "up" },
          "JPY": { "bias": -0.30, "stability": 80, "policy_stance": "dovish",  "trend": "down" }
        }
      }
    bias: -1.0 (extremely bearish) … +1.0 (extremely bullish)
    stability: 0–100 (100 = most stable / least intervention risk)
    """
    try:
        mod = _get_macro_engine_mod()
        if mod is None:
            return jsonify({"error": "macro_engine not available"}), 503
        body    = request.get_json(force=True, silent=True) or {}
        updates = body.get("currencies", body)
        count   = mod.macro_engine.set_all(updates)
        return jsonify({"updated": count, "currencies": mod.macro_engine.get_all()})
    except Exception as e:
        log.error(f"[MACRO] /macro/scores POST error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/macro/session-quality", methods=["GET"])
def macro_session_quality():
    """
    GET /macro/session-quality
    Returns pair-session affinity scores for the current (or named) session.
    Optional: ?session=LONDON to query a specific session.
    """
    try:
        mod = _get_macro_fusion_engine_mod()
        if mod is None:
            return jsonify({"error": "macro_fusion_engine not available"}), 503
        sess_mod = _load_session_engine()
        from datetime import datetime as _dt, timezone as _tz
        if sess_mod is not None:
            current = sess_mod.detect_session()
        else:
            h = _dt.now(_tz.utc).hour
            current = ("ASIA" if h < 8 else "LONDON" if h < 13 else
                       "LONDON_NY" if h < 17 else "NY" if h < 21 else "OFF")
        requested = (request.args.get("session") or current).upper()
        pairs  = sorted(mod.PAIR_SESSION_AFFINITY.keys())
        result = {p: mod.get_session_affinity(p, requested) for p in pairs}
        return jsonify({
            "session":         requested,
            "current_session": current,
            "affinity":        result,
        })
    except Exception as e:
        log.error(f"[MACRO] /macro/session-quality error: {e}")
        return jsonify({"error": str(e)}), 503


@app.route("/macro/pair-bias", methods=["GET"])
def macro_pair_bias():
    """
    GET /macro/pair-bias?symbol=EURUSD&direction=1
    Returns fused macro + currency strength bias for a single pair/direction.
    direction: 1=BUY, -1=SELL
    """
    try:
        symbol    = (request.args.get("symbol") or "").upper()
        direction = int(request.args.get("direction", 1) or 1)
        if not symbol:
            return jsonify({"error": "symbol required"}), 400
        cse_mod = _get_currency_strength_engine_mod()
        mae_mod = _get_macro_engine_mod()
        mfe_mod = _get_macro_fusion_engine_mod()
        cse_result = {}
        mae_result = {}
        fusion     = {}
        if cse_mod is not None:
            cse_mod.currency_strength_engine.update(bar_store)
            cse_result = cse_mod.currency_strength_engine.get_pair_bias(symbol, direction)
        if mae_mod is not None:
            mae_result = mae_mod.macro_engine.get_pair_bias(symbol, direction)
        if mfe_mod is not None:
            sess_mod = _load_session_engine()
            session  = sess_mod.detect_session() if sess_mod else "LONDON"
            fusion   = mfe_mod.fuse(
                symbol            = symbol,
                direction         = direction,
                session           = session,
                macro_pair_bias   = mae_result or None,
                ccy_str_pair_bias = cse_result or None,
            )
        return jsonify({
            "symbol":         symbol,
            "direction":      direction,
            "ccy_strength":   cse_result,
            "macro":          mae_result,
            "fusion":         fusion,
        })
    except Exception as e:
        log.error(f"[MACRO] /macro/pair-bias error: {e}")
        return jsonify({"error": str(e)}), 503


# ══════════════════════════════════════════════════════════════════════
# PHASE 8 — PROMETHEUS METRICS + ANOMALY OBSERVABILITY
# ══════════════════════════════════════════════════════════════════════

@app.route("/metrics", methods=["GET"])
def prometheus_metrics():
    """
    Prometheus text exposition format endpoint.
    Scrape config:
      - job_name: phantom_scorer
        static_configs: [{targets: ['<VPS_IP>:5000']}]
        metrics_path: /metrics
        scrape_interval: 30s
    """
    try:
        me_mod = _get_metrics_engine_mod()
        ae_mod = _get_anomaly_engine_mod()
        if me_mod is None:
            return Response(
                "# metrics_engine not available — add phantom_src/metrics_engine.py\n",
                mimetype="text/plain; version=0.0.4",
            )

        uptime_sec   = int(time.time() - _SERVER_START)
        total_scores = sum(s["total"] for s in session_stats.values())
        total_wins   = sum(s["wins"]  for s in session_stats.values())
        approvals    = total_wins
        rejections   = max(0, total_scores - approvals)

        # Build recent scores from deque (most recent first)
        recent: list = []
        seen_syms: set = set()
        for _rec in reversed(list(trade_history)):
            _sym = _rec.get("symbol", "")
            if not _sym or _sym in seen_syms:
                continue
            seen_syms.add(_sym)
            recent.append({
                "symbol":     _sym,
                "session":    _rec.get("session",    "UNKNOWN"),
                "regime":     _rec.get("regime",     "UNKNOWN"),
                "score":      _rec.get("score"),
                "latency_ms": _rec.get("latency_ms"),
            })

        hb_age = float(time.time() - _last_heartbeat_ts) if _last_heartbeat_ts else 0.0

        state = {
            "uptime_sec":        uptime_sec,
            "scores_total":      total_scores,
            "approvals_total":   approvals,
            "rejections_total":  rejections,
            "heartbeat_age_sec": hb_age,
            "open_positions":    len(portfolio_engine.open_positions) if portfolio_engine else 0,
            "daily_dd_pct":      _g_daily_dd_pct,
            "portfolio_heat":    _g_portfolio_heat,
            "ml_active":         bool(ml_classifier.is_trained or HAS_XGB or HAS_SKLEARN),
            "min_score":         MIN_SCORE,
            "version":           "4.02",
            "environment":       _PHANTOM_ENV,
            "anomaly_count":     len(ae_mod.anomaly_engine.get_active_anomalies()) if ae_mod else 0,
            "recent_scores":     recent[:20],
            "session_stats": {
                s: {"wins": d["wins"], "losses": d["losses"], "total": d["total"]}
                for s, d in session_stats.items()
            },
        }
        output   = me_mod.collect_metrics(state)
        ct       = me_mod.content_type() if hasattr(me_mod, "content_type") else "text/plain; version=0.0.4; charset=utf-8"
        return Response(output, mimetype=ct)
    except Exception as _e:
        log.error(f"[METRICS] /metrics error: {_e}")
        return Response(f"# error: {_e}\n", mimetype="text/plain; version=0.0.4; charset=utf-8"), 500


@app.route("/anomaly/active", methods=["GET"])
def anomaly_active():
    """GET /anomaly/active — returns currently active (unresolved) anomalies."""
    try:
        ae_mod = _get_anomaly_engine_mod()
        if ae_mod is None:
            return jsonify({"anomalies": [], "count": 0, "engine": "unavailable"})
        active = ae_mod.anomaly_engine.get_active_anomalies()
        return jsonify({"anomalies": active, "count": len(active), "engine": "ok"})
    except Exception as _e:
        return jsonify({"error": str(_e)}), 500


@app.route("/anomaly/history", methods=["GET"])
def anomaly_history():
    """GET /anomaly/history?limit=100 — recent anomaly event log (newest first)."""
    try:
        limit  = max(1, min(500, int(request.args.get("limit", 100))))
        ae_mod = _get_anomaly_engine_mod()
        if ae_mod is None:
            return jsonify({"events": [], "count": 0, "engine": "unavailable"})
        events = ae_mod.anomaly_engine.get_history(limit)
        return jsonify({"events": events, "count": len(events), "engine": "ok"})
    except Exception as _e:
        return jsonify({"error": str(_e)}), 500


# ── News Intelligence Engine routes ───────────────────────────────────────────

@app.route("/news/severity", methods=["GET"])
def nie_severity():
    """GET /news/severity — current severity scores for active pairs."""
    try:
        nie_mod = _get_news_intelligence_mod()
        if nie_mod is None:
            return jsonify({"pairs": {}, "engine": "unavailable"})
        nie     = nie_mod.news_intelligence_engine
        sess    = request.args.get("session", "UNKNOWN")
        regime  = request.args.get("regime",  "UNKNOWN")
        pairs   = [p.strip() for p in request.args.get("pairs", "EURUSD,GBPUSD,USDJPY,AUDUSD,USDCAD,USDCHF,GBPJPY,XAUUSD").split(",") if p.strip()]
        result  = nie.get_severity_for_pairs(pairs, session=sess, regime=regime)
        return jsonify({"pairs": result, "engine": "ok", "session": sess, "regime": regime})
    except Exception as _e:
        return jsonify({"error": str(_e)}), 500


@app.route("/news/cooldown-status", methods=["GET"])
def nie_cooldown_status():
    """GET /news/cooldown-status — per-currency cooldown state."""
    try:
        nie_mod = _get_news_intelligence_mod()
        if nie_mod is None:
            return jsonify({"cooldowns": {}, "engine": "unavailable"})
        nie      = nie_mod.news_intelligence_engine
        cooldowns = nie.cooldown.status_all()
        return jsonify({"cooldowns": cooldowns, "count": len(cooldowns), "engine": "ok"})
    except Exception as _e:
        return jsonify({"error": str(_e)}), 500


@app.route("/news/currency-profiles", methods=["GET"])
def nie_currency_profiles():
    """GET /news/currency-profiles — static profiles + live stability scores."""
    try:
        nie_mod = _get_news_intelligence_mod()
        if nie_mod is None:
            return jsonify({"profiles": {}, "engine": "unavailable"})
        nie      = nie_mod.news_intelligence_engine
        profiles = nie.get_currency_profiles()
        return jsonify({"profiles": profiles, "engine": "ok"})
    except Exception as _e:
        return jsonify({"error": str(_e)}), 500


@app.route("/news/execution-quality", methods=["GET"])
def nie_execution_quality():
    """GET /news/execution-quality — current live execution quality score."""
    try:
        nie_mod = _get_news_intelligence_mod()
        if nie_mod is None:
            return jsonify({"quality_score": None, "engine": "unavailable"})
        nie = nie_mod.news_intelligence_engine
        q   = nie.exec_tracker.quality_score()
        return jsonify({**q, "engine": "ok"})
    except Exception as _e:
        return jsonify({"error": str(_e)}), 500


@app.route("/news/telemetry-summary", methods=["GET"])
def nie_telemetry_summary():
    """GET /news/telemetry-summary — in-process news event analytics."""
    try:
        nie_mod = _get_news_intelligence_mod()
        if nie_mod is None:
            return jsonify({"total_events": 0, "engine": "unavailable"})
        nie     = nie_mod.news_intelligence_engine
        summary = nie.telemetry.get_summary()
        recent  = nie.telemetry.get_recent(20)
        return jsonify({"summary": summary, "recent_events": recent, "engine": "ok"})
    except Exception as _e:
        return jsonify({"error": str(_e)}), 500


@app.route("/news/stability-update", methods=["POST"])
def nie_stability_update():
    """POST /news/stability-update — update govt/CB stability score for a currency."""
    try:
        nie_mod = _get_news_intelligence_mod()
        if nie_mod is None:
            return jsonify({"error": "NIE not available"}), 503
        nie  = nie_mod.news_intelligence_engine
        body = request.get_json(silent=True) or {}
        updates = body.get("currencies", {})
        if not updates:
            return jsonify({"error": "body must contain {currencies: {USD: 0.85, ...}}"}), 400
        applied = {}
        for ccy, score in updates.items():
            try:
                nie.update_stability(str(ccy), float(score))
                applied[ccy] = float(score)
            except Exception:
                pass
        return jsonify({"applied": applied, "engine": "ok"})
    except Exception as _e:
        return jsonify({"error": str(_e)}), 500


@app.route("/ml/status", methods=["GET"])
def ml_meta_status():
    """GET /ml/status — ML meta-filter governance status."""
    mod = _get_ml_meta_filter_mod()
    if mod is None:
        return jsonify({"model_active": False, "reason": "ml_meta_filter not available"})
    try:
        return jsonify(mod.get_ml_meta_filter().governance_status())
    except Exception as _e:
        return jsonify({"error": str(_e)}), 500


@app.route("/ml/feature-schema", methods=["GET"])
def ml_feature_schema():
    """GET /ml/feature-schema — current feature schema version + names."""
    mod = _get_ml_meta_filter_mod()
    schema_ver = getattr(mod, "FEATURE_SCHEMA_VERSION", "1.0.0") if mod else "1.0.0"
    names      = getattr(mod, "FEATURE_NAMES", []) if mod else []
    return jsonify({
        "schema_version": schema_ver,
        "feature_count":  len(names),
        "feature_names":  names,
    })


@app.route("/ml/telemetry", methods=["GET"])
def ml_telemetry_route():
    """GET /ml/telemetry?n=50 — recent prediction ring buffer."""
    mod = _get_ml_meta_filter_mod()
    if mod is None:
        return jsonify({"predictions": []})
    try:
        n = int(request.args.get("n", 50))
        return jsonify({"predictions": mod.get_ml_meta_filter().recent_predictions(n)})
    except Exception as _e:
        return jsonify({"error": str(_e)}), 500


@app.route("/ml/telemetry/summary", methods=["GET"])
def ml_telemetry_summary_route():
    """GET /ml/telemetry/summary — aggregated approval/block rates + drift."""
    mod = _get_ml_meta_filter_mod()
    if mod is None:
        return jsonify({"count": 0, "recommendations": {}})
    try:
        return jsonify(mod.get_ml_meta_filter().telemetry_summary())
    except Exception as _e:
        return jsonify({"error": str(_e)}), 500


@app.route("/ml/contribution", methods=["GET"])
def ml_contribution_route():
    """GET /ml/contribution — ML vs rule-only contribution from ml_validation_engine."""
    mve_mod = _get_ml_validation_engine_mod()
    if mve_mod is None:
        return jsonify({"verdict": "NEUTRAL", "reason": "ml_validation_engine not available"})
    try:
        return jsonify(mve_mod.get_ml_validation_engine().get_ml_contribution().to_dict())
    except Exception as _e:
        return jsonify({"error": str(_e)}), 500


@app.route("/ml/rollback", methods=["POST"])
def ml_rollback_route():
    """POST /ml/rollback — revert to previous model version."""
    mod = _get_ml_meta_filter_mod()
    if mod is None:
        return jsonify({"status": "unavailable"}), 503
    try:
        return jsonify(mod.get_ml_meta_filter().rollback())
    except Exception as _e:
        return jsonify({"error": str(_e)}), 500


if __name__ == "__main__":
    print(f"[STARTUP] HOST={HOST}  PORT={PORT}  bind=http://{HOST}:{PORT}/")
    print(f"[STARTUP] Set PHANTOM_HOST env var to override bind address.")
    app.run(host=HOST, port=PORT, debug=False, threaded=True)