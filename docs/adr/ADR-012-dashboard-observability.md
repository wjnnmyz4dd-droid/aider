# ADR-012 — Dashboard & Observability

Status: Proposed

Owner: Backend Architect (Accountable per `.claude/agents/TEAM.md` §5
RACI, Dashboard row; also already named in `ADR-015`'s Grafana section
as this stage's owner)

Reviewed by: SRE (Consulted per `TEAM.md`'s RACI — "what to surface for
alerting"), **Security Architect (mandatory, added 2026-07-04 governance
pass — see note below)**

**Note — governance gap resolved 2026-07-04:** the prior draft flagged
that this ADR surfaces account-sensitive data (trade/performance
statistics, position status) to a human-facing interface — exactly the
exposure `ADR-015`'s own Grafana section calls out as needing "access
control over who can view account-sensitive metrics" — while `TEAM.md`'s
Dashboard RACI row named no Security Architect reviewer. Evaluated
against: account information exposure, infrastructure visibility,
operational telemetry, authentication assumptions, authorization
boundaries, read-only guarantees, and information-disclosure risk.
**Conclusion: justified, on a different risk axis than Execution
Validator/MT5 Bridge.** Those stages' mandatory Security Architect gate
is about write/order-placement blast radius, which the Dashboard
structurally has none of (§4, §9 — unchanged). The Dashboard's risk is
**information disclosure**: who may *view* real account/position/
performance data is a design-time trust-boundary question squarely
within Security Architect's lane (`TEAM.md` §4's two-tier model —
design-time trust boundaries are Security Architect's, not Application
Security Engineer's diff-time SAST/DAST review). The read-only/no-write
architecture itself (§4, §9) was already sound and is not what this
review changes — only the reviewer list is updated; see the Deliverable
report for the full evaluation.

Date: 2026-07-04

Depends on: `ADR-001-single-authority-architecture.md` (Accepted),
`ADR-002-scanner.md` through `ADR-009-position-manager.md` (all
Accepted — Dashboard displays each stage's health, never their decision
objects), `ADR-010-analytics-decision-provenance.md` (Accepted — source
of all trade/performance statistics and decision-provenance data this
ADR displays), `ADR-011-watchdog-recovery.md` (Accepted — source of all
health/alert data this ADR displays),
`docs/adr/ADR-015-external-data-sources-api-governance.md` (Proposed —
already defines Prometheus and Grafana, this stage's two underlying data
mechanisms, and names this ADR as "the future Dashboard stage")

---

# Pipeline position

**The Dashboard is not part of the trading pipeline.** It is a read-only
operational interface with **no direct connection to any pipeline
stage.** Per `ADR-015`'s already-defined Grafana section: "Pipeline
stages allowed: none directly. Grafana reads only from Prometheus." This
ADR generalizes that same access model to the Dashboard as a whole: its
only two data sources are Prometheus (health/infrastructure metrics,
exported by every stage per `ADR-011` §13's own "export-only, additive"
discipline) and Analytics' already-read-only outputs (`ADR-010` §5 —
`TradeProvenanceRecord`, performance statistics). The Dashboard is
structurally two steps removed from every trading decision: stage →
Prometheus/Analytics → Dashboard.

---

# 1. Mission

**The Dashboard answers exactly one question: "What is the current state
of Phantom?"**

**It never answers:** Should we trade? Should we modify risk? Should we
execute? Should we restart services? Those are, respectively, the
Strategy/Scoring/Risk Engines', the Execution Validator's/MT5 Bridge's,
and the Watchdog's questions — each already answered by its own Accepted
ADR. The Dashboard visualizes the answers those stages already produced;
it never produces a new one.

---

# Hard Rules

These override any other requirement in this document if they ever
appear to conflict:

- **Read-only, structurally, not merely behaviorally.** The Dashboard has
  no write path to Prometheus, Analytics, Watchdog, or any pipeline
  stage — its only connections are read connections to Prometheus and to
  Analytics' read-only query surface (§4).
- **The Dashboard SHALL NEVER:** execute trades, modify configuration,
  restart services, clear alerts, override Compliance, override Risk, or
  override Execution (§3).
- **Alerts are display-only.** No acknowledgement, no suppression, no
  routing — those remain Watchdog's (§6).
- **No trading authority, no operational-control authority.** The
  Dashboard visualizes; it never controls, decides, or executes.

---

# 2. Responsibilities — what the Dashboard displays

The Dashboard SHALL display, all sourced per §4 (never queried directly
from a pipeline stage):

- Scanner status, Strategy status, Scoring status, Risk status,
  Compliance status, Execution Validator status, MT5 Bridge status,
  Position Manager status, Analytics status — each stage's **health**
  (via Prometheus/`ADR-011`), never its decision objects.
- Watchdog health, External API health, Database health, Heartbeat
  status, Recovery status — all sourced from `ADR-011`'s `SystemHealth`
  (via Prometheus).
