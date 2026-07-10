# Technical Specification — Evidence Engine

Specification only. No code exists yet for this component. Cross-
references `PHANTOM_FINAL_ARCHITECTURE.md` (file list, why-it-exists)
and `PHANTOM_IMPLEMENTATION_ROADMAP.md` Phase 3a (build order, exit
criteria) — this document does not repeat those, it specifies the
component in the depth needed to implement it once Phase 1's gate
clears and this spec is approved.

## 1. Purpose

Produce one deterministic, explainable, per-pair read of "what does
the market currently look like" — a 0–100 score, a regime
classification, and a human-readable confidence explanation — for
every enabled pair, continuously. It is the single factual foundation
every downstream decision (Strategy Engine's selection, Risk Engine's
confidence scaling) is built on.

## 2. Responsibilities

- Ingest the price history (candles/ticks) it needs, for enabled pairs
  only, via its own narrow `market_data_source.py`.
- Detect market structure: break of structure (BOS), change of
  character (CHoCH), fair value gaps (FVG), order blocks,
  support/resistance.
- Classify the current regime per pair: trending, ranging, or volatile/
  transitional.
- Compute the deterministic indicator set the scorer depends on.
- Combine structure + regime + indicators into one 0–100 `PairScore`.
- Produce a `PairConfidence` explanation naming which components
  contributed to that score and by how much.
- Emit all of the above through exactly one public entry point.

## 3. Public interfaces

```
evidence_engine.get_pair_evidence(pair: Pair, now: Clock) -> PairEvidence
evidence_engine.get_all_pair_evidence(now: Clock) -> Mapping[Pair, PairEvidence]
```

No other function is exposed. Strategy Engine and Risk Engine consume
only `PairEvidence`; neither may reach into `market_structure.py`,
`indicators.py`, or `regime.py` directly — those are internal.

**Revision (Architecture Hardening):** `evaluate()` and
`get_all_pair_evidence()` are called exclusively by
`phantom/runtime/runtime.py` (`docs/specs/00_runtime_orchestrator.md`)
as of this revision — Evidence Engine itself gains no new caller and no
new dependency; only the identity of its existing caller is now named.
Per-pair evaluation has no shared mutable state and is therefore safely
parallelizable across pairs (closes Red Team Audit Finding 16.1).

## 4. Inputs

- Enabled-pair list and per-pair indicator/lookback parameters
  (`config.py`).
- Price history (candles/ticks) for each enabled pair, sourced by
  `market_data_source.py` — not from PhantomBridgeEA (different data
  domain; PhantomBridgeEA reports execution telemetry, not market
  history).
- A `Clock` (from `phantom/shared/`) for evaluation timestamps.

## 5. Outputs

`PairEvidence` (per pair, per evaluation): `PairScore` (0–100),
`Regime` (trending/ranging/volatile), `PairConfidence` (structured
explanation), and the underlying `MarketStructureFinding` set that
produced them (exposed for audit/logging, not for downstream
recomputation).

## 6. Internal data models

| Model | Shape |
|---|---|
| `MarketStructureFinding` | kind (BOS/CHoCH/FVG/order block/S-R), price level(s), timestamp, timeframe |
| `Regime` | enum: `TRENDING`, `RANGING`, `VOLATILE` |
| `PairScore` | integer 0–100, plus the ordered list of component contributions that sum to it |
| `PairConfidence` | ordered list of `(component_name, contribution, rationale_text)` tuples — the explanation is generated from the same component list that produced the score, never a separate narrative pass, so score and explanation cannot drift apart |
| `PairEvidence` | `(pair, score: PairScore, regime: Regime, confidence: PairConfidence, findings: Tuple[MarketStructureFinding, ...], evaluated_at: Clock)` |

## 7. Decision authority

**None.** Evidence Engine never accepts, rejects, sizes, or blocks a
trade. The "minimum score of 65 to qualify" threshold named in this
specification's brief is enforced by Portfolio Statistical Risk
Engine's Risk Schedule (`PHANTOM_IMPLEMENTATION_ROADMAP.md` §3.1),
not here — Evidence Engine only ever reports the number. Giving this
component its own enforcement of that threshold would create a second
scoring/decision authority, which the architecture lock forbids.

## 8. Dependencies

`phantom/shared/` only (Pair, Timeframe, Clock, Price, shared value
types), plus its own market-data ingestion. No dependency on
PhantomBridgeEA, Strategy Engine, Risk Engine, or any other live
component — Evidence Engine is a leaf in the dependency graph other
than `shared/`.

## 9. Explicit non-responsibilities

- Never selects a strategy or produces a `TradeIdea`.
- Never sizes a position.
- Never applies the 65-point qualification threshold itself.
- Never evaluates news, calendar events, or session/liquidity/spread
  quality — that is Market Intelligence Engine's domain (see the
  architecture freeze §13 item 2 boundary: regime = price-structure
  question, quality scores = execution-safety question).
- Never calls into PhantomBridgeEA or any other live component.
- Never uses a non-deterministic/generative technique — "No AI" in
  this component's original scope holds; scoring is rule-based and
  reproducible.
