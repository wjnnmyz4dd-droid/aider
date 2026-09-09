# Session Edge — Third-Party Dependencies & Licensing Record

Session Edge is an **original implementation**. External repositories may be used
for inspiration and research only. No third-party source code, proprietary
prompts, or protected content is copied into Session Edge.

## Intentional runtime dependencies

| Component | Dependency | License | Used by | Notes |
|---|---|---|---|---|
| Strategy engine (`run_dir/code`) | Python stdlib | PSF | engine | — |
| Strategy engine tests | numpy, pandas | BSD-3-Clause | tests only | scientific stack; not shipped in the EA |
| Filesystem bridge (`bridge/`) | Python stdlib only | PSF | bridge | no third-party |
| MT5 execution adapter (`ea_mt5/`, Python ref + tests) | Python stdlib only | PSF | adapter | no third-party |
| MQL5 EA (`ea_mt5/*.mq5,*.mqh`) | MetaTrader 5 MQL5 standard library (`Trade\Trade.mqh`) | MetaQuotes (bundled with MT5) | EA | first-party MT5 SDK, compiled in MetaEditor |
| Multi-agent layer (`agents/`) | Python stdlib only | PSF | agents | no third-party; no network client shipped |

## Deferred / not yet integrated (require an approved source contract first)

| Item | Status | Gate |
|---|---|---|
| Forex Factory economic calendar | **not integrated** | live scraping is prohibited until an approved data-source contract exists; Phase 4A consumes a pre-supplied *normalized* event bundle only |
| Real LLM provider(s) | **not integrated** | a real provider will implement the single `agents.llm.LLMProvider` interface in a later phase; only an offline deterministic mock ships now |

## Originality statement

- No copied third-party source code.
- No copied proprietary prompts or protected content.
- Serialization, hashing, audit, dedup, validation, and memory are original
  Session Edge implementations (the agent layer reuses the project's own bridge
  serializer/audit — a single internal source of truth, not third-party code).

Update this record whenever a new intentional third-party dependency is added.
