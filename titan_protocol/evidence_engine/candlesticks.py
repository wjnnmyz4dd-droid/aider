"""Candlestick intelligence: single/two/three-candle pattern
recognition, each with quality, context, and confidence (ADR-024 §1
"Candlestick Intelligence").

Every `_match_*` function below is a pure shape test over one, two, or
three bars and returns a `quality` in `[0, 1]` (how closely the bars
match the pattern's textbook shape) or `None` if the shape does not
match at all. `recognize_patterns()` is the single entry point that
walks a bar series once, tries every applicable matcher at each index,
and assembles the final `CandlestickMatch` (quality + context +
confidence) for each hit.
"""

from __future__ import annotations

from typing import Callable, List, Optional, Sequence, Tuple

from .config import EvidenceEngineConfig
from .models import Bar, CandlestickMatch, CandlestickPattern, PatternContext

_CONTEXT_WEIGHT = {
    PatternContext.AT_UPTREND_EXTREME: 1.0,
    PatternContext.AT_DOWNTREND_EXTREME: 1.0,
    PatternContext.MID_RANGE: 0.7,
    PatternContext.UNKNOWN: 0.5,
}


def _body(bar: Bar) -> float:
    return abs(bar.close - bar.open)


def _range(bar: Bar) -> float:
    return bar.high - bar.low


def _body_ratio(bar: Bar) -> float:
    r = _range(bar)
    return _body(bar) / r if r > 0 else 0.0


def _upper_wick(bar: Bar) -> float:
    return bar.high - max(bar.open, bar.close)


def _lower_wick(bar: Bar) -> float:
    return min(bar.open, bar.close) - bar.low


def _upper_wick_ratio(bar: Bar) -> float:
    r = _range(bar)
    return _upper_wick(bar) / r if r > 0 else 0.0


def _lower_wick_ratio(bar: Bar) -> float:
    r = _range(bar)
    return _lower_wick(bar) / r if r > 0 else 0.0


def _is_bullish(bar: Bar) -> bool:
    return bar.close > bar.open


def _is_bearish(bar: Bar) -> bool:
    return bar.close < bar.open


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


# -- Single-candle matchers -------------------------------------------------


def _match_doji(bar: Bar, config: EvidenceEngineConfig) -> Optional[float]:
    ratio = _body_ratio(bar)
    if ratio <= config.doji_body_to_range_max:
        return _clamp01(1.0 - ratio / max(config.doji_body_to_range_max, 1e-9))
    return None


def _match_marubozu(bar: Bar, config: EvidenceEngineConfig) -> Optional[float]:
    if (
        _body_ratio(bar) >= config.long_body_to_range_min
        and _upper_wick_ratio(bar) <= config.marubozu_wick_to_range_max
        and _lower_wick_ratio(bar) <= config.marubozu_wick_to_range_max
    ):
        return _clamp01(_body_ratio(bar))
    return None


def _match_hammer_shape(bar: Bar, config: EvidenceEngineConfig) -> Optional[float]:
    """Shape shared by Hammer and Hanging Man: small body near the top
    of the range, a lower wick at least twice the body, and a small
    upper wick. Which label applies is decided by `recognize_patterns`
    from the surrounding trend context."""
    body = _body(bar)
    if body <= 0 or _range(bar) <= 0:
        return None
    if _lower_wick(bar) >= 2 * body and _upper_wick_ratio(bar) <= config.small_body_to_range_max:
        return _clamp01(_lower_wick_ratio(bar))
    return None


def _match_shooting_star(bar: Bar, config: EvidenceEngineConfig) -> Optional[float]:
    body = _body(bar)
    if body <= 0 or _range(bar) <= 0:
        return None
    if _upper_wick(bar) >= 2 * body and _lower_wick_ratio(bar) <= config.small_body_to_range_max:
        return _clamp01(_upper_wick_ratio(bar))
    return None


