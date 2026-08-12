"""Deterministic instruction builder for the execution-adapter tests.

Kept in a uniquely-named module (not ``conftest``) so it never collides with the
bridge suite's ``conftest.make_instruction`` when both suites run together.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]   # .../aider
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from forex_swing_orb.bridge import serialize   # noqa: E402

NOW = datetime(2024, 1, 25, 12, 0, 0, tzinfo=timezone.utc)


def make_instruction(signal_id="a1b2c3d4e5f60718", direction="LONG",
                     entry=1.10000, stop=None, target=None, now=NOW,
                     symbol="EURUSD.FX", strategy_version="swing_orb.v1.4.0",
                     schema_version=2, generated=None, expiration=None,
                     session_id="LONDON"):
    """A valid engine-shaped instruction dict (WITHOUT integrity_digest)."""
    if stop is None:
        stop = entry - 0.0020 if direction == "LONG" else entry + 0.0020
    if target is None:
        target = entry + 0.0040 if direction == "LONG" else entry - 0.0040
    gen = generated or (now - timedelta(minutes=15))
    exp = expiration or (now + timedelta(minutes=30))
    return {
        "schema_version": schema_version,
        "signal_id": signal_id,
        "session_id": session_id,
        "strategy_id": "forex_swing_orb",
        "strategy_version": strategy_version,
        "symbol": symbol,
        "direction": direction,
        "entry_price": round(entry, 5),
        "stop_loss": round(stop, 5),
        "take_profit": round(target, 5),
        "risk_fraction": 0.0025,
        "generated_timestamp": serialize.iso_utc(gen),
        "expiration_timestamp": serialize.iso_utc(exp),
        "evidence_summary": {"trend_d1": "BULLISH", "trend_h4": "BULLISH"},
        "news_eligibility": {"mode": "VERIFIED", "active": True},
    }
