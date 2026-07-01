"""The scorer — the single place where the composite score is assembled.

It computes the 18 keep-list components, folds in the ORB confirmation layer,
applies the NEUTRAL cap, and maps the total onto APPROVE / WATCHLIST / BLOCK.

Component list (order preserved):
  1 H4 Trend Alignment      7 Order Block          13 Spread Filter*
  2 D1 Trend Alignment      8 RSI Confirmation      14 Correlation Guard*
  3 BOS                     9 Volatility Health     15 Exposure Guard*
  4 CHOCH                  10 Session Filter         16 RR Validation*
  5 Liquidity Sweep        11 News Filter*          17 Prop Compliance*
  6 FVG                    12 Market Regime          18 Strategy Confirmation
  (* = blocking guard. Strategy Confirmation is the consolidated multi-strategy
   layer — ORB + Liquidity Reversal + Session Breakout — an additive, capped
   contribution that NEVER opens a trade.)

Changes vs the previous 19-component model:
  - AI Meta Filter REMOVED (it re-scored trend/structure/momentum → inflation).
    Replaced by an informational Trade Thesis Summary (never scored).
  - ATR + Volatility Ratio MERGED into Volatility Health (state-based).
  - Market Regime RE-SCOPED to environment classification (no longer duplicates
    H4/D1 trend alignment); weight reduced 10 → 5.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from . import indicators as ind
from .config import Config, DEFAULT_CONFIG
from .guards import Guards
from .orb import ORBEngine
from .regime import RegimeEngine
from .strategies import StrategyContext, StrategyEngine
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
    def __init__(self, config: Config = DEFAULT_CONFIG,
                 orb_engine: Optional[ORBEngine] = None,
                 strategy_engine: Optional[StrategyEngine] = None):
        self.config = config
        self.regime_engine = RegimeEngine(config)
        self.structure = StructureAnalyzer(config)
        self.guards = Guards(config)
        self.strategies = strategy_engine or StrategyEngine(config, orb_engine=orb_engine)
        self.orb = self.strategies.orb_engine  # backward-compatible reference

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

    # -- Volatility Health (merged ATR acceleration + Volatility Ratio) -----
    def _volatility_health(self, exec_candles, atr: float, vr: float):
        vp = self.config.volatility
        w = self.config.weights.volatility_health
        ip = self.config.indicators
        atr_prev = ind.atr(exec_candles[:-3], ip.atr_period) if len(exec_candles) > ip.atr_period + 4 else None
        accel = atr_prev is not None and atr > atr_prev
        atr_base = ind.atr(exec_candles, ip.atr_baseline_period)
        ratio = atr / atr_base if atr_base else 1.0
        expanding = ratio >= vp.expansion_ratio
        compressing = ratio <= vp.compression_ratio

        if vr >= vp.extreme_ratio:
            state, points = "Extreme", -w          # blow-off -> -5
        elif vr >= vp.elevated_ratio:
            state, points = "Elevated", w * 0.6    # +3
        elif vr >= vp.healthy_low:
            state, points = "Healthy", w           # +5
        else:
            state, points = "Compressed", 0.0

        tags = [t for t, on in (("accel", accel), ("expanding", expanding),
                                ("compressing", compressing)) if on]
        detail = f"{state} vr={vr:.2f}" + (f" [{','.join(tags)}]" if tags else "")
        return points, state, detail

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

        # regime reading — shared by Volatility Health (#9) and Market Regime (#12)
        reading = self.regime_engine.classify(snap, "H1" if snap.tf("H1") else exec_tf)
        regime = reading.regime
        vr = reading.volatility_ratio

        # 9 Volatility Health (merged ATR acceleration + Volatility Ratio)
        vh_pts, vh_state, vh_detail = self._volatility_health(exec_candles, atr, vr)
        add("Volatility Health", vh_pts, vh_detail)

        # 10 Session Filter
        in_session = self.guards.in_active_session(snap.now)
        add("Session Filter", w.session_filter if in_session else 0.0, "active" if in_session else "off-hours")

        # 11 News Filter (blocking)
        news = self.guards.news(snap)
        add("News Filter", 0.0, news.detail, blocking=True, failed=not news.passed)
        news_safe = news.passed

        # 12 Market Regime — ENVIRONMENT CLASSIFICATION ONLY (not trend confirmation).
        #     Rewards a tradeable directional/breakout environment regardless of the
        #     bias direction, so it no longer duplicates H4/D1 trend alignment.
        tradeable_env = regime in (Regime.TRENDING_UP, Regime.TRENDING_DOWN, Regime.BREAKOUT)
        add("Market Regime", w.market_regime if tradeable_env else 0.0, f"env={regime.value}")

        # 13 Spread Filter (blocking)
        spread = self.guards.spread(snap)
        add("Spread Filter", 0.0, spread.detail, blocking=True, failed=not spread.passed)

        # 14 Correlation Guard (blocking)
        corr = self.guards.correlation(snap, bias)
        add("Correlation Guard", 0.0, corr.detail, blocking=True, failed=not corr.passed)

        # 15 Exposure Guard (blocking)
        expo = self.guards.exposure(snap, bias) if bias != Direction.NONE else self.guards.exposure(snap, Direction.LONG)
        add("Exposure Guard", 0.0, expo.detail, blocking=True, failed=not expo.passed)

        # 16 RR Validation (blocking)
        rr = self._planned_rr(exec_candles, bias, atr)
        rrg = self.guards.rr_validation(rr)
        add("RR Validation", 0.0, rrg.detail, blocking=True, failed=not rrg.passed)

        # 17 Prop Compliance (blocking)
        prop = self.guards.prop_compliance(snap)
        add("Prop Compliance", 0.0, prop.detail, blocking=True, failed=not prop.passed)

        # 18 Strategy Confirmation layer — ORB + Liquidity Reversal + Session
        #    Breakout, consolidated with conflict resolution and a hard cap.
        #    Additive-only; no strategy can open a trade and the layer cannot
        #    inflate the score above the prior single-ORB maximum.
        exposure_safe = {
            Direction.LONG: self.guards.exposure(snap, Direction.LONG).passed,
            Direction.SHORT: self.guards.exposure(snap, Direction.SHORT).passed,
        }
        strat_ctx = StrategyContext(
            regime=regime, h4_dir=h4_dir, d1_dir=d1_dir, bias=bias,
            bos=bos, choch=choch, sweep=sweep, fvg=fvg, ob=ob,
            news_safe=news_safe, spread_safe=spread.passed,
            correlation_safe=corr.passed, exposure_safe=exposure_safe,
            atr=atr, exec_candles=exec_candles,
        )
        outcome = self.strategies.evaluate(snap, strat_ctx)
        total += outcome.net_score
        comps.append(ScoreComponent(
            "Strategy Confirmation", outcome.net_score,
            outcome.detail + (" [CONFLICT]" if outcome.conflict else ""),
            blocking=False,
        ))
        orb_decision = outcome.orb_decision
        # A confirmed, unconflicted strategy can resolve an otherwise-NEUTRAL bias.
        if bias == Direction.NONE and outcome.direction != Direction.NONE and not outcome.conflict:
            bias = outcome.direction

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

        # Trade Thesis Summary — informational only, NEVER added to the score.
        thesis = self._build_thesis(
            snap.symbol.upper(), bias, decision, total, regime, vh_state,
            [bos, choch, sweep, fvg, ob], rsi, orb_decision, h4_dir, d1_dir,
            blocked_by,
        )
        if outcome.conflict:
            thesis += " | STRATEGY CONFLICT"

        return ScoreResult(
            symbol=snap.symbol.upper(),
            total=total,
            decision=decision,
            direction=bias,
            components=comps,
            capped_at=capped_at,
            orb=orb_decision,
            thesis=thesis,
            strategies=outcome.as_dict(),
        )

    def _build_thesis(self, symbol, bias, decision, total, regime, vh_state,
                      structures, rsi, orb_decision, h4_dir, d1_dir, blocked_by) -> str:
        """Human-readable summary of the setup. Display/logging only."""
        fired = [s.detail.split(" ")[0] if s.detail else "sig"
                 for s in structures if s.found and s.direction == bias and bias != Direction.NONE]
        struct = ",".join(n for n, s in zip(
            ["BOS", "CHOCH", "Sweep", "FVG", "OB"], structures)
            if s.found and s.direction == bias and bias != Direction.NONE) or "none"
        confidence = self._meta_coherence(bias, h4_dir, d1_dir, regime, rsi, structures)
        parts = [
            f"{symbol} {bias.value}",
            f"{decision.value} {total:.1f}",
            f"regime={regime.value} vol={vh_state}",
            f"structure: {struct}",
            f"RSI {rsi:.1f}" if rsi is not None else "RSI n/a",
        ]
        if orb_decision is not None and orb_decision.session != "-":
            state = "confirmed" if orb_decision.confirmed else ("blocked" if orb_decision.blocked else "none")
            parts.append(f"ORB {orb_decision.session} {state}({orb_decision.score_impact:+.0f})")
        if blocked_by:
            parts.append("blocked_by: " + ",".join(blocked_by))
        parts.append(f"confidence {confidence:.2f}")
        return " | ".join(parts)

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