def _match_spinning_top(bar: Bar, config: EvidenceEngineConfig) -> Optional[float]:
    ratio = _body_ratio(bar)
    if config.doji_body_to_range_max < ratio <= config.small_body_to_range_max:
        upper, lower = _upper_wick_ratio(bar), _lower_wick_ratio(bar)
        if upper > 0 and lower > 0:
            balance = min(upper, lower) / max(upper, lower)
            if balance >= 0.5:
                return _clamp01(balance)
    return None


# -- Two-candle matchers -----------------------------------------------------


def _match_bullish_engulfing(prev: Bar, curr: Bar, config: EvidenceEngineConfig) -> Optional[float]:
    if _is_bearish(prev) and _is_bullish(curr) and curr.open <= prev.close and curr.close >= prev.open:
        return _clamp01(_body(curr) / max(_body(prev), 1e-9))
    return None


def _match_bearish_engulfing(prev: Bar, curr: Bar, config: EvidenceEngineConfig) -> Optional[float]:
    if _is_bullish(prev) and _is_bearish(curr) and curr.open >= prev.close and curr.close <= prev.open:
        return _clamp01(_body(curr) / max(_body(prev), 1e-9))
    return None


def _match_harami(prev: Bar, curr: Bar, config: EvidenceEngineConfig) -> Optional[float]:
    prev_hi, prev_lo = max(prev.open, prev.close), min(prev.open, prev.close)
    if (
        _body_ratio(prev) >= config.long_body_to_range_min
        and prev_lo <= curr.open <= prev_hi
        and prev_lo <= curr.close <= prev_hi
        and _body(curr) <= _body(prev) * 0.5
    ):
        return _clamp01(1.0 - _body(curr) / max(_body(prev), 1e-9))
    return None


def _match_piercing_pattern(prev: Bar, curr: Bar, config: EvidenceEngineConfig) -> Optional[float]:
    if not (_is_bearish(prev) and _body_ratio(prev) >= config.long_body_to_range_min and _is_bullish(curr)):
        return None
    midpoint = (prev.open + prev.close) / 2.0
    if curr.open < prev.low and midpoint < curr.close < prev.open:
        return _clamp01((curr.close - midpoint) / max(prev.open - midpoint, 1e-9))
    return None


def _match_dark_cloud_cover(prev: Bar, curr: Bar, config: EvidenceEngineConfig) -> Optional[float]:
    if not (_is_bullish(prev) and _body_ratio(prev) >= config.long_body_to_range_min and _is_bearish(curr)):
        return None
    midpoint = (prev.open + prev.close) / 2.0
    if curr.open > prev.high and prev.open < curr.close < midpoint:
        return _clamp01((midpoint - curr.close) / max(midpoint - prev.open, 1e-9))
    return None


def _match_tweezer_top(prev: Bar, curr: Bar, config: EvidenceEngineConfig) -> Optional[float]:
    tolerance = config.equal_level_tolerance_pct / 100.0
    if prev.high == 0:
        return None
    if abs(prev.high - curr.high) / abs(prev.high) <= tolerance and _is_bullish(prev) and _is_bearish(curr):
        return _clamp01(1.0 - abs(prev.high - curr.high) / abs(prev.high) / max(tolerance, 1e-9))
    return None


def _match_tweezer_bottom(prev: Bar, curr: Bar, config: EvidenceEngineConfig) -> Optional[float]:
    tolerance = config.equal_level_tolerance_pct / 100.0
    if prev.low == 0:
        return None
    if abs(prev.low - curr.low) / abs(prev.low) <= tolerance and _is_bearish(prev) and _is_bullish(curr):
        return _clamp01(1.0 - abs(prev.low - curr.low) / abs(prev.low) / max(tolerance, 1e-9))
    return None


# -- Three-candle matchers ---------------------------------------------------


def _match_morning_star(a: Bar, b: Bar, c: Bar, config: EvidenceEngineConfig) -> Optional[float]:
    if not (_is_bearish(a) and _body_ratio(a) >= config.long_body_to_range_min):
        return None
    if not (_body_ratio(b) <= config.small_body_to_range_max):
        return None
    midpoint = (a.open + a.close) / 2.0
    if _is_bullish(c) and c.close > midpoint and max(b.open, b.close) < a.close:
        return _clamp01((c.close - midpoint) / max(a.open - midpoint, 1e-9))
    return None


