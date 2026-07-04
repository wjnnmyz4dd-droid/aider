# ADR-019 — Self-Evolving Market Structure Research Agent

Status: Proposed

Owner: Security Architect (research-AI trust boundary is a design-time
threat-modeling question first, per `.claude/agents/TEAM.md` §4 — same
precedent as `ADR-016`)

Reviewed by: Software Architect (cross-module boundary — this agent's
promotion chain terminates in Strategy Engine changes without being part
of the pipeline itself)

Date: 2026-07-04

Depends on: `ADR-001-single-authority-architecture.md` (Accepted),
`ADR-002-scanner.md` (Accepted), `ADR-003-strategy-engine.md` (Accepted),
`docs/adr/ADR-015-external-data-sources-api-governance.md` (Proposed),
`docs/adr/ADR-016-ai-news-intelligence.md` (Accepted)

Numbering note: requested as "ADR-017." `docs/adr/ARCHITECTURE-GAP-AUDIT-
2026-07-04.md` had already recommended ADR-017 for a Portfolio Manager
and ADR-018 for a Replay & Certification Engine. Renumbered to ADR-019
per explicit decision, confirmed before drafting. `ADR-001`'s Future ADRs
list and the gap audit have been updated to reference it.

---

# 1. Mission

**This agent answers exactly one question: "What market-structure
patterns appear to have statistical edge?"**

It does not answer:

- Should Phantom trade now?
- Should this live setup be approved?
- Should risk be increased?
- Should code be changed automatically?

It is a **hypothesis generator for the research lab**, nothing more. Every
hypothesis it produces is exactly that — a hypothesis, requiring the full
governance chain in §6 before it can influence anything real. It has the
same relationship to Phantom's live pipeline that Vibe-Trading has
(`ADR-015` §6): none, structurally, not merely by policy.

---

# 2. Relationship to existing architecture

- **`ADR-001`:** the live pipeline (Scanner → ... → Position Manager)
  remains deterministic and LLM-free. This agent has no position in it,
  the same structural exclusion `ADR-016` §6 established for the AI News
  Intelligence Layer.
- **Vibe-Trading (`ADR-015` §6, `docs/research/VIBE-TRADING-EVALUATION.md`):**
  this agent should run **inside the same isolated research-lab
  boundary** already established for Vibe-Trading, not a new, parallel
  isolation boundary — reuse, not duplication. Its `BacktestRequest`/
  `WalkForwardRequest`/`MonteCarloRequest` outputs (§4) are intended to be
  fulfilled by Vibe-Trading's existing validation engines (walk-forward,
  Monte Carlo permutation, bootstrap Sharpe CI — already evaluated as
  genuinely useful and classified `ADAPT`/`KEEP SEPARATE` in that
  evaluation), not reimplemented here. This agent is the
  hypothesis-generation front end; the research lab's existing engines
  are the statistical-validation back end it requests, not replaces.
- **`ADR-015` §12:** if this agent is itself implemented using a runtime
  LLM API, that is a new external dependency requiring `ADR-015` §12's
  four-step approval (Council review, Software Architect approval,
  Security Architect review, ADR update) before implementation — the
  same discipline `ADR-016` §2 established.
- **`ADR-016`:** a different research domain (market-structure pattern
  research here, versus news/macro advisory context there), governed by
  the same philosophy. Per the gap audit's recommendation
  (`ARCHITECTURE-GAP-AUDIT-2026-07-04.md` §2.7, §4), `ADR-015` §7,
  `ADR-016`, and this ADR together constitute Phantom's complete **AI
  Research Governance boundary** — a cross-reference note should tie all
  three together explicitly.
- **Gap audit dependencies:** this agent's mandate to study "trade
  outcomes, MAE/MFE, win rate, profit factor, drawdown" (§3) depends on
  reliable historical trade-outcome data — which is the gap audit's
  Trade Decision Memory finding (folded into ADR-010) and, ideally, the
  Replay Engine (ADR-018) once drafted. This agent may begin with more
  limited scope (backtested/research-lab-side historical data) before
  those exist; it is a **consumer** of those future capabilities, never a
  substitute for them.

---

# 3. Research Scope

May study, entirely within historical/research-lab data, never live
pipeline state:

- BOS, CHOCH, swing highs/lows, liquidity sweeps, Fair Value Gaps, Order
  Blocks
- Session behavior; London/NY/Asia patterns
- Volatility regimes; regime transitions
- Pair behavior
- Strategy performance; trade outcomes; MAE/MFE; win rate; profit factor;
  drawdown

**Important boundary:** several of these (BOS, CHOCH, liquidity sweep,
FVG, order block) are the same structural concepts `ADR-002` (Scanner)
already defines as live, single-instant facts. This agent studies
**historical, aggregate patterns** of these same concepts across many
past instances for research purposes — it never reads Scanner's live
output stream, never touches any live pipeline state, and its own
historical structure-detection logic (if any) is independent of, and
irrelevant to, Scanner's live implementation. Studying the same concepts
historically does not create a dependency on, or an integration with,
live Scanner output.

