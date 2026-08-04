"""Shadow Mode integration (Phase 4C) — INFORMATIONAL ONLY.

Runs the advisory agents alongside the authoritative deterministic strategy and
records what the agents *would* have said. It has NO authority: it never modifies
the strategy, orders, stops, targets, bridge instructions, or execution, and it
never writes a bridge instruction. The deterministic strategy decision is an
INPUT (read-only); the shadow layer only observes, scores, explains, and stores.

Pipeline:
    market data -> deterministic strategy -> Market Intelligence -> Liquidity
    -> News & Compliance -> Explainability -> Memory -> Shadow Report
"""

from __future__ import annotations

from collections import Counter

from ..bridge import serialize
from .contract import Advisory, Assessment, SCHEMA_VERSION, StrategyCandidate, deterministic_id

LIVE_AGENTS = ("market_intelligence", "liquidity", "news_compliance")


def _strategy_agreement(candidate, advisory_decision):
    """Do the deterministic strategy and the advisory summary point the same way?"""
    if candidate == StrategyCandidate.QUALIFIED:
        return advisory_decision == Advisory.PROCEED
    return advisory_decision == Advisory.NO_TRADE      # no-trade agreement


def shadow_metrics(strategy_decision, advisory_summary, agent_results):
    """Deterministic per-opportunity statistics. Pure function of its inputs;
    changes nothing."""
    assessments = {n: agent_results[n].get("assessment") for n in LIVE_AGENTS
                   if n in agent_results}
    values = list(assessments.values())
    counts = Counter(values)
    # majority assessment; ties broken toward the more severe (fail-safe reading)
    majority = None
    if counts:
        top = max(counts.values())
        tied = [a for a in Assessment.ALL if counts.get(a, 0) == top]
        majority = max(tied, key=Assessment.severity)
    agreement_score = round(counts.get(majority, 0) / len(values), 3) if values else 0.0
    conflicting = [n for n, a in assessments.items() if a != majority]

    confidences = {n: agent_results[n].get("confidence") for n in assessments}
    reason_freq = Counter()
    for n in assessments:
        for rc in agent_results[n].get("reason_codes", []):
            reason_freq[rc] += 1

    mi = agent_results.get("market_intelligence", {}).get("evidence", {})
    liq = agent_results.get("liquidity", {}).get("evidence", {})
    news = agent_results.get("news_compliance", {}).get("evidence", {})

    return {
        "strategy_decision": strategy_decision.get("candidate"),
        "strategy_direction": strategy_decision.get("direction"),
        "advisory_decision": advisory_summary.get("advisory_decision"),
        "mi_assessment": assessments.get("market_intelligence"),
        "liquidity_assessment": assessments.get("liquidity"),
        "news_assessment": assessments.get("news_compliance"),
        "agreement_score": agreement_score,
        "full_agreement": len(counts) == 1 and bool(values),
        "conflicting_agents": conflicting,
        "strategy_advisory_agreement": _strategy_agreement(
            strategy_decision.get("candidate"), advisory_summary.get("advisory_decision")),
        "confidence_distribution": confidences,
        "min_confidence": round(min([c for c in confidences.values()
                                     if isinstance(c, (int, float))] or [0.0]), 3),
        "reason_code_frequency": dict(reason_freq),
        "market_regime": mi.get("regime"),
        "trend_continuation_context": (mi.get("continuation_context") or {}).get("trend_continuation"),
        "liquidity_observations": {
            "rating": liq.get("liquidity_rating"), "sweep_state": liq.get("sweep_state"),
            "trap_risk": liq.get("trap_risk"),
            "retest_liquidity_quality": liq.get("retest_liquidity_quality")},
        "news_observations": {"rating": news.get("news_rating"),
                              "lockout_hits": len(news.get("lockout_hits", []))},
        "any_block": advisory_summary.get("any_block"),
        "outcome_reference": strategy_decision.get("signal_id"),   # link to outcome later
    }


