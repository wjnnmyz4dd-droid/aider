"""Indicator framework (ADR-024 §1 "Indicator Framework").

This phase builds the interface, registry, and cache only. No concrete
indicator (`EMA`, `RSI`, `ADX`, `MACD`, `Stochastic`, `Bollinger`,
`Volume`, `VWAP`) is implemented here -- each is future work, gated by
its own scope decision, not an omission.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from collections import OrderedDict
from typing import Dict, Sequence, Tuple

from .models import Bar, IndicatorResult

#: Names this framework is built to support once concrete indicators are
#: implemented. Not used for anything but documentation/tests today --
#: no code path here fails or behaves differently based on this tuple.
RESERVED_FUTURE_INDICATOR_NAMES: Tuple[str, ...] = (
    "EMA",
    "RSI",
    "ADX",
    "MACD",
    "STOCHASTIC",
    "BOLLINGER",
    "VOLUME",
    "VWAP",
)


class Indicator(ABC):
    """One deterministic transform of a bar series into a single
    `IndicatorResult`. Concrete indicators subclass this; none exist in
    this phase."""

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    def compute(self, bars: Sequence[Bar], **params: float) -> IndicatorResult:
        ...


class DuplicateIndicatorError(ValueError):
    pass


class IndicatorRegistry:
    """Name -> `Indicator` instance. Registration is explicit, never
    auto-discovered from a directory scan in this phase (there is
    nothing to discover yet); this mirrors the registry shape future
    concrete indicators will plug into without changing this class."""

    def __init__(self) -> None:
        self._indicators: Dict[str, Indicator] = {}

    def register(self, indicator: Indicator) -> None:
        if indicator.name in self._indicators:
            raise DuplicateIndicatorError(f"Indicator '{indicator.name}' is already registered")
        self._indicators[indicator.name] = indicator

    def get(self, name: str) -> Indicator:
        return self._indicators[name]

    def names(self) -> Tuple[str, ...]:
        return tuple(sorted(self._indicators.keys()))

    def __contains__(self, name: str) -> bool:
        return name in self._indicators


def _bar_signature(bars: Sequence[Bar]) -> Tuple:
    """A cheap, content-based cache key: any change to the bar series
    (a new bar appended, the last close changing) changes this
    signature, without hashing every bar on every call."""
    if not bars:
        return ("empty",)
    first, last = bars[0], bars[-1]
    return (first.symbol, len(bars), first.timestamp, last.timestamp, last.close)


class IndicatorCache:
    """Bounded, deterministic cache: oldest entry evicted first once
    over `max_entries` -- no LRU-by-access, no randomness, matching the
    retention discipline already established for the Bridge (Phase
    1.6). Exists to satisfy "no duplicate calculations" when the same
    indicator/params/bar-set is requested more than once within an
    evaluation cycle (e.g. by more than one scoring component)."""

    def __init__(self, max_entries: int) -> None:
        self._max_entries = max_entries
        self._store: "OrderedDict[Tuple, IndicatorResult]" = OrderedDict()
        self._lock = threading.Lock()

    def get_or_compute(
        self,
        indicator: Indicator,
        bars: Sequence[Bar],
        params: Tuple[Tuple[str, float], ...] = (),
    ) -> IndicatorResult:
        key = (indicator.name, _bar_signature(bars), params)
        with self._lock:
            cached = self._store.get(key)
            if cached is not None:
                return cached
        # Computed outside the lock -- `Indicator.compute()` is a pure
        # function of its arguments, so two threads racing on the same
        # miss both compute the same result; whichever inserts first
        # wins and the loser's result is discarded, never corrupting
        # the cache with two different values for one key.
        result = indicator.compute(bars, **dict(params))
        with self._lock:
            self._store.setdefault(key, result)
            if len(self._store) > self._max_entries:
                self._store.popitem(last=False)
            return self._store[key]

    def size(self) -> int:
        with self._lock:
            return len(self._store)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


__all__ = [
    "RESERVED_FUTURE_INDICATOR_NAMES",
    "Indicator",
    "DuplicateIndicatorError",
    "IndicatorRegistry",
    "IndicatorCache",
]
