"""`KnowledgeEngine` — the Knowledge & RAG subsystem's top-level
orchestrator (`ADR-020`): ingestion, deterministic explanation
generation, semantic search, weekly review, research suggestions, and
the read-only Knowledge Dashboard snapshot.

**No decision, execution, risk, compliance, or scoring authority**
(`ADR-020` Hard Rules 1-2) — every method here either stores an
already-produced object or reads one; none constructs a
`RiskDecision`/`ComplianceDecision`/`ExecutionDecision`/`CandidateTrade`/
`PositionManagementDecision`, and no pipeline-stage package imports this
module (`scripts/check_architecture.py` enforces this).

`ExplanationEngine` is deterministic-template-only for Phase 1
(`ADR-020` Hard Rule 5) — every explanation is built from an
already-recorded `reason_codes`/`blocking_rules`/`blocking_reasons`/
`decision_reason` field. An LLM-backed "assistant mode" is a real,
intended future subclass of this same interface — explicitly not built
here (`ADR-020` §8).
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Dict, Optional, Sequence, Tuple

from ..analytics.models import OutcomeKind, TradeProvenanceRecord
from ..compliance_engine.models import ComplianceDecision
from ..compliance_engine.models import Verdict as ComplianceVerdict
from ..execution_validator.models import ExecutionDecision
from ..execution_validator.models import Verdict as ExecutionVerdict
from ..paper_trading import PeriodReport
from ..position_manager.models import ManagementAction, PositionManagementDecision
from ..risk_engine.models import RiskDecision, RiskTier
from ..statistical_risk.models import StatisticalRiskAssessment
from .config import DEFAULT_CONFIG, KnowledgeConfig
from .embeddings import EmbeddingProvider, HashingEmbeddingProvider
from .ingestion import KnowledgeDocumentStore, build_statistical_risk_document, build_trade_memory_record
from .logging_sink import log_document_ingested, log_search_performed, log_trade_recorded
from .memory import TradeMemoryStore
from .metrics import KnowledgeMetrics
from .models import (
    DocumentKind,
    KnowledgeDashboardSnapshot,
    KnowledgeDocument,
    ResearchCategory,
    ResearchSuggestion,
    SCHEMA_VERSION,
    SearchResult,
    TradeMemoryRecord,
)
from .retriever import Retriever
from .search import SemanticSearchService, trade_to_text
from .vector_store import InMemoryVectorStore, VectorStore

_ACTION_PHRASES: Dict[ManagementAction, str] = {
    ManagementAction.NO_ACTION: "No management action was taken",
    ManagementAction.MOVE_TO_BREAKEVEN: "Stop moved to breakeven",
    ManagementAction.MOVE_STOP_LOSS: "Stop loss manually adjusted",
    ManagementAction.TRAIL_STOP: "Trailing stop moved",
    ManagementAction.PARTIAL_CLOSE: "Position partially closed",
    ManagementAction.TIME_EXIT: "Position closed on time exit",
    ManagementAction.EMERGENCY_CLOSE: "Position emergency-closed",
}


class ExplanationEngine:
    """Deterministic, template-based explanation generation. Every
    method reads only fields already present on its input; none calls an
    external service."""

    def explain_risk_decision(self, risk_decision: Optional[RiskDecision]) -> str:
        if risk_decision is None:
            return "No risk decision was recorded for this trace."
        reasons = ", ".join(risk_decision.reason_codes) or "no reason code recorded"
        if risk_decision.risk_tier == RiskTier.HALTED:
            return f"Risk reduced to zero (HALTED) because: {reasons}."
        return (
            f"Risk approved at {risk_decision.approved_risk_percent:.2f}% "
            f"(tier {risk_decision.risk_tier.value}, limited by {risk_decision.limiting_constraint}) "
            f"because: {reasons}."
        )

    def explain_compliance_decision(self, compliance_decision: Optional[ComplianceDecision]) -> str:
        if compliance_decision is None:
            return "No compliance decision was recorded for this trace."
        if compliance_decision.verdict == ComplianceVerdict.BLOCK:
            reasons = ", ".join(compliance_decision.blocking_rules) or "no blocking rule recorded"
            return f"Trade blocked by compliance because: {reasons}."
        reasons = ", ".join(compliance_decision.reason_codes) or "no reason code recorded"
        return f"Trade approved by compliance because: {reasons}."

    def explain_execution_decision(self, execution_decision: Optional[ExecutionDecision]) -> str:
        if execution_decision is None:
            return "No execution decision was recorded for this trace."
        if execution_decision.verdict == ExecutionVerdict.REJECT:
            reasons = ", ".join(execution_decision.blocking_reasons) or "no blocking reason recorded"
            return f"Execution failed because: {reasons}."
        reasons = ", ".join(execution_decision.reason_codes) or "no reason code recorded"
        return f"Execution approved because: {reasons}."

    def explain_position_management(self, decisions: Sequence[PositionManagementDecision]) -> Tuple[str, ...]:
        explanations = []
        for decision in decisions:
            if decision.action == ManagementAction.NO_ACTION:
                continue
            phrase = _ACTION_PHRASES.get(decision.action, decision.action.value)
            explanations.append(f"{phrase} because: {decision.decision_reason}.")
        return tuple(explanations)

    def explain_trade(self, record: TradeProvenanceRecord) -> Tuple[str, Optional[str], Tuple[str, ...], str]:
        """Returns (why_trade_happened, why_trade_skipped,
        rule_explanations, ai_explanation)."""
        risk_explanation = self.explain_risk_decision(record.risk_decision)
        compliance_explanation = self.explain_compliance_decision(record.compliance_decision)
        execution_explanation = self.explain_execution_decision(record.execution_decision)
        position_explanations = self.explain_position_management(record.position_management_decisions)

        rejected = record.final_outcome is not None and record.final_outcome.outcome_kind == OutcomeKind.REJECTED
        entry_concept = record.candidate.entry_concept if record.candidate else None
        reasoning = record.candidate.reasoning if record.candidate else None

        rule_explanations = tuple(
            part for part in (risk_explanation, compliance_explanation, execution_explanation, *position_explanations) if part
        )

        if rejected:
            stage = record.final_outcome.rejected_at_stage if record.final_outcome else None
            stage_reason = record.final_outcome.rejection_reason if record.final_outcome else None
            skip_parts = [
                part
                for part in (
                    f"Rejected at {stage}: {stage_reason}." if stage else None,
                    risk_explanation,
                    compliance_explanation,
                    execution_explanation,
                )
                if part
            ]
            why_trade_skipped = " ".join(skip_parts)
            return "", why_trade_skipped, rule_explanations, why_trade_skipped

        happened_parts = [
            part
            for part in (entry_concept, reasoning, risk_explanation, compliance_explanation, execution_explanation)
            if part
        ]
        why_trade_happened = " ".join(happened_parts)
        return why_trade_happened, None, rule_explanations, why_trade_happened


class KnowledgeEngine:
    def __init__(
        self,
        embedding_provider: Optional[EmbeddingProvider] = None,
        vector_store: Optional[VectorStore] = None,
        document_store: Optional[KnowledgeDocumentStore] = None,
        trade_memory_store: Optional[TradeMemoryStore] = None,
        explanation_engine: Optional[ExplanationEngine] = None,
        config: KnowledgeConfig = DEFAULT_CONFIG,
        metrics: Optional[KnowledgeMetrics] = None,
    ) -> None:
        self._config = config
        self._embedding_provider = embedding_provider or HashingEmbeddingProvider(config.embedding_dimension)
        self._vector_store = vector_store or InMemoryVectorStore()
        self._document_store = document_store or KnowledgeDocumentStore()
        self._trade_memory_store = trade_memory_store or TradeMemoryStore()
        self._explanation_engine = explanation_engine or ExplanationEngine()
        self.metrics = metrics or KnowledgeMetrics()
        self._research_queue: list = []

        self._retriever = Retriever(
            self._embedding_provider, self._vector_store, self._document_store, self._trade_memory_store
        )
        self._search_service = SemanticSearchService(self._retriever, self._trade_memory_store)

    @property
    def trade_memory(self) -> TradeMemoryStore:
        return self._trade_memory_store

    @property
    def documents(self) -> KnowledgeDocumentStore:
        return self._document_store

    @property
    def search_service(self) -> SemanticSearchService:
        return self._search_service

    def ingest_document(self, document: KnowledgeDocument) -> bool:
        added = self._document_store.add(document)
        if added:
            vector = self._embedding_provider.embed(document.content)
            self._vector_store.add(document.document_id, vector, metadata={"kind": document.kind.value})
            log_document_ingested(document)
            self.metrics.record_document_ingested()
        else:
            self.metrics.record_duplicate_document_skipped()
        return added

    def ingest_documents(self, documents: Sequence[KnowledgeDocument]) -> int:
        return sum(1 for document in documents if self.ingest_document(document))

    def record_trade(
        self, record: TradeProvenanceRecord, now: datetime, replay_link: Optional[str] = None
    ) -> TradeMemoryRecord:
        why_happened, why_skipped, rule_explanations, ai_explanation = self._explanation_engine.explain_trade(record)
        memory_record = build_trade_memory_record(
            record, why_happened, why_skipped, rule_explanations, ai_explanation, replay_link, now
        )
        added = self._trade_memory_store.add(memory_record)
        if added:
            vector = self._embedding_provider.embed(trade_to_text(memory_record))
            self._vector_store.add(
                memory_record.trace_id,
                vector,
                metadata={
                    "kind": "TRADE",
                    "symbol": memory_record.symbol or "",
                    "strategy_id": memory_record.strategy_id or "",
                },
            )
            log_trade_recorded(memory_record)
            self.metrics.record_trade_indexed()
        else:
            self.metrics.record_duplicate_trade_skipped()
        return memory_record

    def record_statistical_risk_assessment(self, assessment: StatisticalRiskAssessment, now: datetime) -> bool:
        """Stores one `StatisticalRiskAssessment` as a `KnowledgeDocument`
        (`ADR-022` Amendment 1 §A1.2 item 4) — reuses `ingest_document()`
        verbatim (dedup, embedding, logging, metrics all already covered
        by that path, never a second ingestion implementation)."""
        document = build_statistical_risk_document(assessment, now)
        return self.ingest_document(document)

    def find_statistical_risk_assessments(
        self, recommendation: Optional[str] = None
    ) -> Tuple[KnowledgeDocument, ...]:
        """Literal filter over already-ingested `STATISTICAL_RISK_ASSESSMENT`
        documents (`ADR-022` Amendment 1 §A1.2 item 4) — mirrors
        `SemanticSearchService.find_by_setup_pattern`'s own literal-match
        precedent; free-text questions ("safest trading weeks", "highest
        portfolio heat periods", "compare volatility regimes") are served
        by `search()`'s existing semantic path over the same documents,
        never a second, fabricated NLP layer."""
        return tuple(
            document
            for document in self._document_store.all()
            if document.kind == DocumentKind.STATISTICAL_RISK_ASSESSMENT
            and (recommendation is None or document.metadata.get("statistical_recommendation") == recommendation)
        )

    def search(self, text: str, top_k: Optional[int] = None, filters: Optional[dict] = None) -> Tuple[SearchResult, ...]:
        start = time.monotonic()
        results = self._search_service.search(text, top_k=top_k or self._config.default_top_k, filters=filters)
        latency = time.monotonic() - start
        self.metrics.record_search(latency)
        log_search_performed(text, len(results), latency)
        return results

    def suggest_research(self, period_report: PeriodReport, now: datetime) -> Tuple[ResearchSuggestion, ...]:
        suggestions = []
        if period_report.worst_session is not None:
            suggestions.append(
                ResearchSuggestion(
                    schema_version=SCHEMA_VERSION,
                    category=ResearchCategory.SESSION,
                    description=(
                        f"{period_report.worst_session} ranked worst by realized PnL this period — "
                        f"consider a session filter or reduced sizing for it."
                    ),
                    supporting_evidence=(f"worst_session={period_report.worst_session}",),
                    generated_at=now,
                )
            )
        if period_report.worst_pair is not None:
            suggestions.append(
                ResearchSuggestion(
                    schema_version=SCHEMA_VERSION,
                    category=ResearchCategory.FILTER,
                    description=(
                        f"{period_report.worst_pair} ranked worst by realized PnL this period — "
                        f"consider a pair-level filter or confluence requirement."
                    ),
                    supporting_evidence=(f"worst_pair={period_report.worst_pair}",),
                    generated_at=now,
                )
            )
        if period_report.worst_regime is not None:
            suggestions.append(
                ResearchSuggestion(
                    schema_version=SCHEMA_VERSION,
                    category=ResearchCategory.MARKET_OBSERVATION,
                    description=(
                        f"{period_report.worst_regime} regime ranked worst by realized PnL this period — "
                        f"consider a regime-aware filter."
                    ),
                    supporting_evidence=(f"worst_regime={period_report.worst_regime}",),
                    generated_at=now,
                )
            )
        if period_report.compliance_blocks_by_check:
            top_check = max(period_report.compliance_blocks_by_check, key=period_report.compliance_blocks_by_check.get)
            count = period_report.compliance_blocks_by_check[top_check]
            suggestions.append(
                ResearchSuggestion(
                    schema_version=SCHEMA_VERSION,
                    category=ResearchCategory.RISK,
                    description=(
                        f"Compliance check {top_check!r} blocked the most trades this period ({count}) — "
                        f"review whether the underlying setup should be filtered earlier in the pipeline."
                    ),
                    supporting_evidence=(f"check={top_check}", f"count={count}"),
                    generated_at=now,
                )
            )
        self._research_queue.extend(suggestions)
        return tuple(suggestions)

    def generate_weekly_review(
        self, period_report: PeriodReport, now: datetime
    ) -> Tuple[PeriodReport, Tuple[ResearchSuggestion, ...]]:
        """Wraps an already-built `PeriodReport` (`ReportGenerator`,
        Phase 4) — never a second grouping/statistics implementation
        (`ADR-020` Hard Rule 7) — and adds this package's own
        research-suggestion layer on top."""
        return period_report, self.suggest_research(period_report, now)

    def render_dashboard_snapshot(self, now: datetime) -> KnowledgeDashboardSnapshot:
        all_trades = self._trade_memory_store.all()
        recent_trades = all_trades[-self._config.recent_trade_memory_limit :]
        recent_explanations = tuple(r.ai_explanation for r in recent_trades[-self._config.recent_ai_explanations_limit :])
        recent_insights = tuple(
            r.why_trade_happened or r.why_trade_skipped or ""
            for r in recent_trades[-self._config.recent_insights_limit :]
        )
        return KnowledgeDashboardSnapshot(
            schema_version=SCHEMA_VERSION,
            generated_at=now,
            recent_insights=recent_insights,
            recent_trade_memory=recent_trades,
            research_queue=tuple(self._research_queue),
            recent_ai_explanations=recent_explanations,
        )


__all__ = ["ExplanationEngine", "KnowledgeEngine"]
