# Jarvis Evolution Engine — Design Document

> **Status:** Approved design (two-gate model). **Documentation only — not implemented.**
> **Scope:** This subsystem improves **Jarvis only**. It has no read or write path into
> Phantom's code, trading logic, configuration, credentials, or repository.
> **Next step:** Await approval before beginning implementation phase **EVO-0**.

This document extends the OpenJarvis ↔ Phantom integration plan with a new subsystem, the
**Jarvis Evolution Engine**, which lets Jarvis discover, evaluate, propose, test, and (only
with explicit approval) deploy improvements to **itself**.

---

## 0. Hard rules (absolute — cannot be violated)

* Jarvis and Phantom remain separate services.
* Jarvis never imports Phantom code.
* Jarvis communicates with Phantom only through approved read-only HTTP APIs.
* Jarvis must never modify Phantom's trading logic.
* Jarvis must never deploy code directly into Phantom.
* Jarvis must never place, modify, or close trades.
* Every Jarvis self-update requires explicit approval **before** installation.
* Every update must be fully reversible.
* Every update must be audited and logged.
* **Phantom-related modifications are permanently out of scope for the Evolution Engine.**

### Invariant → enforcement (structural, not procedural)

| Hard rule | How it is enforced by construction |
|---|---|
| Separate services / never import Phantom | Evolution Engine runs in Jarvis's process space; the Phantom repo is not a git remote, submodule, or dependency it can reference |
| Read-only HTTP to Phantom only | The Engine holds **no** Phantom credential at all — even the read token belongs to the *monitor* subsystem, not this one |
| Never modify Phantom / deploy into Phantom | Deployment target is pinned to the Jarvis repo path; a **path-scope guard** rejects any changeset whose files resolve outside `jarvis/` |
| Never place/modify/close trades | No trading capability is registered in this subsystem; capability-off by default |
| Approval before install | Two hard human gates; the state machine cannot advance past `AWAITING_GATE_1` or `AWAITING_GATE_2` without a signed, single-use approval token |
| Fully reversible | No transition into `DEPLOYING` is allowed unless a **verified** rollback point exists |
| Audited & logged | Every state transition writes an append-only, hash-chained audit record |
| Never push directly to main | Branch protection + gated merge; `main` is updated only by a human-confirmed (Gate 2) merge |

---

## 1. Architecture document

**Mission.** Let Jarvis get better over time by *discovering* technologies, *evaluating* them,
*proposing* upgrades, *testing* them in an isolated sandbox, and *deploying* only what you
approve — while remaining fully isolated from Phantom and fully reversible.

**Three planes:**

* **Discovery plane** (read-only, outbound to the internet): the Technology Scout. Produces
  candidates. Downloads nothing.
* **Decision plane** (human-in-the-loop): Recommendation Engine → Evolution Proposal → your
  approval. Two gates.
* **Execution plane** (sandbox-first, reversible): Sandbox Installer → Test Harness → Deployer
  → Rollback. Touches only the Jarvis repo, only in staging until Gate 2.

**Design tenets:**

1. **Isolation is structural, not procedural** (see the invariant table above).
2. **Nothing irreversible without a verified rollback point.**
3. **Two gates, both human**: approve-to-test, then approve-to-deploy.
4. **Fail closed**: any rejection, timeout, failed test, failed verification, or missing
   rollback point stops the workflow, restores state, and notifies you.
5. **Every candidate carries provenance** (source URL, commit hash, license, maintainer) end
   to end into the audit log.

---

## 2. Component diagram

