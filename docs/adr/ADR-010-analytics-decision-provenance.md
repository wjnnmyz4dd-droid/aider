# ADR-010 — Analytics & Decision Provenance

Status: Accepted

Acceptance Date: 2026-07-04

Accepted By: Software Architect / Titan Protocol Engineering Council

Owner: Software Architect (cross-cutting record of the entire pipeline —
no single per-stage owner is appropriate, the same reasoning `TEAM.md`
already applies to whole-architecture concerns)

Reviewed by: Backend Architect (storage/retrieval reliability patterns),
Multi-Agent Systems Architect (strategy attribution must derive from the
Strategy Registry, `ADR-003` §3 — directly closes the
`analytics.STRATEGIES` defect `TEAM.md`'s backlog flags as "relevant to
ADR-010 (Analytics)")

**Note:** `.claude/agents/TEAM.md`'s RACI table has no existing row for
"Analytics" (the same gap noted for Position Manager before its RACI row
was added). Not fixed here — outside this deliverable's scope — flagged
below as a finding.

Date: 2026-07-04

Depends on: `ADR-001-single-authority-architecture.md` (Accepted),
`ADR-002-scanner.md` (Accepted, including Amendment 1),
`ADR-003-strategy-engine.md` (Accepted), `ADR-004-scoring-engine.md`
(Accepted), `ADR-005-risk-engine.md` (Accepted),
`ADR-006-compliance-engine.md` (Accepted),
`ADR-007-execution-validator.md` (Accepted),
`ADR-008-mt5-bridge.md` (Accepted, including Amendment 1),
`ADR-009-position-manager.md` (Accepted)

---

# Pipeline position

Market Data → Scanner → Strategy Engine → Scoring Engine → Risk Engine →
Compliance Engine → Execution Validator → MT5 Bridge → Position Manager →
**Analytics**

Analytics is the terminal stage of the live pipeline: it collects, it
never feeds back into it. It does not define `ADR-017` (Portfolio
Manager), `ADR-018` (Replay & Certification Engine), or `ADR-019`
(Self-Evolving Market Structure Research Agent) — see §10 for how those
recommended/drafted ADRs relate to this one.

---

# 1. Mission

**The Analytics Engine answers three questions: "What happened? Why did
it happen? Can every decision be reconstructed?"**

**It never changes trading decisions.** Every object it collects is a
read-only copy of something another stage already, immutably, decided or
observed. Analytics is Titan Protocol's permanent institutional memory — it
owns history, not authority.

---

# Hard Rules

These override any other requirement in this document if they ever
appear to conflict:

- **Read-only. Analytics never changes live trading.** It has no output
  that any upstream or downstream live-pipeline stage consumes as an
  instruction — its only outputs are historical records and derived
  statistics (§9), consumed by humans and by research (§10), never by
  Scanner through Position Manager.
- **Nothing may be omitted.** Every decision-provenance record (§6) that
  is incomplete — missing any stage's contribution for a given `trace_id`
  — is a reportable defect (missing-event detection, §12), never silently
  stored as if complete.
- **Analytics owns permanent trade history. No other ADR owns it.** Every
  prior stage's own Logging section (`ADR-002` §11 through `ADR-009`
  §12) establishes event-level operational logging for observability —
  this ADR does not replace or duplicate that. Analytics is the first and
  only stage that aggregates copies of those already-immutable objects
  into a permanent, joined, queryable historical record. Operational logs
  answer "what just happened, right now, for on-call." Decision
  provenance (§6) answers "what happened to this specific trade, ever,
  reconstructible in full."
- **Replay must be deterministic** (§8).

---

# 2. Responsibilities — collected objects

Analytics SHALL collect, as immutable, read-only copies:

- `ScannerObservation`, including its market-structure fields
  (`ADR-002` Amendment 1) — not a separate object, part of
  `ScannerObservation`.
- `CandidateTrade` (`ADR-003` §6).
- `ScoreResult` (`ADR-004` §6).
- `RiskDecision` (`ADR-005` §4).
- `ComplianceDecision` (`ADR-006` §4).
- `ExecutionDecision` (`ADR-007` §4).
- `BrokerAcknowledgement`, `ExecutionReceipt`, `BrokerError` (`ADR-008`
  §5) — collectively what this task specifies as "BrokerReceipt": `ADR-008`
  does not define a type by that exact name, so all three broker-event
  types are collected for full provenance rather than guessing which one
  was meant.