class ShadowRunner:
    """Observes an opportunity: runs the advisory pipeline beside the strategy and
    stores a shadow report. Never executes, never writes a bridge instruction."""

    runner_id = "shadow_runner"
    runner_version = "0.1.0"

    def __init__(self, orchestrator):
        self.orchestrator = orchestrator

    def observe(self, request, bundle, strategy_decision, now):
        candidate = strategy_decision.get("candidate", StrategyCandidate.NO_TRADE)
        adv = self.orchestrator.run_advisory(request, bundle, candidate, now)
        metrics = shadow_metrics(strategy_decision, adv["advisory_summary"],
                                 adv["agent_results"])
        ts = serialize.iso_utc(now) if now is not None else ""
        report = {
            "schema_version": SCHEMA_VERSION,
            "report_id": deterministic_id("shadow", request.get("request_id"),
                                          strategy_decision.get("candidate")),
            "runner_id": self.runner_id, "runner_version": self.runner_version,
            "request_id": request.get("request_id"),
            "correlation_id": request.get("correlation_id"),
            "symbol": request.get("symbol"),
            "evaluation_timestamp": request.get("evaluation_timestamp"),
            "strategy_decision": dict(strategy_decision),   # copy; strategy authoritative
            "advisory_summary": adv["advisory_summary"],
            "metrics": metrics,
            "explanation": adv["explanation"],
            "shadow": True, "informational_only": True, "is_order": False,
        }
        # store one immutable shadow record (memory failure never affects anything)
        try:
            report["memory_id"] = self.orchestrator.memory.write_raw(
                "shadow_report", request.get("symbol"), report,
                source=f"{self.runner_id}/{self.runner_version}", timestamp=ts,
                correlation_id=request.get("correlation_id"))
        except Exception as exc:
            self.orchestrator.audit.emit(ts, "shadow", "ERROR",
                                         reason_code="SHADOW_MEM_FAILED",
                                         signal_id=request.get("correlation_id"),
                                         detail={"error": type(exc).__name__})
            report["memory_id"] = None
        self.orchestrator.audit.emit(ts, "shadow", "REPORT",
                                     reason_code=metrics["advisory_decision"],
                                     signal_id=request.get("request_id"),
                                     detail={"strategy": metrics["strategy_decision"],
                                             "agreement": metrics["agreement_score"]})
        return report


class ShadowAnalytics:
    """Read-only aggregation over stored shadow reports (and, when present,
    execution outcomes). Never alters strategy or any live behavior."""

    def __init__(self, memory):
        self.memory = memory

    def _reports(self, symbol=None, correlation_id=None):
        return self.memory.query(kind="shadow_report", subject=symbol,
                                 correlation_id=correlation_id, limit=1_000_000)

    def summarize(self, symbol=None, correlation_id=None):
        reports = self._reports(symbol, correlation_id)
        matrix = Counter()                          # (strategy_candidate, advisory)
        regimes = Counter()
        reason_freq = Counter()
        conf_buckets = Counter()
        agreements = []
        for r in reports:
            m = r.get("content", r).get("metrics", {})
            matrix[(m.get("strategy_decision"), m.get("advisory_decision"))] += 1
            if m.get("market_regime"):
                regimes[m["market_regime"]] += 1
            for rc, c in (m.get("reason_code_frequency", {}) or {}).items():
                reason_freq[rc] += c
            band = _band(m.get("min_confidence"))
            conf_buckets[band] += 1
            if isinstance(m.get("agreement_score"), (int, float)):
                agreements.append(m["agreement_score"])
        return {
            "count": len(reports),
            "historical_agreement_matrix": {f"{k[0]}->{k[1]}": v for k, v in matrix.items()},
            "regime_distribution": dict(regimes),
            "reason_code_frequency": dict(reason_freq),
            "confidence_distribution": dict(conf_buckets),
            "mean_agreement_score": round(sum(agreements) / len(agreements), 3)
            if agreements else 0.0,
        }

    def accuracy(self, symbol=None):
        """Advisory accuracy vs eventual outcomes, when execution_outcome records
        exist. false_positive: advisory PROCEED but the outcome was a loss;
        false_negative: advisory NOT PROCEED but a taken trade won. Returns zeros
        with outcomes_available=False when no outcomes are stored yet."""
        reports = self._reports(symbol)
        # outcome index by signal_id, from stored execution_outcome records
        outcomes = {}
        for o in self.memory.query(kind="execution_outcome", subject=symbol, limit=1_000_000):
            c = o.get("content", {})
            sid = c.get("signal_id")
            if sid:
                outcomes[sid] = c
        tp = fp = tn = fn = considered = 0
        for r in reports:
            m = r.get("content", {}).get("metrics", {})
            sid = m.get("outcome_reference")
            oc = outcomes.get(sid)
            if oc is None:
                continue
            considered += 1
            won = bool(oc.get("won"))
            taken = bool(oc.get("taken", True))
            proceed = m.get("advisory_decision") == Advisory.PROCEED
            if proceed and won:
                tp += 1
            elif proceed and not won:
                fp += 1
            elif (not proceed) and taken and won:
                fn += 1
            else:
                tn += 1
        acc = round((tp + tn) / considered, 3) if considered else 0.0
        return {"outcomes_available": considered > 0, "considered": considered,
                "true_positive": tp, "false_positive": fp,
                "true_negative": tn, "false_negative": fn,
                "advisory_accuracy": acc}


def _band(x):
    if not isinstance(x, (int, float)):
        return "UNKNOWN"
    if x < 0.34:
        return "LOW"
    if x < 0.67:
        return "MEDIUM"
    return "HIGH"
