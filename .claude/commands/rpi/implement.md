---
description: RPI Implement phase - implement an approved plan, then run the unchanged validation gate
argument-hint: [path to docs/plans/<slug>.md with a completed Plan section]
---

Perform the **Implement** phase of the RPI gated workflow
(`.claude/agents/TEAM.md` §9, `docs/adr/ADR-014-multi-agent-governance.md`
Amendment 1) for: $ARGUMENTS

Read `docs/plans/<slug>.md`. If its Plan section is empty or missing,
stop and say so — do not implement against an unapproved plan.

Act as **Minimal Change Engineer** (`TEAM.md` §7 — the sole implementer
on every row): implement the smallest correct diff that satisfies the
Plan section exactly. Do not expand scope beyond the listed files. If the
Plan turns out to be incomplete once you're in the code, stop and update
the Plan section first rather than improvising beyond it.

After implementing, run the **unchanged validation gate** (`TEAM.md` §3,
mandatory, no exceptions) and record every result in `docs/plans/<slug>.md`'s
**Validation** section:
1. `python3 -m compileall phantom_pipeline tests`
2. `python3 -m unittest discover -s tests/phantom_pipeline`
3. `python3 validate.py`
4. Any mandatory reviewer `TEAM.md` §3's routing table names for the
   touched path (state which, if any, and why).

Then act as **Code Reviewer**: review the diff for correctness,
maintainability, and adherence to the approved Plan — record the outcome
in the Validation section too.

Finally, add a dated entry to `CHANGELOG.md` per its own header
convention, and update `IMPLEMENTATION_PLAN.md`/`VALIDATION_MATRIX.md` if
this change affects a pipeline stage's tracked status.

Report using `CLAUDE.md` §4.8's format: Summary, Files changed, Why,
Risks, Validation, Remaining issues, Recommendations.
