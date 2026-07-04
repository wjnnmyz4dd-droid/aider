# Everything Claude Code (ECC) — Engineering Review

Status: Research report only. ECC not installed, cloned, or connected to
anything. No Phantom code or `.claude/agents/` files modified. No code
written.

Owner: Software Architect (per `.claude/agents/TEAM.md` RACI — cross-repo
tooling evaluation is its lane)

Date: 2026-07-04

Source: `github.com/affaan-m/everything-claude-code` ("ECC"), browsed via
raw-content/GitHub fetch. 226k★, 34.6k forks, MIT license, 230+
contributors, v2.0.0 (June 2026), 67 agents / 277 skills / 93 commands /
34 rule sets / 14+ MCP configs across 6+ AI harnesses (Claude Code,
Cursor, Codex, OpenCode, GitHub Copilot, Zed).

---

## What ECC actually is

ECC is not a trading tool, a backtesting tool, or domain-specific software
at all — it's a cross-harness **AI coding-agent configuration platform**:
agents, skills, slash commands, rule files, hooks, and a cross-session
"instinct" learning system, packaged to work identically across Claude
Code, Cursor, Codex, Copilot, and Zed. Its entire value proposition is
generic software-engineering productivity at massive scale (12+ language
ecosystems, dozens of frameworks). This matters for the evaluation below:
almost nothing in ECC is a **KEEP** candidate (verbatim reuse), because
almost nothing in it is Phantom-specific — the honest classification for
the overwhelming majority of ECC is **IGNORE**, with a smaller set of
**ADAPT** candidates where a generic idea is worth reimplementing narrowly
inside Phantom's own governance.

---

## Evaluation by category

For each: problem solved · Python+MT5+institutional fit · ADR-001
conflict · unnecessary complexity · reliability/maintainability/security
impact · classification.

### 1. Agents (67 total)
Solves: delegating scoped subtasks (review, build-fix, language-specific
linting) to focused subagents. **Fit:** poor as a wholesale import —
ECC's roster (planner, architect, code-reviewer, security-reviewer,
python-reviewer, refactor-cleaner, database-reviewer, tdd-guide,
build-error-resolver, etc.) directly overlaps Phantom's existing 10-agent
Council (`TEAM.md` §1), which was deliberately built non-overlapping with
an explicit de-duplication contract (§4). Installing any of these would
either duplicate a Council role or violate `TEAM.md`'s own rule: "No other
agent may be added without demonstrating a clear, measurable benefit...
(see §6)." **ADR-001 conflict:** none directly (ADR-001 governs the
trading pipeline, not tooling), but a second, overlapping agent roster
would conflict with the Council's governance model in `TEAM.md`.
**Complexity:** high if imported wholesale — 67 agents vs. the Council's
deliberately scoped 10. **Verdict: IGNORE** (wholesale). A few individual
agents' *checklists* are worth reading for ideas — see §11 below.

### 2. Skills (277 total)
Solves: reusable, invokable workflow definitions (framework patterns,
domain workflows). **Fit:** almost entirely framework/domain-specific to
stacks Phantom doesn't use (Django, Laravel, Spring Boot, Quarkus,
Next.js, PyTorch, prediction-market/`ito-*` skills for a different market
structure entirely). **ADR-001 conflict:** none directly. **Complexity:**
very high surface area for near-zero applicable coverage. **Verdict:
IGNORE**, with narrow exceptions noted in §11 (verification-loop,
skill-creator's pattern-detection idea, cost-aware-llm-pipeline — as
*ideas*, not the skill files themselves).

### 3. Slash commands (93 + legacy shims)
Solves: quick invocation of common workflows (`/plan`, `/code-review`,
`/security-scan`, `/multi-plan`). **Fit:** some conceptual overlap with
how the Council already operates via `TEAM.md`'s workflow-by-activity
(§2) — but ECC's commands assume ECC's own agent roster and rule set
underneath them, so importing the command without the (rejected) agent
roster achieves nothing. **ADR-001 conflict:** `/multi-execute` and
autonomous-loop-style commands conflict with ADR-001's explicit
sequencing ("no code until each stage has an accepted ADR") if used to
run unsupervised parallel implementation work. **Verdict: IGNORE**
(wholesale); the *idea* of a few (`/update-docs`-style consistency check)
is worth adapting, see §11.

