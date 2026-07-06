# Knowledge & RAG Subsystem — Architecture Diagram

See `docs/adr/ADR-020-knowledge-rag-subsystem.md` for the full authority.
This diagram is illustrative only, not itself an authority.

## Data flow

```mermaid
flowchart TB
    subgraph Pipeline["Existing 14-package pipeline (ADR-001..013, unmodified)"]
        DP["data_pipeline"] --> SC["scanner"] --> SE["strategy_engine"] --> SCE["scoring_engine"]
        SCE --> RE["risk_engine"] --> CE["compliance_engine"] --> EV["execution_validator"]
        EV --> MT5["mt5_bridge"] --> PM["position_manager"] --> AN["analytics"]
        WD["watchdog"] -.observes.-> Pipeline
        DASH["dashboard"] -.reads.-> AN
        DASH -.reads.-> WD
    end

    subgraph Docs["Repository documentation (read-only source)"]
        ADRs["docs/adr/*.md"]
        Plans["docs/plans/*.md"]
        RootDocs["CHANGELOG.md, VALIDATION_MATRIX.md,\nIMPLEMENTATION_PLAN.md, INTERFACE_SPECIFICATION.md,\nTEAM.md, deployment guides"]
    end

    AN -- "TradeProvenanceRecord\n(already produced, read-only)" --> ING["knowledge.ingestion\nbuild_trade_memory_record"]
    ADRs --> ING2["knowledge.ingestion\ningest_repository_documents"]
    Plans --> ING2
    RootDocs --> ING2

    ING --> EXP["knowledge.engine\nExplanationEngine\n(deterministic templates)"]
    EXP --> KE["knowledge.engine\nKnowledgeEngine"]
    ING2 --> KE

    KE --> DOCSTORE["knowledge.ingestion\nKnowledgeDocumentStore"]
    KE --> MEMSTORE["knowledge.memory\nTradeMemoryStore"]
    KE --> EMB["knowledge.embeddings\nEmbeddingProvider\n(Hashing default / SentenceTransformer real)"]
    EMB --> VEC["knowledge.vector_store\nInMemoryVectorStore"]

    KE --> SEARCH["knowledge.search\nSemanticSearchService"]
    SEARCH --> RETR["knowledge.retriever\nRetriever"]
    RETR --> VEC
    RETR --> DOCSTORE
    RETR --> MEMSTORE

    KE --> SUGGEST["ResearchSuggestion queue\n(exported data only)"]
    KE --> SNAPSHOT["KnowledgeDashboardSnapshot\n(additive, separate from dashboard/)"]

    PaperTrading["paper_trading.ReportGenerator\nPeriodReport"] -- "already-computed stats\n(never recomputed)" --> KE

    classDef pipeline fill:#2b6cb0,color:#fff,stroke:#1a365d;
    classDef knowledge fill:#38a169,color:#fff,stroke:#22543d;
    classDef docs fill:#805ad5,color:#fff,stroke:#44337a;
    class DP,SC,SE,SCE,RE,CE,EV,MT5,PM,AN,WD,DASH pipeline;
    class ING,ING2,EXP,KE,DOCSTORE,MEMSTORE,EMB,VEC,SEARCH,RETR,SUGGEST,SNAPSHOT knowledge;
    class ADRs,Plans,RootDocs docs;
```

## Reading the diagram

- **Blue** = the existing, unmodified 14-package pipeline (`ADR-001`
  through `ADR-013`). Every arrow leaving this subgraph toward
  `knowledge` is a **read**, never a call in the other direction — no
  pipeline-stage package imports `knowledge` (enforced by
  `scripts/check_architecture.py`, `ADR-020` Hard Rule 9).
- **Purple** = repository documentation, read directly from disk by
  `ingestion.py`, restricted to the named set in `ADR-020` §2 — never an
  arbitrary directory walk.
- **Green** = the new `phantom_pipeline/knowledge/` package (`ADR-020`).
  `KnowledgeEngine` is the single orchestrator; every other green node is
  one of its 11 collaborator modules (`models.py` omitted from the
  diagram as a pure type module with no data flow of its own).
- `KnowledgeDashboardSnapshot` is additive — it is never consumed by
  `dashboard/`, and `dashboard.models.ViewName` is untouched (`ADR-020`
  Hard Rule 4).
- `ResearchSuggestion` is a dead-end node by design: nothing reads it
  back into the pipeline (`ADR-020` Hard Rule 3).