```
                         ┌──────────────────────── JARVIS (isolated) ────────────────────────┐
   Internet (read)       │                                                                    │
   GitHub / PyPI ──────► │  ┌───────────────┐   candidates   ┌────────────────────────┐       │
   OpenJarvis rel.       │  │ Technology     │ ─────────────► │ Recommendation Engine   │      │
   Claude Code / MCP     │  │ Scout (cont.)  │                │  scoring + dedupe        │      │
   CVE feeds / SDKs      │  └──────┬────────┘                └──────────┬─────────────┘       │
                         │         │ evaluations                        │ Evolution Proposal   │
                         │         ▼                                     ▼                      │
                         │  ┌───────────────┐              ┌────────────────────────────┐      │
                         │  │ Evolution      │◄────────────►│  GATE 1: approve-to-test    │◄──── you
                         │  │ Engine (state  │  approve/rej │  (AWAITING_GATE_1)          │      │
                         │  │ machine + orch)│              └──────────────┬─────────────┘      │
                         │  └──┬────────┬────┘                             │ approved            │
                         │     │        │ create branch/restore/backup     ▼                     │
                         │     │        ▼                    ┌────────────────────────────┐      │
                         │     │  ┌──────────────┐           │  Sandbox / Staging env      │      │
                         │     │  │ Git + Restore│──────────►│  install candidate here only │      │
                         │     │  │ Point mgr    │           └──────────────┬─────────────┘      │
                         │     │  └──────────────┘                          │ run                 │
                         │     │                              ┌─────────────▼──────────────┐      │
                         │     │                              │ Test Harness: lint, unit,   │      │
                         │     │                              │ integ, regression, perf,    │      │
                         │     │                              │ security, compatibility     │      │
                         │     │                              └─────────────┬──────────────┘      │
                         │     │             all pass │ any fail → abort+restore+notify           │
                         │     │                       ▼                                          │
                         │     │        ┌────────────────────────────┐                            │
                         │     │        │ GATE 2: approve-to-deploy    │◄──────────────────── you  │
                         │     │        │ (AWAITING_GATE_2)            │                            │
                         │     │        └──────────────┬─────────────┘                            │
                         │     │                       ▼ approved                                  │
                         │     │        ┌────────────────────────────┐                            │
                         │     └───────►│ Deployer: merge→main, tag,   │                            │
                         │              │ version, docs, rollback meta │                            │
                         │              └──────────────┬─────────────┘                            │
                         │   ┌──────────────┐          │        ┌───────────────┐                 │
   you ◄─── Notifier ◄───┤   │ Evolution     │◄────────┴───────►│ Evolution      │                 │
   (Telegram/email/push) │   │ Memory (prefs, │  read/write     │ Dashboard      │────► you (view) │
                         │   │ history, RAG)  │                 └───────────────┘                 │
                         │   └──────────────┘                                                     │
                         │  ┌──────────────────────────────────────────────────────────────────┐ │
                         │  │ Append-only, hash-chained AUDIT LOG (every transition + provenance)│ │
                         │  └──────────────────────────────────────────────────────────────────┘ │
                         └────────────────────────────────────────────────────────────────────────┘

   ✗ NO ARROW EXISTS from any box above into Phantom. Phantom is not a target of this subsystem.
```

---

## 3. Evolution Engine design

The Engine is the **orchestrator + approval state machine**. It owns no research logic and no
test logic; it sequences them and enforces the gates. It is modeled on an OpenJarvis
**continuous operative** agent with persistent, resumable state.

Guarantees enforced by the Engine:

* No transition into `TESTING` without a passed **Gate 1** token *and* a created
  `evo/*` branch + verified rollback point + backup.
* No transition into `DEPLOYING` without: all tests `PASS`, a passed **Gate 2** token, a
  **verified** rollback point, and a path-scope check confirming every changed file is under
  `jarvis/`.
* Any exception, rejection, timeout, failed test, failed verification, or missing rollback
  point → stop, restore, notify. The Engine never leaves staging half-installed.
* State persists to disk so a Jarvis restart resumes exactly where it left off.

---

## 4. Technology Scout design (Phase A — continuous research)

A **continuous, research-only** agent. Reads the open internet; downloads nothing; installs
nothing.

**Watchlist sources:** GitHub repositories, OpenJarvis releases, Claude Code updates, MCP
servers, LangGraph, Composio, AI SDKs, Python packages (PyPI), security advisories (CVE/GHSA),
LLM improvements, voice AI, memory systems, coding assistants, debugging tools, productivity
tools, automation frameworks.

**Per-candidate evaluation scorecard (0–100 composite, weighted):**

