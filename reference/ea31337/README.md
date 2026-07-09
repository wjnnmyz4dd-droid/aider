# EA31337 (reference only)

Vendored copies of three public repositories from the `EA31337` GitHub
organization, added at the user's request for reference:

- `EA31337/` — https://github.com/EA31337/EA31337
- `EA31337-classes/` — https://github.com/EA31337/EA31337-classes
- `EA31337-strategies/` — https://github.com/EA31337/EA31337-strategies

Each was shallow-cloned (`--depth 1`) and copied in without its `.git`
history — these are plain source snapshots, not git submodules.

**Status: reference-only, not a running authority.** Same posture as
`phantom/` and `phantom_institutional.py` (`CLAUDE.md` §2): these files
may be read and mined for ideas, but nothing in `phantom_pipeline/` or
`mt5/` imports, links against, or is generated from this directory. Per
`CLAUDE.md` §1.10, no implementation may treat this code as authoritative
architecture without its own Accepted ADR.
