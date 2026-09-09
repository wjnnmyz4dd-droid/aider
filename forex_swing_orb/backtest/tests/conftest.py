"""Fixtures for the Tier 1 replay harness tests.

Reuses the SAME deterministic synthetic OHLC generators the engine's own tests use
(``forex_swing_orb/tests/synth.py``) so the harness is exercised against frames
that drive the REAL frozen engine to real ENTER/EXIT episodes. No market data is
invented; synthetic frames prove HARNESS VALIDITY only, never strategy performance.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
ENGINE_TESTS_DIR = REPO / "forex_swing_orb" / "tests"
for p in (str(REPO), str(ENGINE_TESTS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import synth  # noqa: E402  (from forex_swing_orb/tests, added to path above)

from forex_swing_orb.backtest import replay  # noqa: E402

# Tier 1 STRATEGY-ONLY RESEARCH config: explicit news research bypass (no historical
# news dataset exists; never fabricate events, never use today's news). Documented
# limitation surfaced in every report.
RESEARCH_CONFIG = {"news_research_bypass": True}

# Compact but sufficient: 30 days of M15 (2880 bars) keeps the O(n^2) online parity
# replay tractable while giving the engine enough history for D1 trend health.
GOLDEN_DAYS = 30
GOLDEN_DAY = "2024-01-25"
SYMBOL = "EURUSD.FX"


@pytest.fixture(scope="session")
def engine_module():
    module, _ = replay.load_engine(RESEARCH_CONFIG)
    return module


@pytest.fixture
def golden_bull():
    df = synth.uptrend_frame(days=GOLDEN_DAYS)
    df2, ref = synth.inject_bullish_orb(df, GOLDEN_DAY)
    return {SYMBOL: df2}, ref


@pytest.fixture
def golden_bear():
    df = synth.downtrend_frame(days=GOLDEN_DAYS)
    df2, ref = synth.inject_bearish_orb(df, GOLDEN_DAY)
    return {SYMBOL: df2}, ref


@pytest.fixture
def flat_frame():
    # a clean uptrend with NO injected ORB episode -> few/zero setups; used for the
    # empty/no-signal path.
    df = synth.uptrend_frame(days=GOLDEN_DAYS)
    return {SYMBOL: df}
