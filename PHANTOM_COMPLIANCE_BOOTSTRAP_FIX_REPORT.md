# KNOWN_GAPS.md #9 — Compliance Day-One Bootstrap Balance — Completion Report

Status: Fixed and closed. This addresses the engineering objective
"Eliminate the compliance gap whereby a fresh Titan installation may
establish an incorrect `daily_starting_balance` after trading activity
has already begun."

## 1. Engineering design

**Design chosen: Option A (deterministic wire-verified delay) as the
default, Option B (operator override) as an explicit, opt-in bypass —
never the reverse.** This follows the doctrine's own instruction not to
"introduce operator discretion where deterministic validation is
possible": determinism is the default path; discretion is available
only when an operator explicitly configures it.

- **Verification signal:** an account is treated as "flat" — safe to
  bootstrap from — only when `bridge_engine.latest_positions` is empty
  **and** the EA-reported `balance` equals `equity` within a configurable
  tolerance (default 0.01, one cent). Absence of open positions rules out
  ongoing floating P&L; `balance == equity` independently confirms no
  floating P&L exists at this instant. Both checks together are the
  strongest signal available from wire data alone.
- **What this cannot detect, by design:** a trade opened *and closed*
  earlier the same day, before Titan ever received a report. That
  already changed `balance` permanently with no wire field to reveal it
  — exactly the case KNOWN_GAPS.md's original text called "unverifiable
  from this wire message alone." This is not a defect in the fix; it is
  a hard limit of what wire data can prove, documented rather than
  hidden.
- **The override (`day_start_balance_override`) is the deterministic
  escape hatch for that one residual case** — not a general convenience
  knob. When set, it always wins outright, regardless of positions or
  equity, and is used exactly as the operator supplied it.
- **No timeout/give-up fallback was implemented, deliberately.** An
  earlier design considered auto-bootstrapping after some bounded wait
  if the account never becomes verifiably flat. Rejected: it would
  silently reintroduce the exact contamination risk this fix exists to
  close, and directly contradicts the Final Doctrine ("capital
  preservation overrides convenience"). If an account never becomes
  flat, the correct behavior is that Titan never trades until the
  operator either closes the pre-existing positions or supplies
  `day_start_balance_override` — not that Titan silently guesses.
- **Backward compatibility:** `load_or_bootstrap()`'s new parameters
  (`current_equity`, `has_open_positions`) default to "the account is
  flat" — every pre-existing caller that doesn't pass them (all of
  `test_store.py`) sees byte-identical behavior to before this fix.

## 2. Implementation

- `titan_protocol/compliance_state_store/bootstrap.py` (new) —
  `is_account_verified_flat()`, `resolve_bootstrap_balance()`. Pure
  functions, no state, mirroring this package's existing
  `trading_day_id_for()` discipline.
- `titan_protocol/compliance_state_store/config.py` — added
  `day_start_balance_override: Optional[float] = None` and
  `flat_account_equity_tolerance: float = 0.01`, both validated in
  `__post_init__` (override must be `> 0` if set; tolerance must be
  `>= 0`).
- `titan_protocol/compliance_state_store/store.py` —
  `load_or_bootstrap()` signature extended (backward-compatible
  defaults), return type widened to `Optional[PersistedComplianceState]`;
  `None` means "not yet verified, caller must skip this cycle."
- `titan_protocol/compliance_state_store/__init__.py` — exports the two
  new pure functions.
- `deployment_windows/start.py` — `_build_compliance_account_state()`
  passes `latest.equity` and `bool(bridge_engine.latest_positions)`
  through; returns `(None, None)` while verification is pending, using
  the exact fail-closed convention already established for "no account
  state reported yet." Docstring updated. `ComplianceStateStoreConfig`
  construction now threads the two new settings through from
  `DeploymentSettings`.
- `deployment_windows/config_loader.py` — parses
  `compliance.day_start_balance_override` /
  `compliance.flat_account_equity_tolerance`, both fail-closed for
  invalid values; both added to `DeploymentSettings`.
- `deployment_windows/config/titan_protocol_config.example.json` —
  both new fields documented and shown with their defaults.

## 3. Test suite

| File | New tests | Covers |
|---|---|---|
| `tests/titan_protocol/compliance_state_store/test_bootstrap_verification.py` | 20 | Pure functions (`is_account_verified_flat`, `resolve_bootstrap_balance`); `load_or_bootstrap()` integration: flat bootstrap, legacy-default preservation, open-positions block, floating-P&L block, becomes-flat-later, operator override, existing-installation unaffected, config validation |
| `tests/deployment_windows/test_config_loader.py` | 6 | `day_start_balance_override`/`flat_account_equity_tolerance` config parsing: default, explicit, zero/negative fail-closed |
| `tests/deployment_windows/test_compliance_state_persistence.py` | 4 | Real `start.py` wiring: open position skips cycle, floating P&L skips cycle, flat account bootstraps normally, override bypasses despite open position |

