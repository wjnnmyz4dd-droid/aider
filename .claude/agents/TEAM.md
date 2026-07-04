# Phantom Engineering Council

Permanent governance charter for the 10 approved specialist agents installed
in this directory. Sourced verbatim (unmodified prompts) from
[agency-agents](https://github.com/msitarzewski/agency-agents). No other
agent may be added without demonstrating a clear, measurable benefit to a
Python-based institutional algorithmic trading system (see §6).

Architecture priority order (unchanged, from project instructions):
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

R = Responsible (does the work) · A = Accountable (owns the outcome, single
per row by design) · C = Consulted · I = Informed.

Responsible is Minimal Change Engineer on every row by design (§7 — the
Minimal Change philosophy is the default implementation mode everywhere),
except Testing, where the testing agents *are* the doers.

| Component | R | A | C | I |
|---|---|---|---|---|
| **Scanner** (`scanner.py`) | Minimal Change Engineer | Software Architect | Multi-Agent Systems Architect, Backend Architect | SRE, Test Results Analyzer |
| **Scorer** (`scorer.py`) | Minimal Change Engineer | Software Architect | Multi-Agent Systems Architect, Test Results Analyzer | Code Reviewer, SRE |
| **Strategy Orchestrator** (`strategies/`) | Minimal Change Engineer | Multi-Agent Systems Architect | Software Architect, Test Results Analyzer | Code Reviewer, Backend Architect |
| **Risk Engine** (`risk.py`) | Minimal Change Engineer | Backend Architect | Software Architect, Security Architect, Test Results Analyzer | SRE, Code Reviewer |
| **Compliance** (`ComplianceEngine`, `guards.py`) | Minimal Change Engineer | Security Architect | Backend Architect, AppSec Engineer, Test Results Analyzer | SRE, Software Architect |
| **MT5 Bridge** *(not present in this repo)* | Minimal Change Engineer | Backend Architect | Security Architect, SRE | Software Architect |
| **Execution** *(not present — `TradeRouter` is advisory sizing only, never executes)* | Minimal Change Engineer | Backend Architect | **Security Architect (mandatory gate, not just C — highest blast-radius component in the system)**, Software Architect, AppSec Engineer | SRE, everyone |
| **Watchdog** *(not present as source; conceptually SRE's lane)* | Minimal Change Engineer | SRE | Backend Architect, Security Architect | Software Architect |
| **API** (`api.py`) | Minimal Change Engineer | Backend Architect | Security Architect, AppSec Engineer, API Tester | SRE, Software Architect |
| **Dashboard** *(not present — `/metrics` and `/strategies/performance` exist as data feeds, no UI)* | Minimal Change Engineer | Backend Architect | SRE (what to surface for alerting) | Software Architect |
| **Testing** (`validate.py`, `tests/`) | Test Results Analyzer, API Tester | Software Architect | Minimal Change Engineer, Code Reviewer | SRE, Security Architect |

**Read the parenthetical notes literally.** MT5 Bridge, Execution, Watchdog,
and Dashboard have no source code in this repository today (confirmed by
filesystem search in the earlier architecture review) — this RACI is
aspirational for when/if they're built, not a description of existing code.
Execution in particular should not be built without a dedicated Security
Architect threat-model pass *before* any implementation, given it would be
the single highest-risk addition to the system.

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
- **Two parallel scoring/compliance authorities.** `phantom/` (modular,
  stdlib-only, never executes) and `phantom_institutional.py` (10k-line
  monolith with its own ML classifier, risk sizing, and compliance gate via
  `phantom_command_center.py`) both implement independent scoring and
  compliance logic. If both were ever wired to the same MT5 EA
  simultaneously, there would be two authorities capable of disagreeing on
  whether a trade is compliant — unacceptable for a prop-firm system where
  a single, unambiguous kill-switch is the whole point. **Owner: Software
  Architect** — this needs an explicit decision (which system is
  authoritative in production) recorded as an ADR, not left implicit.
  `AUDIT.md`'s own archive policy already gestures at this; it has not been
  resolved.
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

**Priority order for working this backlog**, per the Council's own
Risk-Engine-first architecture ordering: (1) the two-authority question
under Conflicting Responsibilities, since it's Risk/Compliance-adjacent;
(2) the `analytics.STRATEGIES` crash risk under Missing Safety; (3) the
account-feed observability gap; (4) the `swing_points`/`exposure()`
duplication cleanup; (5) everything marked "low priority" above.
