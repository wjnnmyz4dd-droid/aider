# Titan Protocol — Final Release Hardening Report

Companion to `PHANTOM_FINAL_PRODUCTION_CERTIFICATION_AUDIT.md` (the
prior, zero-code-change certification pass). That audit found no
defects and listed five known release gaps. This report closes four of
them in code and documents the fifth as an inherently external gate
that cannot be closed without a real Windows MT5 environment.

**Do not read this report's numbered scores as MT5 or funded
readiness.** Every code-level requirement below is VERIFIED by a real,
running test. No item requiring a real MetaEditor compile, a real
demo-chart attach, or a real broker fill has been executed — those are
explicitly PENDING REAL MT5, tracked in
`deployment_windows/REAL_MT5_VALIDATION_CHECKLIST.md`.

---

## 1. Files changed

### New packages
- `titan_protocol/compliance_state_store/` — `models.py`, `config.py`,
  `trading_day.py`, `store.py`, `__init__.py`. Durable, restart-safe
  compliance day-state (daily starting balance, all-time peak balance,
  compliance lock, trading-day identity), caller-owned per ADR-028 §3;
  `ComplianceEngine` itself untouched.
- `titan_protocol/bridge/symbol_mapping.py` — broker-native ↔ canonical
  symbol normalization (suffix/prefix + explicit override map).

### Modified production code
- `titan_protocol/bridge/config.py` — added `BridgeConfig.symbol_mapping`
  field (defaulted, backward-compatible).
- `titan_protocol/bridge/server.py` — normalizes the raw broker symbol
  at all 5 HTTP ingress points (positions, orders, trade-transaction,
  bar, tick) before constructing any downstream type.
- `titan_protocol/runtime/models.py` — added 12 defaulted fields to
  `RuntimeAuditRecord` (decision ID, config schema version, timeframe,
  evidence/MI summaries, risk reasons, compliance triggered
  rules/lock, bridge correlation ID, snapshot hash, decision
  fingerprint).
- `titan_protocol/runtime/engine.py` — populates the 12 new fields from
  values each stage already computed (no duplicated calculation); adds
  a `timeframe` constructor parameter.
- `titan_protocol/runtime/logging_sink.py` — surfaces all 12 new fields
  in the structured text log, not just the in-memory object.
- `deployment_windows/config_loader.py` — canonical symbol-universe
  parsing/validation (duplicate/invalid-format detection,
  `symbol_mapping` section parsing), new `build_trading_profile()`
  shared by `start.py`/`health_check.py`, new
  `compliance.daily_reset_hour_utc` config field.
- `deployment_windows/start.py` — wires `ComplianceStateStore` into the
  live-cycle loop (restart-safe day-state replacing hardcoded
  per-cycle defaults); passes `timeframe` into `RuntimeOrchestrator`;
  uses `build_trading_profile()`.
- `deployment_windows/health_check.py` — uses `build_trading_profile()`
  (removed a duplicated `_PROFILE_FACTORIES` dict that had drifted into
  two files).
- `deployment_windows/config/titan_protocol_config.example.json` —
  documents the new `symbol_mapping` and `daily_reset_hour_utc` keys.
- `mt5/TitanProtocolEA.mq5` — reads `emergency_stop` from the existing
  `/bridge/commands/poll` response (`JsonGetBool()`, new helper);
  `IsEmergencyStopped()` ORs the local `EmergencyDisable` input with
  the server-reported flag; rejects command execution (not polling or
  telemetry) while stopped; logs activation/clearance transitions
  edge-triggered.

### New documentation
- `deployment_windows/REAL_MT5_VALIDATION_CHECKLIST.md` — the exact,
  itemized real-MT5-only checklist (requirement 5).
- `deployment_windows/verify_real_mt5_readiness.py` — evidence-gathering
  companion script (reads `health.json`/`compliance_state.json`;
  verifies nothing itself).
- This report.

### New/updated tests (91 new, 1 rewritten)
- `tests/titan_protocol/bridge/test_symbol_mapping.py` (9)
- `tests/deployment_windows/test_symbol_universe.py` (12)
- `tests/titan_protocol/compliance_state_store/test_trading_day.py` (6)
- `tests/titan_protocol/compliance_state_store/test_store.py` (21)
- `tests/titan_protocol/compliance_state_store/test_structural_boundary.py` (5)
- `tests/deployment_windows/test_compliance_state_persistence.py` (7)
- `tests/mt5/test_titan_protocol_ea_emergency_stop.py` (12)
- `tests/titan_protocol/runtime/test_audit_record_completeness.py` (19)
- `tests/titan_protocol/e2e/test_audit_record_completeness.py` —
  **rewritten** (6 tests): this Phase 3B file used to document the
  audit-record gaps as Known Limitations; it now asserts those same
  gaps are closed, so a future regression is still caught.