- `FillReport` (`ADR-008` §5).
- `PositionManagementDecision`, `PositionUpdate`,
  `PositionSynchronizationResult` (`ADR-009` §5) — collectively "Position
  history."
- Account snapshots (from `ADR-008` account-state reads and `ADR-009`
  Account State inputs).
- Market snapshots (from `ADR-002` observations and `ADR-007`/`ADR-008`
  fresh-market reads).
- Configuration version — the versioned configuration identifier in
  effect for each decision (every prior stage's configuration is already
  versioned per that stage's own ADR).
- ADR version — which Status/Accepted revision of each relevant ADR was
  in effect (relevant after any future amendment, per the `ADR-002`
  Amendment 1 / `ADR-008` Amendment 1 precedent).
- Strategy version — **derived from the Strategy Registry (`ADR-003`
  §3), never a hand-maintained list.** This is a deliberate, explicit
  architectural requirement, not an implementation detail: `TEAM.md`'s
  backlog already flags `titan_protocol/analytics.py`'s hand-maintained
  `STRATEGIES` tuple as a defect (it silently drifted from the real
  roster and crashed on an unlisted playbook) — this ADR closes that
  defect at the architecture level by requiring strategy attribution to
  come from the same discovery mechanism `ADR-003` already mandates for
  every other purpose.

---

# 3. Analytics shall never

| Forbidden action | Owned instead by |
|---|---|
| Change any trading decision | Nobody — every collected object is immutable at its source stage |
| Generate `CandidateTrade` | Strategy Engine (`ADR-003`) |
| Modify `ScoreResult`, `RiskDecision`, `ComplianceDecision`, `ExecutionDecision` | Nobody — immutable at source |
| Manage or close positions | Position Manager (`ADR-009`) |
| Communicate with MT5 | MT5 Bridge (`ADR-008`) |
| Feed derived statistics back into any live decision | Nobody — see Hard Rules; this is the boundary that keeps Analytics's own calculations (§9) from becoming a second, informal scoring/risk mechanism |
| Grant ADR-019 (or any research process) live pipeline access | Nobody — `ADR-015` §7 / `ADR-016` / `ADR-019` already establish research is advisory-only, data-plane-isolated; this ADR's one-way relationship (§10) is the Analytics-specific instance of that same boundary |

---

# 4. Inputs

All inputs are read-only copies, received as each source stage produces
them (never re-derived, never queried back from a live stage after the
fact in a way that could race with that stage's own state):

- Every object listed in §2, keyed by the shared `trace_id` established
  at Scanner (`ADR-002` §8) and propagated through every subsequent
  stage.
- Configuration, ADR, and strategy version identifiers accompanying each
  object (§2).

---

# 5. Outputs

- **`TradeProvenanceRecord`** (§6) — one per `trace_id`, the full joined
  decision-and-event history for a single trade attempt (whether it was
  ultimately rejected at any stage or fully executed and closed).
- **Performance statistics** (§9) — derived, read-only aggregates over
  one or more `TradeProvenanceRecord`s; never written back to any
  upstream stage.
- **Replay input sets** (§8) — the exact, ordered, immutable inputs a
  given stage saw for a given `trace_id` or time window, sufficient for
  an external replay/certification process (§8) to reproduce that
  stage's decision.
- **Missing-event reports** (§12) — a flagged, non-silent record when any
  expected stage contribution for a `trace_id` is absent.

**Type-level guarantee:** none of these output types can hold a modified
copy of any upstream object — they are read-only joins and derived
statistics, never a mutated or re-decided version of anything collected
(§12).

**Immutability:** every `TradeProvenanceRecord`, once its final outcome
(§6) is recorded, is immutable — a permanent historical record, not a
mutable working object.

---

# 6. Decision provenance

For every trade — whether it terminates at Compliance's BLOCK, Execution
Validator's REJECT, or a fully executed and later closed position — the
`TradeProvenanceRecord` for its `trace_id` must contain:

- **Scanner reason** — the `ScannerObservation` (and market-structure
  fields) that made this trade candidate possible.
- **Strategy reason** — `CandidateTrade`'s reasoning metadata (`ADR-003`
  §6), never re-derived, only quoted.
- **Score reason** — `ScoreResult`'s component breakdown (`ADR-004` §6).
- **Risk reason** — `RiskDecision`'s sizing rationale and which of the
  eight constraints (`ADR-005` §7–§14) bound the outcome.
- **Compliance reason** — `ComplianceDecision`'s verdict and, if BLOCK,
  which check produced it (`ADR-006` §4).
- **Execution reason** — `ExecutionDecision`'s verdict and, if REJECT,
  which check (`ADR-007` §6) produced it.
- **Position management history** — every `PositionManagementDecision`
  (`ADR-009` §6) issued for this position, in order, from Filled through
  Closed.
- **Final outcome** — realized P/L, MAE, MFE, and close reason, if the
  trade reached a position at all; the terminal rejection reason and
  stage, if it did not.

**Nothing may be omitted.** A `trace_id` reaching Analytics without one
of the fields appropriate to how far it progressed (e.g. a fully
executed trade missing its Position management history) is a
missing-event condition (§12), surfaced, never silently completed with a
partial record presented as whole.

---

# 7. Explainability

Every trade must be able to answer, by direct lookup into its
`TradeProvenanceRecord` (§6) — never by Analytics inferring or fabricating
an answer that wasn't already recorded by the deciding stage:

- **Why opened?** — Scanner + Strategy + Score + Risk + Compliance +
  Execution reasons, in the order the pipeline actually evaluated them.
- **Why sized?** — Risk reason.
- **Why approved?** — Compliance reason and Execution reason.
- **Why rejected?** — whichever stage's reason terminated the trade.
- **Why modified?** — the relevant `PositionManagementDecision`'s
  `decision_reason` (`ADR-009` §6).
- **Why closed?** — Final outcome's close reason.

If any of these cannot be answered from already-recorded data, that is a
missing-event condition (§12) — Analytics does not backfill a plausible-
sounding reason to make the record look complete.

---

# 8. Replay

**Analytics owns replay inputs; it does not itself execute or certify
replay.** The gap audit's recommended `ADR-018` (Replay & Certification
Engine, not yet drafted) is the forward-declared consumer that actually
re-runs a stage's logic against archived inputs and certifies the output
matches — this ADR does not duplicate that undrafted ADR's scope, only
guarantees the inputs it will need already exist, in full, immutable, and
correctly ordered.

