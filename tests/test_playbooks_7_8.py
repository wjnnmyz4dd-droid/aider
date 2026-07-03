"""Tests for Playbook 7 (Support & Resistance Bounce) and Playbook 8
(Momentum Continuation).

Required cases:
  * Valid Support & Resistance bounce   -> confirmed
  * Invalid bounce (no rejection)       -> not confirmed
  * Strong momentum continuation        -> confirmed
  * Weak momentum (one-candle spike)    -> not confirmed
  * Ranging market                      -> not confirmed

Plus an additive-safety guard: both playbooks stay silent on the existing
approve fixtures, so the consolidated strategy score is unchanged.
"""

from __future__ import annotations

import unittest
from datetime import timedelta

from phantom.strategies.base import StrategyContext
from phantom.strategies.momentum_continuation import MomentumContinuation
from phantom.strategies.support_resistance import SupportResistanceBounce
from phantom.strategies.engine import StrategyEngine
from phantom.structure import StructureSignal
from phantom.types import Candle, Direction, MarketSnapshot, Regime

from tests.fixtures import NOW, approve_long_snapshot, strong_approve_snapshot


def _ctx(**over):
    base = dict(
        regime=Regime.TRENDING_UP, h4_dir=Direction.LONG, d1_dir=Direction.LONG,
        bias=Direction.LONG, bos=StructureSignal(), choch=StructureSignal(),
        sweep=StructureSignal(), fvg=StructureSignal(), ob=StructureSignal(),
        news_safe=True, spread_safe=True, correlation_safe=True,
        exposure_safe={Direction.LONG: True, Direction.SHORT: True},
        atr=0.0010, exec_candles=[],
    )
    base.update(over)
    return StrategyContext(**base)


def _snap(bars):
    """Wrap an M15 bar list into a MarketSnapshot (only M15 is read by these
    playbooks, via snap.tf(execution_tf))."""
    return MarketSnapshot(symbol="EURUSD", now=NOW, candles={"M15": bars})


def _mk(ohlc):
    """Build M15 candles (oldest->newest) from a list of (o,h,l,c)."""
    bars = []
    start = NOW - timedelta(minutes=15 * (len(ohlc) - 1))
    for i, (o, h, l, c) in enumerate(ohlc):
        bars.append(Candle(start + timedelta(minutes=15 * i), o, h, l, c))
    return bars


# --- Support & Resistance -------------------------------------------------

def _sr_bars_valid():
    """Two swing lows clustered at ~1.0980 (support, 2 touches), then a final
    candle that wicks into the zone and closes back above it (a bounce)."""
    return _mk([
        (1.1010, 1.1015, 1.1008, 1.1012),
        (1.1000, 1.1012, 1.0998, 1.1002),
        (1.1000, 1.1004, 1.0980, 1.0995),  # swing low A @1.0980
        (1.1000, 1.1010, 1.0998, 1.1005),
        (1.1010, 1.1016, 1.1006, 1.1012),
        (1.1005, 1.1010, 1.1002, 1.1006),
        (1.1000, 1.1004, 1.0982, 1.0996),  # swing low B @1.0982
        (1.1000, 1.1008, 1.0998, 1.1004),
        (1.1008, 1.1014, 1.1004, 1.1010),
        (1.1002, 1.1006, 1.0998, 1.1000),
        (1.0999, 1.1002, 1.0996, 1.1000),  # prev: still above the zone
        (1.0998, 1.1000, 1.0978, 1.0996),  # rejection: low pierces zone, closes above
    ])


class TestSupportResistanceBounce(unittest.TestCase):
    def test_valid_bounce_confirms(self):
        sig = SupportResistanceBounce().evaluate(_snap(_sr_bars_valid()), _ctx())
        self.assertTrue(sig.confirmed, sig.reason)
        self.assertEqual(sig.direction, Direction.LONG)
        # base bounce 8 + trend 5 (2 touches -> not strong)
        self.assertEqual(sig.score, 13.0)

    def test_invalid_bounce_no_rejection(self):
        # same zone, but the final candle closes BELOW support (a break, no wick)
        bars = _sr_bars_valid()
        bars[-1] = Candle(bars[-1].ts, 1.0990, 1.0992, 1.0975, 1.0978)  # closes through
        sig = SupportResistanceBounce().evaluate(_snap(bars), _ctx())
        self.assertFalse(sig.confirmed)
        self.assertEqual(sig.score, 0.0)

    def test_bounce_against_trend_rejected(self):
        # a valid support bounce but H4 trend is DOWN -> never bounce against trend
        sig = SupportResistanceBounce().evaluate(
            _snap(_sr_bars_valid()), _ctx(h4_dir=Direction.SHORT))
        self.assertFalse(sig.confirmed)