- Trade statistics, Performance statistics — sourced from `ADR-010` §9.
- System metrics — sourced from Prometheus (`ADR-011` §13).
- Alert status — a read-only mirror of `ADR-011` §11's current alert
  state, never the alerts' underlying acknowledgement/suppression/
  routing state (§6).

---

# 3. Read-only — the Dashboard shall never

| Forbidden action | Owned instead by |
|---|---|
| Execute trades | MT5 Bridge (`ADR-008`) |
| Modify configuration | Whichever stage's own ADR owns that configuration |
| Restart services | Watchdog (`ADR-011`) |
| Clear alerts | Watchdog (`ADR-011`) |
| Override Compliance | Compliance Engine (`ADR-006`) |
| Override Risk | Risk Engine (`ADR-005`) |
| Override Execution | Execution Validator (`ADR-007`) |

---

# 4. Data sources — the structural enforcement of read-only

The Dashboard has exactly two upstream data sources, and no others:

- **Prometheus** (`ADR-015`'s Metrics section) — every stage's
  already-exported, pull-only, export-only metrics (`ADR-002` through
  `ADR-011`, each independently required to export metrics additively).
  The Dashboard (via Grafana or an equivalent visualization layer, per
  `ADR-015`'s Grafana section) reads Prometheus; it never queries a
  pipeline stage directly, and Prometheus itself "never writes back into
  or influences the pipeline" (`ADR-015`, Metrics section) — a
  double-barrier against the Dashboard ever becoming a write path.
- **Analytics' read-only query surface** (`ADR-010` §5, §11) — for
  `TradeProvenanceRecord`, performance statistics, and any decision-
  provenance data displayed in the Audit and Research views (§5).
  Analytics is already structurally read-only and has no live-pipeline
  feedback path (`ADR-010` Hard Rules); the Dashboard inherits that same
  guarantee by having no other way to reach trade history.

**No other connection exists.** The Dashboard has no path to `Scanner`
through `Position Manager`'s internal state, no path to MT5, no database
write access, and no path to Watchdog's alert-management state (§6) —
only to what Prometheus and Analytics already, independently, chose to
export.

---

# 5. Visualization — views

Ten views, each backed only by §4's two data sources:

- **Overview** — Overall Health (`ADR-011` `SystemHealth`) and a
  high-level trade/performance summary (`ADR-010`).
- **Trading** — Scanner/Strategy Engine/Scoring Engine health and trade
  flow, from Prometheus and Analytics respectively.
- **Risk** — Risk Engine health and risk-related aggregate statistics
  (e.g. portfolio heat, sizing distribution) as already recorded by
  Analytics (`ADR-010` §9) — this view visualizes what Risk Engine and
  Analytics already decided/recorded; it introduces no new risk
  computation and must never be read as a second risk authority.
- **Compliance** — Compliance Engine health and current compliance state
  (e.g. kill-switch/lockout status) as already reported — a read-only
  reflection of an already-decided fact, never a new evaluation.
- **Execution** — Execution Validator and MT5 Bridge health.
- **Infrastructure** — CPU/RAM/Disk/Network/VPS/Watchdog health, from
  Prometheus.
- **Analytics** — the performance-statistics view proper: Win Rate,
  Profit Factor, Sharpe, Sortino, Expectancy, MAE, MFE, Drawdown, and
  attribution breakdowns, exactly as `ADR-010` §9 defines them.
- **Alerts** — display-only mirror of Watchdog's current alert state
  (§6).
- **Research** — read-only surface for `ADR-016` (AI News Intelligence)
  and `ADR-019` (Self-Evolving Research Agent) advisory output, for human
  review. Displaying this content adds no capability to either system —
  both remain advisory-only, human-approval-gated, with zero live
  pipeline access (`ADR-015` §7, `ADR-016`, `ADR-019`); the Dashboard is
  a convenience viewer onto already-existing, already-isolated output,
  not a new integration point.
- **Audit** — human-facing browsing of `ADR-010`'s decision-provenance
  records (`TradeProvenanceRecord`) — the human-facing counterpart to the
  explainability `ADR-010` §7 already defines programmatically.

---

# 6. Alerts

**Display only. No acknowledgement. No suppression. No routing. Those
belong to Watchdog** (`ADR-011` §11).

This is not merely a policy choice the Dashboard opts into — it is a
structural consequence of §4: the Dashboard's only connection to alert
data is a read of whatever Prometheus/`ADR-011` already exported. It has
no connection to Watchdog's internal alert-management state (suppression
windows, deduplication counters, escalation timers, `ADR-011` §11) and
therefore no mechanism by which it *could* acknowledge, suppress, or
route an alert even if such an action were attempted. If alert
acknowledgement ever needs a human-facing control surface in the future,
that is a new capability requiring its own ADR and its own Security
Architect review — it is not assumed to exist here, and this ADR does
not create it.

---

# 7. Traceability

Every displayed item links to:

- `trace_id`
- `timestamp`
- `component`
- `status`

For trading-pipeline items this is the same `trace_id` chain established
at Scanner (`ADR-002` §8) and carried through every stage, surfaced via
Analytics (`ADR-010` §6/§7). For operational/health items this is
Watchdog's own health-event `trace_id` chain (`ADR-011` §5/§12) — the two
chains are never merged or confused; a displayed item's `trace_id`
unambiguously identifies which chain it belongs to via its `component`
field.

---

# 8. Metrics

Displayed, sourced per §4, never recomputed by the Dashboard itself:

- **From Analytics (`ADR-010` §9):** Win Rate, Profit Factor,
  Expectancy, MAE, MFE, Drawdown, Sharpe, Sortino.
- **From Prometheus/Watchdog (`ADR-011` §13):** Recovery Time,
  Availability, CPU, RAM, Disk, Network, Latency.

**The Dashboard performs no aggregation or calculation of its own** on
any of these values beyond presentation-layer formatting (e.g. a chart
axis, a percentage display) — every number shown is exactly what
Analytics or Prometheus/Watchdog already computed. This is the same
"never recalculates" discipline every trading stage carries, applied here
even though the Dashboard sits outside the trading pipeline: the concern
isn't feeding a live decision (the Dashboard has no such path, §4) but
avoiding a second, informal, potentially-divergent computation of a
number Analytics or Watchdog already own.

---

# 9. Security

- **Dashboard is read-only. No write capability. No trading authority.**
  (Hard Rules.)
- **No credentials to any pipeline stage, MT5, or the trade-execution
  path.** Its only credentials are read-only, least-privilege connections
  to Prometheus and to Analytics' query surface (`ADR-015`'s Grafana
  section: "data-source credentials to Prometheus should be read-only,
  least-privilege").
- **Access control over account-sensitive data is required** — trade
  statistics, position status, and account-adjacent metrics are
  sensitive even though the Dashboard itself has no write capability;
  who may *view* the Dashboard is a distinct security question from
  whether the Dashboard can *act* (`ADR-015`'s own Grafana section
  already flags this). See the header note — this is precisely the
  concern Security Architect's now-mandatory review (added 2026-07-04)
  covers.
- **Internal-only network binding**, mirroring the same requirement
  `ADR-015` places on the Prometheus endpoint it reads from.

---

# 10. Testing

- **View consistency test** — each of the ten views (§5) renders only
  data attributable to §4's two sources; no view silently reaches a
  pipeline stage directly.
- **Metric consistency test** — every displayed metric (§8) exactly
  matches its source value in Analytics or Prometheus, with no
  Dashboard-side recomputation.
- **Trace consistency test** — every displayed item's `trace_id` (§7)
  resolves correctly to its originating chain (trading vs. health) and
  component.
- **Read-only verification test** — no code path in the Dashboard issues
  a write to any pipeline stage, Watchdog's alert-management state,
  configuration, or MT5.
- **Permission verification test** — the Dashboard's own credentials to
  Prometheus/Analytics are confirmed read-only/least-privilege, and
  viewer-level access control (§9) is enforced.

---

# 11. Architectural invariants

- Dashboard visualizes.
- Dashboard never controls.
- Dashboard never decides.
- Dashboard never executes.

---

# 12. Acceptance criteria

ADR-012 is acceptable only if it guarantees:

- ✓ Every major component observable (§2, §5).
- ✓ Every health state visible (§2, §5 Infrastructure/Overview views).
- ✓ Every alert visible (§6) — display-only, per its own structural
  limitation.
- ✓ Every trade traceable (§7, backed by `ADR-010`'s decision provenance).
- ✓ No operational authority (§3, §6, §9).

---

# 13. Reference material — ideas only, not authority

- **No legacy dashboard implementation exists anywhere in this
  repository** (verified: the reference material's `/metrics` and
  `/strategies/performance` endpoints are data feeds, not a UI). As with
  `ADR-008`, `ADR-009`, and `ADR-011`, there is no legacy module to mine
  for ideas — this stage is designed entirely from first principles.
- `ADR-015`'s already-defined Prometheus/Grafana sections are the direct
  structural idea behind this ADR's data-source model (§4) — this ADR is
  the formal definition of the stage `ADR-015` was written anticipating
  ("maps to the future Dashboard stage, ADR-012"), not a competing
  design.
- `ADR-010`'s Explainability section (§7) is the direct idea behind this
  ADR's Audit view (§5) — the human-facing counterpart to a
  capability `ADR-010` already defined programmatically.

---

Per `ADR-001` and `CLAUDE.md` §1.10, **no implementation begins until this
ADR's Status changes from Proposed to Accepted.**
