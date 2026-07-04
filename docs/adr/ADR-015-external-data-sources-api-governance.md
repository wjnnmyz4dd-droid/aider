# ADR-015 — External Data Sources & API Governance

Status: Proposed

Owner: Software Architect

Date: 2026-07-04

Depends on: `ADR-001-single-authority-architecture.md` (Accepted),
`ADR-002-scanner.md` (Accepted)

Numbering note: this ADR was requested as "ADR-011"; `ADR-001`'s Future
ADRs list had already assigned ADR-011 to Watchdog. Renumbered to ADR-015
(the next open slot after ADR-014) per explicit decision; `ADR-001` has
been updated to reference it. Watchdog remains ADR-011.

---

# 1. Purpose

This ADR is the single source of truth for **every** external API, data
feed, service, connector, and third-party dependency used anywhere in
Phantom — not only market-data feeds. It exists because an institutional
trading system's reliability is bounded by the weakest external
dependency it silently trusts. Two properties are non-negotiable:

- **Every external service has exactly one documented purpose.** If a
  service is listed here, this document says what it's for, and it is not
  used for anything else.
- **Every external dependency is replaceable.** No approved service may
  become load-bearing in a way that a documented, reviewed swap couldn't
  undo (§4).

---

# 2. Design Philosophy

- **Institutional reliability over convenience.** A dependency earns a
  place in §6 by being replaceable, boring, and well-understood — not by
  being the newest or most powerful option.
- **Minimal dependencies.** The default answer to "should we add this
  service" is no; §12 (Future Expansion) exists because the answer is
  sometimes yes, deliberately, not by drift.
- **Deterministic behavior.** Per `ADR-001`/`ADR-002`, the trading
  decision path (Scanner → Strategy Engine → Scoring Engine → Risk Engine
  → Compliance Engine → Execution Validator) must remain deterministic.
  External services that are inherently non-deterministic (LLMs, social
  sentiment, ad hoc research tools) are therefore excluded from that path
  by construction, not merely by policy — see §7 and §3.
- **Not every "external service" is a trading-data source.** Several
  services in §6 (GitHub, Claude, Grafana) are development/operational
  tooling with zero runtime relationship to the trading pipeline. This ADR
  documents them for completeness and governance, but the Data Quality
  framework in §9 applies only to services that actually feed a trading
  decision.

---

# 3. Dependency Rules

1. **No API may become part of business logic.** Scoring, strategy
   confirmation, risk sizing, and compliance rules must never encode a
   specific vendor's request/response shape, field names, or quirks
   directly. A vendor integration lives in a thin adapter at the pipeline
   boundary (Market Data stage, MT5 Bridge, or Watchdog); the adapter
   translates vendor-specific detail into the pipeline's own data model
   (e.g. `ScannerObservation`, per `ADR-002` §8) before anything
   downstream sees it.
2. **Business logic must remain independent from vendors.** A vendor swap
   (broker, database engine, notification channel) must be achievable by
   changing the adapter alone — zero changes to Scanner, Strategy Engine,
   Scoring Engine, Risk Engine, or Compliance Engine logic.
3. **No hidden external dependencies.** Every external call anywhere in
   the codebase must trace to an entry in §6, or the dependency is
   prohibited until it goes through §12. A transitive dependency pulled in
   by a library (e.g. a package that phones home for telemetry) is not
   exempt from this rule merely because it wasn't explicitly imported.
4. **Fail-closed by default.** Where a service feeds anything
   compliance-relevant (news, account state, kill-switch persistence), an
   outage or data-quality failure defaults to the safer state (blocked/
   unknown), never to the more permissive one — consistent with the
   Compliance Engine being final, non-bypassable authority per `ADR-001`.
5. **Logging/metrics/notification services are never gates.** Per
   `ADR-002` §11's "logging is observability, not a gate" — the same
   applies here to Prometheus, Grafana, and Telegram: their failure must
   never block or alter a trading decision.

---

# 4. Vendor Independence

For each approved service (§6), "Replaceability" states concretely what
would need to change to swap vendors. As a general rule:

- Data-shape adapters (§3.1) are the mechanism, not a policy statement —
  if replacing a vendor requires touching Scanner/Strategy Engine/Scoring
  Engine/Risk Engine/Compliance Engine code, the integration was built
  wrong regardless of what this ADR says.
