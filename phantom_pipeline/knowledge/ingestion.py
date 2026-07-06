"""Ingestion for the Knowledge & RAG subsystem (`ADR-020` §2).

Two ingestion paths, both read-only and both restricted to a named
source set — never an arbitrary directory walk, never a credential/`.env`
file (`ADR-020` §2's explicit exclusion):

- **Documents**: `ingest_markdown_file`/`ingest_directory` read `.md`
  files from explicitly-named locations (root docs, `docs/adr/`,
  `docs/plans/`) into `KnowledgeDocument`s. `KnowledgeDocumentStore`
  deduplicates by content hash — re-ingesting an unchanged file is a
  no-op; re-ingesting a *changed* file updates the stored document
  (incremental indexing), it does not create a second entry.
- **Trades**: `build_trade_memory_record` maps an already-produced
  `TradeProvenanceRecord`'s own fields directly onto a
  `TradeMemoryRecord` — entry/exit price, symbol, direction, session,
  regime, strategy, score, risk/compliance/execution verdicts, position
  management history, and PnL/MAE/MFE are all read, never re-derived
  (`ADR-020` Hard Rule 8). Explanation strings are computed by
  `engine.py` and passed in here as plain values — this module performs
  no explanation generation of its own.
"""

from __future__ import annotations

import glob
import hashlib
import os
import threading
from datetime import datetime
from typing import Dict, Optional, Set, Tuple, TypeVar

from ..analytics.models import TradeProvenanceRecord
from ..position_manager.models import LifecycleState
from .models import SCHEMA_VERSION, DocumentKind, KnowledgeDocument, TradeMemoryRecord

T = TypeVar("T")


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _first_not_none(*values: Optional[T]) -> Optional[T]:
    for value in values:
        if value is not None:
            return value
    return None


def ingest_markdown_file(path: str, kind: DocumentKind, now: datetime) -> KnowledgeDocument:
    with open(path, "r", encoding="utf-8") as handle:
        content = handle.read()
    title = os.path.basename(path)
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip() or title
            break
    return KnowledgeDocument(
        schema_version=SCHEMA_VERSION,
        document_id=path,
        kind=kind,
        title=title,
        content=content,
        source_path=path,
        content_hash=_content_hash(content),
        metadata={"source_path": path},
        ingested_at=now,
    )


def ingest_directory(root: str, kind: DocumentKind, now: datetime, pattern: str = "*.md") -> Tuple[KnowledgeDocument, ...]:
    if not os.path.isdir(root):
        return ()
    paths = sorted(glob.glob(os.path.join(root, pattern)))
    return tuple(ingest_markdown_file(path, kind, now) for path in paths)


# Root-relative document -> DocumentKind, per ADR-020 SS2's named list.
KNOWN_ROOT_DOCUMENTS: Dict[str, DocumentKind] = {
    "INTERFACE_SPECIFICATION.md": DocumentKind.INTERFACE_SPEC,
    "IMPLEMENTATION_PLAN.md": DocumentKind.IMPLEMENTATION_PLAN,
    "VALIDATION_MATRIX.md": DocumentKind.VALIDATION_MATRIX,
    "CHANGELOG.md": DocumentKind.CHANGELOG,
    "LIVE_DEPLOYMENT_GUIDE.md": DocumentKind.DEPLOYMENT_GUIDE,
    "VPS_SETUP_GUIDE.md": DocumentKind.DEPLOYMENT_GUIDE,
    "DISASTER_RECOVERY.md": DocumentKind.DEPLOYMENT_GUIDE,
    "OPERATOR_CHECKLIST.md": DocumentKind.DEPLOYMENT_GUIDE,
    os.path.join(".claude", "agents", "TEAM.md"): DocumentKind.TEAM_DOC,
}


def ingest_repository_documents(repo_root: str, now: datetime) -> Tuple[KnowledgeDocument, ...]:
    """Ingests every named root document (`KNOWN_ROOT_DOCUMENTS`), every
    ADR (`docs/adr/*.md`), and every RPI plan artifact
    (`docs/plans/*.md`). Missing files are skipped, never an error — a
    fresh checkout mid-Phase build legitimately may not have every file
    yet."""
    documents = []
    for relative_path, kind in KNOWN_ROOT_DOCUMENTS.items():
        full_path = os.path.join(repo_root, relative_path)
        if os.path.isfile(full_path):
            documents.append(ingest_markdown_file(full_path, kind, now))
    documents.extend(ingest_directory(os.path.join(repo_root, "docs", "adr"), DocumentKind.ADR, now))
    documents.extend(ingest_directory(os.path.join(repo_root, "docs", "plans"), DocumentKind.PLAN_DOC, now))
    return tuple(documents)


