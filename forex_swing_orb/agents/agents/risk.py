"""Risk Agent (DETERMINISTIC ONLY; no LLM, no broker execution).

Reviews position risk against deterministic rules: one-position-per-symbol,
correlated exposure, planned reward-to-risk, account limits, daily-loss and
drawdown limits, stop-distance sanity, and risk-sizing eligibility. Outputs
CLEAR / CAUTION / BLOCK. It NEVER touches the broker or places/sizes an order —
it only judges eligibility. Fails closed on missing required risk inputs.
"""

from __future__ import annotations

from ..base import Agent
from ..contract import Assessment, ReasonCode

REQUIRED_RISK_FIELDS = ("open_positions_symbol", "planned_rr", "stop_distance_pips",
                        "account_daily_loss_pct", "account_drawdown_pct",
                        "max_daily_loss_pct", "max_drawdown_pct")


class RiskAgent(Agent):
    agent_id = "risk"
    agent_version = "0.1.0"
    uses_llm = False

    def _assess(self, request, context, now):
        risk = (context or {}).get("risk")
        if not isinstance(risk, dict):
            return self._block([ReasonCode.DQ_MISSING_INPUT], ["risk"])
        missing = [f for f in REQUIRED_RISK_FIELDS if risk.get(f) is None]
        if missing:
            return self._block([ReasonCode.DQ_MISSING_INPUT], missing)

        reasons = []
        block = False
        caution = False

        # one position per symbol (hard rule)
        if risk["open_positions_symbol"] >= 1:
            block = True; reasons.append(ReasonCode.RISK_REJECT)
        # account limits (hard rules)
        if risk["account_daily_loss_pct"] >= risk["max_daily_loss_pct"]:
            block = True; reasons.append(ReasonCode.RISK_REJECT)
        if risk["account_drawdown_pct"] >= risk["max_drawdown_pct"]:
            block = True; reasons.append(ReasonCode.RISK_REJECT)
        # stop-distance sanity (hard rule)
        if risk["stop_distance_pips"] <= 0:
            block = True; reasons.append(ReasonCode.RISK_REJECT)
        # planned reward:risk (soft rule -> caution)
        if risk["planned_rr"] < 1.5:
            caution = True
        # correlated exposure (soft rule -> caution)
        if risk.get("correlated_exposure_count", 0) >= 2:
            caution = True

        if block:
            assessment, conf = Assessment.BLOCK, 0.95
        elif caution:
            assessment, conf = Assessment.CAUTION, 0.7
            reasons.append(ReasonCode.OK)
        else:
            assessment, conf = Assessment.CLEAR, 0.9
            reasons.append(ReasonCode.OK)

        return {
            "assessment": assessment, "confidence": conf,
            "evidence": {
                "one_position_per_symbol_ok": risk["open_positions_symbol"] < 1,
                "planned_rr": risk["planned_rr"],
                "stop_distance_pips": risk["stop_distance_pips"],
                "within_daily_loss": risk["account_daily_loss_pct"] < risk["max_daily_loss_pct"],
                "within_drawdown": risk["account_drawdown_pct"] < risk["max_drawdown_pct"],
                "sizing_eligible": not block,
            },
            "reason_codes": reasons, "missing_inputs": [], "data_freshness": {},
        }

    def _block(self, reasons, missing):
        return {"assessment": Assessment.BLOCK, "confidence": 0.0,
                "evidence": {"fail_closed": True, "sizing_eligible": False},
                "reason_codes": reasons, "missing_inputs": missing,
                "data_freshness": {}}