### 4. Rule sets (34, common + language-specific)
Solves: always-on guidelines per language/framework. **Fit:** mixed.
`rules/common/testing.md` mandates strict TDD (red-green-refactor) + a
flat 80% coverage gate — this doesn't map cleanly onto Phantom's actual
testing model (`validate.py`'s statistical/regression/distribution
checks, not per-function coverage percentages), though the underlying
discipline (write the failing check before the fix) is compatible with
Minimal Change Engineer's philosophy. `rules/common/security.md` is a
generic web-app checklist (XSS/CSRF/SQL injection/rate limiting) — mostly
inapplicable (no web frontend), but two of its eight items are directly
relevant and worth cross-checking against Phantom's actual code: **no
hardcoded secrets** and **error messages must not leak sensitive info**.
The second one is not hypothetical — `phantom/api.py`'s exception handler
(`except Exception as exc: self._send(500, {"error": str(exc)})`) returns
raw exception text to the HTTP client, which is exactly the pattern this
rule warns against. `rules/python/fastapi.md` is inapplicable (Phantom's
API is stdlib `http.server`, not FastAPI). `rules/common/git-workflow.md`
(conventional commit types, full-diff PR review) is generic good practice
and low-conflict. **ADR-001 conflict:** none. **Verdict: ADAPT** the
error-leakage and secrets principles (concrete, actionable finding);
**IGNORE** the framework-specific rules; **ADAPT** the git-commit
convention as an optional lightweight habit.

### 5. Memory system (Continuous Learning v2 / "instincts")
Solves: cross-session pattern learning — logs every `PreToolUse`/
`PostToolUse` call to `observations.jsonl`, runs a background Haiku agent
to extract "instincts" (confidence-scored heuristics), and auto-injects
high-confidence instincts into future `SessionStart` context, promoting
them to shared skills once confidence ≥0.8 across 2+ projects. **Fit:**
this is the single most concerning component evaluated. **ADR-001
conflict: yes, in spirit.** ADR-001's entire discipline is "no
implementation until the relevant stage has an Accepted ADR" and Core
Rule 10/§1.9 of `CLAUDE.md` requires asking before changing execution
logic rather than guessing. An auto-promoted "instinct" is, by
construction, an unreviewed heuristic that starts silently influencing
agent behavior once a confidence threshold is crossed — the opposite of
the ADR-gated, human-approved change model Phantom has explicitly chosen.
For a prop-firm-adjacent engineering process, autonomously-learned,
silently-injected behavior change is a real governance risk, not a
convenience. **Security:** also worth noting — it persists prompts, tool
calls, and outcomes (including project git-remote identifiers) to disk
outside `~/.claude`, a broader logging surface than Phantom's own
minimal-logging philosophy. **Verdict: IGNORE** the mechanism as
designed. If any form of cross-session memory is wanted later, it should
be a human-reviewed session-notes habit (which `CLAUDE.md`'s own
change-report requirement — Summary/Files changed/Why/Risks/Validation —
already provides), never an auto-injecting confidence-scored system.

### 6. Planning system (`/plan`, `/multi-plan`, autonomous loops, worktree lifecycle)
Solves: task decomposition and parallel execution across agents/worktrees.
**Fit:** conceptually interesting for independent, already-scoped research
tasks (e.g., researching two candidate approaches in parallel), but
**conflicts with ADR-001** if used for parallel *implementation* work,
since ADR-001's sequencing is deliberately one-stage-at-a-time with a
human-reviewed ADR gate between architecture and code. Autonomous loops
that iterate unsupervised are the opposite of that discipline. **Verdict:
ADAPT narrowly** (parallel *research*, never parallel *unreviewed
implementation*) — see Top 20 item on multi-agent orchestration.

### 7. Architecture patterns
ECC's own "architecture" is a DRY adapter pattern for supporting 6+
incompatible AI-harness config formats from one source tree. **Fit:**
zero — this solves a problem specific to ECC's own cross-harness
packaging, not a software architecture question relevant to Phantom's
pipeline. Phantom's architecture patterns question is answered by
ADR-001 through ADR-014, not by anything in ECC. **Verdict: IGNORE.**

