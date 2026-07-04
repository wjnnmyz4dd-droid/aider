# Phantom Architecture Gap Audit

Date: 2026-07-04

Owner: Software Architect

Status: Audit report — not an ADR. No new ADRs created by this document;
it recommends future ADR additions per the explicit instruction not to
draft them yet.

---

# 0. Correction to task premise (verified, not assumed)

The task states "ADR-001 through ADR-016 have been drafted." Verified
against the actual repository state — this is not accurate, and the
correction changes the answer to the final question (§9-10):

| ADR | Topic | Status |
|---|---|---|
| ADR-001 | Single Authority Architecture | **Accepted** |
| ADR-002 | Scanner | **Accepted** |
| ADR-003 | Strategy Engine | **Accepted** |
| ADR-004 | Scoring Engine | Proposed (drafted, not yet accepted) |
| ADR-005 | Risk Engine | **Not drafted** — name reserved only |
| ADR-006 | Compliance Engine | **Not drafted** — name reserved only |
| ADR-007 | Execution Validator | **Not drafted** — name reserved only |
| ADR-008 | MT5 Bridge | **Not drafted** — name reserved only |
| ADR-009 | Position Manager | **Not drafted** — name reserved only |
| ADR-010 | Analytics | **Not drafted** — name reserved only |
| ADR-011 | Watchdog | **Not drafted** — name reserved only |
| ADR-012 | Dashboard | **Not drafted** — name reserved only |
| ADR-013 | Data Pipeline | **Not drafted** — name reserved only |
| ADR-014 | Multi-Agent Governance | **Not drafted** — name reserved only |
| ADR-015 | External Data Sources & API Governance | Proposed |
| ADR-016 | AI News Intelligence Layer | **Accepted** |

**Only 6 of 16 numbered ADRs exist as drafted documents; only 3 are
Accepted.** Ten reserved numbers (ADR-005 through ADR-014) are names in
ADR-001's Future ADRs list with no content. Critically, **the entire
safety-critical back half of the core trading pipeline — Risk Engine,
Compliance Engine, Execution Validator, MT5 Bridge — has zero drafted
architecture.** This is the single largest finding of this audit and
governs the final recommendation in §10.

---

# 1. Is the current design sufficient for an institutional-grade,
prop-firm-safe system?

**Not yet, and not close, for the trading-critical stages — but the
governance scaffolding is unusually mature for this stage.** The pattern
across ADR-002/003/004 (determinism, purity, fail-closed defaults,
explicit forbidden-fields lists, type-level guarantees, trace_id
propagation) is a genuinely strong foundation, and ADR-015/016 give this
project earlier and more rigorous external-dependency and AI-boundary
governance than most systems have at any stage. But "sufficient" has to
be judged against the mission's own stated priority — capital
preservation overrides profit — and that exact capability (Risk Engine,
Compliance Engine) is the part with no architecture at all yet.

---

# 2. Candidate capability evaluation

## 2.1 Market Regime Engine