- **Never calculates session windows, holidays, or DST-adjusted time
  independently.** Market Intelligence Engine is the sole time/session/
  holiday authority (`docs/specs/04_market_intelligence_engine.md`
  §"Authoritative time handling"); if Evidence Engine's regime/
  indicator logic ever needs a session boundary, it consults that
  authority rather than deriving one itself (closes Red Team Audit
  Finding 9.2 for this component).

**Authority restatement (Architecture Hardening):** Evidence Engine
holds **scoring authority only** — the sole source of a pair's
structure/regime/indicator-derived score. No other component may
compute a competing score of this kind (see the system-wide authority
matrix in `PHANTOM_ARCHITECTURE_HARDENING.md`).

## 10. Test plan

- **Unit tests:** one fixture-driven suite per structure detector
  (BOS/CHoCH/FVG/order block/S-R) and per indicator, asserting exact
  output against hand-verified fixture price series.
- **Determinism tests:** the same fixture input run N times must
  produce byte-identical `PairEvidence` every time — no wall-clock or
  RNG dependency anywhere in the scoring path.
- **Score/confidence consistency tests:** assert `PairConfidence`'s
  component contributions always sum to exactly `PairScore` — this is
  a correctness invariant, not merely a nice-to-have.
- **Boundary test:** assert no other package under `phantom/`
  implements its own indicator or market-structure detection (enforces
  "no duplicate indicators").
- **Threshold-reporting test:** assert a fixture pair scoring exactly
  65, 64, and 100 all report through the same code path with no
  special-cased branch at 65 — the threshold has no meaning inside
  this component, confirming §7.

## 11. Performance requirements

- One full pair evaluation (`get_pair_evidence`) must complete well
  within the polling cadence of any consumer — target: under 250ms per
  pair on the reference hardware/timeframe set, so evaluating the full
  enabled-pair list stays under Strategy Engine's own decision-cycle
  budget. This is a target to validate during implementation, not a
  guarantee made here.
- Must not perform blocking I/O (network calls) inside the scoring
  path itself — `market_data_source.py`'s ingestion is a separate,
  cacheable step from `scorer.py`'s computation.

## 12. Failure modes

| Failure | Expected behavior |
|---|---|
| Market data source unavailable for a pair | That pair's `get_pair_evidence` raises a named, catchable error (or returns an explicit "no evidence available" state) — it must never silently return a stale or fabricated score. |
| Insufficient history for a lookback window | Same as above — an explicit insufficient-data state, never a default/placeholder score. |
| A structure detector throws on malformed price data | Caught at the `evidence_engine.py` orchestration layer, logged, and surfaced as a per-pair failure — one pair's bad data must never take down the batch evaluation of other enabled pairs. |

## 13. Security considerations

- No external network exposure — this component is not remotely
  callable; it is an in-process library other components import.
- Market data source credentials (if the historical/candle provider
  requires any) belong in `config.py`'s secret-handling convention,
  never hardcoded, never logged.
- No user-supplied input reaches this component directly (pairs come
  from a fixed, configured enabled-pair list, not runtime user input),
  so this component has a narrow injection surface by construction.

## 14. Logging requirements

- `logging_sink.py` emits one structured event per `get_pair_evidence`
  call: pair, score, regime, evaluation timestamp, and a reference to
  the confidence explanation (not the full explanation text inline, to
  keep log volume bounded — full explanations are queryable on demand).
- `metrics.py` exposes counters/gauges: evaluations per pair, score
  distribution, regime distribution, per-pair evaluation latency, and
  a data-unavailability counter (from §12).

---

## Evidence Engine Scoring Framework (detailed)

### Individual pair scoring

Every enabled pair receives its own `PairScore`, computed independently
of every other pair's score — no cross-pair normalization, ranking, or
curve-fitting. The score is a deterministic sum of named, independently
computed components (structure quality, regime-alignment quality,
indicator confluence, and any further component added only through the
same explicit-approval process as everything else in this project).
Each component contributes a bounded point range; the components are
fixed and documented in `config.py`, never inferred at runtime — this
is what makes "no score inflation" and "no duplicate scoring"
enforceable: there is exactly one place the weights live, and exactly
one function (`scorer.py`) that sums them.

### Minimum score of 65 to qualify

65 is the score at and above which the Risk Schedule
(`PHANTOM_IMPLEMENTATION_ROADMAP.md` §3.1) begins allowing a sized
trade ("Minimum qualified trade" tier, 65–69). Evidence Engine reports
this number like any other; it does not gate, filter, or hide
sub-65 scores from its own output — `get_pair_evidence` returns every
enabled pair's real score regardless of value, so that Research &
Learning Engine's later attribution work (Phase 7) can see the full
distribution, not just the trades that qualified.

### Confidence explanation for every pair

Every `PairEvidence` carries a `PairConfidence` built from the exact
same component list that produced the score — for example (illustrative
only, not a literal implementation): "Market structure: confirmed BOS
on H1, contributes N points. Regime: trending, contributes N points.
Indicator confluence: 2 of 3 configured indicators aligned, contributes
N points." The explanation is generated mechanically from the
component list (template-based), never by a generative/free-form
process — this keeps every score fully auditable back to the rule that
produced each point, which is also why Evidence Engine has no AI
component in its scope.
