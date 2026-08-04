"""Read-only deterministic compliance status dashboard (Phase 5C).

Informational ONLY. It re-evaluates in ``dry_run`` mode (no audit write, no bridge
write) and derives budgets/status from the same frozen helpers the engine uses. It
SHALL NOT influence execution — it has no path that writes anything.
"""

from __future__ import annotations

from . import gates
from .contract import (Decision, ReasonCode, candidate_risk_amount, finite,
                       ftmo_limits)
from .engine import ComplianceEngine


class ComplianceDashboard:
    def __init__(self, engine):
        if not isinstance(engine, ComplianceEngine):
            raise TypeError("ComplianceDashboard requires a ComplianceEngine")
        self._engine = engine

    def status(self, candidate, *, market_state, account_state, broker_health,
               news_bundle, now, kill_switch=False):
        """Return a deterministic, read-only status snapshot. No side effects."""
        cfg = self._engine.config
        decision = self._engine.evaluate(
            candidate, market_state=market_state, account_state=account_state,
            broker_health=broker_health, news_bundle=news_bundle, now=now,
            kill_switch=kill_switch, dry_run=True)

        limits = ftmo_limits(account_state or {}, cfg.ftmo)
        daily_loss = finite((account_state or {}).get("current_daily_loss"))
        open_risk = finite((account_state or {}).get("open_risk_at_stop"))
        equity = finite((account_state or {}).get("equity"))
        initial = finite((account_state or {}).get("initial_balance"))

        remaining_daily = None
        remaining_max = None
        if limits is not None and daily_loss is not None and open_risk is not None:
            remaining_daily = limits["internal_daily_limit"] - (daily_loss + open_risk)
        if limits is not None and equity is not None and initial is not None:
            remaining_max = limits["internal_max_loss"] - (initial - equity)

        # session + news read-outs (dry, no authority)
        try:
            sess = gates.gate_session(candidate, cfg.session, now)
            active_session = sess.evidence.get("active_session")
        except Exception:
            active_session = None

        news_verdict = {v.stage: v for v in decision.gate_verdicts}.get("news")
        news_lockout = bool(news_verdict is not None and not news_verdict.passed
                            and ReasonCode.NEWS_LOCKOUT in news_verdict.reason_codes)
        lockout_expires = (news_verdict.evidence.get("lockout_expires_at")
                           if news_verdict is not None else None)

        ftmo_verdict = {v.stage: v for v in decision.gate_verdicts}.get("ftmo")
        ftmo_status = "OK" if (ftmo_verdict is not None and ftmo_verdict.passed) else (
            ftmo_verdict.reason_codes[0] if ftmo_verdict is not None else "UNKNOWN")

        broker_verdict = {v.stage: v for v in decision.gate_verdicts}.get("broker_health")
        broker_status = "OK" if (broker_verdict is not None and broker_verdict.passed) else (
            broker_verdict.reason_codes[0] if broker_verdict is not None else "UNKNOWN")

        return {
            "compliance_status": decision.decision,
            "compliance_decision": decision.decision,
            "current_compliance_decision": decision.decision,
            "active_reason_codes": list(decision.reason_codes),
            "primary_reason_code": decision.primary_reason_code,
            "ftmo_status": ftmo_status,
            "remaining_daily_loss_budget": remaining_daily,
            "remaining_max_loss_budget": remaining_max,
            "active_session": active_session,
            "active_news_lockout": news_lockout,
            "lockout_expiration": lockout_expires,
            "broker_health": broker_status,
            "kill_switch_active": bool(kill_switch),
            "decision_id": decision.decision_id,
        }