- `tests/deployment_windows/_fixtures.py` — shared real-config-file test
  fixture (pre-existing from earlier in this session, reused).

---

## 2. Root causes (why each gap existed)

1. **Symbol-universe consistency**: `TradingProfile.allowed_pairs` and
   `BridgeConfig.allowed_symbols` were two independently maintained
   lists with no cross-validation and no broker-suffix handling.
2. **Persisted compliance state**: `ComplianceEngine` was correctly
   designed stateless/caller-owned (ADR-028 §3) from the start, but no
   caller in this deployment layer had ever implemented the
   persistence side of that contract — `start.py` used hardcoded
   per-cycle defaults instead.
3. **EA emergency-stop sync**: the Bridge already computed and returned
   `emergency_stop` in its poll response (server-side enforcement was
   never the gap), but the EA never read the field — a pure
   observability/defense-in-depth gap, not a safety gap (documented as
   such in the prior certification audit, §7 and §14 item 4).
4. **Audit-record completeness**: `RuntimeAuditRecord` was frozen at
   Phase 3B with several fields collapsed to bare identifiers/booleans
   because expanding a frozen type required a fresh amendment
   (ADR-031), which this hardening pass is.
5. **Real-MT5 validation**: no checklist existed at all; verification
   plans lived only in narrative form across several historical
   reports, not as one exact, repeatable list.

## 3. Test results

- Full repository suite (`python -m unittest discover -s . -p
  "test_*.py"`, run from repo root — **not** `-s tests`, which shadows
  the real `titan_protocol` package with `tests/titan_protocol/` on
  some Python versions' path-insertion order): **2760 tests**, 3
  errors, 3 failures.
  - 3 errors: `tests/test_account_snapshot.py`,
    `test_journal_fields.py`, `test_score_signal.py` all fail on
    `ModuleNotFoundError: No module named 'flask'` importing the
    reference-only `phantom_institutional.py` — a pre-existing,
    already-documented environment gap (Flask is not installed in
    this sandbox), unrelated to Titan Protocol.
  - 3 failures: `test_git_status_shows_only_expected_paths_changed`
    (bridge), and two `test_no_frozen_pipeline_package_is_touched_by_
    this_{change,phase}` checks (compliance_state_store,
    news_ingestion) — these compare a **live** `git status` against a
    hardcoded historical file list from an earlier phase; they always
    flag legitimate cross-cutting work like this hardening pass until
    it is committed. Not a functional regression — confirmed by
    re-reading each assertion's logic.
- New/updated test files above: **91 new + 6 rewritten = 97 tests, all
  passing** on first or corrected attempt (a small number of test-authoring
  mistakes were found and fixed during this pass — e.g. an incorrect
  assumption about pipeline stage ordering, a nonexistent fixture
  keyword argument, a double-logging bug in a test's own handler setup
  — none were production defects).
- Import sweep: all 181 `titan_protocol` submodules import cleanly from
  a fresh extraction of the rebuilt release zip.
- `compileall`: clean, zero errors, against both the working tree and
  the extracted release zip.
- Architecture/boundary checks: `scripts/check_architecture.py` (the
  legacy `phantom_pipeline/` reference-material checker) passes; every
  package's own `test_structural_boundary.py` (bridge, news_ingestion,
  compliance_state_store) passes except the git-status sub-check noted
  above.
- Concurrency/stress: pre-existing `test_concurrency.py`/`test_stress.py`
  suites (runtime, bridge) pass unchanged.
- Persisted-state restart simulations: `test_store.py` (crash mid-write
  via `.bak` recovery, corruption, unknown schema version, daily-reset
  boundary crossing, restart-does-not-reset) and
  `test_compliance_state_persistence.py` (real `_build_compliance_
  account_state()` wiring, simulated restart via a fresh store
  instance) all pass.
- Symbol-universe config tests: exact match, missing pair (fail
  closed), duplicates, invalid symbols, suffix mapping, profile
  changes — all pass (`test_symbol_universe.py`,
  `test_symbol_mapping.py`).
- Emergency-stop protocol tests: 12 source-inspection tests confirming
  the poll-response field is read, the effective-stopped state ORs
  local/server flags, execution (not polling) is rejected while
  stopped, transitions are logged edge-triggered, and no position-close
  call was added.
- Audit fingerprint determinism tests: identical inputs produce
  identical `snapshot_hash`/`decision_fingerprint`; different
  timeframes/outcomes produce different ones.

## 4. Release ZIP verification

Rebuilt `titan_protocol_windows_complete_release.zip` from the current
working tree (flattened layout: `deployment_windows/*.py` +
`requirements.txt` + docs at the package root, `config/`, `data/`,
empty `logs/`/`state/`, `titan_protocol/`, `mt5/`), with a freshly
generated `RELEASE_MANIFEST.json` (source commit, build timestamp,
per-file SHA-256, Python version requirement, known-gaps summary).