- Schema and query patterns for the Database (§6) must avoid
  vendor-specific SQL extensions, so the SQLite → PostgreSQL migration
  path stays clean (§6, Database).
- MT5 itself is the one exception stated plainly: MT5-the-platform is a
  fixed dependency by project charter (this is an MT5 EA), not something
  this ADR treats as swappable. The **broker account** behind the MT5
  terminal is replaceable; MT5 as the execution platform is not.

---

# 5. Data Layer Architecture

```
MT5 Broker Feed ──┐
MT5 Calendar ──────┼──► Market Data stage (ADR-013) ──► Scanner (ADR-002) ──► ... ──► MT5 Bridge (ADR-008) ──► MT5 Broker Feed (orders)
                   │
Database (SQLite/PostgreSQL) ◄── Analytics (ADR-010), Compliance Engine (ADR-006) state, Watchdog (ADR-011) session logs
                   │
Prometheus ◄── metrics export from every stage (pull-only, additive)
Grafana ◄── Prometheus (visualization only, no pipeline access)
Telegram Bot API ◄── Watchdog (ADR-011), Analytics (ADR-010) (outbound notification only)
                   │
GitHub, Claude ─── development-time only, zero runtime edges into the diagram above
Vibe-Trading ────── fully isolated research lab, zero edges into the diagram above (see §6)
```

Only the Market Data stage and MT5 Bridge touch the MT5 Broker Feed
directly. Every other stage consumes already-normalized internal data
models. This mirrors `ADR-002`'s existing rule that the Scanner "does not
fetch, cache, or validate raw feeds itself."

---

# 6. Approved External Services

## Primary Market Data — MT5 Broker Feed

- **Purpose:** sole source of live OHLCV price data, spread, and
  account/position state.
- **Owner:** Backend Architect (per `TEAM.md` RACI, MT5 Bridge row).
- **Pipeline stages allowed:** Market Data stage (ingestion) and MT5
  Bridge (order channel) only. No other stage may open a connection to
  MT5 directly.
- **Update frequency:** continuous/tick- or bar-close-driven, matching
  the shortest configured timeframe's bar interval (`ADR-002` §13).
- **Failure behavior:** fail-closed. A stale or lost feed must surface as
  an explicit data-quality/feed-stale signal to Compliance Engine and
  Watchdog — never silently continued on.
- **Retry policy:** bounded reconnect attempts with backoff; unbounded
  silent retry is prohibited — persistent failure must raise a Watchdog
  alert (ADR-011), not retry forever quietly.
- **Timeout policy:** explicit per-request timeout, sized empirically at
  implementation time against the terminal's real response behavior — not
  invented here (`CLAUDE.md` §7).
- **Authentication:** broker account credentials via the terminal/MT5
  Python session; never hardcoded; sourced from Secrets (§6, Secrets).
- **Security considerations:** the highest-trust dependency in the
  system — real money, real account. Network isolation from any research
  environment (ties directly to the Vibe-Trading isolation requirement
  below); least-privilege API scope if the broker supports it; credential
  rotation required.
- **Backup provider:** none realistic for the feed itself; resilience
  comes from Watchdog detecting total feed loss and forcing Compliance
  Engine into a no-new-trades state, not from a second vendor.
- **Replaceability:** the broker account is swappable; MT5 as the
  platform is not (§4).

## Economic Calendar — MT5 Calendar

- **Purpose:** scheduled high-impact news events for Compliance Engine's
  news-blackout guard.
- **Owner:** Backend Architect (integration); Consulted: Security
  Architect (feeds a compliance-relevant guard).
- **Pipeline stages allowed:** Compliance Engine only. Scanner/Strategy
  Engine must never independently consume calendar data — one guard, one
  owner, no duplicate news logic (Phantom Protocol rule 4).
- **Update frequency:** periodic refresh; calendar entries are published
  ahead of time, not tick-driven.
- **Failure behavior:** fail-closed — missing or stale calendar data
  defaults the news guard to DANGER (blocking), never to SAFE.
- **Retry policy:** bounded retry with backoff; generous but finite
  staleness TTL (hours, not indefinite trust).
- **Timeout policy:** standard bounded request timeout.
- **Authentication:** typically bundled with the MT5 terminal; no
  separate credential in the common case.
- **Security considerations:** standard API-key hygiene if a credential
  is ever required; no PII involved.
- **Backup provider:** none approved for live use — see the Alternative
  institutional news provider entry below, which is explicitly
  research-only, not a live backup.