# --- Momentum Continuation ------------------------------------------------

def _mom_bars_strong():
    """Flat base then sustained, expanding up-closes (ATR expansion + monotonic
    closes) -> strong continuation."""
    return _mk([
        (1.1000, 1.1003, 1.0999, 1.1000),
        (1.1000, 1.1002, 1.0999, 1.1001),
        (1.1001, 1.1003, 1.0999, 1.1000),
        (1.1000, 1.1002, 1.0999, 1.1001),
        (1.1001, 1.1003, 1.0999, 1.1000),
        (1.1000, 1.1014, 1.0996, 1.1006),  # expansion begins
        (1.1006, 1.1024, 1.1002, 1.1014),
        (1.1014, 1.1034, 1.1010, 1.1024),
        (1.1024, 1.1046, 1.1020, 1.1036),
        (1.1036, 1.1058, 1.1032, 1.1050),  # sustained higher closes
    ])


class TestMomentumContinuation(unittest.TestCase):
    def _ctx_trend(self, **over):
        base = dict(regime=Regime.TRENDING_UP, h4_dir=Direction.LONG,
                    bos=StructureSignal(True, Direction.LONG, "bos up"))
        base.update(over)
        return _ctx(**base)

    def test_strong_momentum_confirms(self):
        sig = MomentumContinuation().evaluate(_snap(_mom_bars_strong()), self._ctx_trend())
        self.assertTrue(sig.confirmed, sig.reason)
        self.assertEqual(sig.direction, Direction.LONG)
        # continuation 8 + structure 5 + strong 5
        self.assertEqual(sig.score, 18.0)

    def test_weak_momentum_one_candle_spike_rejected(self):
        # flat closes then a single spike bar -> not sustained -> rejected
        spike = _mk([
            (1.1000, 1.1003, 1.0999, 1.1000),
            (1.1000, 1.1002, 1.0999, 1.1000),
            (1.1000, 1.1003, 1.0999, 1.1000),
            (1.1000, 1.1002, 1.0999, 1.1000),
            (1.1000, 1.1003, 1.0999, 1.1000),
            (1.1000, 1.1002, 1.0999, 1.1000),
            (1.1000, 1.1003, 1.0999, 1.1000),
            (1.1000, 1.1002, 1.0999, 1.1000),
            (1.1000, 1.1003, 1.0999, 1.1000),
            (1.1000, 1.1060, 1.0999, 1.1050),  # lone spike
        ])
        sig = MomentumContinuation().evaluate(_snap(spike), self._ctx_trend())
        self.assertFalse(sig.confirmed)
        self.assertEqual(sig.score, 0.0)

    def test_ranging_market_rejected(self):
        sig = MomentumContinuation().evaluate(
            _snap(_mom_bars_strong()), self._ctx_trend(regime=Regime.RANGING))
        self.assertFalse(sig.confirmed)
        self.assertEqual(sig.score, 0.0)


# --- Additive safety ------------------------------------------------------

class TestAdditiveSafety(unittest.TestCase):
    def test_playbooks_silent_on_existing_fixtures(self):
        # On the existing approve fixtures the two new playbooks must contribute
        # nothing (not confirmed), so the consolidated strategy score is
        # unchanged from before they were added.
        for snap in (approve_long_snapshot(), strong_approve_snapshot()):
            eng = StrategyEngine()
            signals = [s.evaluate(snap, _ctx()) for s in eng.strategies]
            for name in ("S&R Bounce", "Momentum Continuation"):
                sig = [s for s in signals if s.name == name][0]
                self.assertFalse(sig.confirmed, f"{name} should be silent: {sig.reason}")
                self.assertEqual(sig.score, 0.0)


if __name__ == "__main__":
    unittest.main()
