# ADR-014 — Multi-Agent Governance

Status: Accepted

Acceptance Date: 2026-07-04

Accepted By: Software Architect / Titan Protocol Engineering Council

Owner: Software Architect (per `TEAM.md` §1's own definition of the
role: "Cross-module design, dependency direction, ADRs" — this ADR is
exactly that mandate applied to the whole system rather than one module)

Reviewed by: Security Architect (mandatory — this ADR defines
permission and authority boundaries system-wide, a design-time
trust-boundary question per `TEAM.md` §4), Backend Architect (Consulted
— Pipeline/Infrastructure Agent classification touches the same
API/data-contract patterns Backend Architect already owns per row)

Date: 2026-07-04

Depends on: `ADR-001-single-authority-architecture.md` (Accepted),
`ADR-002-scanner.md` through `ADR-013-data-pipeline.md` (all Accepted —
classified here as Pipeline/Infrastructure Agents without any change to
their own authority), `docs/adr/ADR-015-external-data-sources-api-
governance.md` (Accepted — its four-step future-dependency gate, §12,
is the direct model for this ADR's New Agent Approval process, §9),
`docs/adr/ADR-016-ai-news-intelligence.md` (Accepted — the reference
instance of the Advisory Agent class), `docs/adr/ADR-019-self-evolving-
market-structure-research-agent.md` (Proposed — the reference instance
of the Research Agent class; its Proposed status is preserved here, not
upgraded), `.claude/agents/TEAM.md` (the existing, operational
implementation of this ADR's Governance Agent class — this ADR
formalizes what `TEAM.md` already practices, it does not replace it)

---

# Pipeline position

**Multi-Agent Governance is not a pipeline stage.** Like Watchdog
(`ADR-011`) and Dashboard (`ADR-012`), it is cross-cutting — but where
Watchdog governs infrastructure *health* and Dashboard governs
infrastructure *visibility*, this ADR governs **who is authorized to
take which action, anywhere in Titan Protocol** — engineering, runtime,
research, or human. It touches every prior ADR by classifying the actor
each one already defined; it changes none of them.

---

# 1. Mission

**The Multi-Agent Governance layer answers exactly one question: "Who
is allowed to perform which actions inside Titan Protocol?"**

**It never answers:** Should we trade? Should we score? Should we
execute? Should we manage positions? Those are, respectively, Strategy/
Scoring/Risk Engines', Execution Validator's/MT5 Bridge's, and Position
Manager's questions — each already answered by its own Accepted ADR.
This ADR does not grant, deny, or override any decision those stages
make. **It is a classification and permission framework layered over
already-established authority, not a new decision-maker.**

---

# Hard Rules

These override any other requirement in this document if they ever
appear to conflict:

- **No agent may escalate its own authority.** An agent's permitted
  actions are exactly what its own governing ADR (or, for Governance
  Agents, `TEAM.md`) already grants — never more, regardless of
  circumstance.
- **No agent may modify another agent's authority.** Only the ADR
  amendment / new-ADR process (§9) may change what an agent is permitted
  to do — never another agent acting unilaterally.
- **No agent may bypass ADR approval, Human Review, Compliance, or the
  Execution Validator.** These are absolute, restated from `ADR-001` §1.10,
  `ADR-006`, and `ADR-007`'s own Hard Rules, not weakened here.
- **No agent may override Accepted architecture or modify an Accepted
  ADR autonomously.** Every ADR acceptance and every amendment in this
  session's own history was a distinct, explicit human instruction —
  this ADR formalizes that lived practice as a binding rule, not a new
  aspiration.
- **No Governance Agent — including any AI-assisted role acting as
  Software Architect, Security Architect, or any other Council role —
  may itself transition an ADR's Status to Accepted.** A Governance
  Agent recommends; a human, acting through the Engineering Council
  process, decides. This closes the loop on every "Accept ADR-XXX" task
  this session: the recommendation was always the agent's; the
  instruction to accept was always the human's.

---

# 2. Scope

This ADR governs:

- **Engineering agents** — the ten `TEAM.md` Council roles.
- **Runtime agents** — the deterministic pipeline stages (`ADR-002`
  through `ADR-010`) and infrastructure stages (`ADR-011`, `ADR-012`,
  `ADR-013`).
- **Research agents** — `ADR-019` and any future research-lab process
  under `ADR-015` §6's Vibe-Trading isolation.
- **Infrastructure agents** — Watchdog (`ADR-011`), Dashboard (`ADR-012`).
- **AI advisory agents** — `ADR-016`'s AI News Intelligence Layer and
  any future similar advisory-only system.
- **Human approvals** — the six approval types in §7.
- **ADR lifecycle** — proposal, review, acceptance, amendment,
  deprecation (§9).

---

# 3. Agent classes

| Class | Members | Authority source | Decision authority over live trading |
|---|---|---|---|
| **Pipeline Agents** | Data Pipeline, Scanner, Strategy Engine, Scoring Engine, Risk Engine, Compliance Engine, Execution Validator, MT5 Bridge, Position Manager, Analytics | Each member's own Accepted ADR (`ADR-013`, `ADR-002`–`ADR-010`) | Yes — exactly the authority each one's own ADR grants, never more |
| **Infrastructure Agents** | Watchdog, Dashboard | `ADR-011`, `ADR-012` | **No** — operational/observational only (`ADR-011` Hard Rules, `ADR-012` Hard Rules) |
| **Governance Agents** | The ten `TEAM.md` Council roles (Software Architect, Backend Architect, Code Reviewer, Minimal Change Engineer, Multi-Agent Systems Architect, SRE, Security Architect, AppSec Engineer, API Tester, Test Results Analyzer) | `TEAM.md` §1–§7 | **No** — governs the *development process* (code review, ADR drafting, merge gating), never a live trading decision |
| **Research Agents** | `ADR-019`'s Self-Evolving Research Agent; any future Vibe-Trading-isolated process | `ADR-019`, `ADR-015` §6 | **No** — research-lab-only, human-approval-gated promotion to a real Strategy Engine playbook (`ADR-019` §"promotion chain") |
| **Advisory Agents** | `ADR-016`'s AI News Intelligence Layer; any future similar system | `ADR-016` | **No** — advisory, human-and-Analytics-facing only (`ADR-016` §1, §5) |
| **Human Review** | The Titan Protocol Engineering Council acting through a human — never an agent acting alone | §7 | **Ultimate** — the only class that can accept an ADR, approve production, or authorize an emergency action outside Titan Protocol |

**This table classifies; it does not grant.** A Pipeline Agent's actual
authority is defined exhaustively by its own ADR — this table names
which class it belongs to and, via that class, which cross-cutting rules
(§5 permissions, §6 forbidden actions, §8 communication rules) apply to
it in addition to its own ADR's specific content.

---

# 4. Ownership documentation

For every agent, regardless of class, the following must already be
documented (in the agent's own governing ADR, or in `TEAM.md` for
Governance Agents) — this ADR requires their presence, it does not
redefine any of them:

- **Identity** — a stable name (e.g. "Risk Engine," "Security Architect")
  used consistently across every referencing document.
- **Purpose** — the one-sentence Mission every ADR in this session
  already opens with.
- **Authority** — the exhaustive Responsibilities/Never sections every
  Pipeline/Infrastructure ADR already has, or the RACI row every
  Governance Agent already has in `TEAM.md` §5.
- **Boundaries** — the "shall never" table every ADR in this session
  already includes.
- **Lifecycle** — Proposed → Accepted → (optionally) Amended →
  (optionally) Deprecated (§9's new status value).
- **Ownership** — the single Accountable party (RACI, or an ADR's
  "Owner" line) — never more than one per responsibility (§13).
- **Approval chain** — who reviews and who ultimately accepts (an ADR's
  "Reviewed by" / "Accepted By" lines, or `TEAM.md` §2's workflow-by-
  activity table).
- **Retirement** — how an agent is deprecated or removed (§9).

---

# 5. Permissions

**No implicit permissions.** Every permission below must be explicitly
granted by an agent's own governing ADR or `TEAM.md` row — absence of an
explicit grant is a denial, not an oversight to infer around.

- **Read permissions** — which upstream objects an agent may consume
  (e.g. Risk Engine reads `ScoreResult`, per `ADR-005` §2).
- **Write permissions** — which output objects an agent may produce
  (e.g. only Risk Engine produces `RiskDecision`, per `ADR-005` §4).
- **Decision permissions** — which agents may produce a genuine
  decision object (`ComplianceDecision`, `ExecutionDecision`) versus an
  observation/score (`ScannerObservation`, `ScoreResult`) — the same
  facts-vs-decisions distinction `ADR-002` §3 already established,
  generalized here as a permission category.
- **Execution permissions** — order-placement capability, held
  exclusively by MT5 Bridge (`ADR-008` §10); no other agent, in any
  class, may hold it.
- **Infrastructure permissions** — restart/reconnect/reload actions,
  held exclusively by Watchdog (`ADR-011` §7); no Pipeline Agent may
  perform its own infrastructure recovery outside Watchdog's bounded
  actions.
- **Documentation permissions** — who may draft, amend, or recommend
  acceptance of an ADR (Governance Agents, per `TEAM.md`) versus who may
  actually accept one (Human Review only, per this ADR's Hard Rules).

---

# 6. Forbidden actions

| No agent, in any class, may | Restated from |
|---|---|
| Escalate its own authority | Hard Rules |
| Modify another agent's authority | Hard Rules |
| Bypass ADR approval | `ADR-001` §1.10, `CLAUDE.md` §1.10 |
| Bypass Human Review | Hard Rules, §7 |
| Bypass Compliance | `ADR-006` Hard Rules |
| Bypass the Execution Validator | `ADR-007` Hard Rules |
| Override Accepted architecture | `ADR-001` Resolution |
| Modify an Accepted ADR autonomously | Hard Rules |

---

# 7. Human governance

Six approval types, each already exercised in this session's actual
practice, formalized here rather than newly invented:

- **Architecture approval** — acceptance of `ADR-001` itself, and any
  future pipeline-shape change. Exercised once, already.
- **ADR acceptance** — the "Accepted By: Software Architect / Titan Protocol
  Engineering Council" line on every Accepted ADR in this repository —
  a human instruction, every time, never a Governance Agent acting
  alone (Hard Rules).
- **Implementation approval** — per `CLAUDE.md` §1.10, no code begins on
  any pipeline stage until that stage's ADR is Accepted; the human who
  accepts the ADR is the same authority who must separately authorize
  implementation to begin.
- **Production approval** — per `TEAM.md` §2's existing Deployment
  workflow (Test Results Analyzer sign-off, SRE sign-off, Security
  Architect surface review, Software Architect's final freeze-policy
  call) — this ADR does not redefine that workflow, only confirms it is
  this class of approval.
- **Rollback approval** — the same `TEAM.md` §2 Deployment chain, run in
  reverse; not a separate, faster path that skips review.
- **Emergency approval** — **this is not an in-system override
  mechanism.** Per `ADR-007`'s absolute invariant ("no emergency
  override... that happens entirely outside Titan Protocol, e.g. manually in
  the MT5 terminal"), Emergency approval means a human acting **outside**
  Titan Protocol entirely — never a special agent authority, a "break-glass"
  API, or an elevated permission granted to any agent class inside this
  system. This ADR does not create such a mechanism and forbids any
  future one from being added without a dedicated ADR and Security
  Architect review (mirroring `ADR-015` §12's gate for new dependencies).

---

# 8. Agent communication

- **Allowed communication** — a Pipeline Agent may only exchange data
  via the immutable object handoffs its own ADR already defines
  (`ScannerObservation` → `CandidateTrade` → … → `PositionManagementDecision`,
  plus the already-carved exceptions: `ADR-013` §9's `MarketSnapshot`
  multi-consumer model, `ADR-009` §9's reverse `PositionCloseRequest`/
  `PositionAdjustmentRequest` edge to MT5 Bridge). Infrastructure Agents
  observe already-exported signals (`ADR-011` §2's boundary note); they
  never write to a Pipeline Agent. Governance Agents communicate via
  `TEAM.md` §2's review workflow — never by directly altering a Pipeline
  Agent's runtime behavior outside that process. Research and Advisory
  Agents communicate only through their own explicitly one-way channels
  (`ADR-015` §6, `ADR-016` §2, `ADR-019`).
- **Forbidden communication** — any channel not named in an agent's own
  ADR is forbidden by default, the same "no hidden external dependency"
  discipline `ADR-015` §3.3 already established, generalized here from
  external vendors to inter-agent channels.
- **Shared objects** — every object exchanged between agents is
  immutable at its source (the same guarantee restated in every prior
  ADR's data model section); "shared" means "read by more than one
  consumer," never "jointly writable."
- **Ownership transfer** — an object's *authoritative source* never
  transfers once produced. Downstream consumption (e.g. Analytics
  collecting every stage's output, `ADR-010` §2) does not make Analytics
  the new owner of `ScoreResult` — it remains attributed to Scoring
  Engine forever. "Ownership transfer" in this ADR means only that the
  pipeline's *current step* advances, never that history is rewritten
  or a new party gains write access to an old record.
- **Traceability** — every inter-agent exchange carries the same
  `trace_id` chain established at `ADR-002` §8 and propagated by every
  subsequent ADR, or Watchdog's own health-event `trace_id` chain
  (`ADR-011` §5), never confused with each other (`ADR-012` §7 already
  states this for the Dashboard's display of both).
- **Audit logging** — every Governance Agent action (a review, an ADR
  draft, an acceptance) is already logged via this repository's own git
  history: every commit in this session carries an explicit message,
  a `Co-Authored-By` line, and — for acceptances — an explicit `Accepted
  By` line in the ADR itself. **This is the concrete, already-practiced
  mechanism satisfying this requirement for Governance Agents** — not a
  new system to build, an existing practice this ADR formalizes as
  required rather than incidental.

---

# 9. Change management

- **New agent approval** — for a Pipeline/Infrastructure Agent: a new
  ADR, drafted, reviewed, and Accepted (this session's entire operating
  procedure, e.g. `ADR-013`'s own creation). For a Governance Agent: the
  precedent `TEAM.md` §6 already set ("do not add an 11th agent" without
  demonstrating clear, measurable benefit) is the binding standard, not
  a new one invented here. For a new external dependency any of the
  above needs: `ADR-015` §12's four-step gate.
- **Agent modification** — an ADR amendment, following the `ADR-002`
  Amendment 1 / `ADR-008` Amendment 1 precedent: marked inline, dated,
  never reopening the ADR's Accepted status.
- **Agent deprecation** — introduces a new ADR status value,
  **Deprecated**, for an agent whose ADR is superseded but retained for
  historical/audit reference — mirroring how `CLAUDE.md` §2 already
  marks the pre-`ADR-001` priority order "historical — superseded... kept
  for context only" without deleting it. No existing ADR's status
  changes as a result of defining this value.
- **Agent removal** — deleting an agent's governing ADR outright is not
  a lighter-weight version of deprecation; per `CLAUDE.md`'s Titan Protocol
  Protocol rule 2 ("never remove existing functionality unless explicitly
  instructed"), removal requires the same Human Review as any other
  architecture change, and the historical ADR is retained, not deleted,
  consistent with `ADR-001`'s own treatment of `titan_protocol/` and
  `phantom_institutional.py` as retained reference material rather than
  deleted code.
- **Versioning** — each Pipeline/Infrastructure Agent's output objects
  already carry `schema_version` (`ADR-002` §8 onward); a Governance
  Agent's "version" is its ADR's own Amendment count.
- **Compatibility** — additive, `schema_version`-gated fields only,
  never a breaking redefinition without a new major version and an
  explicit migration note — the same rule `ADR-002` §8's Amendment 1
  already modeled.

---

# 10. Security

This section names the cross-cutting principle; it does not restate
each agent's own already-Accepted security section.

- **Least privilege** — every agent's credentials are scoped to exactly
  what its own ADR requires, never more (`ADR-015` §9's governing
  principle, already applied individually by `ADR-007` §13, `ADR-008`
  §10, `ADR-009` §15, `ADR-011` §15, `ADR-012` §9, `ADR-013` §13).
- **Separation of duties** — no single agent, in any class, holds
  decision authority, execution authority, and audit authority over the
  same action simultaneously. Concretely, already true throughout: Risk
  Engine decides sizing (`ADR-005`) but cannot execute; MT5 Bridge alone
  executes (`ADR-008`) but cannot decide; Analytics alone records
  (`ADR-010`) but cannot decide or execute. This ADR names that existing
  pattern as a formal, system-wide invariant rather than a coincidence of
  independent designs.
- **Credential ownership** — exactly one agent holds each credential
  class; `ADR-008` §10's "MT5 Bridge is the sole stage with order-
  placement capability" is the load-bearing example this principle
  generalizes from.
- **Secret access** — per `ADR-015` §6's Secrets entry and §9; this ADR
  adds no new secret-handling rule, only confirms every agent class is
  bound by the existing one.
- **Network boundaries** — the Vibe-Trading research-lab isolation
  (`ADR-015` §6, `ADR-019`) and MT5-direct-connection restriction
  (`ADR-015` §6, `ADR-013` §1) apply per agent class exactly as their
  own ADRs already state.

---

# 11. Observability

Every agent action must include:

- `trace_id`
- `agent_id` — the acting agent's stable identity (§4)
- `timestamp`
- `authority` — which ADR/RACI grant authorized the action
- `action`
- `result`

For Pipeline/Infrastructure Agents, this is already satisfied by each
stage's own Logging section (`ADR-002` §11 onward) plus the `trace_id`
chain; `agent_id` and `authority` are additive fields naming which stage
and which ADR clause produced the record, not a new logging system. For
Governance Agents, this is satisfied by git commit history: the
committer/co-author line is `agent_id`, the commit message's cited ADR
section is `authority`, and the diff itself is `action`/`result`.

---

# 12. Testing

- **Permission verification** — an agent attempting an action outside
  its documented permissions (§5) is rejected/fails, never silently
  allowed.
- **Boundary verification** — the "shall never" table (§6, and each
  agent's own) holds under test, the same boundary/type-level test
  pattern every prior ADR already requires.
- **Authority verification** — an action's logged `authority` field (§11)
  correctly resolves to a real ADR clause or RACI grant, not a dangling
  or fabricated reference.
- **Audit completeness** — every agent action in a given window has a
  corresponding log record; a gap is a missing-event condition, the same
  discipline `ADR-010` §6 already established for decision provenance,
  applied here to agent actions generally.
- **Trace completeness** — `trace_id` is present and correctly chained
  across every inter-agent exchange (§8).
- **Human approval enforcement test** — a git-history audit that every
  ADR's Status transition to Accepted corresponds to a distinct,
  human-initiated commit (an "accept: ADR-XXX" pattern, as practiced
  throughout this session) — never bundled silently into an unrelated
  commit, and never made by a Governance Agent's own unprompted action.

---

# 13. Architectural invariants

- Every responsibility has exactly one owner.
- **No agent owns another agent.** This means no agent controls
  another's internal decision logic or can override its scope — it does
  not contradict `TEAM.md`'s RACI, where one Governance Agent (e.g.
  Backend Architect) is Accountable for the *development outcome* of
  several Pipeline Agents' code. That is a development-time
  responsibility over an artifact, not runtime ownership of another
  agent's authority — the same distinction `TEAM.md` §4 already draws
  between "architecture" and "implementation."
- Authority never overlaps — the single-Accountable-per-responsibility
  rule already practiced in every RACI row and every ADR's Owner line.
- **No self-modifying governance.** No agent may change the rules that
  govern agents (this ADR, `TEAM.md`, or any agent's own governing ADR)
  as a side effect of its own operation. This is distinct from `ADR-019`'s
  self-evolution: that ADR's self-modification is scoped entirely to the
  Research Agent's own research methodology inside its isolated sandbox
  — it never touches an ADR, a RACI row, or any permission this ADR
  defines. The two are not in tension; they operate at different layers
  (research-process tuning vs. governance-rule authorship).
- No autonomous architecture changes — restated from `ADR-001`'s
  Resolution and `CLAUDE.md` §1.10.

---

# 14. Acceptance criteria

ADR-014 is acceptable only if it guarantees:

- ✓ Every agent classified (§3).
- ✓ Every authority documented (§4) — by pointing to each agent's own
  existing ADR/RACI row, not by restating it.
- ✓ Every permission defined (§5), with no implicit grants.
- ✓ Every boundary enforced (§6, §12).
- ✓ Human approval documented (§7) and structurally distinct from any
  agent's own action (Hard Rules, §12's enforcement test).

---

# 15. Reference material — ideas only, not authority

- **`TEAM.md`** — the existing, operational implementation of this
  ADR's Governance Agent class. Its RACI matrix (§5), workflow-by-
  activity table (§2), mandatory-reviewer routing (§3), de-duplication
  rules (§4), and standing "do not add an 11th agent" precedent (§6) are
  the direct source of this ADR's Change Management (§9) and Permissions
  (§5) sections — restated at a governing-ADR level, not superseded.
  `TEAM.md` remains the operational document; this ADR is its
  architectural backing.
- **Every prior ADR in this session** (`ADR-001` through `ADR-013`,
  `ADR-015`, `ADR-016`, `ADR-019`) — each one's own Owner/Reviewed-by/
  Accepted-By header, Hard Rules, and "shall never" table is the direct
  source of this ADR's classification and permission model; none of
  their content is authoritative *over* this ADR or vice versa — this
  ADR classifies what they already established.
- No legacy Titan Protocol implementation defines any multi-agent governance
  concept — this is designed entirely from first principles, consistent
  with every infrastructure-layer ADR this session (`ADR-008`, `ADR-009`,
  `ADR-011`, `ADR-012`, `ADR-013`) having found no reference-material
  precedent to mine.

---

Per `ADR-001` and `CLAUDE.md` §1.10, **no implementation begins until this
ADR's Status changes from Proposed to Accepted.**

---

# Amendment 1 — Research → Plan → Implement (RPI) gated workflow

Amended: 2026-07-05

**Trigger:** a Council review of an external Claude Code development-
practices reference (`shanraisshan/claude-code-best-practice`) found one
genuinely reusable idea — a named, artifact-producing Research → Plan →
Implement gate — worth adopting. The source repository's own agent
roster (`product-manager`, `ux-designer`, `requirement-parser`, etc.) was
evaluated and rejected: it is built for general product features, not a
trading system, and every one of its roles either has no Titan Protocol
equivalent worth adding or duplicates a `TEAM.md` role that already
exists. Per `TEAM.md` §6's binding "do not add an 11th agent without
demonstrating a clear, measurable benefit" precedent (restated as this
ADR's own binding standard for Governance Agents, §9), **no new agent is
added.** This Amendment adopts only the phase-gate *pattern*, mapped
entirely onto the ten Governance Agents already classified in §3.

**This Amendment grants no new authority, permission, or agent.** It is
purely a formalization of process already required by `CLAUDE.md` §4 and
already practiced by `TEAM.md` §2's existing per-activity workflows — it
makes the "Plan" step of those workflows produce a durable, on-disk
artifact instead of an implicit, undocumented one, and it names a fixed
location for that artifact. Nothing in §3 (Agent classes), §5
(Permissions), or §6 (Forbidden actions) changes.

**The three phases, each performed by an existing Governance Agent
already assigned that lane:**

- **Research** — the RACI Accountable/Consulted architect(s) for the
  touched component (`TEAM.md` §5's existing rows), same as `CLAUDE.md`
  §4's existing "Before" steps 1–4 (read affected files/dependencies,
  check against `ADR-001`'s pipeline, confirm the stage's ADR is
  Accepted, identify duplicate logic/regressions) — now written down as
  a short Research note rather than performed silently.
- **Plan** — Software Architect (cross-module/new-engine changes) or
  Backend Architect (contained changes), exactly `TEAM.md` §2's existing
  "Feature development" step 1/§3's existing "new engine, or any change
  crossing package boundaries" trigger — now required to leave a written
  Plan artifact (approach, architectural-compliance confirmation, a
  circular-dependency check, files to be touched) before Minimal Change
  Engineer begins, rather than only being stated in conversation.
- **Implement** — Minimal Change Engineer, unchanged (`TEAM.md` §7 — the
  sole implementer on every row already).

Followed, unchanged, by the existing validation gate: Code Reviewer +
Test Results Analyzer + any mandatory reviewer `TEAM.md` §3's routing
table already names for the touched path.

**Mandatory only when `TEAM.md` §3 already requires Software Architect**
(new engine, or a change crossing package boundaries) **— optional for
everything else** (a contained bug fix, refactor, or performance change
already covered by `TEAM.md` §2's lighter-weight workflows). This
distinction is deliberate: making every change, however small, produce
a Research/Plan artifact would contradict the Minimal Change Engineer
philosophy (`TEAM.md` §7, `CLAUDE.md` §6) this Amendment is not
permitted to weaken.

**Practical detail — artifact location, the circular-dependency check
recipe, and the changelog convention — lives in `TEAM.md` §9**, per this
ADR's own established division of labor (`TEAM.md` is the operational
document; this ADR is its architectural backing, §15).

This Amendment does not reopen ADR-014's Accepted status and changes no
prior section's text.

---

# Amendment 2 — Three new Governance Agents; SRE's lane extended

Amended: 2026-07-06

**Trigger:** a distinct, human-initiated instruction to extend the
Council (per this ADR's own §9 Change Management standard for a
Governance Agent addition — "the precedent `TEAM.md` §6 already set...
is the binding standard, not a new one invented here"). Four roles were
requested; three genuinely fill a capability gap without overlapping an
existing role (§3's classification test below); one duplicates an
existing role and is folded into it instead, per this ADR's own Hard
Rule that "no agent may be added without demonstrating a clear,
measurable benefit... without overlapping existing roles."

**This Amendment grants no new authority to any *existing* agent and
takes none away.** It adds three new Governance Agents to the class
already defined in §3 (extending that class's membership from ten named
roles to thirteen, without altering §3's original table text — the
original ten-agent list above remains the historical record of what was
Accepted then; this Amendment is the dated extension, following exactly
the pattern Amendment 1 already established for adding the RPI
workflow), and it extends one existing agent's (SRE's) already-granted
lane to explicitly name duties that were always implicitly within
"Watchdog function... incident response" (`TEAM.md` §1) but had not been
enumerated.

## New Governance Agents

### Quant Validation Engineer
- **Fills:** statistical strategy-edge validation (walk-forward analysis,
  Monte Carlo analysis, overfitting detection, parameter robustness,
  risk-adjusted performance validation) — a gap this file's own §6
  (`TEAM.md`) explicitly identified and, at the time, declined to fill
  with a new agent. That recommendation is **not overruled**; the
  candidate it evaluated (a generic equity/VC research agent) remains
  correctly rejected. This Amendment adds a differently, more narrowly
  scoped role, on the explicit-instruction standard §9 requires — see
  `TEAM.md` §6's own inline resolution note for the full reasoning.
- **Authority:** Advisory only. **Never modifies strategy, scoring, or
  risk code directly** — a Governance Agent that proposes, exactly like
  every other Council role (§3's classification: "governs the
  *development process*... never a live trading decision").
- **Mandatory review trigger:** any change to statistical logic in
  Strategy Engine, Scoring Engine, or Replay & Certification Engine
  (`ADR-018`, when built) — per `TEAM.md` §3's updated routing table.
  Advisory; never blocks a merge alone (mirrors Test Results Analyzer's
  own non-blocking-alone standing where it isn't the Accountable party).
- **RACI:** Consulted on Strategy Engine, Scoring Engine, and Testing
  rows (`TEAM.md` §5); never Accountable or Responsible for any component
  — it has no authority over what those stages already own.
- **De-duplication from Test Results Analyzer:** Test Results Analyzer
  validates *code* regression (`validate.py` still passing); Quant
  Validation Engineer validates *strategy-edge* statistics (does the
  edge survive out-of-sample testing). Two-tier, the same shape as
  Security Architect/AppSec Engineer (§4's original split).

### Integration Engineer
- **Fills:** post-hoc verification that the *already-built* system
  matches its documented architecture — interface compatibility,
  dependency/circular-import checks, end-to-end pipeline verification.
  No existing role owns this: Software Architect's mandate (§1, "Cross-
  module design, dependency direction, ADRs") is forward-looking/
  design-time; nothing in the original ten verifies the built result
  stays consistent with that design over time.
- **Authority:** Verification and reporting only. **Never designs new
  architecture and never fixes a detected violation itself** — a finding
  routes to whichever agent already owns the affected component (§5's
  existing RACI grants, unchanged).
- **Mandatory review trigger:** identical to Software Architect's
  existing trigger (`TEAM.md` §3) — "new engine, or any change crossing
  package boundaries" — added as a second, verification-time name on
  that same row, never a replacement for Software Architect's design-
  time sign-off.
- **RACI:** Consulted or Informed on every pipeline-stage row it now
  verifies (`TEAM.md` §5, updated); owns `scripts/check_architecture.py`
  and the RPI workflow's Research-phase circular-dependency check
  (`TEAM.md` §9).
- **De-duplication from Software Architect:** the same design-time/
  verification-time split §4 already established for Security Architect/
  AppSec Engineer, applied to architecture instead of security.

### AI Systems Engineer
- **Fills:** AI-adjacent features with no current owner — trade memory,
  AI trade journal, explainable decisions, outcome analytics, natural-
  language dashboard views, research assistant. Multi-Agent Systems
  Architect's own lane "stops at the strategy layer" (`TEAM.md` §4); none
  of the original ten roles cover an AI/LLM-integration feature class.
- **Authority — the narrowest of the three, restated verbatim from its
  own agent file's Absolute Boundary:** AI Systems Engineer **may never**
  generate a live trade, a candidate, a score, a risk decision, a
  compliance verdict, an execution decision, a broker order, or a
  position-management action, and **may never** override, modify,
  bypass, or influence — directly or indirectly — the output of Scanner,
  Strategy Engine, Risk Engine, Compliance Engine, Execution Validator,
  MT5 Bridge, or Position Manager. This is the same absolute boundary §6
  (Forbidden actions) and the Advisory/Research Agent classes (§3)
  already establish for `ADR-016`/`ADR-019` — AI Systems Engineer is
  classified alongside them for this purpose, not granted any authority
  those classes don't already lack.
- **Mandatory review trigger:** any AI-adjacent feature (`TEAM.md` §3's
  updated routing table), plus Security Architect if the feature touches
  account-sensitive data (mirroring the Dashboard row's existing
  standard, `TEAM.md` §5).
- **RACI:** Consulted or Informed on Analytics, AI News Intelligence,
  and Dashboard rows only (`TEAM.md` §5, updated) — never Accountable or
  Responsible for any pipeline or infrastructure component.

## Extended existing agent: SRE

**"Reliability Engineer (SRE)" was requested as a fourth new agent and is
not added as one.** Its requested responsibilities — runtime reliability,
Watchdog review, recovery validation, chaos testing, restart validation,
service resilience, infrastructure health — are SRE's own existing lane
(`TEAM.md` §1: "Watchdog function... incident response") almost exactly.
Adding a second agent for the same lane would violate this Amendment's
own no-overlap standard and `TEAM.md` §4's existing "SRE is operational,
not correctness" de-duplication rule. **Resolution:** `TEAM.md` §1's
roster entry and §4's de-duplication bullet are extended in place to
name these duties explicitly; no new agent file exists for this request,
and SRE's Accountable/Responsible grants (`TEAM.md` §5) are unchanged.

## Acceptance confirmation

- ✓ Every new agent classified within an existing `ADR-014` §3 class
  (Governance Agents) — no new class invented.
- ✓ Every new agent's authority documented by pointing to `TEAM.md`'s own
  roster/RACI/routing-table entries (§4's "Ownership documentation"
  requirement) — not restated ad hoc here beyond the summary above.
- ✓ No implicit permission granted — AI Systems Engineer's boundary in
  particular is stated as an absolute list, not an inferred scope (§5).
- ✓ No existing agent's authority modified or reduced (Hard Rules — "no
  agent may modify another agent's authority" was honored: SRE's own
  extension was a human instruction acting through this Amendment, not
  another agent editing SRE unilaterally).
- ✓ One unique owner responsibility per new role — none of the three
  duplicates an existing Accountable grant (`TEAM.md` §5 unchanged for
  every pre-existing row's Accountable column).

This Amendment does not reopen ADR-014's Accepted status, does not
modify Amendment 1, and changes no prior section's text.
