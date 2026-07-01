"""The scorer — the single place where the composite score is assembled.

It computes the 19 keep-list components, folds in the ORB confirmation layer,
applies the NEUTRAL cap, and maps the total onto APPROVE / WATCHLIST / BLOCK.

Component list (order preserved):
  1 H4 Trend Alignment      8 RSI Confirmation     15 Correlation Guard*
  2 D1 Trend Alignment      9 ATR                  16 Exposure Guard*
  3 BOS                    10 Volatility Ratio      17 RR Validation*
  4 CHOCH                  11 Session Filter        18 Prop Compliance*
  5 Liquidity Sweep        12 News Filter*          19 AI Meta Filter
  6 FVG                    13 Market Regime
  7 Order Block            14 Spread Filter*
  (* = blocking guard; ORB is an additive confirmation layer, not a component
   in its own right — it can raise, lower, or block the score.)
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from . import indicators as ind
from .config import Config, DEFAULT_CONFIG
from .guards import Guards
from .orb import ORBContext, ORBDecision, ORBEngine
from .regime import RegimeEngine
from .structure import StructureAnalyzer
from .types import (
    Candle,
    Decision,
    Direction,
    MarketSnapshot,
    Regime,
    ScoreComponent,
    ScoreResult,
)


def _trend_direction(candles: List[Candle]) -> Tuple[Direction, float]:
    """Return (direction, strength 0..1) from EMA20/EMA50 structure."""
    closes = [c.close for c in candles]
    if len(closes) < 51:
        return Direction.NONE, 0.0
    ema_fast = ind.ema(closes, 20) or closes[-1]
    ema_slow = ind.ema(closes, 50) or closes[-1]
    price = closes[-1] or 1e-9
    sep = (ema_fast - ema_slow) / price
    strength = min(abs(sep) / 0.004, 1.0)  # ~0.4% separation == full strength
    if ema_fast > ema_slow and sep > 0:
        return Direction.LONG, strength
    if ema_fast < ema_slow and sep < 0:
        return Direction.SHORT, strength
    return Direction.NONE, 0.0


class Scorer:
    def __init__(self, config: Config = DEFAULT_CONFIG, orb_engine: Optional[ORBEngine] = None):
        self.config = config
        self.regime_engine = RegimeEngine(config)
        self.structure = StructureAnalyzer(config)
        self.guards = Guards(config)
        self.orb = orb_engine or ORBEngine(config)

    # -- RR helper ----------------------------------------------------------
    def _planned_rr(self, candles: List[Candle], direction: Direction, atr: float) -> Optional[float]:
        if direction == Direction.NONE or not candles:
            return None
        price = candles[-1].close
        highs, lows = ind.swing_points(candles, self.config.indicators.swing_lookback)
        min_rr = self.config.guards.min_rr
        if direction == Direction.LONG:
            below = [p for _, p in lows if p < price]
            stop = max(below) if below else price - atr
            above = [p for _, p in highs if p > price]
            target = min(above) if above else price + min_rr * (price - stop)
        else:
            above = [p for _, p in highs if p > price]
            stop = min(above) if above else price + atr
            below = [p for _, p in lows if p < price]
            target = max(below) if below else price - min_rr * (stop - price)
        risk = abs(price - stop)
        reward = abs(target - price)
        return reward / risk if risk > 0 else None

    # -- main ---------------------------------------------------------------
    def score(self, snap: MarketSnapshot) -> ScoreResult:
        cfg = self.config
        w = cfg.weights
        comps: List[ScoreComponent] = []
        total = 0.0

        exec_tf = cfg.orb.execution_tf
        exec_candles = snap.tf(exec_tf)
        atr = ind.atr(exec_candles, cfg.indicators.atr_period) or 0.0

        # --- trend (1,2) ---
        h4_dir, h4_str = _trend_direction(snap.tf("H4"))
        d1_dir, d1_str = _trend_direction(snap.tf("D1"))

        # --- preliminary bias from trend ---
        votes = [d for d in (h4_dir, d1_dir) if d != Direction.NONE]
        bias = Direction.NONE
        if votes:
            longs = votes.count(Direction.LONG)
            shorts = votes.count(Direction.SHORT)
            bias = Direction.LONG if longs > shorts else Direction.SHORT if shorts > longs else Direction.NONE

        # --- structure (3-7) ---
        bos = self.structure.bos(exec_candles)
        choch = self.structure.choch(exec_candles)
        sweep = self.structure.liquidity_sweep(exec_candles)
        fvg = self.structure.fvg(exec_candles)
        ob = self.structure.order_block(exec_candles)

        if bias == Direction.NONE:
            sdirs = [s.direction for s in (bos, choch, sweep, fvg, ob) if s.found and s.direction != Direction.NONE]
            if sdirs:
                bias = Direction.LONG if sdirs.count(Direction.LONG) >= sdirs.count(Direction.SHORT) else Direction.SHORT

        def add(name, points, detail="", blocking=False, failed=False):
            nonlocal total
            c = ScoreComponent(name, points, detail, blocking, failed)
            comps.append(c)
            if not blocking:
                total += points
            return c

        # 1,2 trend alignment
        add("H4 Trend Alignment", w.h4_trend_alignment * h4_str if h4_dir == bias and bias != Direction.NONE else 0.0,
            f"{h4_dir.value} str={h4_str:.2f}")
        add("D1 Trend Alignment", w.d1_trend_alignment * d1_str if d1_dir == bias and bias != Direction.NONE else 0.0,
            f"{d1_dir.value} str={d1_str:.2f}")

        def struct_points(sig, weight):
            return weight if (sig.found and sig.direction == bias and bias != Direction.NONE) else 0.0

        # 3-7 structure
        add("BOS", struct_points(bos, w.bos), bos.detail)
        add("CHOCH", struct_points(choch, w.choch), choch.detail)
        add("Liquidity Sweep", struct_points(sweep, w.liquidity_sweep), sweep.detail)
        add("FVG", struct_points(fvg, w.fvg), fvg.detail)
        add("Order Block", struct_points(ob, w.order_block), ob.detail)

        # 8 RSI confirmation
        rsi = ind.rsi(exec_candles, cfg.indicators.rsi_period)
        rsi_pts = 0.0
        rsi_detail = "n/a"
        if rsi is not None:
            rsi_detail = f"{rsi:.1f}"
            if bias == Direction.LONG and 50 <= rsi <= 70:
                rsi_pts = w.rsi_confirmation * (1 - abs(rsi - 60) / 10)
            elif bias == Direction.SHORT and 30 <= rsi <= 50:
                rsi_pts = w.rsi_confirmation * (1 - abs(rsi - 40) / 10)
        add("RSI Confirmation", max(rsi_pts, 0.0), rsi_detail)

        # 9 ATR (acceleration)
        atr_prev = ind.atr(exec_candles[:-3], cfg.indicators.atr_period) if len(exec_candles) > cfg.indicators.atr_period + 4 else None
        atr_pts = w.atr if (atr_prev is not None and atr > atr_prev) else 0.0
        add("ATR", atr_pts, f"atr={atr:.5f} accel={'+' if atr_pts else '0'}")

        # 10 Volatility Ratio + 13 Market Regime share one regime reading
        reading = self.regime_engine.classify(snap, "H1" if snap.tf("H1") else exec_tf)
        regime = reading.regime
        vr = reading.volatility_ratio
        vr_pts = w.volatility_ratio if 0.8 <= vr <= 1.6 else 0.0
        add("Volatility Ratio", vr_pts, f"ratio={vr:.2f} ({'healthy' if vr_pts else 'off-band'})")

        # 11 Session Filter
        in_session = self.guards.in_active_session(snap.now)
        add("Session Filter", w.session_filter if in_session else 0.0, "active" if in_session else "off-hours")

        # 12 News Filter (blocking)
        news = self.guards.news(snap)
        add("News Filter", 0.0, news.detail, blocking=True, failed=not news.passed)
        news_safe = news.passed

        # 13 Market Regime
        regime_aligned = (
            (regime == Regime.TRENDING_UP and bias == Direction.LONG)
            or (regime == Regime.TRENDING_DOWN and bias == Direction.SHORT)
            or regime == Regime.BREAKOUT
        )
        add("Market Regime", w.market_regime if regime_aligned else 0.0, regime.value)

        # 14 Spread Filter (blocking)
        spread = self.guards.spread(snap)
        add("Spread Filter", 0.0, spread.detail, blocking=True, failed=not spread.passed)

        # 15 Correlation Guard (blocking)
        corr = self.guards.correlation(snap, bias)
        add("Correlation Guard", 0.0, corr.detail, blocking=True, failed=not corr.passed)

        # 16 Exposure Guard (blocking)
        expo = self.guards.exposure(snap, bias) if bias != Direction.NONE else self.guards.exposure(snap, Direction.LONG)
        add("Exposure Guard", 0.0, expo.detail, blocking=True, failed=not expo.passed)

        # 17 RR Validation (blocking)
        rr = self._planned_rr(exec_candles, bias, atr)
        rrg = self.guards.rr_validation(rr)
        add("RR Validation", 0.0, rrg.detail, blocking=True, failed=not rrg.passed)

        # 18 Prop Compliance (blocking)
        prop = self.guards.prop_compliance(snap)
        add("Prop Compliance", 0.0, prop.detail, blocking=True, failed=not prop.passed)

        # --- ORB confirmation layer ---
        exposure_safe = {
            Direction.LONG: self.guards.exposure(snap, Direction.LONG).passed,
            Direction.SHORT: self.guards.exposure(snap, Direction.SHORT).passed,
        }
        h4d1_aligned = {
            Direction.LONG: h4_dir == Direction.LONG and d1_dir == Direction.LONG,
            Direction.SHORT: h4_dir == Direction.SHORT and d1_dir == Direction.SHORT,
        }
        bos_dir = {
            Direction.LONG: bos.found and bos.direction == Direction.LONG,
            Direction.SHORT: bos.found and bos.direction == Direction.SHORT,
        }
        orb_ctx = ORBContext(
            regime=regime,
            h4d1_aligned=h4d1_aligned,
            bos=bos_dir,
            news_safe=news_safe,
            spread_safe=spread.passed,
            exposure_safe=exposure_safe,
            atr=atr,
        )
        orb_decision: ORBDecision = self.orb.evaluate(snap, orb_ctx)
        total += orb_decision.score_impact
        comps.append(ScoreComponent(
            "ORB Confirmation", orb_decision.score_impact,
            orb_decision.reason, blocking=False,
        ))
        # An ORB-confirmed breakout can resolve an otherwise-NEUTRAL bias.
        if bias == Direction.NONE and orb_decision.confirmed:
            bias = orb_decision.breakout_direction

        # 19 AI Meta Filter — coherence of the directional thesis.
        coherence = self._meta_coherence(bias, h4_dir, d1_dir, regime, rsi, [bos, choch, sweep, fvg, ob])
        ai_pts = 5.0 * coherence
        add("AI Meta Filter", ai_pts, f"coherence={coherence:.2f}")

        # --- clamp, cap, decide ---
        total = max(cfg.score_floor, min(total, cfg.score_ceiling))
        capped_at = None
        if bias == Direction.NONE or regime in (Regime.RANGING, Regime.NEUTRAL):
            if total > cfg.thresholds.neutral_cap:
                capped_at = cfg.thresholds.neutral_cap
                total = cfg.thresholds.neutral_cap

        blocked_by = [c.name for c in comps if c.blocking and c.failed]
        if blocked_by:
            decision = Decision.BLOCK
        elif total >= cfg.thresholds.approve:
            decision = Decision.APPROVE
        elif total >= cfg.thresholds.watchlist:
            decision = Decision.WATCHLIST
        else:
            decision = Decision.BLOCK

        return ScoreResult(
            symbol=snap.symbol.upper(),
            total=total,
            decision=decision,
            direction=bias,
            components=comps,
            capped_at=capped_at,
            orb=orb_decision,
        )

    @staticmethod
    def _meta_coherence(bias, h4_dir, d1_dir, regime, rsi, structures) -> float:
        if bias == Direction.NONE:
            return 0.0
        score = 0.0
        checks = 0.0
        for d in (h4_dir, d1_dir):
            checks += 1
            if d == bias:
                score += 1
        checks += 1
        if (regime == Regime.TRENDING_UP and bias == Direction.LONG) or \
           (regime == Regime.TRENDING_DOWN and bias == Direction.SHORT) or \
           regime == Regime.BREAKOUT:
            score += 1
        if rsi is not None:
            checks += 1
            if (bias == Direction.LONG and rsi >= 50) or (bias == Direction.SHORT and rsi <= 50):
                score += 1
        aligned_struct = sum(1 for s in structures if s.found and s.direction == bias)
        conflicting = sum(1 for s in structures if s.found and s.direction != Direction.NONE and s.direction != bias)
        checks += 1
        if aligned_struct > conflicting:
            score += 1
        return score / checks if checks else 0.0
