# Phantom Protocol — Release

**Status (superseded 2026-07-04 by `docs/adr/ADR-001-single-authority-architecture.md`,
Accepted):** the forward test described below has concluded, and
`phantom_institutional.py` — the system this release freezes — is now
**reference material only**, not a running authority. ADR-001 is the
authoritative architecture; the new Phantom system is being rebuilt from
first principles, one accepted ADR per pipeline stage, with no
implementation until each stage's ADR is Accepted. The freeze policy below
no longer applies to any live system. Kept as a historical record of the
last frozen state of `phantom_institutional.py`.

**Version:** `v1.0-forward-test` (historical)

**Status (historical, at time of freeze):** Production Ready

**Frozen commit:** `156f18c7d60ad70b9d5397a0ddab5af856c6ad53`
**Tag:** `v1.0-forward-test` (annotated) → `156f18c`

## Purpose

2–4 week forward test.

## Architecture

- Institutional Server
- Command Center
- Watchdog
- `phantom_src/`
- MT5 EA
- Statistical Risk
- Compliance
- Trade Journal
- Prometheus Metrics

## Known deployment checks

- Verify startup launches both processes (Command Center first, then the
  Institutional Server).
- Verify `phantom_mt5_bridge.py` is not required by the deployment.
- Verify the VPS account-snapshot cadence (every 10–15s; `/account/status`
  `age_seconds` stays low).
- Verify `phantom_src/` external dependencies (Config JSON / data files).

## Freeze policy (historical — no longer in effect)

- No new features.
- Only confirmed runtime bug fixes.

This policy applied only while `phantom_institutional.py` was live and
mid-forward-test. That forward test has concluded and the file is now
reference-only, so this freeze no longer governs any code in this
repository. Current implementation rules are ADR-001's: no code until the
relevant pipeline stage has an Accepted ADR (see `CLAUDE.md` §1.10).

---

_See `AUDIT.md` for the verified production architecture and evidence
(historical), and `docs/adr/ADR-001-single-authority-architecture.md` for
the current authoritative architecture._
