"""Prop Firm Compliance Engine (Phase 2E).

The final authority before execution. Answers exactly one question: is
a statistically-approved trade allowed under operational and prop-firm
rules? It never selects a strategy, calculates evidence, calculates
statistical risk, reads news providers directly, or executes trades --
it may only APPROVE, REDUCE, or REJECT, never increase risk. See
`docs/adr/ADR-028-compliance-engine.md`.
"""

from __future__ import annotations

from .bands import BandEvaluation, evaluate_graduated_bands
from .compliance_score import compute_compliance_score
from .config import (
    COMPLIANCE_ENGINE_VERSION,
    DEFAULT_DAILY_LOSS_BANDS,
    DEFAULT_DRAWDOWN_BANDS,
    DEFAULT_PROFIT_PROTECTION_BANDS,
    DEFAULT_RULE_PROFILE,
    ComplianceEngineConfig,
)
from .consecutive_loss import consecutive_loss_pause_triggered
from .daily_loss import daily_loss_pct_consumed, evaluate_daily_loss_protection
from .drawdown import evaluate_drawdown_protection, total_drawdown_pct_consumed
from .engine import ComplianceEngine
from .explainability import build_compliance_snapshot
from .lock import apply_daily_reset, apply_operator_unlock, is_locked, trigger_lock
from .logging_sink import log_compliance_snapshot
from .market_conditions import (
    check_max_spread,
    check_market_safety,
    check_news_blackout,
    check_peg_policy,
    check_session_restriction,
)
from .metrics import ComplianceEngineMetrics
from .models import (
    SCHEMA_VERSION,
    AccountState,
    AuditEntry,
    ComplianceDecision,
    ComplianceLockState,
    ComplianceRuleId,
    ComplianceRuleProfile,
    ComplianceSnapshot,
    GraduatedBand,
    LockRecommendation,
)
from .position_limits import check_position_limits
from .profit_protection import daily_profit_pct, evaluate_profit_protection
from .rule_profile import (
    check_consistency_rule,
    check_max_trades_per_day,
    check_pair_disabled,
    check_required_stop_loss,
    check_weekend_restriction,
    profit_target_status,
    trading_days_status,
)

__all__ = [
    "COMPLIANCE_ENGINE_VERSION",
    "SCHEMA_VERSION",
    "DEFAULT_DAILY_LOSS_BANDS",
    "DEFAULT_DRAWDOWN_BANDS",
    "DEFAULT_PROFIT_PROTECTION_BANDS",
    "DEFAULT_RULE_PROFILE",
    "ComplianceEngineConfig",
    "ComplianceEngine",
    "ComplianceEngineMetrics",
    "ComplianceDecision",
    "ComplianceRuleId",
    "GraduatedBand",
    "ComplianceRuleProfile",
    "ComplianceLockState",
    "LockRecommendation",
    "AccountState",
    "AuditEntry",
    "ComplianceSnapshot",
    "BandEvaluation",
    "evaluate_graduated_bands",
    "daily_loss_pct_consumed",
    "evaluate_daily_loss_protection",
    "total_drawdown_pct_consumed",
    "evaluate_drawdown_protection",
    "daily_profit_pct",
    "evaluate_profit_protection",
    "consecutive_loss_pause_triggered",
    "check_pair_disabled",
    "check_weekend_restriction",
    "check_required_stop_loss",
    "check_max_trades_per_day",
    "check_consistency_rule",
    "trading_days_status",
    "profit_target_status",
    "check_position_limits",
    "check_session_restriction",
    "check_market_safety",
    "check_news_blackout",
    "check_peg_policy",
    "check_max_spread",
    "is_locked",
    "apply_daily_reset",
    "apply_operator_unlock",
    "trigger_lock",
    "compute_compliance_score",
    "build_compliance_snapshot",
    "log_compliance_snapshot",
]
