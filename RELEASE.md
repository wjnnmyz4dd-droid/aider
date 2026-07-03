# Phantom Protocol — Release

**Version:** `v1.0-forward-test`

**Status:** Production Ready

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

## Freeze policy

- No new features.
- Only confirmed runtime bug fixes.

---

_See `AUDIT.md` for the verified production architecture and evidence._