- **Replaceability:** could be replaced by a vetted institutional calendar
  API, only through the §12 approval process.

## Economic Calendar — Alternative institutional news provider (research only)

- **Purpose:** research-side comparison/validation of calendar data
  quality, used only inside the isolated research environment (Vibe-
  Trading or equivalent), never by the live pipeline.
- **Owner:** Software Architect (research-boundary governance).
- **Pipeline stages allowed: none.** This is the load-bearing
  classification for this entry — it must never be wired into Compliance
  Engine's live news guard under any circumstance without a full new ADR
  and Security Architect review. Conflating a research-only source with a
  live compliance-relevant guard input would defeat the entire point of
  §3's "one documented purpose" rule.
- **Update frequency / failure behavior / retry / timeout:** governed by
  whatever research-lab process consumes it (see
  `docs/research/VIBE-TRADING-EVALUATION.md`), not by this ADR's live
  pipeline requirements.
- **Authentication:** its own isolated credentials, never shared with
  Phantom's live-pipeline secrets.
- **Security considerations:** must run fully isolated per the Vibe-
  Trading entry below.
- **Backup provider:** N/A.
- **Replaceability:** fully replaceable; it's a research convenience, not
  a system dependency.

## Source Control — GitHub

- **Purpose:** version control and code review for Phantom's source and
  documentation.
- **Owner:** Software Architect.
- **Pipeline stages allowed: none.** GitHub is development-time tooling
  only; the deployed trading pipeline has zero runtime dependency on it.
- **Update frequency:** event-driven, developer-triggered.
- **Failure behavior:** affects development velocity only; zero effect on
  live trading.
- **Retry / timeout policy:** standard git/CI tooling defaults; not a
  trading SLA concern.
- **Authentication:** SSH keys / scoped personal access tokens, least
  privilege for any automation (CI).
- **Security considerations:** secret scanning, branch protection,
  mandatory review before merge — already effectively enforced by
  `TEAM.md` §3's mandatory-reviewer routing table.
- **Backup provider:** N/A (standard git remote/mirror practice, not a
  runtime failover concern).
- **Replaceability:** replaceable in principle; a tooling decision, not an
  architecture decision for the trading pipeline.

## AI Development — Claude

- **Purpose:** development-time engineering assistant (this Council, ADR
  drafting, code review support).
- **Owner:** Software Architect.
- **Pipeline stages allowed: none, absolutely.** Per `ADR-001`'s
  LLM-free decision path and the Explicit Prohibitions (§7): zero runtime
  pipeline stages may call Claude or any LLM at inference time for a
  trading decision. This is a hard boundary, not a preference.
- **Update frequency:** developer-invoked, session-based.
- **Failure behavior:** affects development velocity only; a Claude/
  Anthropic outage never affects live trading, precisely because it has
  no runtime edge into the pipeline.
- **Retry / timeout policy:** standard API client practice; not a trading
  SLA concern.
- **Authentication:** API key via Secrets management (§6, Secrets); never
  embedded in code or committed configuration.
- **Security considerations:** prompt-injection awareness when reading
  external content (research docs, third-party repos) during development
  sessions — practiced throughout this session's own research work.
  Blast radius is bounded by mandatory human review (Code Reviewer gate,
  `TEAM.md` §3) before anything Claude produces merges.
- **Backup provider:** N/A — not a runtime dependency.
- **Replaceability:** fully replaceable; low-stakes precisely because it's
  excluded from the runtime path.

## Research Laboratory — Vibe-Trading (RESEARCH ONLY — never connected to live execution)

- **Purpose:** standalone statistical/backtesting research (walk-forward,
  Monte Carlo, metrics) per
  `docs/research/VIBE-TRADING-EVALUATION.md`'s existing evaluation.
- **Owner:** Software Architect (research-boundary governance).
- **Pipeline stages allowed: none, with no exception.** No stage may
  query it, receive data from it automatically, or execute anything it
  produces without the human-approval gate already established: research
  idea → VIBE backtest → report → human approval → reimplementation as a
  new playbook inside the Strategy Engine (`ADR-003`), never a direct
  port. This restates, and does not loosen, the isolation boundary from
  the existing VIBE evaluation.
- **Update frequency:** ad hoc, human-initiated research sessions only.
- **Failure behavior:** zero effect on trading by design — full isolation
  means a VIBE outage or compromise cannot reach the live pipeline.
