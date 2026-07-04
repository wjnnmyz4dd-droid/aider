# ADR-016 — AI News Intelligence Layer

Status: **Accepted**

Owner: Security Architect (advisory-AI trust boundary is a design-time
threat-modeling question first, per `.claude/agents/TEAM.md` §4)

Reviewed by: Software Architect (cross-module boundary — this layer
touches Compliance Engine's and Analytics' input surfaces without being
part of the pipeline itself)

Date: 2026-07-04

Acceptance Date: 2026-07-04

Accepted By: Software Architect / Phantom Engineering Council

Depends on: `ADR-001-single-authority-architecture.md` (Accepted),
`docs/adr/ADR-015-external-data-sources-api-governance.md` (Proposed)

---

# 1. Purpose

The AI News Intelligence Layer produces **advisory, human-and-Analytics-
facing context** about news and macro themes — narrative summaries,
affected-currency tagging, event-severity labeling — to help humans and
the Analytics stage (ADR-010) understand *why* a market behaved a certain
way, and to inform future research (the `docs/research/`-style workflow
already established for Vibe-Trading). It exists entirely **outside**
the deterministic trading pipeline (`ADR-001`) and has **zero authority**
over any trade, any score, any size, or any execution decision.

It is explicitly **not** a replacement for, or an enhancement to,
Compliance Engine's rule-based news guard (ADR-006, Accepted,
conceptually mirroring `phantom/guards.py`'s news-blackout idea per
`ADR-001`). It is a separate, advisory-only system that happens to look
at related source material for an entirely different purpose: producing
readable context for humans, never a blocking input for machines.

---

# 2. Relationship to existing architecture

- **`ADR-001`:** the trading decision path (Scanner → Strategy Engine →
  Scoring Engine → Risk Engine → Compliance Engine → Execution Validator
  → MT5 Bridge → Position Manager) remains deterministic and LLM-free.
  This layer has no position in that pipeline at all (§5).
- **Compliance Engine (ADR-006, Accepted):** its rule-based news
  guard remains the **only** authority for news-based blocking. This
  layer never feeds into, informs, or replaces that guard's logic. A
  human may look at both side by side; the guard's own decision is never
  a function of this layer's output or availability.
- **`ADR-015` (External Data Sources & API Governance):** if this layer
  is implemented using an LLM API (Claude or another provider) called at
  runtime, that specific vendor dependency is a **new** external service
  and must be approved through `ADR-015` §12's four-step process
  (Engineering Council review, Software Architect approval, Security
  Architect review, ADR update adding a new `ADR-015` §6 entry) **before
  implementation begins.** This ADR defines the architectural boundary
  and rules; it does not itself constitute that vendor approval —
  `ADR-015`'s existing "AI Development — Claude" entry is explicitly
  scoped to development-time tooling (`ADR-015` §6) and does not cover a
  runtime advisory service.
- **Analytics (ADR-010, forward reference):** the primary machine
  consumer of this layer's output, for contextual annotation of
  reporting — never a decision input.

---

# 3. Inputs

- Economic calendar
- Central bank news / communications
- Macro headlines
- Scheduled events (calendar-driven, known ahead of time)
- Unscheduled breaking news (real-time, unpredictable)
- Currency-specific news

**Data-plane isolation (a firm design decision, not an open question):**
this layer must consume its **own dedicated** feed(s) — it must never
share Compliance Engine's live MT5 Calendar connection (`ADR-015` §6). It
may reuse the already-approved "Alternative institutional news provider
(research only)" entry, or a newly-approved dedicated feed via `ADR-015`
§12, but never the compliance-critical live feed. Sharing a data plane
between an advisory system and a compliance-critical guard is exactly the
kind of hidden coupling `ADR-015` §1 ("exactly one documented purpose")
and §3 ("no hidden external dependencies") exist to prevent — a failure,
latency spike, or compromise in this layer's data source must never have
any shared-fate risk with Compliance Engine's guard.

---

# 4. Outputs — `NewsTheme`