- **Covered?** Partially. `ADR-002` (Scanner) §5 already outputs
  per-timeframe trend state, a classified volatility state, session
  state, and liquidity events as raw facts. What's **missing** is a
  composite regime classification (the equivalent of the reference
  material's TRENDING_UP/RANGING/BREAKOUT/HIGH_VOLATILITY label) combining
  those facts into one shared value every playbook can reuse.
- **Should it be its own ADR?** No — recommend a targeted **amendment to
  `ADR-002`**, not a new ADR. Composite regime classification is still a
  Scanner-stage *fact* ("what is the market doing"), not a strategy
  decision, and squarely fits Scanner's existing mission (`ADR-002` §1).
  Splitting it into a separate stage would violate `ADR-002`'s own purity
  boundary from the other direction.
- **Owning stage:** Scanner.
- **Owning Council member:** Software Architect (`ADR-002`'s owner).
- **Dependencies:** reopening `ADR-002` (Accepted) for a scoped amendment.
- **Risk if omitted:** every playbook independently reinvents regime
  classification from the same raw facts, risking the same
  duplicate-computation and inconsistent-interpretation problems already
  on record for `swing_points()` and `analytics.STRATEGIES` — two
  playbooks could disagree on whether the market is "trending" at the
  same instant, with no shared source of truth to arbitrate.

## 2.2 Portfolio Manager

- **Covered?** Barely. `ADR-001`'s one-line descriptions mention
  "Portfolio limits" under Risk Engine and "Max positions/exposure" under
  Compliance Engine — but neither ADR-005 nor ADR-006 has been drafted,
  and even once they are, a **portfolio-wide, cross-symbol view**
  (aggregate currency exposure, correlation across all open positions,
  risk-budget allocation across multiple simultaneously-approved
  candidates) is a materially different question from either stage's
  current one-line scope, which reads as single-trade-at-a-time.
- **Naming collision to flag explicitly:** "Portfolio Manager" (this gap)
  is easily confused with **"Position Manager" (ADR-009, reserved)**,
  which per `ADR-001` is about a *single* position's lifecycle after
  entry (partial closes, trailing/breakeven) — a different concept
  entirely. Whoever drafts ADR-009 must not silently absorb portfolio-wide
  scope, and vice versa.
- **Should it be its own ADR?** Yes — recommend a **new ADR (ADR-017)**,
  not currently reserved anywhere in `ADR-001`'s list. Neither Risk Engine
  nor Compliance Engine, as currently one-line-scoped, is a natural owner
  of a genuinely cross-symbol, cross-strategy portfolio view.
- **Owning stage:** logically sits alongside/after Risk Engine and
  Compliance Engine — needs visibility into both's per-trade output to
  compute an aggregate view.
- **Owning Council member:** Security Architect as Accountable (mirrors
  the existing Compliance Engine RACI precedent — this is a safety-
  critical, capital-preservation-adjacent concern), Backend Architect
  Consulted.
- **Dependencies:** ADR-005 (Risk Engine) and ADR-006 (Compliance Engine)
  must exist first.
- **Risk if omitted:** multiple independently-approved trades (e.g. five
  different strategies each producing a correlated LONG hypothesis on
  EURUSD-adjacent instruments) could each individually pass single-trade
  Risk/Compliance checks while collectively creating dangerous
  concentrated exposure — precisely the "no uncontrolled pyramiding"
  failure mode the project's own Phantom Protocol rules were written to
  prevent, with no structural guarantee anything catches it.

## 2.3 Trade Decision Memory

- **Covered?** Partially. The *mechanism* this needs — structured,
  `trace_id`-linked logging at every stage — is already a mandatory,
  consistently-enforced requirement in `ADR-002` §11, `ADR-003` §12, and
  `ADR-004` §10. What's missing is the **aggregation/storage/query
  layer** that assembles those per-stage records into one queryable
  decision record for a given trade.
- **Should it be its own ADR?** No — recommend folding this in as an
  **explicit, named requirement inside ADR-010 (Analytics)** when
  drafted, rather than a new document. Analytics is already the
  "reads everything, decides nothing" stage per `ADR-001`, and this
  capability is a natural extension of that mission — but it must be
  called out explicitly, since the reference material's narrow
  `phantom/analytics.py` (win-rate/P&L only) is the wrong scope to default
  to.
- **Owning stage:** Analytics (ADR-010).
- **Owning Council member:** Backend Architect (Analytics RACI owner).
- **Dependencies:** every upstream stage's already-established logging
  discipline; `ADR-015`'s Database entry (§6).
- **Risk if omitted:** no way to reconstruct *why* a specific historical
  trade happened beyond scattered per-stage logs — a real audit and
  debugging gap for an institutional, prop-firm-scrutinized system.

## 2.4 Explainability Layer

- **Covered?** Substantially, for the front half; unknown for the back
  half. "Why was it scanned" / "why did the strategy trigger" / "why was
  it scored this way" already have strong, tested, explicit answers built
  into `ADR-002`/`ADR-003`/`ADR-004` (reason codes, evidence, rule
  contributions, audit-trail framing in `ADR-004` §12). "Why was risk
  allocated" / "why was compliance satisfied" / "why was execution
  approved" depend entirely on ADR-005/006/007, which don't exist yet —
  so this isn't a confirmed gap for those three, it's an **unverified
  continuation** of a pattern that has held well so far.
- **Should it be its own ADR?** No. The established pattern —
  explainability as a mandatory per-stage requirement, not a bolted-on
  cross-cutting layer — has worked well through three ADRs and should
  continue, not be replaced. Recommend instead: a standing **checklist
  requirement** that ADR-005 through ADR-009 each include an explicit
  explainability section mirroring `ADR-004` §5/§12, enforced the same
  way `TEAM.md`'s mandatory-reviewer routing table enforces other
  requirements — not a new architecture document.
- **Owning stage:** distributed — each stage owns its own explainability
  section.
- **Owning Council member:** whichever architect owns each respective
  future ADR.
- **Dependencies:** ADR-005 through ADR-009.
- **Risk if omitted:** the back half of the pipeline — precisely where
  compliance and execution-approval scrutiny matters most — could ship
  with weaker explainability rigor than the front half, creating an audit
  blind spot in exactly the wrong place.

## 2.5 Replay Engine

- **Covered?** Partially, and in an interesting way: the *precondition*
  (full determinism, explicitly required "for regression testing,
  walk-forward validation, debugging, certification") is thoroughly
  established in `ADR-002` §14 and extended in `ADR-003`/`ADR-004`. But
  the actual **replay mechanism** — tooling that takes historical data and
  a `trace_id`, re-runs it through the pipeline, and diffs the reproduced
  decision path against the original — is not designed anywhere. This is
  a gap-within-a-gap: a documented requirement (§14's "mandatory for...
  certification") with no architecture yet built to satisfy it.
- **Should it be its own ADR?** Yes — recommend a **new ADR (ADR-018,
  "Replay & Certification Engine")**, not currently reserved. It's
  genuinely cross-cutting (spans every stage) and isn't naturally owned by
  any existing reserved slot — not Analytics (which consumes results, not
  replays them), not Watchdog (operational monitoring, not certification
  tooling).
- **Owning stage:** cross-cutting, alongside rather than inside the main
  pipeline.
- **Owning Council member:** Test Results Analyzer (statistical/
  regression validation is already its lane per `TEAM.md`), Software
  Architect as cross-cutting reviewer.
- **Dependencies:** every stage's determinism guarantee (already
  required); Trade Decision Memory (§2.3, needs the historical record to
  replay against); `ADR-015`'s Database entry.
- **Risk if omitted:** the certification and walk-forward-validation uses
  already named as mandatory in `ADR-002` §14 have no mechanism to
  actually fulfill them.

## 2.6 Configuration Governance

- **Covered?** Partially. Per-stage configuration versioning (rule
  versions, weight versions, feature flags, safe-defaults-to-disabled) is
  consistently required in `ADR-003` §13 and `ADR-004` §11. What's
  missing is the **cross-cutting governance process**: who approves a
  configuration change before it takes effect, how a bad change gets
  rolled back, and a unified audit trail of configuration changes over
  time — distinct from code-change governance, which `TEAM.md` already
  covers thoroughly.
- **Should it be its own ADR?** Judgment call, presented both ways rather
  than decided unilaterally: (a) **extend `TEAM.md`** to state explicitly
  that its existing mandatory-review pipeline applies to configuration
  changes, not only code changes, plus a small addition to `ADR-015`
  covering versioning/rollback/audit-trail storage mechanics — the
  lighter-weight option, reusing what already exists; or (b) **a new,
  dedicated ADR**, for which the already-reserved **ADR-014
  (Multi-Agent Governance — "Engineering Council process itself")** is a
  reasonable home, since configuration-change approval is fundamentally a
  governance-process question closely related to how the Council already
  governs code. Recommend (a) as the default — it's the smaller diff —
  unless the Council decides configuration governance warrants dedicated
  treatment.
- **Owning stage:** cross-cutting.
- **Owning Council member:** Software Architect (process) with Backend
  Architect (mechanics/storage).
- **Dependencies:** `ADR-015` (Database, Secrets), `TEAM.md`'s existing
  review pipeline.
- **Risk if omitted:** an unreviewed, unversioned configuration change
  (e.g. silently loosening a risk threshold or disabling a
  compliance-relevant feature flag) could bypass the entire code-review-
  gated safety model this project has built, since `ADR-002`/`ADR-003`/
  `ADR-004` deliberately push most tunable behavior into configuration
  rather than code — exactly the surface a governance gap here would
  leave exposed.

## 2.7 AI Research Governance

- **Covered?** Yes — the best-covered of the seven candidates, genuinely,
  across three existing documents: `ADR-015` §6 (Vibe-Trading's isolation
  requirements) and §7 (explicit prohibitions: no AI-generated trading
  decisions, no direct LLM execution, no auto strategy generation, no
  auto parameter optimization), `ADR-016` in its entirety (a fully
  isolated, advisory-only AI layer with a hard human-approval gate), and
  `docs/research/VIBE-TRADING-EVALUATION.md`'s recommended integration
  path (research → report → human approval → reimplementation, "a hard
  gate, not a formality").
- **Should it be its own ADR?** No. Consolidating already-adequate,
  well-specified governance into a new document would be redundant work
  against the Minimal Change philosophy. Recommend only a lightweight
  cross-reference note tying `ADR-015` §7 and `ADR-016` together
  explicitly as "the AI Research Governance boundary," so it's findable
  without re-deriving it — documentation polish, not a new ADR.
- **Owning Council member:** Security Architect (already the pattern for
  both existing documents).
- **Risk if omitted:** none — already mitigated.

---

# 3. Missing Capability Matrix

| Capability | Status | New ADR? | Owning stage | Council owner |
|---|---|---|---|---|
| Market Regime Engine | Partially covered | No — amend ADR-002 | Scanner | Software Architect |
| Portfolio Manager | Missing (barely gestured at) | **Yes — ADR-017** | New, alongside Risk/Compliance | Security Architect |
| Trade Decision Memory | Partially covered | No — fold into ADR-010 | Analytics | Backend Architect |
| Explainability Layer | Substantially covered (front half); unverified (back half) | No — per-stage checklist requirement | Distributed | Distributed |
| Replay Engine | Partially covered (precondition only) | **Yes — ADR-018** | New, cross-cutting | Test Results Analyzer |
| Configuration Governance | Partially covered | Judgment call — lean extend TEAM.md/ADR-015 | Cross-cutting | Software Architect |
| AI Research Governance | Covered | No — cross-reference note only | N/A | Security Architect |

---

# 4. Recommended ADR additions

1. **ADR-017 — Portfolio Manager** (new, not currently reserved).
2. **ADR-018 — Replay & Certification Engine** (new, not currently
   reserved).
3. **Amendment to `ADR-002`** — composite Market Regime classification.
4. **Amendment to `ADR-010` (when drafted)** — explicit Trade Decision
   Memory requirement.
5. **Standing checklist requirement for ADR-005 through ADR-009** —
   mandatory explainability section per stage.
6. **Extension to `TEAM.md` and `ADR-015`** (or, alternatively, treat
   under ADR-014) — Configuration Governance.
7. **Cross-reference note** tying `ADR-015` §7 and `ADR-016` together as
   the AI Research Governance boundary.

No new ADRs have been created by this audit, per instruction.

---

# 5. Recommended priority order

Weighted by the mission's own stated priority (capital preservation
overrides profit) and actual current exposure, not simply pipeline order:

1. **ADR-005 — Risk Engine.** Highest priority: completely undesigned,
   and the mission's #1 stated concern.
2. **ADR-006 — Compliance Engine.** Equally critical — the other half of
   capital preservation, and the system's non-bypassable final authority
   per `ADR-001`.
3. **Resolve ADR-004's Proposed status** (accept or amend) — Risk Engine
   will consume its `ScoreResult` output directly.
4. **ADR-007 — Execution Validator.** The last gate before MT5.
5. **ADR-017 — Portfolio Manager (new).** Tightly coupled to Risk/
   Compliance; draft in the same window as items 1-2, not deferred.
6. **ADR-008 — MT5 Bridge.**
7. **ADR-009 — Position Manager.** (Watch the naming-collision risk
   against ADR-017, §2.2.)
8. **`ADR-002` Market Regime amendment.** Cheap, valuable, no blocking
   dependency — can happen opportunistically alongside items 1-7.
9. **ADR-010 — Analytics** (incorporating Trade Decision Memory, §2.3).
10. **ADR-018 — Replay & Certification Engine (new).** Valuable, not
    blocking core trading capability.
11. **ADR-011 — Watchdog.**
12. **ADR-013 — Data Pipeline.** Can be drafted opportunistically —
    `ADR-002` already defines what Scanner needs *from* it as an input
    contract, so it doesn't block anything already Accepted.
13. **ADR-012 — Dashboard.** Lowest priority, consistent with the
    project's own original stated priority order.
14. **ADR-014 — Multi-Agent Governance** (optionally absorbing
    Configuration Governance, §2.6).

---

# 6. Updated ADR roadmap

| ADR | Topic | Current status | This audit's recommendation |
|---|---|---|---|
| 001 | Single Authority Architecture | Accepted | — |
| 002 | Scanner | Accepted | Amend: add composite regime classification |
| 003 | Strategy Engine | Accepted | — |
| 004 | Scoring Engine | Proposed | Resolve (accept or amend) before Risk Engine |
| 005 | Risk Engine | Not drafted | Draft next — top priority |
| 006 | Compliance Engine | Not drafted | Draft next — top priority |
| 007 | Execution Validator | Not drafted | Draft after 005/006 |
| 008 | MT5 Bridge | Not drafted | Draft after 007 |
| 009 | Position Manager | Not drafted | Draft after 008; watch naming vs. ADR-017 |
| 010 | Analytics | Not drafted | Must include Trade Decision Memory requirement |
| 011 | Watchdog | Not drafted | Mid-priority |
| 012 | Dashboard | Not drafted | Lowest priority |
| 013 | Data Pipeline | Not drafted | Opportunistic, non-blocking |
| 014 | Multi-Agent Governance | Not drafted | Optionally absorb Configuration Governance |
| 015 | External Data Sources & API Governance | Proposed | Resolve acceptance |
| 016 | AI News Intelligence Layer | Accepted | Add cross-reference note tying to ADR-015 §7 |
| **017** | **Portfolio Manager** | **New — recommended** | Draft alongside 005/006 |
| **018** | **Replay & Certification Engine** | **New — recommended** | Draft after core pipeline (005-009) |

---

# 7. Anything that should be removed

None. Every drafted ADR (001-004, 015, 016) is coherent, non-duplicative,
and consistent with the others — nothing reviewed here warrants removal
or rework.

---

# 8. Anything duplicated

No outright duplication found between drafted documents. One **naming
collision risk**, not yet an actual duplication since neither exists:
**"Portfolio Manager" (recommended, §2.2) vs. "Position Manager" (ADR-009,
reserved)** — different concepts (portfolio-wide exposure vs. a single
position's post-entry lifecycle) with easily-confused names. Flagging
this now, before either is drafted, is the cheapest time to prevent scope
bleed between them.

---

# 9. Overall architecture maturity

A single invented percentage would misrepresent this more than it would
clarify it — the same reasoning `ADR-002`/`ADR-003`/`ADR-004` already
apply to refusing invented performance numbers applies here too. Rated
qualitatively by section:

- **Governance & process (ADR-001, `TEAM.md`, `CLAUDE.md`):** Mature.
  Unusually thorough for this stage of a project.
- **External-dependency & AI-boundary governance (ADR-015, ADR-016,
  `docs/research/`):** Mature. Earlier and more rigorous than most
  systems have at any stage.
- **Front-half trading pipeline (Scanner, Strategy Engine; Scoring Engine
  pending):** Mature and internally consistent — determinism, purity,
  fail-closed defaults, and type-level guarantees are all real,
  cross-checked properties, not aspirational language.
- **Back-half trading pipeline (Risk Engine, Compliance Engine,
  Execution Validator, MT5 Bridge):** **Foundational — zero drafted
  architecture.** This is precisely the highest-stakes portion of the
  entire system per its own stated mission.
- **Supporting capabilities (Portfolio Manager, Trade Decision Memory,
  Replay Engine):** Foundational to partial, per §2 above.

Net assessment: **the architecture is strongest exactly where the risk is
lowest, and has no architecture at all exactly where the risk is
highest.** That imbalance, not a percentage, is the real maturity
signal.

---

# 10. Final recommendation

**The question as posed — "can Phantom safely begin implementation after
ADR-010?" — has a false premise: ADR-005 through ADR-010 don't exist yet
(§0).** The real question is whether implementation can safely begin now,
given what actually exists.

**Answer: implementation readiness is per-stage, not all-or-nothing, and
the accepted rule (`ADR-001`, `CLAUDE.md` §1.10 — no implementation until
a stage's own ADR is Accepted) already governs this correctly:**

- **Scanner (ADR-002) and Strategy Engine (ADR-003) are architecturally
  ready for implementation today** — both Accepted, both internally
  consistent with everything reviewed in this audit.
- **Scoring Engine (ADR-004) is one acceptance decision away** — drafted,
  reviewed, no blocking gap found in its own prior review.
- **Full pipeline implementation — anything that would touch real risk
  sizing, real compliance, or real MT5 — must not begin** until at
  minimum ADR-005 (Risk Engine), ADR-006 (Compliance Engine), and ADR-007
  (Execution Validator) are drafted and Accepted. This is not a
  process formality: it is the literal safety-critical core the
  project's own mission statement names as its first priority, and it
  currently has no architecture at all.
- **Additional architecture documents are required before full
  implementation**, specifically ADR-017 (Portfolio Manager) and ADR-018
  (Replay & Certification Engine), per §4-6 — recommended as new roadmap
  additions, not yet drafted per instruction.

No new ADRs were created by this audit. No implementation code was
written. No source files were modified.

---

# Addendum (2026-07-04, same day)

`docs/adr/ADR-019-self-evolving-market-structure-research-agent.md` was
subsequently drafted (Proposed). It was requested as "ADR-017"; to avoid
colliding with this audit's own ADR-017 (Portfolio Manager) and ADR-018
(Replay & Certification Engine) recommendations above, it was renumbered
to ADR-019 per explicit decision before drafting. It is a research-lab
hypothesis generator, governed by the same AI Research Governance
boundary as `ADR-015` §7 / `ADR-016` (§2.7 above) — a distinct capability
from, and not a replacement for, the still-unaddressed ADR-017/ADR-018
recommendations. `ADR-001`'s Future ADRs list has been updated to
reference all three (017, 018, 019).

## Second addendum (2026-07-04, same day)

A request for "ADR-020 — Institutional Market Structure Engine" (richer
market-structure interpretation: external/internal structure, swing
hierarchy, equal highs/lows, range structure, accumulation/distribution,
trend acceleration/exhaustion, market phase, structure confidence) was
resolved as **Amendment 1 to `ADR-002` (Scanner)**, not a new ADR — this
is exactly the resolution §2.1 of this audit already recommended for the
"Market Regime Engine" candidate ("recommend a targeted amendment to
ADR-002, not a new ADR"). No `ADR-020` file was created. `ADR-002` §5,
§8, §9, §10, §13, §15, §17, and §18 were amended accordingly, each
addition clearly marked "Amendment 1" to keep the originally Accepted
content distinguishable from this later expansion. ADR-017 (Portfolio
Manager) and ADR-018 (Replay & Certification Engine) remain open,
undrafted recommendations from this audit.
