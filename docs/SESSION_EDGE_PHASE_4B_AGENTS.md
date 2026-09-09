# Session Edge — Phase 4B: Initial Advisory Agent Implementation

Implements live advisory behavior for the first three agents — **Market
Intelligence**, **Liquidity**, **News & Compliance** — on the Phase 4A
foundation. Risk, Critic, and Decision-Coordinator authority remain the
**inactive** Phase 4A skeleton. All three agents are advisory: they classify,
summarize, flag, and produce CLEAR/CAUTION/BLOCK plus structured evidence and one
immutable memory record. They cannot create direction, write bridge instructions,
place/modify orders, or override the deterministic strategy. No networking, no
Forex Factory scraping, no live LLM, no changes to strategy/bridge/EA.

## Market Intelligence (live)

Deterministically classifies **regime** — TRENDING / RANGING / TRANSITIONAL /
DISORDERED / UNKNOWN — by **interpreting strategy-produced facts** (H4/D1 trend,
Trend Health, session, volatility, structure, continuation). It never recomputes
trend, Trend Health, the London ORB, breakout, retest, or price-action (the facts
are echoed verbatim into `structure_summary`; `recomputes_strategy=false`). An
abnormal-volatility regime is DISORDERED→BLOCK; opposing HTF trends add
`MI_STRUCTURE_CONFLICT`; an unfavorable session downgrades to CAUTION. Output:
`assessment, regime, structure_summary, session_context, volatility_context,
continuation_context, supports_candidate, evidence, reason_codes, confidence,
data_freshness, missing_inputs`. LLM (shared) enriches the summary only and is
rejected if malformed (facts stand regardless).

## Liquidity (live)

Computes liquidity structure from **closed bars only** (no lookahead, deterministic
tolerances): equal highs/lows from **local extrema**, prior-session extremes,
liquidity pools/stop-cluster **inference**, completed **sweeps**
(CONFIRMED/UNCONFIRMED), **failed breakouts** (close-beyond-then-reclaim, distinct
from a wick sweep), breakout-**trap risk**, and **retest quality** vs nearby
liquidity. It **consumes** strategy swing points (never recomputes pivots). Output
maps FAVORABLE→CLEAR / CAUTION / AVOID→BLOCK and includes `liquidity_above,
liquidity_below, nearest_liquidity_distance_pips, sweep_state, trap_risk,
retest_liquidity_quality` plus evidence. It never creates direction
(`creates_direction=false`), never qualifies a setup alone, and frames stops/pools
as evidence-based inference. Fails closed on stale (BLOCK) / insufficient
(<20 bars → CAUTION) data. When no closed-bar bundle is supplied it falls back to
explicit advisory flags (deterministic).

## News & Compliance (live, deterministic)

Consumes a **normalized event bundle** (no scraping/HTTP). Validates the event
schema (`event_id, source, source_timestamp, event_timestamp, timezone, currency,
impact, event_name, previous, forecast, actual?, verification_state,
ingestion_timestamp`), maps currencies to the pair (base/quote), and applies
deterministic **pre/post-event lockout**: relevant HIGH-impact in-window → BLOCK;
MEDIUM → CAUTION; else CLEAR. Fails closed on missing / stale / malformed /
unverifiable / timezone-ambiguous / conflicting data. Operates logically 24/7
(weekends included). Never creates direction or predicts outcomes; rumors
(`verification_state != VERIFIED`) are never treated as verified. Backward
compatible with the Phase 4A event shape.

## Reason-code inventory (added to the single registry)

- MI: `MI_TRENDING_SUPPORTIVE, MI_RANGING, MI_TRANSITIONAL, MI_DISORDERED,
  MI_STRUCTURE_CONFLICT, MI_VOLATILITY_ABNORMAL, MI_SESSION_UNFAVORABLE,
  MI_DATA_INSUFFICIENT, MI_UNKNOWN`
- Liquidity: `LIQUIDITY_FAVORABLE, LIQUIDITY_POOL_NEAR_TARGET,
  LIQUIDITY_POOL_BEHIND_ENTRY, LIQUIDITY_SWEEP_CONFIRMED,
  LIQUIDITY_SWEEP_UNCONFIRMED, LIQUIDITY_TRAP_RISK, LIQUIDITY_FAILED_BREAKOUT,
  LIQUIDITY_RETEST_WEAK, LIQUIDITY_DATA_INSUFFICIENT, LIQUIDITY_DATA_STALE`
- News: `NEWS_CLEAR, NEWS_CAUTION_WINDOW, NEWS_HIGH_IMPACT_BLOCK,
  NEWS_DATA_UNAVAILABLE, NEWS_DATA_STALE, NEWS_DATA_MALFORMED,
  NEWS_SOURCE_UNVERIFIED, NEWS_TIMEZONE_AMBIGUOUS, NEWS_CURRENCY_NOT_MAPPED,
  NEWS_CONFLICTING_RECORDS`

## Orchestration (`Orchestrator.run_advisory`)

Runs `data_quality → market_intelligence → liquidity → news_compliance →
explainability → memory_write`. Risk / Critic / Decision-Coordinator authority
stay INACTIVE (the Phase 4A `run()` skeleton is unchanged). It fails closed on
data-quality BLOCK, schema mismatch, missing/malformed required agent result, and
**news BLOCK**, and a deterministic strategy no-trade always stays no-trade. The
result is an **advisory summary only** (`is_order=false`,
`coordinator_authority_used=false`) — never a bridge instruction.

## Shared memory / LLM / explainability

- **Memory:** one shared `MemoryStore`; each agent evaluation writes one immutable
  content-addressed raw record (with request/correlation ids, assessment,
  confidence, evidence, reason codes, freshness, missing inputs, model/prompt when
  used, provenance, input references). A memory-write failure is audited and never
  alters the advisory result.
- **LLM:** one shared `LLMProvider`; the same instance is injected into the two
  LLM-eligible agents; News is deterministic (no LLM). Malformed LLM output is
  rejected; agents work with `llm=None`.
- **Explainability:** the single service emits strategy-candidate state, all three
  agent outputs, evidence, conflicts, missing data, final advisory, reason codes,
  confidence, and `any_block`; it is not a decision-maker.

## Boundaries confirmed by tests

No networking, no MT5 imports, no bridge writes, no Forex Factory scraping, no
strategy-engine imports/modification, no duplicate agent responsibilities,
strategy/news/agent BLOCK non-override, and advisory output is never an order.

## Tests

56 Phase 4B tests (`test_mi_4b`, `test_liquidity_4b`, `test_news_4b`,
`test_shared_boundaries_4b`) covering all 56 required checks, plus all 68 Phase 4A
foundation tests (125 total). One Phase 4A assertion updated to the bumped MI
prompt version (`market_intelligence.v2`) — coverage unchanged.

## Deviations

- Live agents remain backward compatible with the Phase 4A input shapes so no
  existing test was weakened.
- News consumes a pre-supplied normalized bundle (approved-source adapter
  deferred). No new third-party dependency added (record unchanged).

**Disposition:** READY FOR PHASE 4B INDEPENDENT REVIEW.
