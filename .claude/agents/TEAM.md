# Phantom Engineering Council

Permanent governance charter for the 10 approved specialist agents installed
in this directory. Sourced verbatim (unmodified prompts) from
[agency-agents](https://github.com/msitarzewski/agency-agents). No other
agent may be added without demonstrating a clear, measurable benefit to a
Python-based institutional algorithmic trading system (see §6).

**Status note (updated 2026-07-04, documentation synchronization pass):**
`docs/adr/ADR-001-single-authority-architecture.md` is Accepted and
supersedes the priority order below wherever the two conflict. `phantom/`
and `phantom_institutional.py` are reference-only — mined for proven
algorithms and safety mechanisms, neither is the permanent authority. The
roster, workflow, and RACI in this file govern how the Council operates
and how reference material is reviewed; the actual target pipeline is
ADR-001's: **Market Data → Scanner → Strategy Engine → Scoring Engine →
Risk Engine → Compliance Engine → Execution Validator → MT5 Bridge →
Position Manager → Analytics**, defined stage-by-stage in ADR-002 through
ADR-010. `CLAUDE.md` §2 has already been reconciled with ADR-001 (it
states the same pipeline as authoritative).

**Per-stage ADR status, as of this pass — the full core pipeline
(ADR-002 through ADR-010) is now Accepted, stage by stage:**

| Stage | ADR | Status |
|---|---|---|
| Architecture | ADR-001 | Accepted |
| Scanner | ADR-002 (+ Amendment 1) | Accepted |
| Strategy Engine | ADR-003 | Accepted |
| Scoring Engine | ADR-004 | Accepted |
| Risk Engine | ADR-005 | Accepted |
| Compliance Engine | ADR-006 | Accepted |
| Execution Validator | ADR-007 | Accepted |
| MT5 Bridge | ADR-008 (+ Amendment 1) | Accepted |
| Position Manager | ADR-009 | Accepted |
| Analytics & Decision Provenance | ADR-010 | Accepted |
| AI News Intelligence | ADR-016 | Accepted (side-ADR, not a pipeline stage) |

§5's RACI table below is updated to name and reflect all ten pipeline
stages plus AI News. Every stage's ADR is now Accepted; per-stage
**implementation** still remains gated on `CLAUDE.md` §1.10 separately
from a stage's ADR being Accepted — Accepted is a precondition for code,
not code itself. No implementation exists for any pipeline stage as of
this pass.

Architecture priority order (original, from project instructions, now
superseded by ADR-001 above where they conflict):
**Risk Engine → Execution Safety → MT5 Bridge → Watchdog → Scanner → Scorer
→ Analytics → Dashboard.**

---

## 1. Roster — one responsibility each

| # | Agent (file) | Invocation name | Single clear responsibility |
|---|---|---|---|
| 1 | `engineering-software-architect.md` | Software Architect | Cross-module design, dependency direction, ADRs |
| 2 | `engineering-backend-architect.md` | Backend Architect | API/data contracts, reliability patterns, migrations |
| 3 | `engineering-code-reviewer.md` | Code Reviewer | Final correctness/maintainability pass on every diff |
| 4 | `engineering-minimal-change-engineer.md` | Minimal Change Engineer | Implements the smallest correct diff |
| 5 | `engineering-multi-agent-systems-architect.md` | Multi-Agent Systems Architect | Strategy layer (`phantom/strategies/`) as a distributed system |
| 6 | `engineering-sre.md` | SRE | Watchdog function: SLOs, alerting, incident response |
| 7 | `security-architect.md` | Security Architect | Threat models / trust boundaries (design-time) |
| 8 | `security-appsec-engineer.md` | Application Security Engineer | Secure code review / CVE scanning (diff-time) |
| 9 | `testing-api-tester.md` | API Tester | Behavioral validation of `phantom/api.py` routes |
| 10 | `testing-test-results-analyzer.md` | Test Results Analyzer | Statistical read on `validate.py` / regression risk |

No responsibility appears twice. Where two agents look adjacent (the two
architects, the two security agents, the two testers), §4 states exactly
which one acts and when — see "De-duplication" below.

---

## 2. Workflow order by activity

Agents listed only when their lane is actually touched; skipping an
irrelevant agent is correct behavior, not a shortcut.

**Feature development** (new capability — playbook, engine, endpoint)
1. Software Architect — approach/boundary sign-off (new engine or cross-module change only)
2. Multi-Agent Systems Architect — only if it's a new strategy/playbook
3. Backend Architect — only if it adds/changes an API or data contract
4. Security Architect — only if it opens a new trust boundary or route
5. **Minimal Change Engineer — implements**
6. **Code Reviewer — reviews**
7. Application Security Engineer — only if the diff touches `api.py` / `account.py` / `guards.py` / `trade_router.py`
8. API Tester — only if routes changed
9. **Test Results Analyzer — mandatory `validate.py` regression check**

**Bug fixing**
1. SRE — triage only if surfaced via `/health`, `/metrics`, or an incident
2. The RACI "Accountable" owner for the affected component (§5)
3. **Minimal Change Engineer — smallest fix, no scope creep**
4. **Code Reviewer**
5. **Test Results Analyzer — confirm no drift beyond the fix**

**Refactoring** (no intended behavior change)
1. Software Architect — confirms scope and that it is genuinely behavior-neutral
2. **Minimal Change Engineer — implements** (this activity is its home turf)
3. **Code Reviewer**
4. **Test Results Analyzer — mandatory proof of zero behavior drift** (the "fixtures unchanged" class of check)

**Performance optimization**
1. Whichever architect owns the touched component (§5) — confirms the change cannot alter decision semantics
2. **Minimal Change Engineer — implements**
3. **Code Reviewer**
4. **Test Results Analyzer — mandatory before/after proof that scores/decisions are identical**

**Security review** (a dedicated pass, not tied to a specific feature)
1. Security Architect — refreshes the threat model
2. Application Security Engineer — line-level review of flagged areas
3. **Minimal Change Engineer — implements remediation**
4. **Code Reviewer**
5. **Test Results Analyzer — confirm guard/compliance behavior unchanged except as intended**

**Testing** (extending coverage, not validating one change)
1. Test Results Analyzer — designs statistical/regression coverage
2. API Tester — designs endpoint coverage
3. **Minimal Change Engineer — implements the test code**
4. **Code Reviewer**

**Deployment** (forward-test freeze / release, per `RELEASE.md`)
1. Test Results Analyzer — go/no-go statistical sign-off
2. SRE — uptime/alerting readiness sign-off
3. Security Architect — surface review, only if the attack surface changed since the last freeze
4. Software Architect — final call; enforces the freeze policy (no new features mid-freeze)

---

## 3. Mandatory before any merge

**Always, no exceptions:**
- Minimal Change Engineer (produced the diff)
- Code Reviewer (reviewed it)
- Test Results Analyzer (`validate.py` green, no unexplained score/decision drift)

**Mandatory only when their file-path lane is touched, but non-negotiable when it is** (this is the routing table that keeps the pipeline from running unnecessary reviews):

| Changed path | Additional mandatory reviewer |
|---|---|
| `phantom/api.py`, `phantom/account.py`, `phantom/trade_router.py`, `phantom/guards.py` | Application Security Engineer |
| Any new or changed HTTP route in `phantom/api.py` | API Tester, Security Architect |
| `phantom/strategies/**` | Multi-Agent Systems Architect |
| New engine, or any change crossing package boundaries | Software Architect |
| `/health`, `/metrics`, alerting thresholds, anything watchdog-adjacent | SRE |

A diff touching only, say, `phantom/indicators.py` never triggers Security
Architect, API Tester, or SRE — that is the mechanism for "minimize bugs
without unnecessary review," not an accident.

---

## 4. De-duplication (where two agents look adjacent)

- **Security is two-tier.** Security Architect designs/updates the threat
  model when a surface changes (rare, design-time). Application Security
  Engineer reviews every touching diff against that existing model
  (frequent, diff-time). Neither re-does the other's pass — confirmed by
  Security Architect's own file, which states it "hands code-level SAST/DAST
  and SDLC work to the AppSec Engineer."
- **Architecture is two-tier.** Software Architect owns anything crossing
  module boundaries or changing overall shape. Backend Architect owns the
  concrete contract *inside* an already-decided shape. If a change doesn't
  cross a boundary, skip straight to Backend Architect.
- **Implementation and review never merge into one step.** Minimal Change
  Engineer writes; Code Reviewer reviews. Code Reviewer never rewrites;
  Minimal Change Engineer never self-approves.
- **Multi-Agent Systems Architect's lane stops at the strategy layer.** It
  does not opine on the API or account feed — that's Backend Architect's,
  even though both are "architecture" roles.
- **SRE is operational, not correctness.** It owns uptime/alerting/incident
  process; it does not review code. Its thresholds are an input to Backend
  Architect's reliability design, not a substitute for Code Reviewer/AppSec.
- **Testing splits by lens, not by file.** API Tester owns "does the
  endpoint behave correctly"; Test Results Analyzer owns "is this a
  statistical regression." The same PR can need both without duplication.

---

## 5. RACI matrix — Phantom components

**Scope note (updated 2026-07-04, documentation synchronization pass):**
this matrix names and tracks all ten `ADR-001` pipeline stages (Scanner
through Analytics) plus `ADR-016`'s AI News Intelligence layer,
cross-checked row-by-row against each stage's own ADR "Owner" /
"Reviewed by" declaration where one exists. Legacy module names
(`scanner.py`, `scorer.py`, `strategies/`, etc.) are kept in parentheses
only as a pointer to the reference-only code each stage's ADR mined for
ideas — they are not the stage's authority. **Scoring Engine**, **Risk
Engine**, and **Compliance Engine** are now Accepted (`ADR-004`/`ADR-005`/
`ADR-006`) — see the per-stage status table above.

R = Responsible (does the work) · A = Accountable (owns the outcome, single
per row by design) · C = Consulted · I = Informed.

Responsible is Minimal Change Engineer on every row by design (§7 — the
Minimal Change philosophy is the default implementation mode everywhere),
except Testing, where the testing agents *are* the doers.

| Component | R | A | C | I |
|---|---|---|---|---|
| **Scanner** (`ADR-002`, Accepted; ref. `scanner.py`) | Minimal Change Engineer | Software Architect | Multi-Agent Systems Architect, Backend Architect | SRE, Test Results Analyzer |
| **Strategy Engine** (`ADR-003`, Accepted; ref. `strategies/`) | Minimal Change Engineer | Multi-Agent Systems Architect | Software Architect, Test Results Analyzer | Code Reviewer, Backend Architect |
| **Scoring Engine** (`ADR-004`, Accepted; ref. `scorer.py`) | Minimal Change Engineer | Software Architect | Multi-Agent Systems Architect, Test Results Analyzer | Code Reviewer, SRE |
| **Risk Engine** (`ADR-005`, Accepted; ref. `risk.py`) | Minimal Change Engineer | Backend Architect | Software Architect, Security Architect, Test Results Analyzer | SRE, Code Reviewer |
| **Compliance Engine** (`ADR-006`, Accepted; ref. `ComplianceEngine`, `guards.py`) | Minimal Change Engineer | Security Architect | Backend Architect, **Software Architect** (moved from I — `ADR-006`'s own "Reviewed by" names Software Architect for cross-module boundary sign-off, the same standing every other stage gives that role when named as a reviewer), AppSec Engineer, Test Results Analyzer | SRE |
| **Execution Validator** (`ADR-007`, Accepted) | Minimal Change Engineer | Backend Architect | **Security Architect (mandatory gate, not just C — `ADR-007`'s own "Reviewed by" states this explicitly, not just this table)**, Software Architect, AppSec Engineer | SRE, everyone |
| **MT5 Bridge** (`ADR-008` + Amendment 1, Accepted) | Minimal Change Engineer | Backend Architect | Security Architect, SRE | Software Architect |
| **Position Manager** (`ADR-009`, Accepted) | Minimal Change Engineer | Backend Architect | SRE, Security Architect | Software Architect |
| **Analytics & Decision Provenance** (`ADR-010`, Accepted) | Minimal Change Engineer | Software Architect | Backend Architect, Multi-Agent Systems Architect (strategy attribution must derive from the Strategy Registry, `ADR-003` §3 — not a hand-maintained list, per the now-closed `analytics.STRATEGIES` defect, §8) | Security Architect, SRE |
| **AI News Intelligence** (`ADR-016`, Accepted — side-ADR, not a pipeline stage) | Minimal Change Engineer | Security Architect | Software Architect | Backend Architect, SRE |
| **Watchdog** *(ADR-011, not yet drafted; conceptually SRE's lane)* | Minimal Change Engineer | SRE | Backend Architect, Security Architect | Software Architect |
| **API** (`api.py`) | Minimal Change Engineer | Backend Architect | Security Architect, AppSec Engineer, API Tester | SRE, Software Architect |
| **Dashboard** *(ADR-012, not yet drafted)* | Minimal Change Engineer | Backend Architect | SRE (what to surface for alerting), **Security Architect (added 2026-07-04 — ADR-012's own governance review found account-sensitive data exposure/access-control a design-time trust-boundary question, per §4's two-tier model)** | Software Architect |
| **Testing** (`validate.py`, `tests/`) | Test Results Analyzer, API Tester | Software Architect | Minimal Change Engineer, Code Reviewer | SRE, Security Architect |

**Read the parenthetical notes literally.** Watchdog and Dashboard have no
ADR at all yet (`ADR-011`/`ADR-012` are reserved, undrafted) and no source
code in this repository today — their RACI here is aspirational for
when/if they're drafted and built, not a description of existing code or
existing acceptance. Every other pipeline stage above (Scanner through
Analytics) now has an Accepted ADR but still no implementation, per
`CLAUDE.md` §1.10 (Accepted ADR is a precondition for code, not code
itself). Execution Validator's mandatory Security Architect gate was
already flagged in this table before `ADR-007` existed and has since been
confirmed, not invented, by `ADR-007`'s own "Reviewed by" line.

**Two components named in a review request but out of this table's
current scope, on purpose:**
- **Research** (`ADR-019`, Self-Evolving Market Structure Research Agent)
  — still **Proposed**, not Accepted. Its own governance (research-lab
  isolation, promotion chain, human-approval gates) is fully specified in
  `ADR-019` itself; adding a Council RACI row here before it's Accepted
  would overstate its status. Revisit when `ADR-019` is accepted.
- **Data Pipeline** (`ADR-013`) — not yet drafted at all (unlike Watchdog/
  Dashboard, which at least have reserved ADR numbers and an aspirational
  row here already). Nothing exists yet to reconcile a RACI row against;
  adding one now would be inventing scope this task didn't ask for
  drafting. Flagged in §"Remaining documentation gaps" below instead of
  silently added.

---

## 6. Missing capability — evaluated, not filled with a bad fit

**Gap found:** none of the 10 agents perform *quantitative strategy-edge
validation* — i.e., whether a playbook's win rate / profit factor reflects
a real statistical edge or curve-fitting (walk-forward validation,
out-of-sample confirmation, correcting for testing 5 strategies
simultaneously). Test Results Analyzer validates whether `validate.py`
regressed; it does not validate whether a strategy's edge is real.

**Recommendation: do not add an 11th agent.** The one candidate evaluated
from the source repo (`finance-investment-researcher.md`) is built for
equity/VC fundamental research and needs more translation than it's worth —
installing it would be exactly the kind of speculative addition point 8
below argues against. Instead, close the gap with a lightweight checklist
(minimum sample size before a playbook counts toward `AGGRESSIVE` tier,
walk-forward split before any new playbook ships, explicit note when
comparing 5 strategies simultaneously) owned jointly by **Test Results
Analyzer** (statistical mechanics) and **Software Architect** (whether the
checklist is actually enforced in the merge pipeline). This is simpler than
a new agent and testable the same way everything else here is tested.

---

## 7. Governing rule — Minimal Change Engineer first

Every other agent proposes direction (architecture, security requirements,
strategy design). None of them writes the diff. Minimal Change Engineer is
the sole implementer on every row of §5 except Testing, and its philosophy
— smallest diff, tolerate three similar lines before extracting a fourth,
no defensive code for impossible scenarios, no drive-by refactors inside a
bug-fix PR — is the default constraint on everyone else's recommendations.
An architect's proposal that can't be implemented as a minimal diff gets
split into a separate, explicitly-scoped follow-up rather than expanded
inline.

Ground rules that override any agent's individual recommendation, per
project instructions: never weaken risk management, never introduce score
inflation or duplicate scoring/indicators, preserve backward compatibility
unless explicitly approved, run `validate.py` before and after every
change. Any agent whose recommendation would conflict with these escalates
to the user instead of proceeding.

---

## 8. Architecture audit — standing improvement backlog

Re-derived from the full-repo review already performed this session
(`scanner.py`, `scorer.py`, `orb.py`, `guards.py`, `api.py`, `validate.py`
and dependencies), reframed into the six lenses requested. No code has been
changed — this is the backlog the Council works from, in RACI-assigned
order, not a set of edits already made.

### Duplicate logic
- `ind.swing_points()` is recomputed 4× per scan on identical input —
  `StructureAnalyzer.bos()/.choch()/.liquidity_sweep()` each call it
  independently, and `Scorer._planned_rr()` calls it a 4th time.
  **Owner: Software Architect (approves) → Minimal Change Engineer (dedup) → Test Results Analyzer (proves zero drift).**
- `Guards.exposure()` is called 3× per scan in `scorer.py` — once for the
  Exposure Guard component, then again for LONG and SHORT inside
  `exposure_safe`, one of which duplicates the first call whenever
  `bias != NONE`. Same owner chain as above.
- `phantom/analytics.py`'s `STRATEGIES` tuple is a hand-maintained registry
  that has already drifted from the real 5-strategy roster (see "missing
  safety" below) — a duplicated, divergent source of truth for "what
  strategies exist" when `StrategyOrchestrator.registered_names` already
  computes this correctly. **Owner: Multi-Agent Systems Architect (approves
  deriving from discovery) → Minimal Change Engineer → Test Results
  Analyzer.**

### Conflicting responsibilities
- **Two parallel scoring/compliance authorities — RESOLVED 2026-07-04 by
  `ADR-001`.** `phantom/` (modular, stdlib-only, never executes) and
  `phantom_institutional.py` (10k-line monolith with its own ML classifier,
  risk sizing, and compliance gate via `phantom_command_center.py`) both
  implemented independent scoring and compliance logic — if both were ever
  wired to the same MT5 EA simultaneously, there would have been two
  authorities capable of disagreeing on whether a trade is compliant.
  `ADR-001` resolved this: neither becomes the permanent authority; both
  are retired to reference-only status, and a new single-authority pipeline
  is designed from first principles via ADR-002 onward. No further action
  needed on this item specifically — see the priority-order note below for
  what that changes about the rest of this backlog.
- Three separate places (`Scanner.__init__`, `Scorer.__init__`,
  `PhantomApp.__init__`) each independently re-derive
  `self.orb = self.strategies.orb_engine` as a "backward-compatible
  reference." Not incorrect, but three owners of the same alias is a mild
  smell worth collapsing to one accessor. Low priority.

### Unnecessary complexity
- `phantom_institutional.py` bundles 15 "hedge-fund upgrades" (ML
  classifier, Monte Carlo simulator, sentiment aggregator, multi-account
  orchestrator, latency optimizer) into a single 10,167-line file, in
  parallel with the clean modular `phantom/` package that deliberately
  avoids all of this. This is the largest complexity/maintainability risk
  in the repository. **Owner: Software Architect** — recommend a consolidation
  roadmap decision, not a code change, as the immediate next step.
- `StrategyParams` in `config.py` flattens every playbook's tunables
  (`sweep_*`, `session_*`, `sr_*`, `mom_*`) into one dataclass. Functional
  today at 5 strategies; worth revisiting if a 6th/7th playbook is added.
  Low priority — flagging, not acting.

### Missing safety mechanisms
- Legacy (no-equity) `ComplianceEngine` fallback path has no kill-switch or
  daily-lockout persistence — a drawdown breach doesn't latch and silently
  recovers once the scalar dips back under threshold. **Owner: Security
  Architect (Accountable per RACI for Compliance) decides whether to
  deprecate the fallback or explicitly document it as a degraded mode with
  its own alert.**
- Position/exposure/correlation guard inputs (`open_positions`,
  `position_counts`, `symbol_exposure_pct`) have no staleness check, unlike
  the equity feed's TTL. **Owner: Backend Architect.**
- `analytics.STRATEGIES` omitting `"S&R Bounce"` / `"Momentum Continuation"`
  means `app.record_trade()` raises an uncaught `KeyError` for either
  playbook's live trade feedback — an execution-safety-adjacent crash risk,
  not just an analytics gap. **Owner: Multi-Agent Systems Architect +
  Backend Architect jointly (§4 doesn't have a clean single owner here,
  which is itself worth noting as a minor RACI gap) → Minimal Change
  Engineer fixes by deriving the list from discovery.**

### Missing observability
- No telemetry distinguishes "account feed never connected" from "account
  feed healthy" — both currently read `phantom_account_feed_stale = 0`.
  **Owner: SRE (this is exactly the Watchdog's job) + Backend Architect.**
- No shared `trace_id` across a scan's `log_scan` + `log_orb` + strategy
  detail log lines — Multi-Agent Systems Architect's own installed
  methodology explicitly calls for "structured logs with a shared trace_id
  across the entire pipeline" for exactly this reason. **Owner: SRE +
  Multi-Agent Systems Architect.**
- `StrategyPerformanceTracker._pnl` is an unbounded list recomputed in full
  on every `/metrics` scrape (unlike `RiskIntelligenceEngine`'s properly
  bounded `deque(maxlen=window)`) — a slow-burning observability-cost and
  memory issue as the account ages. **Owner: Backend Architect.**

### Simplification opportunities
- Derive `analytics.STRATEGIES` from `StrategyOrchestrator.registered_names`
  instead of hand-maintaining a tuple — removes a class of bug (this one
  already happened once) rather than just fixing this instance of it.
- Cache `swing_points()` once per scan instead of computing it 4 times —
  simplification and performance improvement in the same change.
- Resolve the `phantom/` vs. `phantom_institutional.py` question explicitly
  (§ Conflicting responsibilities) rather than carrying two systems
  indefinitely — the single highest-leverage simplification available.

**Status of this backlog, updated 2026-07-04 (RACI reconciliation pass).**
The two-authority question (former item 1) is resolved by `ADR-001` — see
above. Per `ADR-001`'s Resolution ("no code will be written until each
pipeline stage has its own accepted ADR"), the remaining items below are
**not** live work items to fix in place inside `phantom/` under the
Council's normal merge pipeline — `phantom/` is reference-only now. They
are retained here as **known defects in the reference material**: things
to deliberately not repeat when each stage ADR mines this code for proven
logic. Re-evaluated against the now-drafted ADRs:

1. **The `analytics.STRATEGIES` crash risk (Missing Safety) — CLOSED at
   the architecture level by `ADR-010` §2/§9 (Accepted).** `ADR-010`
   requires strategy attribution to derive from the Strategy Registry
   (`ADR-003` §3), never a hand-maintained list, explicitly citing this
   defect by name. Remains open only as an implementation task once
   Analytics is actually built.
2. The account-feed observability gap (Missing Observability) — status
   updated only: `ADR-006` (Compliance Engine) is now **Accepted**, not
   Proposed. Whether its text substantively closes this specific
   telemetry gap (distinguishing "never connected" from "healthy") was
   not re-audited in this documentation-only pass — flagged as
   unverified, not claimed resolved. `ADR-011` (Watchdog) remains not yet
   drafted.
3. **The `swing_points()` duplication half (Scanner) — CLOSED at the
   architecture level by `ADR-002` §14/reference material (Accepted).**
   The `Guards.exposure()` duplication half (Compliance) — status updated
   only: `ADR-006` is now **Accepted**; whether its text substantively
   addresses this duplication was not re-audited in this pass, flagged as
   unverified rather than claimed resolved.
4. Everything marked "low priority" above — revisit opportunistically, no
   assigned stage.

---

## 9. Research → Plan → Implement (RPI) — gated workflow (`ADR-014` Amendment 1)

Added 2026-07-05. Formalizes `CLAUDE.md` §4's existing Before/During/After
steps and §2's existing per-activity workflows into three named phases
with a durable, on-disk artifact — **using the existing 10 agents only.
No 11th agent is added** (§6's binding precedent, restated as `ADR-014`
§9's own binding standard). Grants no new authority or permission.

**When it applies.** Mandatory exactly where §3's routing table already
requires Software Architect (new engine, or any change crossing package
boundaries) — optional for everything else (a contained bug fix,
refactor, or performance change already covered by §2's lighter-weight
workflows). A one-line fix to `phantom_pipeline/scanner/config.py` does
not need a Plan artifact; a new pipeline stage does. Over-applying this
gate to trivial changes would contradict §7's Minimal Change Engineer
philosophy, which this section may not weaken.

**Artifact location.** `docs/plans/<slug>.md`, one file per gated change,
using `docs/plans/TEMPLATE.md`'s three sections (Research, Plan,
Validation). The file accumulates across the change's lifecycle — the
same "one document, updated as work proceeds" pattern
`IMPLEMENTATION_PLAN.md`/`VALIDATION_MATRIX.md` already use — it is not
three separate files per change.

**Phase 1 — Research** (the RACI Accountable/Consulted architect(s) for
the touched component, §5, + Minimal Change Engineer):
- Read the affected files and their dependencies (`CLAUDE.md` §4.1).
- Confirm the touched stage's ADR is Accepted, not merely Proposed
  (`CLAUDE.md` §1.10, §4.3).
- Identify duplicate logic and potential regressions (`CLAUDE.md` §4.4).
- Run the circular-dependency/private-state check below and record the
  result.
- Write these findings into `docs/plans/<slug>.md`'s Research section.

**Circular-dependency / private-state check** (run from the repo root):
```
python3 scripts/check_architecture.py
```
Verifies, across every `phantom_pipeline/` package: no import cycle, and
every cross-package import targets only another package's `.models`,
`.trace`, `.registry`, or its `__init__.py` public re-exports — never
another package's `.engine`/`.state_store`/`.config`/`.checks`/
`.metrics`/`.logging_sink`/`.idempotency_store` (the same private-state
boundary the Phase 1 Certification Audit verified manually; this script
makes that check repeatable rather than re-derived by hand each time).

**Phase 2 — Plan** (Software Architect for cross-module/new-engine
changes, per §2's existing "Feature development" step 1 and §3's
existing trigger table; Backend Architect for a contained
single-package change):
- State the approach and its boundaries.
- Confirm architectural compliance against `ADR-001`'s pipeline and the
  touched stage's own ADR (`CLAUDE.md` §4.2–.3).
- List the files to be touched.
- Written into `docs/plans/<slug>.md`'s Plan section **before** Minimal
  Change Engineer begins — this is the one genuinely new requirement
  this Amendment adds: the sign-off `TEAM.md` §2 already required is now
  a saved artifact, not only a stated intention.

**Phase 3 — Implement** (Minimal Change Engineer, unchanged, §7):
implements the smallest correct diff against the approved Plan.

**Unchanged validation gate** (§3, mandatory, no exceptions): Code
Reviewer, Test Results Analyzer (`validate.py` green, full
`unittest discover` green, `compileall` clean), plus any mandatory
reviewer §3's routing table names for the touched path. Record the
validation results in `docs/plans/<slug>.md`'s Validation section —
this is the "final validation report" `CLAUDE.md` §4.8 already requires,
now also saved to the plan file, not only stated in the response.

**Documentation and changelog** — unchanged practice (`IMPLEMENTATION_
PLAN.md`/`VALIDATION_MATRIX.md` updates, exactly as done for every ADR-002
through ADR-013 stage in this repository's history), plus one addition:
update `CHANGELOG.md` at repo root with a dated entry summarizing the
change, per its own header convention. `CHANGELOG.md` starts from
2026-07-05 forward; git history remains the authoritative record of
everything before it — this Amendment does not retroactively fabricate
changelog entries for prior work.

**Static analysis** — `python3 -m compileall phantom_pipeline tests`
remains the existing static check (unchanged). Adding a linter/type
checker (mypy, flake8, or equivalent) is explicitly out of scope here —
it would be new tooling with its own configuration decisions, not a
formalization of something already practiced, and belongs in its own
explicitly-scoped follow-up per §7's "split into a separate, scoped
follow-up rather than expanded inline" rule.
