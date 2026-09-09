"""Fixtures for the Phase 4A multi-agent foundation tests."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]   # .../aider
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from forex_swing_orb.agents import (Orchestrator, MockLLMProvider, MemoryStore,  # noqa: E402
                                    build_request, StrategyCandidate)
from forex_swing_orb.bridge.audit import AuditLog                                # noqa: E402

NOW = datetime(2024, 1, 25, 12, 0, 0, tzinfo=timezone.utc)


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def now():
    return NOW


@pytest.fixture
def memory(tmp_path):
    return MemoryStore(tmp_path / "mem")


@pytest.fixture
def audit(tmp_path):
    return AuditLog(tmp_path / "agent_audit.jsonl")


@pytest.fixture
def llm():
    return MockLLMProvider()


@pytest.fixture
def orchestrator(memory, audit, llm):
    return Orchestrator(memory, audit, llm=llm)


def make_request(symbol="EURUSD.FX", correlation_id="corr-1"):
    return build_request(symbol, iso(NOW), "forex_swing_orb", "swing_orb.v1.4.0",
                         "md://ref", "news://ref", "mem://ref", correlation_id)


def good_bundle(now=NOW):
    fresh = iso(now - timedelta(minutes=1))
    return {
        "market": {"timestamp": fresh, "provenance": "price_feed", "timezone": "UTC",
                   "bars_monotonic": True, "regime": "TRENDING", "htf_structure": "HH_HL",
                   "session": "LONDON", "volatility": "NORMAL",
                   "trend_continuation": "YES", "ranging_vs_trending": "TRENDING",
                   "age_sec": 60},
        "news": {"timestamp": fresh, "provenance": "calendar", "verified": True,
                 "events": [], "age_sec": 60, "pre_lockout_min": 30, "post_lockout_min": 30},
        "liquidity": {"retest_quality": "GOOD", "breakout_trap_risk": False,
                      "equal_highs": True, "equal_lows": False, "prior_session_high": 1.10,
                      "prior_session_low": 1.09, "swing_highs": [], "swing_lows": [],
                      "liquidity_pools": [], "liquidity_sweeps": False,
                      "failed_breakouts": False, "stop_clusters": []},
        "risk": {"open_positions_symbol": 0, "planned_rr": 2.0, "stop_distance_pips": 20,
                 "account_daily_loss_pct": 0.5, "account_drawdown_pct": 1.0,
                 "max_daily_loss_pct": 3.0, "max_drawdown_pct": 10.0,
                 "correlated_exposure_count": 0},
        "critic_flags": {},
    }