| Dimension | Signal source | Notes |
|---|---|---|
| Compatibility | Declared deps vs Jarvis lockfile / Python version / OpenJarvis API | **Hard gate** — incompatible ⇒ never proposed |
| Popularity | Stars, downloads, dependents | Momentum, not just size |
| Maintenance | Commit recency, issue/PR turnover, release cadence | Detects abandonware |
| Security | Open CVEs, advisory history, dependency risk | **Hard gate** — unresolved critical CVE ⇒ never proposed |
| License | SPDX identifier vs allowlist | **Hard gate** — non-allowlisted/absent ⇒ never proposed |
| Performance | Benchmarks / claims (verified later in sandbox) | Provisional until sandbox-measured |
| Stability | Release maturity, breaking-change frequency | Pre-1.0 flagged |
| Long-term viability | Backing org, bus factor, roadmap | Qualitative + heuristic |

**Output:** a ranked candidate list with full provenance (URL, latest commit hash, license,
maintainer, score breakdown), written to Evolution Memory and deduped against
already-accepted / already-rejected items. **Nothing is downloaded.**

**Cadence & cost control:** bounded schedule (watchlist sweep daily, security feeds hourly),
respects your remembered notification preferences, and never floods you — candidates below a
memory-tuned threshold are logged, not surfaced.

---

## 5. Update workflow (A→E end to end)

1. **Scout** surfaces a scored candidate (Phase A).
2. **Recommendation Engine** decides if it clears the value + safety threshold; if so it emits
   an **Evolution Proposal** (Phase B).
3. **Gate 1 notification** → you approve or reject. *No candidate code is downloaded,
   installed, or executed until you approve.*
4. On approval: Engine creates **`evo/*` branch + rollback point + backup**, installs the
   candidate **into staging only** (Phase C), and runs the **full test battery**: lint, unit,
   integration, regression, performance benchmark, security scan, compatibility.
5. **Any failure** → abort, restore previous state, notify. Candidate → `TEST_FAILED`.
6. **All pass** → **Gate 2 notification** with complete results → you approve deployment.
7. On approval: **Deployer** merges to production, tags the release, records the version,
   updates documentation, and saves verified rollback metadata (Phase D).
8. **Post-deployment verification** (`VERIFIED`) + notification (Phase E "after"): installed
   version, duration, tests passed, perf/memory/CPU deltas, rollback status → `COMPLETE`.
9. Outcome (accepted/rejected/failed/perf history) written to **Evolution Memory**.

### Example Evolution Proposal (Gate 1 payload)

```
Jarvis Evolution Proposal #58

Repository:      OpenJarvis
Feature:         Persistent semantic memory

Benefits         • Faster retrieval  • Better long-term memory  • Lower RAM usage
Compatibility    OpenJarvis: PASS   Phantom Integration: PASS   Dependencies: PASS
Security Scan    PASS
Est. Install     3 minutes
Rollback         Available

Awaiting User Approval  (no code changes occur before approval)
```

---

## 6. Approval workflow — the two-gate model (approved)

**Two mandatory human gates. Neither can be bypassed, auto-approved, or defaulted.**

### Gate 1 — Approve to Test

* Jarvis sends the complete upgrade proposal (feature, source repo, benefits, risks,
  dependencies, test plan, rollback availability).
* **No candidate code is downloaded, installed, or executed until you approve.**
* After approval, the Engine creates a dedicated `evo/*` branch and tests **only** in an
  isolated staging environment.

### Gate 2 — Approve to Deploy

* After all tests and benchmarks pass, Jarvis sends you the **complete results**.
* Jarvis must wait for your **second explicit approval** before merging or deploying.
* **No automatic merge to `main`.**

**Token properties:** each approval mints a **single-use, candidate-and-version-bound,
expiring** token that the Engine must present to advance. A Gate-1 approval can never be
replayed for a different candidate or version; a failed-test candidate can never reach Gate 2.
Every token issuance and use is audit-logged.

---

## 7. Rollback workflow

**Reversibility is a precondition, not an afterthought — deployment is blocked unless rollback
is proven possible first.**

Before install (Phase C), the Engine creates three independent restore layers:

1. **Git restore point** — tagged commit of the current known-good Jarvis
   (`pre-evo-<proposal-id>`).
