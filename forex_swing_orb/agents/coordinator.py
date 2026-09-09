"""Decision Coordinator (DETERMINISTIC ONLY).

Collects the structured agent outputs, verifies required evidence is present,
applies a deterministic decision policy, and emits ONE advisory decision that
preserves every agent's evidence and reason codes.

It is NOT a strategy engine and cannot place or modify a trade. Hard invariants
(never overridden by confidence or any agent):
  * a deterministic strategy NO_TRADE stays NO_TRADE
  * a data-quality failure -> NO_TRADE
  * a news BLOCK -> NO_TRADE
  * a risk BLOCK -> NO_TRADE
  * any agent BLOCK -> NO_TRADE
Advisory PROCEED still passes through the downstream deterministic risk/
compliance gates, the filesystem bridge and the MT5 adapter — it is not an order.
"""

from __future__ import annotations

from .contract import (Advisory, Assessment, ReasonCode, StrategyCandidate,
                       confidence_band)

REQUIRED_AGENTS = ("market_intelligence", "liquidity", "news_compliance",
                   "risk", "critic")


class DecisionCoordinator:
    agent_id = "decision_coordinator"
    agent_version = "0.1.0"

    def decide(self, request, agent_results, strategy_candidate, data_quality_ok):
        """Return one advisory decision record. ``agent_results`` maps agent_id ->
        result dict; ``strategy_candidate`` is what the deterministic strategy
        produced (this class never computes it)."""
        reasons = []
        evidence = {"agent_assessments": {}, "agent_reason_codes": {}}
        for name, res in agent_results.items():
            evidence["agent_assessments"][name] = res.get("assessment")
            evidence["agent_reason_codes"][name] = res.get("reason_codes")

        # 1. data quality (hard)
        if not data_quality_ok:
            return self._decision(request, Advisory.NO_TRADE,
                                  [ReasonCode.COORD_BLOCK_DATA_QUALITY], evidence,
                                  agent_results, strategy_candidate, 0.0)
        # 2. deterministic strategy no-trade (hard; never override)
        if strategy_candidate != StrategyCandidate.QUALIFIED:
            return self._decision(request, Advisory.NO_TRADE,
                                  [ReasonCode.COORD_NO_TRADE_STRATEGY], evidence,
                                  agent_results, strategy_candidate, 0.0)
        # 3. required evidence present (fail closed)
        missing = [a for a in REQUIRED_AGENTS if a not in agent_results]
        if missing:
            evidence["missing_agents"] = missing
            return self._decision(request, Advisory.NO_TRADE,
                                  [ReasonCode.COORD_BLOCK_AGENT], evidence,
                                  agent_results, strategy_candidate, 0.0)

        # 4. hard blocks (news / risk / any agent)
        if agent_results["news_compliance"].get("assessment") == Assessment.BLOCK:
            return self._decision(request, Advisory.NO_TRADE,
                                  [ReasonCode.COORD_BLOCK_NEWS], evidence,
                                  agent_results, strategy_candidate, 0.0)
        if agent_results["risk"].get("assessment") == Assessment.BLOCK:
            return self._decision(request, Advisory.NO_TRADE,
                                  [ReasonCode.COORD_BLOCK_RISK], evidence,
                                  agent_results, strategy_candidate, 0.0)
        blocking = [n for n, r in agent_results.items()
                    if r.get("assessment") == Assessment.BLOCK]
        if blocking:
            evidence["blocking_agents"] = blocking
            return self._decision(request, Advisory.NO_TRADE,
                                  [ReasonCode.COORD_BLOCK_AGENT], evidence,
                                  agent_results, strategy_candidate, 0.0)

        # 5. cautions -> advisory caution; else proceed (advisory only)
        cautions = [n for n, r in agent_results.items()
                    if r.get("assessment") == Assessment.CAUTION]
        conf = self._aggregate_confidence(agent_results)
        if cautions:
            evidence["caution_agents"] = cautions
            return self._decision(request, Advisory.CAUTION,
                                  [ReasonCode.COORD_CAUTION], evidence,
                                  agent_results, strategy_candidate, conf)
        return self._decision(request, Advisory.PROCEED,
                              [ReasonCode.COORD_PROCEED_ADVISORY], evidence,
                              agent_results, strategy_candidate, conf)

    # -- helpers ------------------------------------------------------------
    def _aggregate_confidence(self, agent_results):
        vals = [r.get("confidence", 0.0) for r in agent_results.values()
                if isinstance(r.get("confidence"), (int, float))]
        return round(min(vals), 3) if vals else 0.0    # conservative aggregate

    def _decision(self, request, advisory, reasons, evidence, agent_results,
                  strategy_candidate, confidence):
        return {
            "coordinator_id": self.agent_id,
            "coordinator_version": self.agent_version,
            "request_id": request.get("request_id"),
            "correlation_id": request.get("correlation_id"),
            "symbol": request.get("symbol"),
            "advisory_decision": advisory,          # NEVER an order
            "strategy_candidate": strategy_candidate,
            "confidence": confidence,
            "confidence_band": confidence_band(confidence),
            "reason_codes": list(reasons),
            "evidence": evidence,
            "is_order": False,                      # explicit: not a trade
        }
