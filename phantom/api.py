"""Read-only HTTP API (Python stdlib only).

Routes are registered in an explicit table (``_ROUTES``) so the registration
point is unambiguous. Everything here is read-only — the API never triggers a
scan or an order; it reports state the scanner has already produced.

    GET /health                 -> liveness
    GET /orb/status             -> active ORB sessions, ORB high/low per pair,
                                   breakout status, last ORB decision
    GET /orb/log                -> recent ORB decision log records
    GET /scan/log               -> recent scan decision log records
    GET /strategies/performance -> Strategy Performance Panel (per-strategy
                                   trades / win rate / profit factor / P&L,
                                   plus best & worst)
    GET /metrics                -> Prometheus text exposition of the above
                                   (scrape target for Grafana). Export only.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Dict, Tuple
from urllib.parse import urlparse

from .app import PhantomApp


def _orb_status(app: PhantomApp, query: dict) -> Tuple[int, dict]:
    now = datetime.now(timezone.utc)
    return 200, app.orb.status(now)


def _orb_log(app: PhantomApp, query: dict) -> Tuple[int, dict]:
    limit = int(query.get("limit", ["50"])[0])
    return 200, {"records": app.sink.recent("orb", limit)}


def _scan_log(app: PhantomApp, query: dict) -> Tuple[int, dict]:
    limit = int(query.get("limit", ["50"])[0])
    return 200, {"records": app.sink.recent("scan", limit)}


def _strategies_performance(app: PhantomApp, query: dict) -> Tuple[int, dict]:
    return 200, app.performance.panel()


def _metrics(app: PhantomApp, query: dict) -> Tuple[int, str]:
    from .metrics import render
    return 200, render(app, datetime.now(timezone.utc))


def _compliance_view(app: PhantomApp):
    cs = app.compliance.state()
    status = "KILL_SWITCH" if cs["killswitch_active"] else ("LOCKED" if cs["locked_day"] else "OK")
    return cs, status


def _risk_status(app: PhantomApp, query: dict) -> Tuple[int, dict]:
    cs, _status = _compliance_view(app)
    return 200, app.risk.evaluate(current_dd_pct=cs["total_dd_pct"]).as_dict()


def _risk_analytics(app: PhantomApp, query: dict) -> Tuple[int, dict]:
    cs, status = _compliance_view(app)
    return 200, app.risk.analytics(
        compliance_status=status,
        current_dd_pct=cs["total_dd_pct"],
        peak_dd_pct=cs["total_dd_pct"],
    )


def _risk_sizing(app: PhantomApp, query: dict) -> Tuple[int, dict]:
    try:
        symbol = query.get("symbol", ["EURUSD"])[0]
        equity = float(query.get("equity", ["0"])[0])
        stop = float(query.get("stop", ["0"])[0])
    except (ValueError, IndexError):
        return 400, {"error": "equity and stop must be numbers"}
    return 200, app.size_trade(symbol, equity, stop).as_dict()


def _health(app: PhantomApp, query: dict) -> Tuple[int, dict]:
    return 200, {"status": "ok", "service": "phantom", "now": datetime.now(timezone.utc).isoformat()}


# --- ROUTE REGISTRATION POINT -------------------------------------------------
_ROUTES: Dict[Tuple[str, str], Callable[[PhantomApp, dict], Tuple[int, object]]] = {
    ("GET", "/health"): _health,
    ("GET", "/orb/status"): _orb_status,
    ("GET", "/orb/log"): _orb_log,
    ("GET", "/scan/log"): _scan_log,
    ("GET", "/strategies/performance"): _strategies_performance,
    ("GET", "/metrics"): _metrics,
    ("GET", "/risk/status"): _risk_status,
    ("GET", "/risk/analytics"): _risk_analytics,
    ("GET", "/risk/sizing"): _risk_sizing,
}


def make_handler(app: PhantomApp):
    from urllib.parse import parse_qs

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):  # silence default stderr logging
            pass

        def _dispatch(self):
            parsed = urlparse(self.path)
            handler = _ROUTES.get((self.command, parsed.path))
            if handler is None:
                self._send(404, {"error": "not found", "path": parsed.path})
                return
            try:
                status, body = handler(app, parse_qs(parsed.query))
            except Exception as exc:  # pragma: no cover - defensive
                self._send(500, {"error": str(exc)})
                return
            self._send(status, body)

        def do_GET(self):
            self._dispatch()

        def _send(self, status: int, body):
            if isinstance(body, str):  # Prometheus exposition (text/plain)
                payload = body.encode("utf-8")
                ctype = "text/plain; version=0.0.4; charset=utf-8"
            else:
                payload = json.dumps(body, default=str).encode("utf-8")
                ctype = "application/json"
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    return Handler


def serve(app: PhantomApp, host: str = "127.0.0.1", port: int = 8080) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), make_handler(app))
    return server


def registered_routes():
    """Expose the route table for diagnostics / the validation suite."""
    return [f"{method} {path}" for (method, path) in _ROUTES]