### 8. Code review workflow
`code-reviewer` + language-specific reviewer agents + `/code-review`
command. **Fit:** directly duplicates the Council's existing Code
Reviewer role and its mandatory-before-merge gate (`TEAM.md` §3).
**ADR-001 conflict:** none directly, but installing a second code-review
agent would violate the Council's own de-duplication rule (§4:
"Implementation and review never merge into one step... Code Reviewer
never rewrites"). **Verdict: IGNORE** the agent; the specific
blocker/suggestion/nit severity-tagging convention some ECC review
agents use is a reasonable idea already present in the source
`engineering-code-reviewer.md` file the Council installed, so there's
nothing new to adopt here.

### 9. Security workflow
`security-reviewer` agent + `security.md` rules + **AgentShield**
(a real, useful component: a static pattern-matching scanner for
suspicious hooks, hidden prompt-injection patterns, over-broad
permissions, risky MCP configs, and secret exposure in agent configs —
1,282 rules, 98% test coverage per ECC's own claims, not independently
verified). **Fit:** the `security-reviewer` agent duplicates the
Council's Security Architect/AppSec Engineer split. **AgentShield's
underlying idea, however, is genuinely useful and Phantom-agnostic** — a
periodic scan of `.claude/agents/*.md` and any future hooks for exactly
the classes of risk it targets (prompt injection, over-broad tool
permissions, secret exposure) is a good practice regardless of what
generated it. **ADR-001 conflict:** none. **Verdict: IGNORE** the agent;
**ADAPT** the AgentShield *concept* as an occasional Security Architect
self-audit of `.claude/agents/` (not installing ECC's actual scanner,
which is bundled with the rest of the platform).

### 10. Testing workflow
`tdd-guide` agent, `tdd-workflow`/`verification-loop`/`e2e-testing`
skills, 80%-coverage rule. **Fit:** partially compatible in spirit —
Phantom already has a rigorous, arguably *more* domain-appropriate testing
discipline (`validate.py`'s 13 statistical/regression/distribution
checks, `tests/` unit suite, Test Results Analyzer's mandatory
`validate.py`-green gate). ECC's model is generic-software TDD (write a
failing unit test, make it pass); Phantom's is closer to
regression/behavioral-invariant testing appropriate for a scoring engine.
**ADR-001 conflict:** none — this is complementary territory. **Verdict:
ADAPT** the "write the check before the fix" discipline for **new**
pipeline-stage code (ADR-002 onward), without replacing `validate.py`'s
existing statistical model or imposing a flat coverage percentage that
doesn't fit a decision-engine's actual risk profile.

