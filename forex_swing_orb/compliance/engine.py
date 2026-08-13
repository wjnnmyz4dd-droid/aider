"""The deterministic FTMO Compliance Engine (Phase 5C).

Runs the frozen evaluation pipeline in its mandatory order and produces a
:class:`ComplianceDecision`. On PASS it writes the audit record and THEN invokes
the injected bridge writer; on REJECT it writes the audit record and performs NO
bridge write, NO acknowledgement, NO execution. The engine never touches the
strategy, the bridge internals, the Position Manager, or the MT5 adapter — the
bridge writer is injected from outside so no frozen subsystem is modified.

Execution order (frozen):
  1 Kill Switch  2 Market  3 FTMO  4 Session  5 News  6 Broker Health  7 Risk
  8 Final Compliance Decision
"""

from __future__ import annotations

from ..bridge import serialize
from . import gates
from .news import gate_news
from .contract import (ComplianceConfig, ComplianceDecision, Decision,
                       ENGINE_VERSION, ReasonCode, SCHEMA_VERSION, Stage,
                       _sanitize, decision_id)


class ComplianceEngine:
    """Mandatory deterministic gate between strategy and bridge."""

    def __init__(self, config=None, audit_log=None, bridge_writer=None):
        self.config = config or ComplianceConfig()
        self.audit_log = audit_log
        # bridge_writer(candidate, decision) -> None. Injected; may be None.
        self.bridge_writer = bridge_writer

    # -- public API ---------------------------------------------------------
    def evaluate(self, candidate, *, market_state, account_state, broker_health,
                 news_bundle, now, kill_switch=False, dry_run=False):
        """Evaluate one strategy candidate. Deterministic; side effects (audit +
        bridge) happen only when ``dry_run`` is False. Returns ComplianceDecision.
        """
        cfg = self.config
        verdicts = []

        # ordered pipeline; short-circuit (fail closed) on first reject
        pipeline = (
            lambda: gates.gate_kill_switch(kill_switch),
            lambda: gates.gate_market(candidate, market_state, now),
            lambda: gates.gate_ftmo(candidate, account_state, cfg.profile, cfg.ftmo, cfg.session, now),
            lambda: gates.gate_session(candidate, cfg.session, now),
            lambda: gate_news(candidate, news_bundle, cfg.news, now),
            lambda: gates.gate_broker_health(broker_health, now),
            lambda: gates.gate_risk(candidate, account_state, cfg.profile, cfg.ftmo, now,
                                    broker_health=broker_health),
        )

        reject = None
        for step in pipeline:
            v = step()
            verdicts.append(v)
            if not v.passed:
                reject = v
                break

        if reject is None:
            decision = Decision.PASS
            primary = ReasonCode.COMPLIANCE_PASS
            reason_codes = (ReasonCode.COMPLIANCE_PASS,)
        else:
            decision = Decision.REJECT
            primary = reject.reason_codes[0]
            reason_codes = tuple(reject.reason_codes)

        record = self._build_record(candidate, decision, primary, reason_codes,
                                    verdicts, now)
        result = ComplianceDecision(decision, primary, reason_codes,
                                    tuple(verdicts), record)

        if not dry_run:
            # audit is durable BEFORE any bridge write; on REJECT no bridge write.
            if self.audit_log is not None:
                self.audit_log.emit(record)
            if result.is_pass and self.bridge_writer is not None:
                self.bridge_writer(candidate, result)
        return result

    # -- record construction ------------------------------------------------
    def _build_record(self, candidate, decision, primary, reason_codes, verdicts, now):
        body = {
            "schema_version": SCHEMA_VERSION,
            "engine_version": ENGINE_VERSION,
            "config_digest": self.config.digest(),
            "timestamp": serialize.iso_utc(now) if now is not None else None,
            "signal_id": (candidate or {}).get("signal_id"),
            "symbol": (candidate or {}).get("symbol"),
            "direction": (candidate or {}).get("direction"),
            "decision": decision,
            "primary_reason_code": primary,
            "reason_codes": list(reason_codes),
            "gate_verdicts": {v.stage: v.to_dict() for v in verdicts},
        }
        body = _sanitize(body)
        body["decision_id"] = decision_id(body)
        return body