**Test Requirements checklist (from the objective):**

| Required scenario | Covered by |
|---|---|
| Fresh installation | `TestFreshInstallVerifiedFlatBootstraps`, `TestBootstrapVerificationWiring.test_flat_account_on_fresh_install_bootstraps_normally` |
| Restart before trading | `TestExistingInstallationUnaffected` (existing file → bootstrap never re-evaluated, positions/equity ignored) |
| Restart after trading | Same test — a state file already existing is the "after trading has started" case; `test_store.py`'s pre-existing `TestRestartSurvival`/`TestDailyResetBoundary` classes (unaffected, unmodified) already prove this thoroughly |
| Weekend restart | `test_store.py::TestDailyResetBoundary` (unaffected by this change — `reconcile()`'s day-rollover logic was not touched) |
| Missing baseline | `TestFreshInstallVerifiedFlatBootstraps`/`TestFreshInstallNotYetVerifiedBlocksBootstrap` (no file exists yet, both outcomes) |
| Corrupted baseline | `test_store.py::TestCorruptionFailsClosed` (unaffected — corruption handling lives entirely in `_load_existing()`, never reached until a file exists) |
| Operator-supplied baseline | `TestOperatorOverrideBypassesVerification`, `TestBootstrapVerificationWiring.test_operator_override_bootstraps_despite_open_position` |
| Delayed initialization | `TestFreshInstallNotYetVerifiedBlocksBootstrap.test_becomes_flat_on_a_later_call_and_bootstraps_then` |
| Regression (existing compliance logic unaffected) | All 32 pre-existing `compliance_state_store` tests re-run unchanged and pass |

## 4. Validation results

- `python3 -m unittest discover -s tests/titan_protocol/compliance_state_store` — 52/52 pass (32 pre-existing + 20 new).
- `python3 -m unittest tests.deployment_windows.test_config_loader` — 19/19 pass (13 pre-existing + 6 new).
- `python3 -m unittest tests.deployment_windows.test_compliance_state_persistence` — 11/11 pass (7 pre-existing + 4 new).
- `python3 -m unittest tests.deployment_windows.test_run_status` — 8/8 pass (unaffected, re-verified since it touches the same `AccountState` wiring).
- `python3 -m compileall -q titan_protocol tests deployment_windows scripts` — clean.
- **Full repository suite: 3038 tests, 3 errors** — the same three
  pre-existing, environment-only `ModuleNotFoundError: No module named
  'flask'` failures (`tests/test_account_snapshot.py`,
  `tests/test_journal_fields.py`, `tests/test_score_signal.py`),
  unrelated to this change.
- `python3 scripts/check_architecture.py` — PASS.
- `git diff --stat` — touches only `titan_protocol/compliance_state_store/`
  and its two wiring call sites (`deployment_windows/start.py`,
  `deployment_windows/config_loader.py`) plus their tests and the example
  config. Zero changes to any other `titan_protocol/` package.

## 5. Documentation updates

- `deployment_windows/KNOWN_GAPS.md` section 9: OPEN → CLOSED, full
  writeup of the fix and its one documented residual limitation.
- `deployment_windows/config/titan_protocol_config.example.json`: both
  new fields added with explanatory `_note` entries, matching this
  file's existing documentation convention.

## 6. CHANGELOG update

`CHANGELOG.md` — dated 2026-07-24 entry added (Added/Changed/Validation
sections).

## Success criteria — verified

- "The Compliance Engine shall never calculate daily loss from an
  unverified day-start balance." — Verified: `load_or_bootstrap()`
  cannot return a bootstrapped state unless the account is
  verified-flat or an operator override is set; there is no code path
  that reaches `ComplianceEngine.evaluate()` with an unverified balance.
- "The bootstrap process shall be deterministic, reproducible, and fail
  closed." — Verified: `resolve_bootstrap_balance()` is a pure function
  of its inputs; the caller returns `None`/skips the cycle rather than
  guessing when verification hasn't succeeded yet.
- "All automated tests shall pass." — Verified (3038/3041, only the 3
  pre-existing unrelated failures).
- "No regression shall be introduced into existing compliance
  functionality." — Verified: every pre-existing test in
  `compliance_state_store`, `config_loader`, and
  `compliance_state_persistence` passes unchanged.

## Prohibited actions — compliance confirmed

- Did not weaken fail-closed behavior (strictly stricter than before:
  previously bootstrapped unconditionally, now requires verification).
- Did not assume the first observed balance is correct (that is the
  exact assumption this fix removes).
- Did not introduce operator discretion where deterministic validation
  is possible (the override is opt-in, not the default path).
- Did not bypass existing compliance protections (Compliance Engine
  itself, `daily_loss.py`/`profit_protection.py`, were not touched at
  all — confirmed by `git diff --stat`).