---

# 4. Outputs

**Allowed:**

- **`ResearchHypothesis`** — a candidate pattern/edge, stated as a
  testable claim.
- **`PatternObservation`** — a specific, descriptive, factual pattern
  observed in historical data.
- **`StatisticalSummary`** — aggregate statistics (win rate, profit
  factor, MAE/MFE distributions, etc.) for a studied pattern or an
  existing live playbook's historical performance.
- **`WeaknessReport`** — an identified weakness in an existing live
  playbook's historical performance (e.g. "Playbook X underperforms in a
  RANGING regime") — advisory feedback only, never an automatic code
  change.
- **`CandidateExperiment`** — a proposed next research experiment.
- **`BacktestRequest` / `WalkForwardRequest` / `MonteCarloRequest`** —
  structured requests routed to the research lab's existing validation
  engines (§2); this agent requests validation, it does not perform
  validation itself.
- **`HumanReviewRequest`** — the terminal output type. Every hypothesis,
  regardless of how thoroughly validated, ultimately produces a
  `HumanReviewRequest` before anything can move toward Phantom (§6).

**Forbidden:**

- BUY / SELL, APPROVE / BLOCK, SCORE, RISK %, LOT SIZE, SL / TP, EXECUTE,
  MODIFY CODE, DEPLOY.
- **Any field that could function as a de facto trading signal, approval,
  or code-modification instruction under a different name** — the same
  proactive closure `ADR-016` §5 applied to its own forbidden-outputs
  list, applied here.

**Type-level guarantee:** every one of the nine allowed output types must
be structurally incapable of holding any forbidden field — the same
guarantee established for every other data model this session
(`ScannerObservation`, `CandidateTrade`, `ScoreResult`, `NewsTheme`),
verified by a dedicated test (§9).

---

# 5. Governance — Promotion Pipeline

Every hypothesis must pass, in order:

**Research Agent → Human Review → Backtest → Walk-forward → Monte Carlo →
Shadow Account → Engineering Council Approval → ADR update if
architecture changes → Implementation by human-approved engineer.**

- **Research Agent** produces a `ResearchHypothesis` and a
  `CandidateExperiment`.
- **Human Review** — a human, never another AI, decides whether to pursue
  it further. First gate; not a formality.
- **Backtest / Walk-forward / Monte Carlo** — statistical validation via
  the research lab's existing engines (§2), reused, not reimplemented.
- **Shadow Account** — comparing what the hypothesis would have done
  against real historical trade journals, reusing the concept
  `docs/research/VIBE-TRADING-EVALUATION.md` §7 already identified as a
  genuinely useful pattern worth borrowing.
- **Engineering Council Approval** — routed through `TEAM.md`'s existing
  review pipeline: Software Architect for architectural fit,
  Multi-Agent Systems Architect if promotion means a new Strategy Engine
  playbook, Security Architect if any new trust boundary is touched.
- **ADR update if architecture changes** — if promoting a hypothesis
  requires a new playbook, that is a Strategy Engine change following
  `ADR-003`'s own extensibility model (§7/§17: new module plus registry
  entry) — a change to Strategy Engine's architecture, never to this
  agent's.
- **Implementation by human-approved engineer** — the actual code is
  written by a human, or by Minimal Change Engineer under explicit human
  direction, never by this research agent, and never automatically.

**No automatic promotion. No self-modifying production code. No live
pipeline access.** All three are absolute, not defaults that can be
overridden by configuration.

---

# 6. Security Boundary

The agent has:

- No broker credentials.
- No MT5 access.
- No execution permissions.
- **No write access to production code.**
- **No write access to any ADR document** — accepted ADRs are immutable
  to it; only humans, through the Engineering Council process, may amend
  them.
- No deployment permissions.
- No access to live order routing.

**It may only write research reports** — and, per §7, its own
research-process state (hypothesis backlog, pattern taxonomy, experiment
queue, report templates). It has zero write access to the Phantom
repository's production code, zero write access to any ADR, and zero
write access to configuration governing the live pipeline.

Additionally, mirroring `ADR-016` §8:

- **Dedicated, isolated credentials** for whatever LLM/data API powers
  it — never shared with Phantom's live-pipeline secrets (`ADR-015` §6,
  Secrets).
- **Network isolation** from MT5 Bridge and any broker-facing component.
- **Prompt-injection / data-integrity awareness** — this agent processes
  large volumes of historical data and text that could be adversarially
  crafted or corrupted; testing must include adversarial content (§9).

---

# 7. Self-Evolution Rules

Self-evolution is allowed **only for this agent's own research
behavior** — a deliberate, explicit exception to the "no adaptive
behavior" rule governing Scanner/Strategy Engine/Scoring Engine
(`ADR-002` §2, `ADR-003` §2, `ADR-004` §2). That rule exists to bound
live-trading risk; it does not need to apply here, precisely because this
agent has zero authority and zero live pipeline access (§5, §6). Adaptive
research behavior is safe in a component that can only ever produce a
`HumanReviewRequest`, in a way it would never be safe inside the trading
pipeline itself.

