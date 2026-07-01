"""Prometheus-compatible metrics export (stdlib only).

Observability layer — it reads existing pipeline state and emits it in the
Prometheus text exposition format (v0.0.4). It never touches trading, execution,
risk, or scoring logic. Counters are incremented by the scanner after a decision
is already made; gauges are computed at scrape time from the same data the
dashboard endpoints already return.
"""

from __future__ import annotations

import threading
from typing import Dict, List, Optional, Tuple

# name -> (type, help). Keeps HELP/TYPE lines consistent across counters/gauges.
_META: Dict[str, Tuple[str, str]] = {
    "phantom_up": ("gauge", "1 if the service is responding."),
    "phantom_scans_total": ("counter", "Scans completed, by decision and direction."),
    "phantom_strategy_signals_total": ("counter", "Strategy signals, by strategy and outcome."),
    "phantom_strategy_conflicts_total": ("counter", "Scans where strategies disagreed on direction."),
    "phantom_orb_confirmed_total": ("counter", "ORB confirmations."),
    "phantom_orb_false_breakout_total": ("counter", "ORB false breakouts."),
    "phantom_orb_duplicate_suppressed_total": ("counter", "ORB duplicate confirmations suppressed (idempotency)."),
    "phantom_orb_blocked_total": ("counter", "ORB evaluations blocked by a gate."),
    "phantom_guard_blocks_total": ("counter", "Blocking-guard failures, by guard."),
    "phantom_warmup_total": ("counter", "Scans flagged insufficient-data / warmup."),
    "phantom_last_score": ("gauge", "Most recent composite score, by symbol."),
    "phantom_strategy_trades": ("gauge", "Recorded trades, by strategy."),
    "phantom_strategy_win_rate": ("gauge", "Win rate (0..1), by strategy."),
    "phantom_strategy_profit_factor": ("gauge", "Profit factor, by strategy (+Inf when no losses)."),
    "phantom_strategy_pl": ("gauge", "Net P/L, by strategy."),
    "phantom_strategy_selected": ("gauge", "1 for the best/worst strategy by role."),
    "phantom_orb_active_sessions": ("gauge", "Active ORB sessions right now."),
    "phantom_orb_ranges_tracked": ("gauge", "ORB ranges currently tracked."),
    "phantom_orb_confirmed_sessions": ("gauge", "Confirmed ORB sessions retained (idempotency)."),
    "phantom_orb_processed_signal_ids": ("gauge", "Processed ORB signal ids retained (idempotency)."),
}

# A metric sample: (labels-as-sorted-tuple, value).
Labels = Tuple[Tuple[str, str], ...]


def _key(labels: Optional[Dict[str, str]]) -> Labels:
    return tuple(sorted((str(k), str(v)) for k, v in (labels or {}).items()))


class MetricsRegistry:
    """Thread-safe counters and gauges. Additive; incrementing has no effect on
    any pipeline decision."""

    def __init__(self):
        self._lock = threading.Lock()
        self._counters: Dict[Tuple[str, Labels], float] = {}
        self._gauges: Dict[Tuple[str, Labels], float] = {}

    def inc(self, name: str, labels: Optional[Dict[str, str]] = None, amount: float = 1.0) -> None:
        k = (name, _key(labels))
        with self._lock:
            self._counters[k] = self._counters.get(k, 0.0) + amount

    def set_gauge(self, name: str, labels: Optional[Dict[str, str]] = None, value: float = 0.0) -> None:
        k = (name, _key(labels))
        with self._lock:
            self._gauges[k] = value

    def snapshot(self):
        with self._lock:
            return dict(self._counters), dict(self._gauges)


def _esc(s: str) -> str:
    return str(s).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _fmt(v) -> str:
    if v is None:
        return "+Inf"  # analytics reports None for an infinite profit factor
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, int):
        return str(v)
    f = float(v)
    if f == float("inf"):
        return "+Inf"
    if f == float("-inf"):
        return "-Inf"
    if f != f:
        return "NaN"
    return repr(f)


def _labels_str(labels: Labels) -> str:
    if not labels:
        return ""
    return "{" + ",".join(f'{k}="{_esc(v)}"' for k, v in labels) + "}"


def render(app, now) -> str:
    """Render the full exposition text for ``app`` at time ``now``."""
    counters, gauges = app.metrics.snapshot()

    # name -> (type, list[(labels, value)])
    series: Dict[str, List[Tuple[Labels, object]]] = {}
    types: Dict[str, str] = {}

    def add(name: str, mtype: str, labels: Labels, value) -> None:
        series.setdefault(name, []).append((labels, value))
        types[name] = mtype

    # --- registry-driven counters + gauges ---
    for (name, labels), value in counters.items():
        add(name, _META.get(name, ("counter", ""))[0], labels, value)
    for (name, labels), value in gauges.items():
        add(name, _META.get(name, ("gauge", ""))[0], labels, value)

    # --- static/service ---
    add("phantom_up", "gauge", (), 1)

    # --- strategy performance (existing dashboard: /strategies/performance) ---
    panel = app.performance.panel()
    for strat, st in panel["strategies"].items():
        lbl: Labels = (("strategy", strat),)
        add("phantom_strategy_trades", "gauge", lbl, st["trades"])
        add("phantom_strategy_win_rate", "gauge", lbl, st["win_rate"])
        add("phantom_strategy_profit_factor", "gauge", lbl, st["profit_factor"])
        add("phantom_strategy_pl", "gauge", lbl, st["pl"])
    for role in ("best", "worst"):
        chosen = panel.get(role)
        if chosen:
            add("phantom_strategy_selected", "gauge",
                (("role", role), ("strategy", chosen)), 1)

    # --- ORB status (existing dashboard: /orb/status) ---
    status = app.orb.status(now)
    add("phantom_orb_active_sessions", "gauge", (), len(status["active_sessions"]))
    add("phantom_orb_ranges_tracked", "gauge", (), len(status["ranges"]))
    add("phantom_orb_confirmed_sessions", "gauge", (), status["confirmed_sessions"])
    add("phantom_orb_processed_signal_ids", "gauge", (), status["processed_signal_ids"])

    # --- emit ---
    lines: List[str] = []
    for name in sorted(series):
        help_text = _META.get(name, (types[name], ""))[1]
        if help_text:
            lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} {types[name]}")
        for labels, value in series[name]:
            lines.append(f"{name}{_labels_str(labels)} {_fmt(value)}")
    return "\n".join(lines) + "\n"
