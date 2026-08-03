# Plan artifacts (RPI gated workflow)

This directory holds the Research → Plan → Implement (RPI) artifacts
required by `.claude/agents/TEAM.md` §9 / `docs/adr/ADR-014-multi-agent-
governance.md` Amendment 1, for any change matching `TEAM.md` §3's
existing Software Architect trigger (a new engine, or a change crossing
`phantom_pipeline/` package boundaries). It is optional documentation for
everything else — a contained bug fix, refactor, or performance change
already covered by `TEAM.md` §2's lighter-weight workflows does not need
a file here.

## How to use this

1. Copy `TEMPLATE.md` to `<slug>.md` (a short, kebab-case name for the
   change — e.g. `portfolio-manager-phase1.md`).
2. Fill in **Research** before writing any Plan content — read the
   affected files/dependencies, confirm the touched stage's ADR is
   Accepted, check for duplicate logic, and run
   `python3 scripts/check_architecture.py`.
3. Fill in **Plan** — approach, architectural-compliance confirmation,
   files to be touched — before Minimal Change Engineer starts
   implementing.
4. Implement.
5. Fill in **Validation** with the actual command output
   (`compileall`, `unittest discover`, `validate.py`) once the change is
   complete.
6. Update `CHANGELOG.md` with a dated entry pointing back to this file.

## What this is not

- Not a replacement for `IMPLEMENTATION_PLAN.md` (the per-ADR-stage
  build-order tracker) or `VALIDATION_MATRIX.md` (the per-stage test/
  validation record) — those remain the authoritative per-stage status
  documents. A plan file here is per-*change*, not per-*ADR-stage*; a
  single ADR stage's implementation may span one or several plan files
  if done incrementally.
- Not a gate on trivial changes. See `TEAM.md` §9 for exactly when this
  is mandatory versus optional.