**May update:**

- Its own research questions.
- Its hypothesis backlog.
- Its pattern taxonomy.
- Its experiment queue.
- Its report templates.

**May never update:**

- Phantom production code.
- Accepted ADRs.
- Risk rules.
- Compliance rules.
- Scoring rules.
- Execution rules.

Even within this narrow, permitted self-evolution, every change to the
agent's own research priorities must itself be logged and auditable —
a human must be able to see *why* its research focus shifted over time,
the same explainability discipline `ADR-004` §12 established for scoring.
Self-evolution that isn't itself traceable would be an unaccountable
process, even in a component this constrained.

---

# 8. Testing / Validation

- **Prompt-injection tests** — adversarial historical-data or text
  content attempting to manipulate output (§6).
- **Hallucination containment tests** — every claim in a
  `ResearchHypothesis`/`PatternObservation`/`WeaknessReport` traces to
  cited historical data, the same discipline `ADR-016` §9 required of
  `NewsTheme`.
- **Lookahead-bias checks** — required and explicit. `docs/research/
  VIBE-TRADING-EVALUATION.md` §2 flagged that Vibe-Trading's own
  `validation.py` "does not implement purity gates or lookahead bias
  detection" — this agent's governance must not inherit that gap. Any
  hypothesis using information that would not have been available at the
  historical decision point is rejected before reaching Human Review.
- **Data leakage checks** — distinct from lookahead bias: verifies
  training/study data and validation data are properly separated.
- **Overfitting checks** — directly closes the missing-capability finding
  already on record (`TEAM.md` §6: no agent validates whether a
  strategy's edge is statistically real or curve-fit, especially when
  testing multiple strategies/patterns simultaneously). This agent's
  overfitting checks, combined with the promotion pipeline's Walk-forward
  and Monte Carlo gates (§5), are the mechanism that closes that gap.
- **Out-of-sample testing** — a hypothesis validated only in-sample never
  reaches Human Review.
- **Walk-forward testing / Monte Carlo validation / Bootstrap confidence
  intervals** — performed by the research lab's existing engines (§2),
  requested via `WalkForwardRequest`/`MonteCarloRequest`, not
  reimplemented by this agent.

---

# 9. Architectural Invariants

- This agent never approves, blocks, scores, sizes, or executes a trade.
- This agent has zero position in the `ADR-001` pipeline — no live
  pipeline access under any circumstance.
- This agent never writes to Phantom's production code or any ADR
  document.
- No hypothesis is ever automatically promoted; every promotion requires
  the complete §5 chain ending in human-approved-engineer implementation.
- Self-evolution is scoped exclusively to this agent's own research
  process (§7) — never to risk, compliance, scoring, or execution rules.
- Every research artifact is structurally incapable of holding a
  forbidden field (§4).

---

# 10. Acceptance Criteria

ADR-019 is acceptable only if it guarantees:

- ✓ The agent answers only "what patterns show statistical edge," never
  a live trading question (§1).
- ✓ Zero live pipeline access (§2, §9).
- ✓ All nine output types are structurally incapable of holding a
  forbidden field (§4).
- ✓ No automatic promotion of any hypothesis (§5, §9).
- ✓ No write access to production code or ADRs (§6, §9).
- ✓ No broker/MT5/execution credentials or access of any kind (§6).
- ✓ Self-evolution is bounded to research behavior only, and is itself
  auditable (§7).
- ✓ Lookahead-bias and overfitting checks are required, explicit, and
  close previously-identified gaps rather than reproducing them (§8).
- ✓ Reuses the existing Vibe-Trading isolation boundary and validation
  engines rather than duplicating them (§2).

---

# 11. Reference material — ideas only, not authority

- `docs/research/VIBE-TRADING-EVALUATION.md` — its isolation requirements
  and validation engines (walk-forward, Monte Carlo, bootstrap CI) are
  reused via request/response (§2, §5), not reimplemented; its Shadow
  Account concept directly informs §5's promotion chain.
- `ADR-002`/`ADR-003`/`ADR-004` — the structural concepts this agent
  studies (BOS/CHOCH/FVG/order block/liquidity sweep) are the same ones
  those ADRs define for live use; this agent's historical study of them
  creates no dependency on or integration with the live implementations.
- `ADR-015` §7, `ADR-016` — the same AI Research Governance boundary;
  together these three documents should be cross-referenced as one
  coherent governance story (per the gap audit's recommendation).
- `phantom_institutional.py`'s `AdaptiveModel`/ML-classifier concepts —
  explicitly **not** an idea carried forward here. Those represent
  exactly the kind of self-modifying, production-adjacent adaptive
  behavior this ADR's self-evolution boundary (§7) is designed to
  prevent, studied as a negative example the same way prior ADRs treated
  this file's other reference-only components.

---

Per `ADR-001` and `CLAUDE.md` §1.10, **no implementation begins until this
ADR's Status changes from Proposed to Accepted**, and no runtime LLM/data
vendor may be connected until `ADR-015` §12's approval process is
separately satisfied.