2. **Environment backup** — snapshot of the venv/lockfile + config + memory store.
3. **Rollback metadata** — exact commands + hashes to return to the known-good state,
   **verified by a dry-run before deployment is permitted.**

**Triggers:** any test failure (auto), any deployment or verification error (auto), or your
manual "roll back" from the dashboard/notification (on-demand, even post-deploy).

**On rollback:** restore git + environment, run a Jarvis self-check, mark the candidate
`ROLLED_BACK` (terminal), write the reason and outcome to memory + audit, and notify you.
Phantom is never involved in any rollback path.

---

## 8. Security model

**Isolation (enforced structurally):** Phantom repo, credentials, and write endpoints are
absent from this subsystem. A **path-scope guard** rejects any changeset touching files
outside `jarvis/`, closing the "never deploy into Phantom" rule by construction.

**Supply-chain safety:**

* License allowlist (hard gate) + SPDX capture.
* Security scan at two points: Scout (advisory triage) and Sandbox (dependency + SAST scan on
  the actual pinned artifact).
* **Pinned by hash** — the artifact tested is byte-for-byte the artifact deployed (no floating
  tags between test and deploy).
* **No unverified code** reaches production: `DEPLOYING` requires a passed security scan on the
  exact staged artifact.

**Least privilege:** the Engine's deploy credential can write only the Jarvis repo `main` via
the gated merge; it holds no Phantom token, no trading capability, and no ability to reach any
Phantom endpoint.

**Auditability:** append-only, **hash-chained** audit log — each record links the previous
record's hash, so tampering is detectable. Every transition, gate token, provenance record,
test result, and rollback is logged.

### Capability matrix

| Jarvis MAY | Jarvis MAY NEVER |
|---|---|
| Research, recommend, benchmark, test, explain, notify | Modify Phantom automatically |
| Install into staging after Gate 1 | Change trading logic |
| Merge to `main` after Gate 2 | Access Phantom write endpoints |
| Roll back on demand | Push directly to `main` |
| | Install unverified code |
| | Bypass approval / ignore failed tests / skip rollback creation |

---

## 9. Git workflow (hard rules)

```
main (PROTECTED: no direct push; updated only by a Gate-2 human-confirmed merge)
 │
 ├─ tag: pre-evo-<id>        ← rollback point created & verified before staging
 │
 └─ branch: evo/<id>-<slug>  ← candidate installed & tested HERE (staging only)
        │  lint / unit / integ / regression / perf / security / compat run on this branch
        │
        ▼ (only if ALL pass AND Gate 2 approved)
     merge → main → tag release vX.Y.Z → record version → update docs → save rollback metadata
```

Applied hard Git rules:

* **Protect `main`.**
* **No direct pushes to `main`.**
* **Merge only through the gated evolution workflow.**
* **Every candidate receives its own `evo/*` branch.**
* **Failed branches are retained or archived for audit** (never merged).
* **Every production upgrade receives a release tag and a recorded version.**
* **Rollback metadata must be verified before deployment.**
* **The Phantom repository must not be configured as a remote, dependency, credential target,
  writable path, or deployment target.**

All of the above happens in the **Jarvis** repository only.

---

## 10. Memory model (continuous learning)

**Jarvis-only persistent memory** (OpenJarvis operative memory + a structured store). It never
reads from or writes to Phantom.

**Retained:**

* Accepted upgrades and rejected upgrades (with your stated reasons where given).
* Your preferred coding style and architecture.
* Your preferred notification frequency / verbosity.
* Successful vs failed upgrades; per-candidate outcomes.
* Performance history (perf / memory / CPU deltas over time).

**How it feeds the loop:**

* The Recommendation Engine down-ranks classes of tools you repeatedly reject and up-ranks
  patterns you accept.
* The Scout tunes surfacing thresholds and cadence to your notification preferences.
* Proposals are phrased to match your preferred style and architecture.

**Isolation:** a write-guard prevents any memory record from targeting Phantom state. This
memory influences **only** future Jarvis proposals.

---

## 11. Notification workflow

Uses the alert channel chosen for the monitor subsystem (Telegram / email / Jarvis push — TBD
from the integration plan).

**Defaults (recorded):**