- **Theme** — a named/categorized market theme (e.g. "USD rate-hawkish
  repricing").
- **Affected currencies** — list.
- **Event severity** — a qualitative label (e.g. LOW / MEDIUM / HIGH /
  EXTREME), never a numeric score (§5).
- **Narrative summary** — human-readable text.
- **Confidence label** — a qualitative label (e.g. LOW / MEDIUM / HIGH)
  describing confidence in the *summarization's accuracy*, never a
  numeric confidence score. This applies the same lesson `ADR-003`'s
  architectural review surfaced for reasoning metadata — a qualitative
  label is far harder to mistake for, or quietly evolve into, an implicit
  scoring mechanism than a number is.
- **Source list** — which articles/feeds contributed.
- **Timestamp** — when generated.
- **Expiration time** — when this theme should no longer be considered
  current; news relevance decays, mirroring the freshness concept
  `ADR-002` §8 established for `ScannerObservation`.
- **Schema version** — `NewsTheme` carries `schema_version`, the same
  discipline established for every other pipeline-adjacent data object
  this session (`ScannerObservation`, `CandidateTrade`, `ScoreResult`),
  so Analytics and human tooling can evolve independently of this layer.

---

# 5. Forbidden outputs

`NewsTheme` must never contain:

- BUY / SELL
- APPROVE / BLOCK
- A numeric score
- Lot size
- Stop Loss / Take Profit
- An execution instruction
- **Any field that could function as a de facto score, approval, or
  execution signal under a different name** — closing, from the start,
  the exact "smuggled scoring mechanism" loophole `ADR-003`'s
  architectural review flagged for reasoning metadata, rather than
  needing a later patch to close it.

**Type-level guarantee:** `NewsTheme`'s data model must be structurally
incapable of holding any forbidden field — verified by a dedicated test
(§8), mirroring the same guarantee established for `ScannerObservation`
(`ADR-002` §8), `CandidateTrade` (`ADR-003` §6), and `ScoreResult`
(`ADR-004` §6).

---

# 6. Pipeline position

This layer runs **beside** Phantom, not inside the execution path. It has
**no position whatsoever** in the `ADR-001` pipeline diagram (Market Data
→ Scanner → ... → Analytics). It is a parallel, independent system with
exactly two consumers:

- **Compliance Engine** — advisory context only. This means a human
  reviewing Compliance Engine's decisions and logs may also see this
  layer's `NewsTheme`s as background context. It does **not** mean any
  automated input to Compliance Engine's blocking logic — there is no
  code path in that logic that reads this layer's output. That remains
  true unless a future ADR explicitly designs and Security-Architect-
  reviews such an integration, with the same caution `ADR-015` applied to
  the research-only news provider (§6, "APIs to Avoid").
- **Analytics** — contextual annotation for reporting and research.

No other pipeline stage (Scanner, Strategy Engine, Scoring Engine, Risk
Engine, Execution Validator, MT5 Bridge, Position Manager) has any
awareness that this layer exists.

---

# 7. Failure behavior

If this layer fails, times out, or is entirely unavailable, **Phantom
continues using the rule-based calendar/news guard exactly as if this
layer did not exist.** This is not a graceful-degradation mechanism to
build — it is a structural guarantee that follows directly from §6's
positioning: there is no dependency edge from Compliance Engine's guard
into this layer for a failure to propagate along. **AI failure must never
disable, weaken, bypass, or even pause compliance.** This extends
`ADR-015` §3's "logging/metrics/notification services are never gates"
principle: this layer is never a gate either, in either direction (its
absence never blocks trading, and its presence never authorizes it).

---

# 8. Security

- **No broker credentials, no MT5 access, no order access, no execution
  permissions** — this layer has no path to any of them, structurally,
  per §6's isolation.
- **Dedicated, isolated credentials** for whatever news/LLM API it uses —
  never shared with Phantom's live-pipeline secrets (`ADR-015` §6,
  Secrets), mirroring the isolation already required of the Vibe-Trading
  research lab.
- **Network isolation** from the MT5 Bridge and any broker-facing
  component, the same isolation principle `ADR-015` §6 applied to
  Vibe-Trading.
- **Prompt-injection awareness** — this layer processes external,
  attacker-influenceable text (headlines, articles) by design. This is
  exactly the risk class `docs/research/ECC-EVALUATION.md`'s AgentShield
  finding and `docs/research/VIBE-TRADING-EVALUATION.md`'s
  LLM-generated-content risk both flagged. Testing must include adversarial
  content specifically designed to manipulate output (§9).

---

# 9. Testing

- **Prompt-injection tests** — adversarial headline/article content
  attempting to manipulate the layer into producing a forbidden output
  (§5) or altering its own behavior; asserts the forbidden-output
  guarantee holds even under active manipulation attempts, not just
  benign input.