### 11. Python-specific tooling
`python-reviewer` agent, `python-patterns`/`python-testing` skills,
`rules/python/*.md` (coding-style, fastapi, hooks, patterns, security,
testing). **Fit:** generically reasonable Python quality guidance, but
`fastapi.md` is inapplicable (Phantom's API is stdlib `http.server`) and
the rest substantially overlaps what the Council's Backend Architect/Code
Reviewer/AppSec Engineer already cover for this specific codebase.
**Verdict: IGNORE** the agent and framework-specific rules; **ADAPT** only
the general coding-style/security checklist items as informal
cross-checks, not a new rule file.

### 12. Git workflow
Conventional commit types (`feat/fix/refactor/docs/test/chore/perf/ci`),
full-diff PR review (not just latest commit), test-plan-with-TODOs in PR
descriptions. **Fit:** generic good practice, no conflict with anything
Phantom has established. **Verdict: ADAPT** — a low-cost, optional
convention for future commits; not required by anything currently in
`CLAUDE.md`/`TEAM.md`, but doesn't conflict with either.

### 13. Documentation workflow
`doc-updater`/`docs-lookup` agents, `/update-docs`, `/update-codemaps`.
**Fit:** the underlying need (keep docs consistent with code/architecture
changes) is real and exactly what this session did manually for
`AUDIT.md`/`RELEASE.md`/`README.md` against `ADR-001`. **ADR-001
conflict:** an *autonomous* doc-rewriting agent conflicts with the
Council's human-gated review model — doc changes should go through
Software Architect sign-off the same as any other change, not run
unsupervised. **Verdict: ADAPT** the discipline (check doc/architecture
consistency after every ADR or major change) as a checklist item, not the
autonomous agent.

---

## Top 20 components worth adopting (ideas, not code — nothing here is a verbatim import)

1. **Error-message leakage check** — cross-reference `phantom/api.py`'s
   `except Exception as exc: ... str(exc)` pattern against
   `rules/common/security.md`'s "don't leak sensitive info in errors"
   principle; concrete, actionable finding for whichever future ADR
   governs the API/Execution Validator surface.
2. **Secrets-never-in-code discipline** — reinforce as an explicit AppSec
   Engineer checklist item (already implicit in TEAM.md, worth making
   explicit).
3. **AgentShield-style self-audit** — periodic Security Architect review
   of `.claude/agents/*.md` and any future hooks for prompt-injection
   patterns, over-broad permissions, secret exposure.
4. **"Write the check before the fix" discipline** — apply to **new**
   pipeline-stage code from ADR-002 onward, alongside (not replacing)
   `validate.py`'s statistical model.
5. **Conventional commit type prefixes** — optional, low-cost habit for
   future commits.
6. **Full-diff PR review habit** (review entire commit range, not just
   HEAD) — already effectively how this session's commits were reviewed;
   worth stating explicitly for future contributors.
7. **Test-plan-with-TODOs in PR/commit descriptions** — cheap, useful
   convention.
8. **Doc/architecture consistency check as a recurring habit** — formalize
   what this session already did for `AUDIT.md`/`RELEASE.md`/`README.md`:
   after any ADR is accepted, sweep for stale status claims elsewhere.
9. **Rules-hierarchy structural idea** (common + component-specific
   folders) — worth adopting *structurally* once several stage-ADRs exist
   and `CLAUDE.md`/`TEAM.md` risk growing unwieldy; not urgent now.
10. **Verification-loop framing** (checkpoint vs. continuous eval) — maps
    onto how Test Results Analyzer should validate each new ADR-002+
    stage before merge; formalizes an idea the Council already implies.
11. **Build-error-resolution checklist mentality** — fold into Minimal
    Change Engineer's existing post-implementation validation step, not a
    new agent.
12. **Refactor-cleaner's separation discipline** — already present
    verbatim in Minimal Change Engineer's philosophy ("keep bug fixes and
    refactors in separate changes"); ECC's version confirms rather than
    adds.
13. **Search-first / verify-before-answering principle** — already
    codified independently in `CLAUDE.md` §7 ("Never guess. Verify
    assumptions against the actual repository"); confirms Phantom's
    existing rule rather than introducing something new.
14. **Cost-aware-LLM-pipeline thinking** — not applicable to Phantom's
    pipeline (zero LLM in the trading decision path by ADR-001), but
    relevant to managing *my own* token/session efficiency on a
    multi-document project like this one.
15. **Session-pruning / retention-window habit** — reasonable hygiene
    idea for whatever session/decision logging Phantom's own Watchdog
    (ADR-011) eventually implements.
16. **Multi-agent orchestration for independent *research* tasks only**
    — e.g., parallel investigation of two candidate libraries — never for
    parallel unreviewed *implementation*, which would conflict with
    ADR-001's sequencing.
17. **Contexts-per-stage idea** — load only the relevant reference
    material (e.g., only `phantom/scanner.py`) when implementing a single
    ADR's stage, rather than the whole repo's context at once.
18. **Selective-install philosophy** — ECC's own "install only what you
    need" principle is the correct lens to apply to ECC itself, and
    validates why this evaluation recommends adopting ~12 ideas out of
    67+277+93+34 components rather than installing the platform.
19. **PR description structure** (summary, test plan, risks) — already
    matches `CLAUDE.md` §4's change-report requirement; confirms rather
    than changes anything.
20. **Incident-response escalation shape** (stop work → escalate → fix
    critical items first → rotate any exposed credentials → audit for
    recurrence) from `security.md` — reasonable shape for a future
    Security Architect incident-response runbook, complementing (not
    duplicating) SRE's operational incident-response lane in `TEAM.md`.

## Components to avoid

- **All 67 agents, wholesale** — duplicates the Council's roles and
  violates `TEAM.md`'s own "no new agent without demonstrated benefit"
  rule.
- **Continuous Learning v2 (instinct auto-injection)** — conflicts with
  ADR-001's ADR-gated, human-approved change discipline; broadens the
  logging/persistence surface unnecessarily.
- **Autonomous loops / unsupervised parallel implementation** — conflicts
  with ADR-001's deliberate one-stage-at-a-time sequencing.
- **The entire multi-harness adapter system** (Cursor/Codex/Copilot/Zed/
  Gemini/Antigravity/Qwen configs) — Phantom's Council is Claude-Code-only
  by design; pure noise otherwise.
- **Dashboard GUI (Tkinter)** — no relevance to a Phantom research/
  governance question.
- **Prediction-market (`ito-*`) skills** — different market structure
  from FX/CFD; not transferable.
- **Framework-specific skills/rules** for stacks Phantom doesn't use
  (FastAPI, Django, Laravel, Spring Boot, Quarkus, Next.js, heavy
  Docker/K8s patterns).
- **MCP configs** (Supabase, Vercel, Railway, Playwright, etc.) — none map
  to Phantom's actual infrastructure.
- **"ECC Pro" hosted GitHub App** — third-party hosted-service dependency
  with no reason to exist in this project.

## Missing capabilities ECC does not provide

- Any quantitative/statistical trading-strategy validation (walk-forward,
  Monte Carlo, purity gates) — that gap is filled by VIBE
  (`docs/research/VIBE-TRADING-EVALUATION.md`), not by ECC, and remains a
  gap ECC does nothing to close.
- Any MT5/FX/prop-firm domain knowledge whatsoever.
- An ADR-driven, stage-gated architecture governance model of its own —
  ECC optimizes for fast iterative feature velocity, not deliberate,
  compliance-grade sequencing; Phantom's ADR-001 model is *stricter* than
  anything ECC provides, not something ECC could have supplied.
- An explicit non-overlapping-responsibility contract across its own 67
  agents comparable to `TEAM.md` §4/§5 — several ECC agents (code-reviewer
  vs. refactor-cleaner vs. per-language reviewers) plausibly overlap
  without as rigorous a de-duplication rule as the Council already has.

## Recommended implementation order

All of the following are **documentation-only** additions to Phantom's
own governance docs, sequenced by dependency — none require installing
anything from ECC:

1. Record the `phantom/api.py` error-leakage finding (item 1 above) as a
   known-defect note, the same way the earlier architecture audit backlog
   in `TEAM.md` §8 already records similar findings — for whichever ADR
   ends up governing the API/Execution Validator surface.
2. Add the AgentShield-style self-audit as an occasional Security
   Architect checklist item, next time `.claude/agents/` or hooks change.
3. Add the "write the check before the fix" discipline to Minimal Change
   Engineer's role, scoped explicitly to *new* ADR-002+ code, not
   retrofitted onto reference material.
4. Adopt the conventional-commit and full-diff-review habits immediately
   — zero dependency, no conflict, applies to the very next commit.
5. Revisit the rules-hierarchy structural split (common vs.
   component-specific) once 3-4 stage ADRs exist and `CLAUDE.md`/`TEAM.md`
   have grown enough to justify it — not before.
6. Everything else in the Top 20 — adopt opportunistically, always
   through the existing Council review pipeline, never as an autonomous
   or auto-injecting mechanism.

## Final recommendation

**Reject** wholesale adoption or installation of ECC. **Adapt** roughly a
dozen narrow ideas (Top 20 list) into Phantom's own documentation over
time, through the existing Council review pipeline. **Do not install**
any ECC agent, skill, command, hook, rule file, or the memory/instinct
system.

Justification: ECC is a well-engineered, large-scale generic
software-engineering productivity platform, not domain-relevant reference
material the way VIBE's backtesting/validation code was. Its core
architectural bet — 67 overlapping agents, an auto-learning memory system
that silently promotes heuristics into behavior, autonomous parallel
execution loops — is optimized for maximizing feature velocity across
generic software teams. That bet is close to the opposite of what
`ADR-001` and `TEAM.md` deliberately chose for Phantom: a small,
non-overlapping, explicitly-RACI'd agent roster; an ADR-gated,
one-stage-at-a-time implementation discipline; and a hard preference for
human-reviewed, deterministic process over autonomously-learned behavior.
Importing ECC's actual components would not improve reliability,
maintainability, or security for Phantom specifically — it would
reintroduce exactly the kind of duplicate/conflicting-responsibility risk
the Council's governance was built to prevent. The dozen ideas worth
keeping are worth keeping precisely because they're generic enough to
survive translation into Phantom's much stricter governance model; the
rest isn't.
