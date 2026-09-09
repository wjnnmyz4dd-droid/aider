"""Tier 1 historical replay harness (measurement/orchestration ONLY).

This package measures the FROZEN Session Edge strategy by REUSING the canonical
production strategy engine (``run_dir/code/signal_engine.py``) verbatim. It has
ZERO authority over signal generation, direction, entry, stop, target, session,
trend, breakout/retest, compliance, news, risk, PR-3J sizing, or Position Manager
logic — it only drives the real engine over historical bars, reconstructs trade
records from the engine's OWN audit output, and delegates all performance math to
the existing ``research.portfolio`` analytics.

Tier 1 is STRATEGY-EDGE RESEARCH under the engine's own canonical static SL/TP/
time-exit model. It is NOT a live MT5 simulation, NOT a full FTMO-compliance
simulation, NOT a Position Manager simulation, NOT a historical-news-complete
simulation, and NOT a production fill simulation. Every report carries that label.
"""

from __future__ import annotations

__all__ = ["replay", "trade_records", "runner"]