- **Retry / timeout policy:** N/A to the live pipeline.
- **Authentication:** its own isolated credential set; never shares
  Phantom's broker or database credentials.
- **Security considerations:** must run in a fully separate environment
  (machine/container/venv) with no shared filesystem and no network path
  to MT5, per the existing evaluation's finding that VIBE executes
  LLM-generated code locally — a real prompt-injection-adjacent risk if
  that isolation is ever relaxed.
- **Backup provider:** N/A.
- **Replaceability:** fully optional; Phantom's architecture (`ADR-001`
  through `ADR-014`) does not require VIBE, or any research lab, to exist.

## Notifications — Telegram Bot API

- **Purpose:** outbound operational alerts (Watchdog triggers, kill-switch
  notifications, summaries) — one-directional, notify-only.
- **Owner:** SRE.
- **Pipeline stages allowed:** Watchdog (ADR-011) and Analytics (ADR-010)
  for outbound notification only. **Telegram must never be an inbound
  control channel** for the trading pipeline (no "send a command to pause
  trading" pattern) unless a future ADR explicitly designs and Security-
  Architect-reviews that as a new control surface — prohibited by default.
- **Update frequency:** event-driven (alert-triggered), plus optional
  periodic heartbeat/summary.
- **Failure behavior:** must never block or degrade trading — a pure side
  channel. Failure is logged and trading continues normally, mirroring
  `ADR-002` §11's "logging is observability, not a gate."
- **Retry policy:** bounded retry with backoff; must not retry so
  persistently that it delays a more urgent alert.
- **Timeout policy:** short timeout; best-effort side channel.
- **Authentication:** bot token via Secrets management, scoped to a single
  bot/chat.
- **Security considerations:** token never committed; validate that only
  authorized chat IDs receive alerts, to avoid broadcasting account/risk
  data to an unintended recipient; be aware of Telegram's own API rate
  limits.
- **Backup provider:** none required for v1; Watchdog's own health-check/
  heartbeat is the authoritative signal, Telegram is a convenience layer
  on top of it.
- **Replaceability:** fully replaceable by any notification channel;
  deliberately low-stakes.

## Metrics — Prometheus

- **Purpose:** metrics collection/scraping for observability, mirroring
  the reference material's existing Prometheus-format `/metrics` pattern.
- **Owner:** SRE.
- **Pipeline stages allowed:** any stage may export metrics (Scanner,
  Strategy Engine, Risk Engine, Compliance Engine, Watchdog, Analytics);
  Prometheus itself never writes back into or influences the pipeline —
  pull-only, export-only, additive (mirrors the reference material's
  "additive; changes nothing" discipline).
- **Update frequency:** scrape-interval driven, Prometheus-side
  configuration, not a Phantom-side push.
- **Failure behavior:** zero effect on trading if scraping fails or
  Prometheus is down; the exposed metrics endpoint must never hold a lock
  that could block trading logic.
- **Retry / timeout policy:** Prometheus does the pulling; the exposed
  endpoint must have a bounded response time regardless.
- **Authentication:** typically none, or network-level restriction for an
  internal-only endpoint.
- **Security considerations:** the metrics endpoint must never leak
  account/credential data; bind to an internal-only interface.
- **Backup provider:** N/A.
- **Replaceability:** fully replaceable by any Prometheus-compatible
  scraper; low stakes.

## Visualization — Grafana

- **Purpose:** human-facing dashboarding of Prometheus metrics (maps to
  the future Dashboard stage, ADR-012).
- **Owner:** Backend Architect (per `TEAM.md` RACI, Dashboard row).
- **Pipeline stages allowed: none directly.** Grafana reads only from
  Prometheus; it has no interaction with the trading pipeline itself.
- **Update frequency:** refresh-interval driven, human-facing.
- **Failure behavior:** zero effect on trading; pure visualization
  convenience.
- **Retry / timeout policy:** N/A (client-side dashboard refresh).
- **Authentication:** Grafana's own dashboard-user auth; data-source
  credentials to Prometheus should be read-only, least-privilege.
- **Security considerations:** access control over who can view
  account-sensitive metrics; internal-only network binding.
- **Backup provider:** N/A.
- **Replaceability:** fully replaceable by any dashboard tool.

## Database — SQLite (initial) / PostgreSQL (future)

- **Purpose:** durable storage for the trade journal, session/decision
  logs, and analytics history behind Analytics (ADR-010); potentially
  Compliance Engine's persistent kill-switch/lockout state (a
  consideration to resolve concretely in `ADR-006`, not here).
