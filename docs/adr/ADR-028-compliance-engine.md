# ADR-028 — Prop Firm Compliance Engine

Status: **Proposed** — not yet Accepted. Per CLAUDE.md §1.10, no
implementation begins on this pipeline stage until this ADR reaches
**Accepted**, the same gate every prior `phantom/` stage
(`ADR-024`–`ADR-027`) passed through first.

Owner: TBD (per `TEAM.md`'s RACI, `ADR-006`'s existing Compliance
Engine names Security Architect as Accountable — likely the same here,
pending confirmation once full scope is known).

Accepted By: *pending* — only one requirement has been given so far
(§1 below). Full acceptance requires the remaining scope described in
§2.

Date opened: 2026-07-10

Depends on: `ADR-026-strategy-engine.md` (Accepted — consumes
`StrategySnapshot`), `ADR-027-portfolio-statistical-risk-engine.md`
(Accepted — consumes `RiskSnapshot`; Compliance sits immediately after
Risk in the ADR-001 pipeline: `... Risk Engine → Compliance Engine →
Execution Validator ...`).

---

# 0. Relationship to existing architecture

`ADR-006` (Compliance Engine, `phantom_pipeline/`) already exists as a
guard-based FTMO/prop-firm rule package. Per the established `phantom/`
track precedent (`ADR-024`–`ADR-027` §0, each disclosing the same class
of overlap and resolving it identically): **fresh, independent, no
reuse.** `phantom/compliance_engine/` (name pending — see §2) will be
built clean-room, mined for proven rule shapes only, never importing
`phantom_pipeline/compliance/` or sharing its guard registry.

---

# 1. Requirement captured so far: Daily Loss Safety Buffer (REQUIRED)

Given verbatim, this session:

> The Compliance Engine SHALL begin reducing allowable risk before the
> configured daily loss limit is reached.

Example schedule given (explicitly **configurable** — mirrors the
Risk Engine's own confidence-tier schedule precedent, ADR-027 §3):

| Daily loss consumed (of a 5.0% example limit) | Behavior |
|---|---|
| 0.0%–2.5% | Normal operation |
| 2.5%–3.5% | Reduce maximum position size |
| 3.5%–4.0% | Significant reduction; new trades require exceptionally high confidence |
| 4.0%–4.5% | Only the highest-quality setups may be considered; additional risk reductions applied |
| ≥ 4.5% | Reject all new positions; existing positions continue to be managed per plan; compliance lock remains until the next trading day (per configured reset rules) |

This is consistent with the Risk Engine's own architecture rule
(ADR-027 §1): **"Compliance may only reduce size or reject a trade —
never increase it."** This buffer is exactly that: a graduated
*reduction* schedule layered on top of whatever the Risk Engine already
approved, never a mechanism that could push size upward.

Open sub-questions, deferred to §2 rather than guessed:
- Where does "daily loss consumed so far" come from? By the same
  precedent as `PortfolioState`/`TradeHistory` (ADR-027 §0a), this is
  presumably a caller-supplied input (today's realized P&L against the
  account's daily limit) rather than something Compliance computes
  itself — needs confirmation.
- What defines "exceptionally high confidence" and "highest-quality
  setups" in the 3.5%–4.5% bands — a threshold against
  `RiskSnapshot.confidence_tier`/`StrategySnapshot`'s own qualification
  score, or a new Compliance-owned scoring dimension?
- "Configured reset rules" for the compliance lock — daily reset at a
  fixed time, broker-day rollover, something else?

---

# 2. Scope not yet provided — needed before this ADR can be Accepted

Every other `phantom/` stage ADR (`ADR-024`–`ADR-027`) was accepted
from a complete, single spec message covering: mission, what the stage
never decides, permitted inputs, hard rules, architecture rules,
performance targets, and a testing mandate. Only one hard rule (§1
above) has been given for Compliance so far. Still needed:

- **Mission statement** — the full scope of what this Compliance
  Engine evaluates (prop-firm rules generally cover more than daily
  loss: e.g. max overall drawdown, consistency rules, minimum trading
  days, weekend/overnight holding restrictions, news-trading
  restrictions, prohibited-strategy rules, lot-size/leverage caps —
  which of these are in scope here?).
- **Inputs** — presumably `RiskSnapshot` (ADR-027) and `StrategySnapshot`
  (ADR-026) at minimum, per the ADR-001 pipeline order; confirm whether
  any new caller-supplied state (e.g. today's realized P&L, account
  metadata, trading-day count) is needed, following the ADR-027 §0a
  precedent for new input types.
- **Other hard rules** beyond the daily-loss buffer.
- **Architecture rules** (no execution, no re-scoring, etc. — likely
  mirrors prior stages' patterns but needs stating explicitly).
- **Testing mandate** and **deliverables** format (has been identical
  across all four prior phases; presumably continues unchanged).

---

# Status

**Proposed.** Implementation does not begin until the above is
supplied and this ADR is marked **Accepted**.