- **Replay every decision** — every collected object (§2) is retained
  exactly as produced, sufficient to reconstruct what each stage saw.
- **Replay every market snapshot** — every market/price observation
  collected (§2) is retained at the same fidelity it was originally
  observed.
- **Replay every position event** — every `PositionUpdate`/
  `PositionManagementDecision` is retained in the order it occurred.
- **Replay must be deterministic.** Since every collected object was
  itself produced by a deterministic stage (`ADR-002` through `ADR-009`,
  each independently required to be deterministic), replaying the same
  archived inputs through the same stage logic must reproduce the same
  decision. Analytics's responsibility here is narrow but load-bearing:
  if its stored inputs are incomplete, reordered, or mutated, replay
  determinism becomes impossible to verify regardless of how
  deterministic the original stages were — this is why §6's "nothing may
  be omitted" and §5's immutability guarantee are prerequisites for §8,
  not independent concerns.

---

# 9. Performance

**Analytics is the one stage authorized to compute derived statistics
from historical fact.** This is not a "recalculation" in the sense every
prior ADR forbids (`ADR-005` through `ADR-009`'s "never recalculates
anything") — those prohibitions are about re-deriving a *live trading
decision* another stage already made. Performance statistics are
retrospective, read-only, and structurally incapable of feeding back into
any `RiskDecision`, `ScoreResult`, or other live object (§3) — this is
the boundary that keeps them from becoming an informal second scoring
mechanism.

Document and compute, over one or more `TradeProvenanceRecord`s:

- Win Rate
- Profit Factor
- Sharpe
- Sortino
- Expectancy
- MAE (Maximum Adverse Excursion)
- MFE (Maximum Favorable Excursion)
- Drawdown
- **Strategy attribution** — grouped by strategy identifier from the
  Strategy Registry (`ADR-003` §3), never a hand-maintained list (§2).
- **Regime attribution** — grouped by the market-structure/regime fields
  captured in `ScannerObservation` (`ADR-002` Amendment 1).
- **Session attribution** — grouped by the session context captured in
  `ScannerObservation`/`CandidateTrade`.
- **Pair attribution** — grouped by traded symbol.

---

# 10. Research relationship

**`ADR-019` may consume Analytics. Analytics never consumes `ADR-019`.
One-way relationship.** This is the Analytics-specific instance of the
same AI Research Governance boundary `ADR-015` §7, `ADR-016`, and
`ADR-019` already establish: research reads historical fact, historical
fact is never influenced by research output. Concretely:

- `ADR-019`'s own text already forward-declares this dependency
  ("this agent's mandate ... depends on reliable historical trade-outcome
  data — which is the gap audit's Trade Decision Memory finding \[folded
  into `ADR-010`\]"); this ADR is the fulfillment of that forward
  reference.
- Analytics exposes read-only historical data and performance statistics
  (§9) to research processes; it has no input path from `ADR-019` or any
  research process, and no mechanism exists (§3) by which research output
  could alter a `TradeProvenanceRecord` or a performance statistic.
- `ADR-018` (Replay & Certification Engine), once drafted, is the other
  named consumer of Analytics's replay inputs (§8) — also one-way.

---

# 11. Security

- **Analytics is read-only. It never changes live trading.** (Hard
  Rules.) It holds no credentials capable of submitting orders, modifying
  positions, or altering compliance/risk state — the same least-privilege
  discipline established at every prior stage.
- All collected objects (§2) are read-only copies; Analytics never
  mutates the source object at its origin stage, and never presents a
  mutated copy as if it were the original.
- The one-way research boundary (§10) is enforced the same way `ADR-015`
  §9 establishes for credentials generally: research processes are
  granted read access to Analytics's outputs, never write access to any
  `TradeProvenanceRecord` or the collection pipeline itself.

---

# 12. Testing

- **Unit tests** — isolated, fixture-based.
- **Replay tests** — archived inputs for a given `trace_id`, replayed
  through the same stage logic, reproduce the same recorded decision.
- **Decision reconstruction test** — every field required by §6/§7 can be
  retrieved for a fully executed trade and for a trade rejected at each
  possible stage (Compliance BLOCK, Execution Validator REJECT).
- **Trace integrity test** — `trace_id` is present and consistent across
  every collected object for a given trade.
- **Schema validation test** — every collected object matches its source
  stage's defined schema (`schema_version`, `ADR-002` §8 onward); a
  schema mismatch is flagged, not silently accepted.
- **Data completeness test** — a `TradeProvenanceRecord` for a fully
  executed and closed trade contains every field listed in §6.
- **Missing-event detection test** — a `trace_id` with a gap in its
  expected chain (e.g. a `RiskDecision` present but no corresponding
  `ComplianceDecision`) is flagged as incomplete (§6), not silently
  stored as if complete.

---

# 13. Architectural invariants

- Analytics owns history. No other ADR owns permanent trade history.
- Analytics owns decision provenance.
- Analytics owns replay inputs — not replay execution or certification
  (§8, forward-declared to `ADR-018`).
- Analytics has no live decision authority.

---

# 14. Acceptance criteria

ADR-010 is acceptable only if it guarantees:

- ✓ Every trade fully reconstructable (§6, §7).
- ✓ Every decision traceable (§6, `trace_id` propagation, §12).
- ✓ Replay deterministic — contingent on §6's completeness and §5's
  immutability guarantees (§8).
- ✓ Research supported — one-way, read-only (§10, §11).
- ✓ No live decision authority — read-only, no credentials, no feedback
  path into any upstream object (§3, §11).

---

# 15. Reference material — ideas only, not authority

- `titan_protocol/analytics.py`'s `StrategyPerformanceTracker` — the general
  idea of per-strategy win-rate/profit-factor tracking from real recorded
  results only (`"Stats are computed from REAL recorded trade results
  only — nothing is fabricated"`) is the direct idea behind §9's
  read-only, non-fabricated performance statistics. **Its hand-maintained
  `STRATEGIES` tuple is explicitly a negative example** — the exact
  defect `TEAM.md`'s backlog flags as relevant to this ADR (§2) — and is
  not reused; strategy attribution here is required to derive from the
  Strategy Registry (`ADR-003` §3) instead.
- `titan_protocol/analytics.py`'s `StrategyPerformanceTracker._pnl` being an
  unbounded list recomputed in full on every scrape — also a negative
  example (flagged in `TEAM.md`'s backlog as an observability-cost/memory
  concern), not reused; this ADR does not mandate a specific storage
  shape, but any implementation must avoid this pattern.
- `phantom_institutional.py` — has no distinct decision-provenance or
  replay capability separate from its scoring logic; wherever trade
  outcomes are referenced, they are not retained as a joined, replayable
  history. Studied as the same negative example every prior ADR's
  reference-material review has identified for this file.

---

Per `ADR-001` and `CLAUDE.md` §1.10, **no implementation begins until this
ADR's Status changes from Proposed to Accepted.**
