"""TradeRouter / position sizing (advisory, non-executing).

Computes position size for a trade intent. It does NOT place orders, choose
entries, or touch the scanner/scorer. It only decides *how much* to risk, under
two authorities, in strict order:

  1. ComplianceEngine is FINAL — kill-switch or daily lockout => refuse (size 0).
     Evaluated fail-CLOSED: if compliance state can't be read, refuse.
  2. RiskIntelligenceEngine may only REDUCE or CAP risk, never raise it:
        risk_pct = min(Config base_risk_pct, risk_engine.current_risk_pct)
     clamped to [risk_min, base_risk_pct]. Fail-SAFE: any risk-engine error =>
     minimum risk (never more).

Sizing is broker-agnostic: risk_amount = equity * risk_pct/100; units =
risk_amount / stop_distance; lots = units / contract_size.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from .config import Config, DEFAULT_CONFIG


@dataclass
class SizingDecision:
    allowed: bool
    risk_pct: float
    risk_amount: float
    units: float
    lots: float
    mode: str
    reason: str

    def as_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "risk_pct": round(self.risk_pct, 4),
            "risk_amount": round(self.risk_amount, 2),
            "units": round(self.units, 2),
            "lots": round(self.lots, 4),
            "mode": self.mode,
            "reason": self.reason,
        }


class TradeRouter:
    def __init__(self, config: Config, risk_engine, compliance):
        self.config = config
        self.risk_engine = risk_engine
        self.compliance = compliance

    def _refuse(self, reason: str, mode: str = "DEFENSIVE") -> SizingDecision:
        return SizingDecision(False, 0.0, 0.0, 0.0, 0.0, mode, reason)

    def _sized(self, equity, stop_distance, risk_pct, mode, note="") -> SizingDecision:
        r = self.config.risk
        if equity is None or equity <= 0 or stop_distance is None or stop_distance <= 0:
            return self._refuse("invalid equity/stop")
        # Never exceed the configured ceiling; never below the floor.
        risk_pct = max(r.risk_min, min(risk_pct, r.base_risk_pct))
        risk_amount = equity * risk_pct / 100.0
        units = risk_amount / stop_distance
        lots = units / r.contract_size
        reason = f"{mode} risk={risk_pct:.2f}%" + (f" ({note})" if note else "")
        return SizingDecision(True, risk_pct, risk_amount, units, lots, mode, reason)

    def size(self, symbol: str, equity: float, stop_distance: float,
             current_dd_pct: Optional[float] = None, now: Optional[datetime] = None) -> SizingDecision:
        r = self.config.risk
        now = now or datetime.now(timezone.utc)

        # 1) Compliance is final authority — fail-closed.
        try:
            cs = self.compliance.state(now)
        except Exception:
            return self._refuse("compliance-state-error (fail-closed)")
        if cs.get("killswitch_active"):
            return self._refuse("compliance kill-switch active")
        if cs.get("daily_lockout"):
            return self._refuse("compliance daily lockout")

        dd = current_dd_pct if current_dd_pct is not None else cs.get("total_dd_pct", 0.0)

        # 2) Risk engine may only reduce/cap — fail-safe to minimum risk.
        try:
            st = self.risk_engine.evaluate(dd)
            if not st.trading_allowed:
                return self._refuse(f"risk halt: {st.reasons[0] if st.reasons else st.mode.value}",
                                    mode=st.mode.value)
            risk_pct = min(r.base_risk_pct, st.risk_pct)  # engine cannot raise above config
            return self._sized(equity, stop_distance, risk_pct, st.mode.value)
        except Exception as exc:
            return self._sized(equity, stop_distance, r.risk_min, "DEFENSIVE",
                               note=f"fail-safe:{type(exc).__name__}")
