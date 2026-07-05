"""Scanner-only metrics surface (ADR-002 §12).

Export-only: recording a metric has zero effect on any returned
`ScannerObservation` — mirrors the "additive, changes nothing" discipline
`phantom/metrics.py` already established. No Dashboard, no Prometheus wire
format here — this is the Scanner's own metric surface only.

Per-symbol scan latency is stored as "most recent value per symbol" —
bounded by distinct symbol count, the same acceptable-in-spirit bounded
state §13 already permits for a per-symbol dict.
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

from .models import ScannerObservation


class ScannerMetrics:
    def __init__(self) -> None:
        self._observations_total: Dict[str, int] = {}
        self._structural_signals_total: Dict[Tuple[str, str], int] = {}
        self._scan_latency_seconds: Dict[str, float] = {}

    def record_observation(
        self, observation: ScannerObservation, latency_seconds: Optional[float] = None
    ) -> None:
        flag = observation.data_quality_flag.value
        self._observations_total[flag] = self._observations_total.get(flag, 0) + 1

        for signal in observation.structure:
            key = (signal.kind.value, signal.direction.value)
            self._structural_signals_total[key] = self._structural_signals_total.get(key, 0) + 1

        if latency_seconds is not None:
            self._scan_latency_seconds[observation.symbol] = latency_seconds

    @property
    def observations_total(self) -> Dict[str, int]:
        return dict(self._observations_total)

    @property
    def structural_signals_total(self) -> Dict[Tuple[str, str], int]:
        return dict(self._structural_signals_total)

    @property
    def scan_latency_seconds(self) -> Dict[str, float]:
        return dict(self._scan_latency_seconds)