- **Owner:** Backend Architect.
- **Pipeline stages allowed:** Analytics, Watchdog, and Compliance Engine
  (for durable safety-state persistence only). **Scanner, Strategy
  Engine, Scoring Engine, and Risk Engine must remain stateless with
  respect to the database** — per `ADR-002`'s purity principle, core
  decision logic must never depend on a database read/write to produce
  its output.
- **Update frequency:** write-on-event (trade closed, decision logged);
  read on-demand for reporting.
- **Failure behavior:** fail-closed for anything Compliance-critical (if
  persistent kill-switch state can't be reliably read/written, Compliance
  Engine defaults to the safe/blocking state — mirroring the reference
  material's existing "compliance-state-error (fail-closed)" pattern).
  For pure Analytics/logging, degrade gracefully (buffer and retry) rather
  than block trading, since Analytics is explicitly non-blocking per
  `ADR-001`.
- **Retry policy:** bounded retries with backoff for transient failures;
  prefer durable queuing over dropping records.
- **Timeout policy:** bounded per-query timeout, sized empirically.
- **Authentication:** local file permissions for SQLite; least-privilege
  database role (read/write only to Phantom's own schema, no superuser)
  for PostgreSQL, via Secrets.
- **Security considerations:** encryption at rest worth evaluating for
  PostgreSQL in production; SQLite file permissions restricted; no
  personal data, only operational trade/decision records.
- **Backup provider:** PostgreSQL is the documented future upgrade path
  from SQLite when concurrent-write or scale needs exceed SQLite's
  comfortable range; that transition itself goes through §12 when
  actually proposed, not assumed here.
- **Replaceability:** both are standard SQL stores; schema/queries must
  avoid vendor-specific SQL extensions (§4) to keep the migration path
  clean.

## Secrets — Environment Variables (initial) / Secret Manager (future)

- **Purpose:** credential storage/injection for every other service
  requiring authentication (MT5, Telegram, Claude, database, alternative
  calendar provider).
- **Owner:** Security Architect (design), Application Security Engineer
  (implementation review) — the Council's existing two-tier security
  split (`TEAM.md` §4) applies directly here.
- **Pipeline stages allowed:** cross-cutting — consumed by whichever
  stage needs a specific credential, never hardcoded into business logic
  (§3.1). This is the concrete mechanism that makes "no vendor-specific
  business logic" enforceable in practice.
- **Update frequency:** rotated on a defined cadence, and immediately on
  suspected compromise.
- **Failure behavior:** a missing or invalid required credential must fail
  closed at boot — the affected component refuses to start or refuses to
  enable that integration, rather than running in a silently degraded,
  insecure mode.
- **Retry / timeout policy:** N/A — local read, not a network call, for
  the Environment Variables approach.
- **Authentication:** N/A — this is the authentication substrate for
  everything else in §6.
- **Security considerations:** the highest-priority security surface in
  this ADR. Least privilege per credential (scoped API keys wherever the
  vendor supports it); never logged; never committed; rotation procedure
  defined and auditable once a Secret Manager is in place.
- **Backup provider:** N/A.
- **Replaceability:** Environment Variables → Secret Manager (e.g. a
  vault-style service) is itself a planned future migration and, being a
  new external service, must go through §12 like any other addition.

---

# 7. Explicitly Prohibited

- **No AI-generated live trading decisions** — the decision path is
  deterministic and LLM-free per `ADR-001`.
- **No direct LLM execution** inside any runtime pipeline stage — Claude
  or any LLM is development-time tooling only (§6, AI Development).
- **No automatic strategy generation** — new playbooks enter only through
  a human-approved Strategy Engine change (`ADR-003`), never auto-
  generated and auto-deployed.
- **No automatic parameter optimization** — consistent with the standing
  finding in `TEAM.md` §6 that no agent performs unsupervised parameter
  tuning, and the VIBE evaluation's explicit rejection of unsupervised
  optimizers being wired into Phantom.
- **No social-media sentiment trading** — no Twitter/Reddit/similar
  sentiment feed as a trading input. This explicitly rules out anything
  resembling `phantom_institutional.py`'s reference-only "Sentiment
  Aggregator" (COT proxy, retail positioning) from ever becoming an
  approved service without a full new ADR and Council review.
- **No hidden external dependencies** — every dependency traces to §6 or
  is rejected via §12; a transitive dependency is not exempt (§3.3).
- **No vendor-specific business logic** — enforced structurally by §3.1
  and the Secrets mechanism in §6.

---

# 8. Data Quality Requirements

This framework applies to services that actually feed a trading decision
— **MT5 Broker Feed** and **MT5 Calendar** — not to development/
operational tooling (GitHub, Claude, Grafana) or the isolated research lab
(Vibe-Trading), which have no trading-decision edge to hold to this
standard.

| Dimension | MT5 Broker Feed | MT5 Calendar |
|---|---|---|
| **Freshness** | Must not exceed the execution timeframe's bar interval before being flagged stale. | Refreshed on a defined periodic schedule; entries older than their own TTL are flagged stale. |
| **Completeness** | All requested timeframes present or the observation is flagged missing-timeframe (`ADR-002` §9). | All configured currencies/instruments' upcoming events present for the lookahead window. |
| **Latency** | Bounded per-request timeout, sized empirically (§6). | Bounded per-request timeout. |
| **Availability** | Reconnect with backoff; Watchdog alerts on persistent loss. | Reconnect with backoff; Watchdog alerts on persistent loss. |
| **Confidence** | Reported via `data_quality_flag` (`ADR-002` §8), never silently assumed nominal. | Missing/stale data defaults the news guard to DANGER, never SAFE. |
| **Validation rules** | Reject non-monotonic timestamps, zero/negative prices, impossible OHLC ordering (`ADR-002` §9). | Reject malformed/incomplete event records rather than treat them as "no news." |
| **Failure handling** | Fail-closed per `ADR-002` §10 — never fabricate a reading. | Fail-closed — treat as DANGER, block rather than guess. |

Any future service added under §12 that feeds a trading decision must
define all seven dimensions above as part of its approval, following this
same table shape.

---

# 9. Security

- **API key management:** every credential lives in Secrets (§6), never
  in source, config committed to the repo, or logs.
- **Credential rotation:** defined cadence per service, plus immediate
  rotation on suspected compromise (mirrors `security.md`'s incident-
  response shape noted in `docs/research/ECC-EVALUATION.md`).
- **Least privilege:** scoped API keys/roles wherever the vendor supports
  them (broker API scope, database role, bot-token chat scope).
- **Rate limiting:** respected per-vendor (Telegram, any calendar API);
  Phantom's own exposed endpoints (metrics) must not be a source of
  unbounded load either.
- **Audit logging:** credential use and rotation events are logged
  (without logging the credential itself); ties into Watchdog's
  operational logging (§10).
- **Network isolation:** the MT5 Broker Feed and MT5 Bridge sit on a
  trusted network path; the Vibe-Trading research lab sits on a fully
  separate one with no shared path to either, per §6.

---

# 10. Operational Requirements

- **Monitoring / health checks / heartbeats:** each live-pipeline service
  in §6 (MT5 Broker Feed, MT5 Calendar, Database) has a defined health
  signal Watchdog (ADR-011) can observe.
- **Metrics:** exported per §6 (Prometheus) for every stage that touches
  an external service.
- **Alerting:** persistent failure of any live-pipeline service raises a
  Watchdog alert, delivered via Telegram (§6) as the default channel.
- **Circuit breakers:** bounded retry-with-backoff (stated per-service in
  §6) rather than unbounded retry; persistent failure trips to the
  fail-closed state defined per service, not an infinite retry loop.
- **Graceful degradation:** non-critical services (Prometheus, Grafana,
  Telegram) degrade silently from the trading pipeline's perspective;
  critical services (MT5 Broker Feed, MT5 Calendar, Compliance-relevant
  Database state) degrade to the fail-closed state, never to "continue as
  if nothing happened."

---

# 11. Testing Requirements

- **Mock providers** for every live-pipeline service in §6, so Scanner/
  Strategy Engine/Compliance Engine tests never make a real network call
  (consistent with `ADR-002` §15's isolated-unit-test requirement).
- **Replay testing** — historical data replayed through mock providers
  must reproduce identical pipeline behavior, tying into `ADR-002` §14's
  Determinism Requirement.
- **Failure simulation** — each failure mode in §6/§8 (stale feed, missing
  timeframe, calendar outage, database unavailable) must have a
  corresponding test proving fail-closed behavior.
- **Timeout simulation** — verify bounded-timeout behavior under a
  simulated slow/hanging external call.
- **API contract tests** — verify the adapter layer (§3.1) correctly
  translates each vendor's actual response shape into Phantom's internal
  data model; contract tests catch a vendor's silent API change before it
  reaches the trading pipeline.
- **Regression tests** — any change to an adapter must prove no change in
  the internal data model it produces for a fixed input, the same
  determinism discipline `ADR-002` already established for the Scanner.

---

# 12. Future Expansion — approval process for any new external dependency

No new external dependency of any kind may be added to Phantom without
**all four** of the following, in order:

1. **Engineering Council review** — proposed in the same review pipeline
   as any other change (`TEAM.md` §2).
2. **Software Architect approval** — confirms the dependency has exactly
   one documented purpose (§1) and fits the Dependency Rules (§3).
3. **Security Architect review** — threat-models the new trust boundary
   before any code is written, per the Council's existing design-time
   security lane (`TEAM.md` §4).
4. **ADR update** — this document gains a new §6 entry (or a new ADR is
   drafted, for a large addition) before implementation begins, per
   `ADR-001`'s and `CLAUDE.md` §1.10's ADR-gated implementation rule.

A dependency that skips any of these four steps is, by definition, a
"hidden external dependency" under §7 and is prohibited regardless of how
useful it might be.

---

# 13. Recommended Approved APIs

- MT5 Broker Feed (Primary Market Data)
- MT5 Calendar (Economic Calendar)
- GitHub (Source Control)
- Claude (AI Development — development-time only, zero runtime edge)
- Vibe-Trading (Research Laboratory — fully isolated, zero runtime edge)
- Telegram Bot API (Notifications — outbound only)
- Prometheus (Metrics)
- Grafana (Visualization)
- SQLite (Database, initial)
- Environment Variables (Secrets, initial)

# 14. APIs to Avoid

- **Alternative institutional news provider** as a *live* Compliance
  Engine input — approved for research-only use exactly as scoped in §6;
  using it as a live backup calendar source would violate §3's
  one-documented-purpose rule and is explicitly not approved.
- Any social-media sentiment API (§7).
- Any service that would require embedding vendor-specific logic directly
  into Scanner/Strategy Engine/Scoring Engine/Risk Engine/Compliance
  Engine (§3.1) rather than sitting behind an adapter.
- Any LLM API called at runtime inference time inside the trading
  decision path (§7) — this includes Claude; its approval in §6 is
  strictly development-time.

# 15. Future Candidates

- **PostgreSQL** — documented future upgrade from SQLite (§6, Database);
  candidate once concurrent-write/scale needs are demonstrated, not
  speculative.
- **Secret Manager** (vault-style service) — documented future upgrade
  from Environment Variables (§6, Secrets); candidate once credential
  count/rotation complexity justifies it.
- A vetted institutional news/calendar API to replace or supplement MT5
  Calendar (§6) — only through §12, and only for live use if it can meet
  the Data Quality framework in §8.

# 16. Remaining Risks

- **MT5 Broker Feed timeout/retry numeric budgets are deliberately left
  unspecified** (§6) pending real implementation measurement — this is a
  known open item for whichever ADR/implementation phase actually builds
  the Market Data stage (ADR-013) and MT5 Bridge (ADR-008), not a gap in
  this ADR's design.
- **Compliance Engine's persistent kill-switch/lockout storage** is
  referenced here (§6, Database) as a consideration but is not fully
  resolved — that resolution belongs to `ADR-006` (Compliance Engine),
  and this ADR should be cross-checked against it once drafted for
  consistency.
- **PostgreSQL/Secret Manager migrations are unscheduled** — listed as
  future candidates (§15) with no committed timeline; this ADR does not
  presume they will happen, only that they would follow §12 if proposed.
- **Vibe-Trading's isolation is a documented requirement, not an enforced
  one** — this ADR (and the existing VIBE evaluation) states the
  isolation boundary; actual enforcement (network policy, credential
  separation) is an operational/infrastructure concern outside any ADR's
  ability to guarantee by text alone.

# 17. Recommendation

**ADR-015 is ready for acceptance.** It defines exactly one purpose per
service, states replaceability for each, prohibits the seven categories of
risk explicitly named, and establishes a concrete four-step approval gate
for anything added later. The three items in §16 are known, scoped,
forward-referenced risks — not open design questions this ADR fails to
answer — and do not block acceptance of the governance model itself.