- **Malformed-news tests** — garbled or incomplete source data must not
  crash the layer or produce a fabricated `NewsTheme`; degrades to no
  theme or a low-confidence theme, never a confident-sounding guess.
- **Stale-news tests** — a `NewsTheme` past its expiration time (§4) is
  correctly flagged or excluded from active consumption.
- **Hallucination containment tests** — every claim in a `NewsTheme`
  (affected currencies, severity, narrative) must trace to at least one
  entry in its own source list; a claim with no supporting source is a
  test failure, not an acceptable summarization behavior.
- **Deterministic schema validation** — a distinction worth stating
  explicitly, since it differs from every other ADR this session:
  `NewsTheme`'s **narrative text is not required to be byte-for-byte
  deterministic** (it is LLM-generated natural language, which is not
  expected to reproduce identically run-to-run). What **must** be
  deterministically enforced is schema conformance and the boundary
  rules themselves — every `NewsTheme` produced, regardless of the
  narrative's exact wording, structurally satisfies §4's schema and
  structurally cannot contain a §5 forbidden field. This is schema-level
  determinism, not content-level determinism, and is a deliberate,
  narrower guarantee than `ADR-002`/`ADR-003`/`ADR-004` require of the
  actual trading pipeline stages.

---

# 10. Human review

AI news summaries may inform future research — the same
human-approval-gated path already established for Vibe-Trading
(`docs/research/VIBE-TRADING-EVALUATION.md` §9: research idea → analysis
→ report → human approval → Phantom implementation, never an automated
pipe). **Live trading decisions remain entirely rule-based**, produced
only by Scanner → Strategy Engine → Scoring Engine → Risk Engine →
Compliance Engine → Execution Validator, none of which read this layer's
output.

---

# 11. Architectural Invariants

Must never be violated:

- AI never approves a trade.
- AI never blocks a trade.
- AI never scores a trade.
- AI never sizes a trade.
- AI never executes a trade.
- AI output never directly triggers or prevents any pipeline action —
  consumed only by humans and Analytics, never by any stage in the
  `ADR-001` decision path.
- Compliance Engine's rule-based news guard is the sole authority for
  news-based blocking, unaffected by this layer's existence, output, or
  availability (§7).
- This layer's data source is never Compliance Engine's live calendar
  feed (§3).

---

# 12. Acceptance Criteria

ADR-016 is acceptable only if it guarantees:

- ✓ AI output is advisory only (§1, §6, §11).
- ✓ Compliance Engine remains the only authority for news blocking (§2,
  §6, §11).
- ✓ Risk Engine, Scoring Engine, and Execution Validator remain
  rule-based, with no awareness this layer exists (§6, §11).
- ✓ No LLM output can directly trigger or prevent a trade (§5, §11).
- ✓ `NewsTheme` is structurally incapable of holding a forbidden field
  (§5).
- ✓ AI failure never disables, weakens, or bypasses compliance (§7).
- ✓ No broker/MT5/execution credentials or access of any kind (§8).
- ✓ A dedicated, isolated news data source, never shared with
  Compliance Engine's live calendar feed (§3).
- ✓ Any underlying LLM/news-API vendor dependency is approved via
  `ADR-015` §12 before implementation (§2).

---

# 13. Reference material — ideas only, not authority

- `phantom_institutional.py`'s "Sentiment Aggregator" (COT proxy, retail
  positioning) is **not** an idea carried forward here — it is already
  prohibited outright by `ADR-015` §7's "no social-media sentiment
  trading," and this layer is explicitly narrower in scope (news/calendar
  narrative context, never a sentiment-derived trading signal).
- `docs/research/VIBE-TRADING-EVALUATION.md` — the human-approval-gate
  pattern (§9, §10 above) is reused directly as the model for this
  layer's own research/human-review boundary.
- `docs/research/ECC-EVALUATION.md` — its AgentShield and
  prompt-injection findings are the relevant security prior art for §8/§9
  above; no code from that evaluation is adopted, only the risk-awareness
  it documented.

---

Per `ADR-001` and `CLAUDE.md` §1.10, **no implementation begins until this
ADR's Status changes from Proposed to Accepted**, and no runtime LLM/news
vendor may be connected until `ADR-015` §12's approval process is
separately satisfied.
