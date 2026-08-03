---
description: RPI Research phase - investigate a proposed change before any plan or code is written
argument-hint: [short description of the proposed change]
---

Perform the **Research** phase of the RPI gated workflow
(`.claude/agents/TEAM.md` §9, `docs/adr/ADR-014-multi-agent-governance.md`
Amendment 1) for the change described in: $ARGUMENTS

This uses Phantom's existing Council agents only — no new agent. Act as
the RACI Accountable/Consulted architect(s) for the touched component
(`TEAM.md` §5's RACI matrix), or delegate to them via the Agent tool if a
specialist review adds real value (e.g. Security Architect for a
compliance-adjacent change).

Do:
1. Read the affected files and their dependencies (`CLAUDE.md` §4.1).
2. Confirm the touched stage's own ADR is **Accepted**, not merely
   Proposed (`CLAUDE.md` §1.10, §4.3). If it isn't, stop here and say so
   — do not proceed to Plan.
3. Identify duplicate logic and potential regressions (`CLAUDE.md` §4.4).
4. Run `python3 scripts/check_architecture.py` and record the result.
5. Determine whether this change actually needs a full RPI gate at all
   — per `TEAM.md` §9, that's only when it's a new engine or crosses a
   `phantom_pipeline/` package boundary. If it's a contained, single-
   package bug fix/refactor/performance change, say so and recommend
   skipping straight to implementation under `TEAM.md` §2's lighter
   workflow instead.

If this change does need the full gate: create `docs/plans/<slug>.md`
from `docs/plans/TEMPLATE.md` (choose a short, kebab-case `<slug>`) and
fill in only the **Research** section — leave Plan and Validation empty
for the next phases. Do not write any implementation code in this phase.

Report the Research findings and whether you recommend proceeding to
`/rpi:plan`.
