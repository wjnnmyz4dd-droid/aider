---
description: RPI Plan phase - produce a written implementation plan from an existing Research artifact
argument-hint: [path to docs/plans/<slug>.md, or a short description if no Research artifact exists yet]
---

Perform the **Plan** phase of the RPI gated workflow
(`.claude/agents/TEAM.md` §9, `docs/adr/ADR-014-multi-agent-governance.md`
Amendment 1) for: $ARGUMENTS

Act as **Software Architect** if this crosses a `phantom_pipeline/`
package boundary or introduces a new engine (`TEAM.md` §2's existing
"Feature development" step 1 / §3's existing trigger table); act as
**Backend Architect** if it's a contained, single-package change that
still warranted the full gate. If a `docs/plans/<slug>.md` file doesn't
already exist with a completed Research section, run `/rpi:research`
first — do not plan against unresearched assumptions.

Do:
1. State the approach and its explicit boundaries (what this change does
   and does NOT do).
2. Confirm architectural compliance against `ADR-001`'s pipeline and the
   touched stage's own ADR (`CLAUDE.md` §4.2–.3).
3. List every file to be touched.
4. Confirm the Research phase's `check_architecture.py` result is clean,
   or explain why a flagged issue is acceptable/out of scope for this
   change.

Write this into `docs/plans/<slug>.md`'s **Plan** section. This must be
saved to the file — a plan stated only in the response does not satisfy
`TEAM.md` §9's requirement (the one genuinely new obligation this
workflow adds over prior practice). Do not begin implementing.

End by stating clearly whether the plan is ready for `/rpi:implement`, or
what open question blocks it.