* Routine scans with nothing important found **remain silent**.
* **Notify before testing** (Gate 1): feature name, source repository, benefits, risks,
  dependencies, test plan, rollback availability → **wait for approval.**
* **Notify again before deployment** (Gate 2): complete test + benchmark results, measured
  perf/resource deltas → **wait for approval.**
* **Notify after successful deployment**: installed version, duration, tests passed,
  performance change, memory change, CPU change, rollback status.
* **Notify immediately after any failure or rollback**: what failed, that state was restored,
  and current health.

Frequency and verbosity are governed by your remembered preferences.

---

## 12. Approval-state machine

```
DISCOVERED
    │
    ▼
PROPOSED
    │
    ▼
AWAITING_GATE_1 ──(reject / timeout)────────────────► STOPPED
    │ approve
    ▼
APPROVED_FOR_TEST ──(no rollback point)─────────────► STOPPED
    │ branch + verified rollback + backup created
    ▼
TESTING
    ├──(any test fails)──► TEST_FAILED ──► abort + restore + notify ──► STOPPED
    │ all pass
    ▼
AWAITING_GATE_2 ──(reject / timeout)────────────────► STOPPED
    │ approve
    ▼
APPROVED_FOR_DEPLOY ──(rollback metadata unverified)─► STOPPED
    │ verified
    ▼
DEPLOYING ──(merge / tag error)─────────────────────► restore + notify ──► STOPPED
    │
    ▼
VERIFIED ──(post-deploy self-check fails)───────────► rollback + notify ──► STOPPED
    │
    ▼
COMPLETE
```

**Any rejection, timeout, failed test, failed verification, or missing rollback point stops the
workflow** (terminal `STOPPED`), restores the prior state where applicable, and notifies you.

---

## Evolution Dashboard

A read-only, Jarvis-side view:

| Panel | Content |
|---|---|
| Current Version | Running Jarvis version + last-deployed timestamp |
| Available Updates | Scout candidates above threshold |
| Pending Proposals | Awaiting Gate 1 / Gate 2 |
| Installed Features | What's live + when + version |
| Rollback Points | Restore tags + verified/available status |
| Performance History | perf / memory / CPU trend across upgrades |
| Resource Usage | Current Jarvis footprint |
| Security Status | Open advisories affecting installed dependencies |
| Technology Watchlist | Sources tracked + last sweep time |
| Repository Health | Maintenance/activity signals per watched repo |
| Upgrade Timeline | Chronological accepted / rejected / rolled-back log |

---

## Implementation roadmap

*Sequenced after the base integration plan's Phase 1 (read-only Phantom monitoring) is live.
No code is written until you approve **EVO-0**.*

* **EVO-0 — Foundations:** confirm the OpenJarvis custom-skill/agent authoring path; stand up
  the hash-chained audit log + Evolution Memory schema; define the path-scope guard and branch
  protection on the Jarvis repo. *Deliverable: skeletons + policies, no functional upgrades.*
* **EVO-1 — Technology Scout (read-only):** continuous research + scorecard + provenance +
  dedupe. Surfaces candidates to memory/dashboard only. Downloads nothing.
* **EVO-2 — Recommendation Engine + Evolution Proposal + Gate 1:** proposals in the format
  above; wire the approve-to-test gate + notifications. Still no installs.
* **EVO-3 — Sandbox + Test Harness + Rollback:** branch/rollback/backup creation, staging
  install, full test battery, auto-abort + restore on failure. Everything stays in staging.
* **EVO-4 — Deployer + Gate 2 + Git release flow:** gated merge to `main`, tag/version/docs/
  rollback metadata, post-deploy notification. First approved self-upgrade possible here.
* **EVO-5 — Evolution Dashboard.**
* **EVO-6 — Continuous learning tuning:** feed accept/reject/perf history back into scoring,
  cadence, and proposal phrasing.

Each EVO phase ends with a demo + your sign-off before the next begins.

---

## Boundary restatement (the line that matters most)

**The Evolution Engine's write scope is `jarvis/` and nothing else. Phantom is not a git
remote, not a dependency, not a credential, not a writable path, and not a deployment target
for any component in this design.** Improving Jarvis can never, by construction, touch
Phantom's trading logic, code, configuration, or repository.
