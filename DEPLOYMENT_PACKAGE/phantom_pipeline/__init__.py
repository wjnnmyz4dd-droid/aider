"""Phantom's single-authority pipeline implementation (ADR-001 onward).

Distinct from `phantom/` and `phantom_institutional.py`, both of which are
reference-only per ADR-001 and must never be extended as if they were a
running authority (CLAUDE.md §2). Every module under this package
implements exactly one Accepted ADR; see docs/adr/ for the authoritative
specification each module follows.
"""