def _match_evening_star(a: Bar, b: Bar, c: Bar, config: EvidenceEngineConfig) -> Optional[float]:
    if not (_is_bullish(a) and _body_ratio(a) >= config.long_body_to_range_min):
        return None
    if not (_body_ratio(b) <= config.small_body_to_range_max):
        return None
    midpoint = (a.open + a.close) / 2.0
    if _is_bearish(c) and c.close < midpoint and min(b.open, b.close) > a.close:
        return _clamp01((midpoint - c.close) / max(midpoint - a.open, 1e-9))
    return None


def _match_three_white_soldiers(a: Bar, b: Bar, c: Bar, config: EvidenceEngineConfig) -> Optional[float]:
    bars = (a, b, c)
    if not all(_is_bullish(bar) and _body_ratio(bar) >= config.long_body_to_range_min for bar in bars):
        return None
    if not (a.close < b.close < c.close and a.open < b.open < c.open):
        return None
    if not all(_upper_wick_ratio(bar) <= config.small_body_to_range_max for bar in bars):
        return None
    return _clamp01(min(_body_ratio(bar) for bar in bars))


def _match_three_black_crows(a: Bar, b: Bar, c: Bar, config: EvidenceEngineConfig) -> Optional[float]:
    bars = (a, b, c)
    if not all(_is_bearish(bar) and _body_ratio(bar) >= config.long_body_to_range_min for bar in bars):
        return None
    if not (a.close > b.close > c.close and a.open > b.open > c.open):
        return None
    if not all(_lower_wick_ratio(bar) <= config.small_body_to_range_max for bar in bars):
        return None
    return _clamp01(min(_body_ratio(bar) for bar in bars))


def _match_three_inside_up(a: Bar, b: Bar, c: Bar, config: EvidenceEngineConfig) -> Optional[float]:
    if _match_harami(a, b, config) is None or not _is_bearish(a):
        return None
    if _is_bullish(c) and c.close > a.open:
        return _clamp01((c.close - a.open) / max(_range(a), 1e-9))
    return None


def _match_three_inside_down(a: Bar, b: Bar, c: Bar, config: EvidenceEngineConfig) -> Optional[float]:
    if _match_harami(a, b, config) is None or not _is_bullish(a):
        return None
    if _is_bearish(c) and c.close < a.open:
        return _clamp01((a.open - c.close) / max(_range(a), 1e-9))
    return None


def _match_three_outside_up(a: Bar, b: Bar, c: Bar, config: EvidenceEngineConfig) -> Optional[float]:
    if _match_bullish_engulfing(a, b, config) is None:
        return None
    if _is_bullish(c) and c.close > b.close:
        return _clamp01((c.close - b.close) / max(_range(b), 1e-9))
    return None


def _match_three_outside_down(a: Bar, b: Bar, c: Bar, config: EvidenceEngineConfig) -> Optional[float]:
    if _match_bearish_engulfing(a, b, config) is None:
        return None
    if _is_bearish(c) and c.close < b.close:
        return _clamp01((b.close - c.close) / max(_range(b), 1e-9))
    return None


_SINGLE_MATCHERS: Tuple[Tuple[CandlestickPattern, Callable[[Bar, EvidenceEngineConfig], Optional[float]]], ...] = (
    (CandlestickPattern.DOJI, _match_doji),
    (CandlestickPattern.MARUBOZU, _match_marubozu),
    (CandlestickPattern.SHOOTING_STAR, _match_shooting_star),
    (CandlestickPattern.SPINNING_TOP, _match_spinning_top),
)

