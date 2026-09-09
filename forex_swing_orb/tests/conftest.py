"""Pytest fixtures for the Forex Swing-ORB SignalEngine tests.

The engine module is loaded by file path exactly the way Vibe-Trading's backtest
runner loads a run-dir signal engine, so the tests exercise the real deliverable.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ENGINE_PATH = Path(__file__).resolve().parents[1] / "run_dir" / "code" / "signal_engine.py"


def _load_engine_module():
    spec = importlib.util.spec_from_file_location("swing_orb_signal_engine", ENGINE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def se():
    return _load_engine_module()


@pytest.fixture(scope="session")
def synthmod():
    import synth
    return synth


@pytest.fixture
def bullish_setup(synthmod):
    df = synthmod.uptrend_frame(days=60)
    df2, ref = synthmod.inject_bullish_orb(df, "2024-01-25")
    return df2, ref


@pytest.fixture
def bearish_setup(synthmod):
    df = synthmod.downtrend_frame(days=60)
    df2, ref = synthmod.inject_bearish_orb(df, "2024-01-25")
    return df2, ref