class KnowledgeDocumentStore:
    """Real Phase 1 in-memory document repository, thread-safe,
    deduplicated by content hash (`ADR-020` §2's "Automatic
    deduplication")."""

    def __init__(self) -> None:
        self._documents: Dict[str, KnowledgeDocument] = {}
        self._hashes: Set[str] = set()
        self._lock = threading.Lock()

    def add(self, document: KnowledgeDocument) -> bool:
        """Returns True if newly added or updated (content changed),
        False if an identical (same `document_id`, same `content_hash`)
        document is already stored — the incremental-indexing no-op
        case."""
        with self._lock:
            existing = self._documents.get(document.document_id)
            if existing is not None and existing.content_hash == document.content_hash:
                return False
            if existing is not None:
                self._hashes.discard(existing.content_hash)
            self._documents[document.document_id] = document
            self._hashes.add(document.content_hash)
            return True

    def get(self, document_id: str) -> Optional[KnowledgeDocument]:
        with self._lock:
            return self._documents.get(document_id)

    def all(self) -> Tuple[KnowledgeDocument, ...]:
        with self._lock:
            return tuple(self._documents.values())

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._documents)


def build_trade_memory_record(
    record: TradeProvenanceRecord,
    why_trade_happened: str,
    why_trade_skipped: Optional[str],
    rule_explanations: Tuple[str, ...],
    ai_explanation: str,
    replay_link: Optional[str],
    now: datetime,
) -> TradeMemoryRecord:
    symbol = _first_not_none(
        record.candidate.symbol if record.candidate else None,
        record.risk_decision.symbol if record.risk_decision else None,
        record.compliance_decision.symbol if record.compliance_decision else None,
        record.execution_decision.symbol if record.execution_decision else None,
    )
    direction = _first_not_none(
        record.candidate.direction if record.candidate else None,
        record.risk_decision.direction if record.risk_decision else None,
        record.compliance_decision.direction if record.compliance_decision else None,
        record.execution_decision.direction if record.execution_decision else None,
    )
    sessions = record.scanner_observation.session.active_sessions if record.scanner_observation else ()
    market_regime = (
        record.scanner_observation.phase.value
        if record.scanner_observation is not None and record.scanner_observation.phase is not None
        else None
    )
    strategy_id = record.candidate.strategy_id if record.candidate else None
    score_total = record.score_result.overall_score if record.score_result else None
    risk_tier = record.risk_decision.risk_tier.value if record.risk_decision else None
    compliance_verdict = record.compliance_decision.verdict.value if record.compliance_decision else None
    execution_verdict = record.execution_decision.verdict.value if record.execution_decision else None
    position_management_actions = tuple(d.action.value for d in record.position_management_decisions)

    entry_price = None
    if record.fill_reports:
        entry_price = min(record.fill_reports, key=lambda f: f.fill_timestamp).fill_price

    exit_price = None
    if record.position_updates:
        latest_update = max(record.position_updates, key=lambda u: u.timestamp)
        if latest_update.lifecycle_state == LifecycleState.CLOSED:
            exit_price = latest_update.current_price

    realized_pnl = record.final_outcome.realized_pnl if record.final_outcome else None
    mae = record.final_outcome.mae if record.final_outcome else None
    mfe = record.final_outcome.mfe if record.final_outcome else None

    return TradeMemoryRecord(
        schema_version=SCHEMA_VERSION,
        trace_id=record.trace_id,
        symbol=symbol,
        direction=direction,
        entry_price=entry_price,
        exit_price=exit_price,
        sessions=sessions,
        market_regime=market_regime,
        strategy_id=strategy_id,
        score_total=score_total,
        risk_tier=risk_tier,
        compliance_verdict=compliance_verdict,
        execution_verdict=execution_verdict,
        position_management_actions=position_management_actions,
        realized_pnl=realized_pnl,
        mae=mae,
        mfe=mfe,
        why_trade_happened=why_trade_happened,
        why_trade_skipped=why_trade_skipped,
        rule_explanations=rule_explanations,
        ai_explanation=ai_explanation,
        replay_link=replay_link,
        collected_at=now,
    )


__all__ = [
    "KNOWN_ROOT_DOCUMENTS",
    "KnowledgeDocumentStore",
    "ingest_markdown_file",
    "ingest_directory",
    "ingest_repository_documents",
    "build_trade_memory_record",
]