_TWO_MATCHERS: Tuple[Tuple[CandlestickPattern, Callable[[Bar, Bar, EvidenceEngineConfig], Optional[float]]], ...] = (
    (CandlestickPattern.BULLISH_ENGULFING, _match_bullish_engulfing),
    (CandlestickPattern.BEARISH_ENGULFING, _match_bearish_engulfing),
    (CandlestickPattern.HARAMI, _match_harami),
    (CandlestickPattern.PIERCING_PATTERN, _match_piercing_pattern),
    (CandlestickPattern.DARK_CLOUD_COVER, _match_dark_cloud_cover),
    (CandlestickPattern.TWEEZER_TOP, _match_tweezer_top),
    (CandlestickPattern.TWEEZER_BOTTOM, _match_tweezer_bottom),
)

_THREE_MATCHERS: Tuple[Tuple[CandlestickPattern, Callable[[Bar, Bar, Bar, EvidenceEngineConfig], Optional[float]]], ...] = (
    (CandlestickPattern.MORNING_STAR, _match_morning_star),
    (CandlestickPattern.EVENING_STAR, _match_evening_star),
    (CandlestickPattern.THREE_WHITE_SOLDIERS, _match_three_white_soldiers),
    (CandlestickPattern.THREE_BLACK_CROWS, _match_three_black_crows),
    (CandlestickPattern.THREE_INSIDE_UP, _match_three_inside_up),
    (CandlestickPattern.THREE_INSIDE_DOWN, _match_three_inside_down),
    (CandlestickPattern.THREE_OUTSIDE_UP, _match_three_outside_up),
    (CandlestickPattern.THREE_OUTSIDE_DOWN, _match_three_outside_down),
)


def recognize_patterns(
    bars: Sequence[Bar],
    config: EvidenceEngineConfig,
    contexts: Optional[Sequence[PatternContext]] = None,
) -> Tuple[CandlestickMatch, ...]:
    """Scans every index once and tries every applicable matcher.
    `contexts[i]`, if supplied, is the trend context to attribute to a
    pattern confirmed at index `i` (defaults to `UNKNOWN`).

    The Hammer/Hanging-Man shape is a single shared matcher
    (`_match_hammer_shape`): a `AT_DOWNTREND_EXTREME` context labels it
    `HAMMER` (bullish reversal reading); `AT_UPTREND_EXTREME` labels it
    `HANGING_MAN` (bearish reversal reading); any other context defaults
    to `HAMMER` at reduced confidence, since the shape alone cannot
    otherwise disambiguate the two readings.
    """
    matches: List[CandlestickMatch] = []

    def context_at(i: int) -> PatternContext:
        if contexts is not None and i < len(contexts):
            return contexts[i]
        return PatternContext.UNKNOWN

    for i, bar in enumerate(bars):
        context = context_at(i)
        for pattern, matcher in _SINGLE_MATCHERS:
            quality = matcher(bar, config)
            if quality is not None:
                matches.append(_build_match(pattern, i, quality, context))

        hammer_quality = _match_hammer_shape(bar, config)
        if hammer_quality is not None:
            if context == PatternContext.AT_UPTREND_EXTREME:
                pattern = CandlestickPattern.HANGING_MAN
            else:
                pattern = CandlestickPattern.HAMMER
            matches.append(_build_match(pattern, i, hammer_quality, context))

        if i >= 1:
            prev = bars[i - 1]
            for pattern, matcher in _TWO_MATCHERS:
                quality = matcher(prev, bar, config)
                if quality is not None:
                    matches.append(_build_match(pattern, i, quality, context))

        if i >= 2:
            a, b = bars[i - 2], bars[i - 1]
            for pattern, matcher in _THREE_MATCHERS:
                quality = matcher(a, b, bar, config)
                if quality is not None:
                    matches.append(_build_match(pattern, i, quality, context))

    return tuple(matches)


def _build_match(pattern: CandlestickPattern, index: int, quality: float, context: PatternContext) -> CandlestickMatch:
    confidence = _clamp01(quality * _CONTEXT_WEIGHT[context])
    return CandlestickMatch(pattern=pattern, index=index, quality=quality, context=context, confidence=confidence)


__all__ = ["recognize_patterns"]