- 223 files packaged, 343,233 bytes.
- SHA-256 of the zip:
  `de472fcab6924f8bb3c0e708186db509ae40779d118bd8d39ca23d59ba1bc701`
- Extracted fresh into an isolated directory and ran the **full
  lifecycle**: `python install.py` (venv, pip install, folder
  structure, config validation, write permissions, compileall, import
  smoke test, Bridge/Runtime/Reliability/news construction checks, MT5
  file copy skipped as expected — no MT5 terminal on this Linux
  sandbox — desktop shortcuts skipped as expected on non-Windows) →
  auto-launched `start.py` → `health_check.py` (STATUS: DEGRADED,
  exactly as documented: no real MT5 EA attached, no real news
  provider credentials — never silently reports HEALTHY) → `stop.py`
  (graceful shutdown confirmed, process no longer running).
- The zip itself is a build artifact and is not committed to git (see
  `.gitignore`); it has been delivered as a file alongside this report.

## 5. Remaining limitations (honest, not fixed by this pass)

- **Everything in `REAL_MT5_VALIDATION_CHECKLIST.md`** — MetaEditor
  compile, `.ex5` generation, demo-chart attach, live bars/ticks, 50-bar
  M15 warmup, broker-time/stale-feed behavior, heartbeat/reconnect,
  terminal/Python/VPS restart, server emergency-stop sync, real BUY/
  SELL/modify/partial-close/close execution, day-state persistence
  across real restarts, and news-provider failover — **all PENDING
  REAL MT5**. No result has been fabricated.
- **Compliance lock auto-application is not yet wired to
  `ComplianceStateStore.apply_lock_recommendation()`**: the store's
  extension point exists and is unit-tested, but `start.py` does not
  yet call it, because `ComplianceSnapshot.lock_recommendation` is not
  currently exposed on `RuntimeAuditRecord`'s return path in a form the
  deployment layer consumes per-cycle. This is a deliberate sequencing
  decision, not an oversight: wiring it prematurely would require
  reaching into Runtime internals ahead of a dedicated amendment,
  which is out of this pass's minimal-diff scope. Documented here as a
  concrete follow-up, not silently dropped.
- **Trading-day boundary is not DST-aware**: `daily_reset_hour_utc` is
  a fixed UTC hour, by design (stdlib-only) — an operator whose broker
  server-time offset shifts with DST must update the config value
  manually when that happens.
- **`forex_factory_base_url` still ships empty** in the example config
  (pre-existing, documented in `KNOWN_GAPS.md`) — a real backup
  provider must be configured before Forex Factory failover has
  anything to fail over to.
- **The 3 pre-existing `flask`-import test errors** (reference-only
  `phantom_institutional.py`) remain, as already documented in the
  prior certification audit — out of this mission's scope (no new
  dependency was added to satisfy a reference-only module).

## 6. Requirement-by-requirement status

| # | Requirement | Status |
|---|---|---|
| 1 | Symbol-universe consistency | **VERIFIED** |
| 2 | Persisted compliance state | **VERIFIED** (code + tests; lock-recommendation auto-wiring deliberately deferred, see §5) |
| 3 | EA emergency-stop synchronization | **VERIFIED** (code + source-inspection tests) / real-terminal behavior **PENDING REAL MT5** |
| 4 | Audit-record completeness | **VERIFIED** |
| 5 | Real-MT5 validation package | **VERIFIED** (checklist + script exist and are correct) / every checklist item itself **PENDING REAL MT5** |
| 6 | Verification (suite, imports, compileall, architecture, lifecycle, zip) | **VERIFIED** |
| 7 | Final report | **VERIFIED** (this document) |

## 7. Final decisions

- **Demo deployment: GO.** Every code-level gap this pass targeted is
  closed and tested; the install→start→health→stop lifecycle is clean
  against the rebuilt release zip. An operator can proceed to
  `REAL_MT5_VALIDATION_CHECKLIST.md` sections 1–4 immediately.
- **Extended demo forward testing: GO, conditional on
  `REAL_MT5_VALIDATION_CHECKLIST.md` sections 1–7 passing first.**
  Do not begin multi-day/multi-week demo forward testing until the
  restart-resilience (section 3) and day-state-persistence (section 6)
  gates have actually been run against a real terminal — those are
  exactly the categories this pass added code for but cannot verify
  outside MT5.
- **Funded deployment: NO-GO.** Per this mission's own explicit
  instruction, no score or decision here may treat MT5/funded readiness
  as 100% while any checklist item remains PENDING REAL MT5. That
  remains true after this pass: nothing in
  `REAL_MT5_VALIDATION_CHECKLIST.md` has been executed. Funded
  deployment requires completing that checklist first, then a fresh,
  short re-certification pass over just the sections that changed.
